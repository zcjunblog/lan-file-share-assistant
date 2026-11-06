"""M3 fault cases. Fakes only for inaccessible OS policies; real files/sockets otherwise."""
import errno
import json
import os
from pathlib import Path
import secrets
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/lan-file-share-assistant/scripts'))
import core
import preflight
import session
from http_service import ShareServer
import test_m2_runtime as m2


class FailureRecovery(m2.Fixture):
    def test_private_setup_failure_revokes_partial_secrets(self):
        # Catches credential files left behind when config write fails before launch.
        manifest = core.inspect_sources(self.req['file_paths'])
        real_save = core.save
        def disk_error(path, value):
            if Path(path).name == 'request.json':
                raise OSError(errno.ENOSPC, 'Synthetic full volume')
            real_save(path, value)
        with patch('session.run', return_value=(self.req, {'can_start': True}, manifest)), patch('session.save', side_effect=disk_error):
            try:
                result = session.start(self.req, self.root, self.req['file_paths'], self.req['host_context'], None)
            except OSError:
                result = {'state': 'unhandled_io_error'}
        private_left = [p.name for p in self.root.rglob('*') if p.name in session.SENSITIVE_FILES]
        self.assertEqual(private_left, [], 'Setup failure must revoke all partial credentials/inputs')
        self.assertEqual(result['state'], 'failed')
        self.assertFalse(result['can_publish'])

    def test_corrupt_state_is_unverifiable_and_never_published(self):
        # Catches traceback/ambiguous state when host interruption truncates metadata.
        root = core.workspace(self.root)
        sid = secrets.token_hex(16)
        directory = session.directory_for(root, sid)
        directory.mkdir(mode=0o700)
        (directory/'state.json').write_text('{"state":')
        for action in (session.status, session.stop):
            try:
                result = action(root, sid)
            except ValueError:
                result = {'state': 'uncaught_corruption'}
            self.assertEqual(result['state'], 'unverified_stale')
            self.assertFalse(result['can_publish'])
            self.assertNotIn('url', result)
            self.assertTrue((directory/'state.json').exists())  # no destructive guessed recovery

    def test_readonly_workspace_and_unreadable_source_block(self):
        root = core.workspace(self.root)
        root.chmod(0o500)
        try:
            _, report, _ = preflight.run(self.req, root, self.req['file_paths'], self.req['host_context'])
            self.assertFalse(report['can_start'])
            self.assertNotEqual(next(c for c in report['checks'] if c['id']=='workspace')['status'], 'pass')
        finally:
            root.chmod(0o700)
        self.source.chmod(0)
        try:
            _, report, _ = preflight.run(self.req, root, self.req['file_paths'], self.req['host_context'])
            self.assertFalse(report['can_start'])
            source = next(c for c in report['checks'] if c['id']=='source_files')
            self.assertEqual(source['reason_code'], 'source_invalid')
            self.assertTrue(source['remediation'])
        finally:
            self.source.chmod(0o600)

    def test_size_caps_without_reading_large_payload(self):
        giant = self.base/'too-large.bin'
        with open(giant,'wb') as stream:
            stream.truncate(2*1024**3+1)
        self.assertCode('source_invalid',lambda:core.inspect_sources([str(giant)]))
        paths=[]
        for i in range(3):
            path=self.base/('cap-%d.bin'%i)
            with open(path,'wb') as stream:
                stream.truncate(2*1024**3)
            paths.append(str(path))
        self.assertCode('source_invalid',lambda:core.inspect_sources(paths))

    def test_ambiguous_loopback_virtual_and_denied_bind(self):
        for candidates in ([], [{'address':'127.0.0.1'}], [{'address':'192.168.1.2'},{'address':'10.0.0.2'}]):
            with patch('preflight.interfaces',return_value=candidates):
                _, report, _=preflight.run(self.req,self.root,self.req['file_paths'],self.req['host_context'])
            self.assertFalse(report['can_start'])
            self.assertFalse(report['can_publish'])
            self.assertNotEqual(next(c for c in report['checks'] if c['id']=='interface')['status'], 'pass')
        # An explicitly selected VPN-only address is not admitted by physical discovery.
        request=dict(self.req,bind_address='10.0.0.2')
        with patch('preflight.interfaces',return_value=[{'address':'192.168.1.2'}]):
            _, report, _=preflight.run(request,self.root,request['file_paths'],request['host_context'])
        self.assertIn('interface_ambiguous',[c['reason_code'] for c in report['checks']])
        with patch('preflight.interfaces',return_value=[{'address':'192.168.1.2'}]), patch('preflight.socket.socket') as sock:
            sock.return_value.__enter__.return_value.bind.side_effect=PermissionError(errno.EACCES,'Synthetic denied bind')
            _, report, _=preflight.run(self.req,self.root,self.req['file_paths'],self.req['host_context'])
        self.assertIn('bind_denied',[c['reason_code'] for c in report['checks']])
        self.assertFalse(report['can_start'])

    def test_non_macos_explicitly_reports_unsupported_backend(self):
        for platform in ('linux','win32'):
            with patch('sys.platform',platform):
                _, report, _=preflight.run(self.req,self.root,self.req['file_paths'],self.req['host_context'])
            self.assertFalse(report['can_start'])
            self.assertIn('platform_unverified',[c['reason_code'] for c in report['checks']])
            self.assertIn('clock_backend_unverified',[c['reason_code'] for c in report['checks']])

    def test_execution_denied_cleans_owned_preparation(self):
        manifest=core.inspect_sources(self.req['file_paths'])
        with patch('session.run',return_value=(self.req,{'can_start':True},manifest)), patch('session.launch',side_effect=PermissionError('Synthetic execution denial')):
            result=session.start(self.req,self.root,self.req['file_paths'],self.req['host_context'],None)
        self.assertEqual(result['reason_code'],'execution_forbidden')
        self.assertFalse(result['can_publish'])
        self.assertFalse(any(p.name in session.SENSITIVE_FILES for p in self.root.rglob('*')))


