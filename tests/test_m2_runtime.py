"""Observable security/lifecycle contracts; fixtures only, no user documents."""
import concurrent.futures
import hashlib
import http.client
import json
import os
from pathlib import Path
import secrets
import socket
import stat
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/lan-file-share-assistant/scripts'
sys.path.insert(0, str(SCRIPTS))
import core
import preflight
import session
from http_service import ShareServer, page


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.source = self.base / '合成需求确认书.txt'
        self.source.write_bytes('纯合成测试资料\n'.encode() * 100)
        self.root = self.base / 'private-runtime'
        self.req = dict(schema_version='1.0', title='测试文件分享', file_paths=[str(self.source)], ttl_seconds=60,
                        bind_address=None, port=0, host_context={'kind': 'local', 'evidence': 'desktop_adapter'}, transport='http')

    def tearDown(self):
        self.temp.cleanup()

    def assertCode(self, code, action):
        with self.assertRaises(core.ShareError) as caught:
            action()
        self.assertEqual(caught.exception.code, code)


class FileTests(Fixture):
    def test_exact_independent_scope(self):
        self.assertCode('scope_unconfirmed', lambda: preflight.validate_request(self.req, []))
        preflight.validate_request(self.req, [str(self.source)])

    def test_parameter_limits_and_types(self):
        for key, value in [('ttl_seconds', True), ('ttl_seconds', 59), ('ttl_seconds', 3601), ('port', 80), ('port', True), ('transport', 'https'), ('bind_address', '0.0.0.0'), ('bind_address', '127.0.0.1')]:
            request = dict(self.req, **{key: value})
            with self.assertRaises(core.ShareError):
                preflight.validate_request(request, [str(self.source)])
        with self.assertRaises(core.ShareError):
            preflight.validate_request(dict(self.req, extra='untrusted'), [str(self.source)])

    def test_file_count_directories_fifo_and_duplicate(self):
        for paths in ([], [str(self.base)], [str(self.source)] * 2, [str(self.source)] * 21):
            with self.assertRaises(core.ShareError):
                core.inspect_sources(paths)
        fifo = self.base / 'fifo'
        os.mkfifo(str(fifo))
        began = time.monotonic()
        self.assertCode('source_invalid', lambda: core.inspect_sources([str(fifo)]))
        self.assertLess(time.monotonic() - began, .5)

    def test_symlink_ancestors_and_hardlink_alias_rejected(self):
        link = self.base / 'alias'
        link.symlink_to(self.source)
        self.assertCode('source_invalid', lambda: core.inspect_sources([str(link)]))
        directory = self.base / 'directory-alias'
        directory.symlink_to(self.base, target_is_directory=True)
        self.assertCode('source_invalid', lambda: core.inspect_sources([str(directory / self.source.name)]))
        hardlink = self.base / 'hardlink'
        os.link(str(self.source), str(hardlink))
        self.assertCode('source_invalid', lambda: core.inspect_sources([str(self.source), str(hardlink)]))

    def test_path_traversal_relative_and_glob_rejected(self):
        for p in ('relative.txt', str(self.base) + '/../secret.txt', str(self.base / '*.txt'), str(self.base / 'control\nfile')):
            self.assertCode('source_invalid', lambda: core.inspect_sources([p]))

    def test_snapshot_immutable_source_replacement_detected(self):
        manifest = core.inspect_sources([str(self.source)])
        before = self.source.read_bytes()
        files = core.snapshot(manifest, self.base / 'snapshots')
        self.assertEqual(self.source.read_bytes(), before)
        snapshot = self.base / files[0]['snapshot_relative_path']
        self.assertEqual(snapshot.read_bytes(), before)
        self.source.write_bytes(b'new version')
        self.assertEqual(snapshot.read_bytes(), before)
        self.assertEqual(files[0]['sha256'], hashlib.sha256(before).hexdigest())
        self.assertEqual(stat.S_IMODE(snapshot.stat().st_mode), 0o600)
        self.assertCode('source_changed', lambda: core.snapshot(manifest, self.base / 'another'))

    def test_mid_copy_mutation_and_path_swap_blocked(self):
        for mode in ('modify', 'replace'):
            self.source.write_bytes(b'initial data' * 10)
            manifest = core.inspect_sources([str(self.source)])
            def change():
                if mode == 'replace':
                    self.source.rename(self.base / ('old-' + mode))
                self.source.write_bytes(b'altered source')
            self.assertCode('source_changed', lambda: core.snapshot(manifest, self.base / mode, change))

    def test_private_workspace_no_adoption(self):
        root = core.workspace(self.root)
        self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
        core.save(root / 'private.json', {'value': 'synthetic secret'})
        self.assertEqual(stat.S_IMODE((root / 'private.json').stat().st_mode), 0o600)
        other = self.base / 'other'
        other.mkdir(mode=0o700)
        self.assertCode('workspace_unwritable', lambda: core.workspace(other))
        public = self.base / 'public'
        public.mkdir(mode=0o755)
        self.assertCode('workspace_unwritable', lambda: core.workspace(public))

    def test_deadline_wall_forward_rollback_and_continuous(self):
        class Clock:
            now = lambda self: 100
        clock = Clock()
        with patch('core.time.time', return_value=1000):
            deadline = core.Deadline(60, clock)
        with patch('core.time.time', return_value=999):
            self.assertFalse(deadline.due())
            clock.now = lambda: 160
            self.assertTrue(deadline.due())
        clock.now = lambda: 101
        with patch('core.time.time', return_value=1060):
            self.assertTrue(deadline.due())