class RequestBoundary(m2.Fixture):
    def setUp(self):
        super().setUp()
        directory=self.base/'http';directory.mkdir(mode=0o700)
        files=core.snapshot(core.inspect_sources([str(self.source)]),directory/'snapshots')
        state={'title':'M3 fixture','files':files,'expires_at':core.utc(time.time()+60),'session_id':secrets.token_hex(16),'owner_instance':secrets.token_hex(32),'request_digest':'b'*64}
        self.server=ShareServer(('127.0.0.1',0),directory,state,secrets.token_hex(32),m2.FakeDeadline())
        self.server.server_activate()
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.02},daemon=True);self.thread.start()

    def tearDown(self):
        self.server.revoke();self.thread.join(timeout=1)
        super().tearDown()

    def raw(self,request):
        with socket.create_connection(self.server.server_address,timeout=2) as sock:
            sock.sendall(request.encode('ascii'))
            sock.shutdown(socket.SHUT_WR)
            data=b''
            while True:
                part=sock.recv(8192)
                if not part:break
                data+=part
        return data

    def test_duplicate_host_and_upload_rejected_without_secret_echo(self):
        srv=self.server
        req='GET %s HTTP/1.1\r\nHost: %s\r\nHost: attacker.invalid\r\n\r\n'%(srv.prefix,srv.authority)
        response=self.raw(req)
        self.assertIn(b' 403 ',response.split(b'\r\n')[0])
        response=self.raw('POST %s HTTP/1.1\r\nHost: %s\r\nContent-Length: 0\r\n\r\n'%(srv.prefix,srv.authority))
        self.assertIn(b' 501 ',response.split(b'\r\n')[0])
        self.assertNotIn(srv.token.encode(),response)
        response=self.raw('GET %scontrol HTTP/1.1\r\nHost: %s\r\n\r\n'%(srv.prefix,srv.authority))
        self.assertIn(b' 404 ',response.split(b'\r\n')[0])

    def test_idle_connections_do_not_prevent_revocation(self):
        sockets=[]
        try:
            for _ in range(8):
                sock=socket.create_connection(self.server.server_address,timeout=2)
                sock.sendall(b'GET / HTTP/1.1\r\n')
                sockets.append(sock)
            began=time.monotonic();self.server.revoke()
            self.assertLess(time.monotonic()-began,2)
            with self.assertRaises(OSError):socket.create_connection(self.server.server_address,timeout=.2)
        finally:
            for sock in sockets:sock.close()


if __name__=='__main__':unittest.main()