class PreflightTests(Fixture):
    def run_report(self, **changes):
        req = dict(self.req, **changes)
        return preflight.run(req, self.root, req['file_paths'], req['host_context'])[1]

    def test_unknown_host_missing_probe_never_publish(self):
        report = self.run_report(host_context={'kind': 'unknown', 'evidence': 'none'})
        self.assertEqual(len(report['checks']), 8)
        self.assertEqual(report['result'], 'needs_action')
        self.assertFalse(report['can_start'])
        self.assertFalse(report['can_publish'])
        self.assertIn('lifecycle_unverified', [c['reason_code'] for c in report['checks']])
        for row in report['checks']:
            self.assertNotEqual(row['evidence'], 'fixture')
            if row['status'] != 'pass':
                self.assertTrue(row['remediation'])
        import jsonschema
        schema = json.loads((SCRIPTS.parents[2] / 'schemas/preflight.schema.json').read_text())
        jsonschema.validate(report, schema)

    def test_remote_unsupported_and_attestation_cannot_come_from_request(self):
        report = self.run_report(host_context={'kind': 'remote', 'evidence': 'none'})
        self.assertEqual(report['result'], 'unsupported')
        _, report, _ = preflight.run(self.req, self.root, self.req['file_paths'], {'kind': 'unknown', 'evidence': 'none'})
        self.assertEqual(report['checks'][0]['reason_code'], 'host_unconfirmed')

    def test_no_qr_dependency_blocks_start(self):
        with patch.dict(sys.modules, {'segno': None}):
            report = self.run_report()
        self.assertIn('dependency_missing', [c['reason_code'] for c in report['checks']])
        self.assertFalse(report['can_start'])

    def test_ambiguous_interface_and_disk_space_block(self):
        with patch('preflight.interfaces', return_value=[]), patch('preflight.shutil.disk_usage') as usage:
            usage.return_value.free = 1
            report = self.run_report()
        self.assertIn('interface_ambiguous', [c['reason_code'] for c in report['checks']])
        self.assertIn('insufficient_space', [c['reason_code'] for c in report['checks']])
        self.assertFalse(report['can_start'])

    def test_port_collision_does_not_close_foreign_listener(self):
        try:
            candidates = core.interfaces()
        except core.ShareError:
            self.skipTest('No verified local adapter backend')
        if not candidates:
            self.skipTest('No active physical RFC1918 interface')
        address = candidates[0]['address']
        with socket.socket() as occupied:
            occupied.bind((address, 0))
            occupied.listen()
            req = dict(self.req, bind_address=address, port=occupied.getsockname()[1])
            # Real occupied local RFC1918 port; no user files are served.
            with patch('preflight.interfaces', return_value=[{'address': address}]), patch('preflight.verify_probe'):
                normalized, report, _ = preflight.run(req, self.root, req['file_paths'], req['host_context'])
            self.assertIn('port_in_use', [c['reason_code'] for c in report['checks']])
            self.assertFalse(report['can_start'])
            self.assertEqual(occupied.getsockname()[1], req['port'])
            with socket.create_connection((address, req['port']), timeout=.2):
                pass

    def test_stale_status_cannot_publish_or_stop_by_pid(self):
        root = core.workspace(self.root)
        sid = secrets.token_hex(16)
        directory = session.directory_for(root, sid)
        directory.mkdir(mode=0o700)
        core.save(directory / 'state.json', {'state': 'ready', 'heartbeat_at': time.time() - 20})
        self.assertEqual(session.status(root, sid)['state'], 'unverified_stale')
        self.assertEqual(session.stop(root, sid)['reason_code'], 'owner_unverified')
        self.assertCode('invalid_identifier', lambda: session.directory_for(root, '../outside'))


class LifecycleTests(Fixture):
    def make_preparing(self):
        root = core.workspace(self.root)
        sid = secrets.token_hex(16)
        directory = session.directory_for(root, sid)
        directory.mkdir(mode=0o700)
        manifest = core.inspect_sources(self.req['file_paths'])
        core.save(directory / 'state.json', dict(state='preparing', session_id=sid,
                  owner_instance=secrets.token_hex(32), heartbeat_at=time.time(), files=[], last_error=None))
        core.save(directory / 'secrets.json', {'access_token': secrets.token_hex(32), 'control_token': secrets.token_hex(32)})
        core.save(directory / 'source-manifest.json', manifest)
        core.save(directory / 'request.json', {'request': self.req, 'host_attestation': self.req['host_context'], 'admitted_at': time.time()})
        return root, sid, directory, manifest

    def test_blocked_preflight_never_launches_service(self):
        with patch('session.run', return_value=(self.req, {'can_start': False}, [])), patch('session.launch') as launch:
            result = session.start(self.req, self.root, self.req['file_paths'], self.req['host_context'], None)
        self.assertEqual(result['state'], 'blocked')
        self.assertFalse(result['can_publish'])
        launch.assert_not_called()

    def test_bind_failure_cleans_private_inputs_and_copies(self):
        root, sid, directory, manifest = self.make_preparing()
        with patch('session.run', return_value=(self.req, {'can_start': True}, manifest)), patch('session.ShareServer', side_effect=OSError('synthetic failure')):
            session.worker(root, sid)
        self.assertEqual(core.load(directory / 'state.json')['state'], 'failed')
        self.assertTrue(session.status(root, sid)['temporary_resources_removed'])
        self.assertFalse((directory / 'request.json').exists())
        self.assertFalse((directory / 'source-manifest.json').exists())
        self.assertEqual(self.source.read_bytes(), '纯合成测试资料\n'.encode() * 100)

    def test_preparing_cancellation_has_no_listener_and_cleans(self):
        root, sid, directory, manifest = self.make_preparing()
        state = core.load(directory / 'state.json')
        secret = core.load(directory / 'secrets.json')
        core.save(directory / 'control.json', dict(schema_version='1.0', session_id=sid,
                  owner_instance=state['owner_instance'], control_token=secret['control_token'], requested_at=time.time()))
        with patch('session.ShareServer') as server:
            session.worker(root, sid)
        server.assert_not_called()
        self.assertEqual(session.status(root, sid)['state'], 'stopped')
        self.assertTrue(session.status(root, sid)['temporary_resources_removed'])

    def test_expired_admission_never_binds(self):
        root, sid, directory, manifest = self.make_preparing()
        value = core.load(directory / 'request.json')
        value['admitted_at'] -= 31
        core.save(directory / 'request.json', value)
        with patch('session.ShareServer') as server:
            session.worker(root, sid)
        server.assert_not_called()
        self.assertEqual(core.load(directory / 'state.json')['last_error'], 'preflight_expired')
        self.assertTrue(session.status(root, sid)['temporary_resources_removed'])

    def test_qr_failure_after_bind_closes_owned_socket(self):
        root, sid, directory, manifest = self.make_preparing()
        import segno
        class FailedQR:
            def save(self, *args, **kwargs):
                raise OSError('synthetic QR failure')
        with patch('session.run', return_value=(self.req, {'can_start': True}, manifest)), patch('session.ShareServer') as server, patch.object(segno, 'make_qr', return_value=FailedQR()):
            server.return_value.server_address = ('127.0.0.1', 12345)
            session.worker(root, sid)
        server.return_value.server_close.assert_called_once()
        server.return_value.server_activate.assert_not_called()
        self.assertEqual(session.status(root, sid)['state'], 'failed')
        self.assertTrue(session.status(root, sid)['temporary_resources_removed'])


class FakeDeadline:
    def __init__(self):
        self.expired = False
    def due(self):
        return self.expired


class HTTPTests(Fixture):
    def setUp(self):
        super().setUp()
        self.directory = self.base / 'share'
        self.directory.mkdir(mode=0o700)
        self.files = core.snapshot(core.inspect_sources([str(self.source)]), self.directory / 'snapshots')
        self.token = secrets.token_hex(32)
        self.clock = FakeDeadline()
        self.state = {'title': '<script>alert(1)</script> @@FILES@@', 'files': self.files, 'expires_at': core.utc(time.time()+60),
                      'session_id': secrets.token_hex(16), 'owner_instance': secrets.token_hex(32), 'request_digest': 'a'*64}
        self.server = ShareServer(('127.0.0.1', 0), self.directory, self.state, self.token, self.clock)
        self.server.server_activate()
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .02}, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.revoke()
        self.thread.join(timeout=1)
        super().tearDown()

    def request(self, suffix='', headers=None, method='GET', path=None):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=2)
        try:
            connection.request(method, path if path is not None else self.server.prefix + suffix, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_exact_snapshot_hash_and_header(self):
        status, headers, data = self.request('files/' + self.files[0]['file_id'])
        self.assertEqual(status, 200)
        self.assertEqual(data, self.source.read_bytes())
        self.assertEqual(headers['Content-Type'], 'application/octet-stream')
        self.assertIn('attachment;', headers['Content-Disposition'])
        self.assertIn("filename*=UTF-8''", headers['Content-Disposition'])
        self.assertEqual(headers['Cache-Control'], 'no-store, max-age=0')
        self.assertEqual(headers['Referrer-Policy'], 'no-referrer')
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.source.write_bytes(b'subsequent change')
        self.assertEqual(self.request('files/' + self.files[0]['file_id'])[2], data)

    def test_untrusted_paths_tokens_host_and_origin(self):
        for path in ('/', '/s/' + '0'*64 + '/', self.server.prefix + '../state.json', self.server.prefix + 'files/../../secret', self.server.prefix + '%2e%2e/', self.server.prefix + '?x=1', self.server.prefix + 'files/' + '0'*32, self.server.prefix + 'qr.png'):
            self.assertEqual(self.request(path=path)[0], 404)
        self.assertEqual(self.request(headers={'Host': 'evil.example'})[0], 403)
        self.assertEqual(self.request(headers={'Origin': 'http://evil.example'})[0], 403)
        self.assertNotIn(self.token.encode(), self.request(path='/')[2])

    def test_html_escape_and_no_external_resources(self):
        status, headers, body = self.request()
        self.assertEqual(status, 200)
        self.assertIn(b'&lt;script&gt;', body)
        self.assertNotIn(b'<script>alert(1)</script>', body)
        self.assertIn(b'@@FILES@@', body)  # user text is not recursively interpolated
        self.assertNotIn(b'http://', body)
        self.assertIn('sha256-', headers['Content-Security-Policy'])

    def test_health_nonce_and_owner(self):
        challenge = secrets.token_hex(16)
        status, _, data = self.request('health', {'X-Lan-Challenge': challenge})
        value = json.loads(data)
        self.assertEqual(status, 200)
        self.assertEqual(value['challenge'], challenge)
        self.assertEqual(value['owner_instance'], self.state['owner_instance'])
        self.assertNotIn('control_token', value)
        self.assertEqual(self.request('health')[0], 400)

    def test_two_download_limit(self):
        self.server.downloads.acquire()
        self.server.downloads.acquire()
        try:
            self.assertEqual(self.request('files/' + self.files[0]['file_id'])[0], 503)
        finally:
            self.server.downloads.release()
            self.server.downloads.release()
        self.assertEqual(self.request('files/' + self.files[0]['file_id'])[0], 200)

    def test_authoritative_deadline_denies_refresh_and_download(self):
        self.clock.expired = True
        self.assertEqual(self.request()[0], 410)
        self.assertEqual(self.request('files/' + self.files[0]['file_id'])[0], 410)

    def test_revoke_closes_listener_and_active_transfer(self):
        # Bigger than socket buffers; receiver deliberately does not consume body.
        snap = self.directory / self.files[0]['snapshot_relative_path']
        with open(snap, 'wb') as stream:
            stream.truncate(64 * 1024 * 1024)
        self.files[0]['size_bytes'] = snap.stat().st_size
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=2)
        connection.request('GET', self.server.prefix + 'files/' + self.files[0]['file_id'])
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        began = time.monotonic()
        self.clock.expired = True
        self.server.revoke()
        self.assertLess(time.monotonic() - began, 2)
        received = 0
        while True:
            try:
                block = response.read(1024 * 1024)
            except http.client.IncompleteRead as e:
                received += len(e.partial)
                break
            if not block:
                break
            received += len(block)
        self.assertLess(received, self.files[0]['size_bytes'])
        connection.close()
        with self.assertRaises(OSError):
            socket.create_connection(self.server.server_address, timeout=.2)


if __name__ == '__main__':
    unittest.main()
