#!/usr/bin/env python3
"""Synthetic native acceptance, never production LAN/desktop attestation.

prepare and exercise MUST be separate processes. Private proof/state stays in
ignored outputs. Only a whitelisted result is printed; exceptions never print
paths, addresses, credentials, file names or process ownership details.
"""
import argparse
import hashlib
import http.client
import io
import json
import re
import os
from pathlib import Path
import secrets
import shutil
import socket
import stat
import sys
import threading
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'skills' / 'lan-file-share-assistant' / 'scripts'))
import core
import preflight
import session
from http_service import ShareServer

PAYLOAD = bytes(range(256)) * 2048  # 512 KiB, owned synthetic bytes only.


class AcceptanceFailure(Exception):
    pass


def require(condition, label):
    if not condition:
        raise AcceptanceFailure(label)


def output_directory(value):
    # Restrict this tool to its own ignored synthetic tree, including cleanup.
    directory = (REPO / value).resolve()
    expected = (REPO / 'outputs' / 'native-platform').resolve()
    require(directory == expected, 'synthetic_directory_required')
    return directory


def private_check(path):
    if os.name == 'nt':
        import windows_backend
        windows_backend.check_private(path)
    else:
        info = path.stat()
        require(info.st_uid == os.getuid(), 'private_owner')
        require(stat.S_IMODE(info.st_mode) == (0o700 if path.is_dir() else 0o600), 'private_mode')


def wait_for(predicate, seconds=3):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        if predicate():
            return True
        time.sleep(.025)
    return False


def prepare(out):
    require(not out.exists(), 'fresh_synthetic_directory_required')
    out.mkdir(parents=True)
    # This public fixed marker carries no private proof and has a general parent.
    (out / '.native-acceptance-owner').write_text(
        json.dumps({'schema': 1, 'tool': 'native-platform-acceptance'}), encoding='utf-8')
    source = out / 'synthetic-source.bin'
    source.write_bytes(PAYLOAD)
    if os.name == 'posix':
        source.chmod(0o600)
    root = core.workspace(out / 'runtime')
    probe = preflight.start_probe(root)
    directory = root / ('probe-' + probe['probe_id'])
    core.save(root / 'native-proof.json', {'probe_id': probe['probe_id'], 'first_heartbeat': 0})
    require(wait_for(lambda: (directory / 'heartbeat.json').exists()), 'probe_initial_heartbeat')
    hb = core.load(directory / 'heartbeat.json')
    core.save(root / 'native-proof.json', {'probe_id': probe['probe_id'], 'first_heartbeat': hb['at']})
    private_check(root)
    private_check(root / 'native-proof.json')
    print('Native synthetic preparation complete; no file service started.', flush=True)


class ComponentSession:
    """Harness-owned watchdog around real HTTP/control APIs, not a worker clone.

    No CLI TTL/admission bypass is added. This component is explicitly loopback
    only and cannot attest production LAN or a real Agent host.
    """
    def __init__(self, root, manifest, ttl):
        self.root = root
        self.session_id = secrets.token_hex(16)
        self.directory = session.directory_for(root, self.session_id)
        core.private_mkdir(self.directory)
        self.access = secrets.token_hex(32)
        self.control = secrets.token_hex(32)
        self.done = threading.Event()
        self.forced = threading.Event()
        self.error = None
        self.server = None
        self.http_thread = None
        self.watch_thread = None
        try:
            self.deadline = core.Deadline(ttl)
            self.state = dict(schema_version='1.0', session_id=self.session_id,
                              owner_instance=secrets.token_hex(32), request_digest=core.digest({'synthetic': True}),
                              state='ready', title='Native synthetic component', created_at=core.utc(),
                              ready_at=core.utc(), expires_at=core.utc(self.deadline.wall),
                              bind_address='127.0.0.1', port=None,
                              files=core.snapshot(manifest, self.directory / 'snapshots'),
                              heartbeat_at=time.time(), last_error=None)
            core.save(self.directory / 'secrets.json', {'access_token': self.access, 'control_token': self.control})
            self.server = ShareServer(('127.0.0.1', 0), self.directory, self.state, self.access, self.deadline)
            self.state['port'] = self.server.server_address[1]
            core.save(self.directory / 'state.json', self.state)
            self.server.server_activate()
            self.http_thread = threading.Thread(target=self.server.serve_forever,
                                                kwargs={'poll_interval': .025}, daemon=True)
            self.http_thread.start()
            self.watch_thread = threading.Thread(target=self.watch, daemon=True)
            self.watch_thread.start()
        except BaseException:
            if self.server:
                if self.http_thread and self.http_thread.is_alive():
                    self.server.revoke()
                    self.http_thread.join(2)
                else:
                    self.server.server_close()
            session.clean(self.directory)
            raise

    def watch(self):
        outcome = 'failed'
        try:
            # Hard bound protects this helper even if an API regresses.
            until = time.monotonic() + 12
            while time.monotonic() < until:
                if self.deadline.due():
                    outcome = 'expired'
                    break
                if self.forced.is_set() or session.control_valid(self.directory, self.state, self.control):
                    outcome = 'stopped'
                    break
                self.state['heartbeat_at'] = time.time()
                core.save(self.directory / 'state.json', self.state)
                time.sleep(.025)
        except BaseException as error:
            self.error = type(error).__name__
        finally:
            try:
                self.server.revoke()
                self.http_thread.join(2)
                session.clean(self.directory)
                self.state.update(state=outcome, ended_at=core.utc(), heartbeat_at=time.time(), files=[])
                core.save(self.directory / 'state.json', self.state)
            except BaseException as error:
                self.error = type(error).__name__
            self.done.set()

    def close(self):
        self.forced.set()
        require(self.done.wait(4), 'component_watchdog_stopped')
        self.watch_thread.join(1)
        require(not self.watch_thread.is_alive() and not self.http_thread.is_alive(), 'component_threads_stopped')
        require(self.error is None, 'component_cleanup_io')

    def listener_closed(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(.3)
            return sock.connect_ex(('127.0.0.1', self.state['port'])) != 0


def blocked_host_checks(root, source):
    for kind in ('unknown', 'remote'):
        context = {'kind': kind, 'evidence': 'none'}
        req = dict(schema_version='1.0', title='Synthetic admission rejection', file_paths=[str(source)],
                   ttl_seconds=60, bind_address=None, port=0, host_context=context, transport='http')
        _, report, _ = preflight.run(req, root, [str(source)], context)
        require(not report['can_start'] and not report['can_publish'], 'host_preflight_blocks')
        host = next(c for c in report['checks'] if c['id'] == 'host_context')
        require(host['status'] == 'fail' and host['reason_code'] in ('host_unconfirmed', 'remote_host_only'), 'host_reason')
        for name in ('runtime', 'source_files', 'workspace', 'qr'):
            require(next(c for c in report['checks'] if c['id'] == name)['status'] == 'pass', 'native_' + name)
        before = set(root.glob('share-*'))
        result = session.start(req, root, [str(source)], context, None)
        require(result['state'] == 'blocked' and not result['can_publish'], 'host_start_blocks')
        require(set(root.glob('share-*')) == before, 'host_no_session_created')


def exercise(out, summary):
    root = core.workspace(out / 'runtime')
    source = out / 'synthetic-source.bin'
    proof = core.load(root / 'native-proof.json')
    probe_dir = root / ('probe-' + core.identifier(proof['probe_id']))
    require(core.load(probe_dir / 'heartbeat.json')['at'] >= proof['first_heartbeat'], 'cross_process_proof')
    preflight.verify_probe(root, proof['probe_id'])  # Demands a new heartbeat, then authenticated stop/done.
    require((probe_dir / 'receipt.json').is_file() and (probe_dir / 'done.json').is_file(), 'probe_controlled_stop')
    summary['cross_invocation_probe'] = True
    blocked_host_checks(root, source)
    summary['unknown_and_remote_admission_blocked'] = True
    private_check(root)
    private_check(root / '.lan-share-root')
    private_check(probe_dir)
    private_check(probe_dir / 'owner.json')
    fd = core.safe_open(str(source))
    try:
        require(stat.S_ISREG(os.fstat(fd).st_mode), 'safe_source_regular')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            require(hashlib.sha256(stream.read()).digest() == hashlib.sha256(PAYLOAD).digest(), 'safe_source_digest')
    finally:
        os.close(fd)
    manifest = core.inspect_sources([str(source)])
    clock = core.ContinuousClock()
    before = clock.now()
    time.sleep(.035)
    require(clock.now() > before, 'native_clock_progress')
    summary['native_continuous_clock_progress'] = True
    try:
        candidates = core.interfaces()
        summary['physical_interface_candidates'] = len(candidates)
        summary['interface_enumeration'] = 'observed'
    except core.ShareError:
        summary['physical_interface_candidates'] = 0
        summary['interface_enumeration'] = 'unavailable_on_runner'
    component = ComponentSession(root, manifest, 10)
    try:
        item = component.state['files'][0]
        snap = component.directory / item['snapshot_relative_path']
        private_check(component.directory)
        private_check(snap.parent)
        private_check(snap)
        private_check(component.directory / 'state.json')
        with core.open_private_binary(snap) as stream:
            require(hashlib.sha256(stream.read()).hexdigest() == item['sha256'], 'snapshot_digest')
        report = session.status(root, component.session_id)
        require(report['state'] == 'ready' and report['can_publish'], 'component_status_health')
        connection = http.client.HTTPConnection('127.0.0.1', component.state['port'], timeout=3)
        try:
            connection.request('GET', '/s/' + component.access + '/files/' + item['file_id'])
            response = connection.getresponse()
            data = response.read()
            require(response.status == 200 and len(data) == len(PAYLOAD), 'http_complete_bytes')
            require(hashlib.sha256(data).hexdigest() == item['sha256'] == hashlib.sha256(PAYLOAD).hexdigest(), 'http_digest')
        finally:
            connection.close()
        # Wrong control proof cannot revoke this owned session.
        core.save(component.directory / 'control.json', dict(schema_version='1.0', session_id=component.session_id,
                  owner_instance=component.state['owner_instance'], control_token=secrets.token_hex(32), requested_at=time.time()))
        require(not session.control_valid(component.directory, component.state, component.control), 'wrong_control_rejected')
        stopped = session.stop(root, component.session_id)
        require(stopped['state'] == 'stopped' and not stopped['can_publish'] and stopped['temporary_resources_removed'], 'authenticated_stop_cleanup')
        require(component.listener_closed(), 'stop_listener_closed')
    finally:
        component.close()
    summary.update(private_workspace_and_files=True, safe_source_and_snapshot=True,
                   loopback_http_512kib_sha256=True, status_health=True,
                   wrong_control_rejected=True, authenticated_stop_cleanup=True)
    expiry = ComponentSession(root, manifest, 1.0)
    try:
        require(session.verified_health(expiry.state, expiry.access), 'expiry_initial_health')
        require(expiry.done.wait(4), 'actual_expiry_completed')
        result = session.status(root, expiry.session_id)
        require(expiry.deadline.due() and not expiry.server.valid(), 'expiry_rejects_access')
        require(result['state'] == 'expired' and not result['can_publish'] and result['temporary_resources_removed'], 'expiry_cleanup')
        require(expiry.listener_closed(), 'expiry_listener_closed')
    finally:
        expiry.close()
    require(source.read_bytes() == PAYLOAD, 'source_unchanged')
    summary['actual_component_expiry_cleanup'] = True
    summary['owned_listeners_and_threads_closed'] = True


def cleanup(out):
    """Stop only the probe whose proof this tool wrote; never kill by PID/port."""
    if not out.exists():
        return
    marker = out / '.native-acceptance-owner'
    require(marker.is_file() and json.loads(marker.read_text(encoding='utf-8')) == {'schema': 1, 'tool': 'native-platform-acceptance'},
            'cleanup_owned_directory_required')
    root = out / 'runtime'
    proof = root / 'native-proof.json'
    if proof.exists():
        value = core.load(proof)
        directory = root / ('probe-' + core.identifier(value['probe_id']))
        owner = core.load(directory / 'owner.json')
        if not (directory / 'done.json').exists():
            core.save(directory / 'stop', {'nonce': owner['nonce']})
            require(wait_for(lambda: (directory / 'done.json').exists(), 3), 'probe_cleanup_stop')
        require(core.load(directory / 'done.json')['nonce'] == owner['nonce'], 'probe_cleanup_owner')
    if out.exists():
        shutil.rmtree(out)


class ScrubbedTestResult(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.scrubbed = []

    def addError(self, test, err):
        super().addError(test, err)
        self.scrubbed.append({'test': test.id(), 'type': err[0].__name__, 'causes': error_codes(err[1])})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.scrubbed.append({'test': test.id(), 'type': err[0].__name__, 'causes': error_codes(err[1])})


def error_codes(error):
    """Only exception classes and numeric OS codes; never message/path text."""
    rows=[]
    while error is not None and len(rows)<5:
        item={'type':type(error).__name__}
        for key in ('winerror','errno'):
            value=getattr(error,key,None)
            if type(value) is int:item[key]=value
        for key in ('native_stage','powershell_error_id'):
            value=getattr(error,key,None)
            if isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_.,-]{1,160}',value):item[key]=value
        rows.append(item)
        error=error.__cause__
    return rows


def backend_tests(release=False):
    pattern = 'test_distribution.py' if release else 'test_*backend*.py'
    suite = unittest.defaultTestLoader.discover(str(REPO / 'tests'), pattern=pattern)
    result = ScrubbedTestResult()
    # Capture incidental output; only the whitelist below reaches hosted logs.
    from contextlib import redirect_stdout, redirect_stderr
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        suite.run(result)
    require(result.testsRun > 0, 'backend_tests_discovered')
    label = 'NATIVE_RELEASE_TESTS_JSON=' if release else 'NATIVE_BACKEND_TESTS_JSON='
    print(label + json.dumps({'run': result.testsRun, 'skipped': len(result.skipped),
          'passed': result.wasSuccessful(), 'failures': result.scrubbed}, sort_keys=True), flush=True)
    return result.wasSuccessful()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('prepare', 'exercise', 'cleanup', 'tests', 'release-tests'))
    parser.add_argument('--directory', default='outputs/native-platform')
    args = parser.parse_args()
    summary = dict(schema_version=1, platform=sys.platform, python='.'.join(map(str, sys.version_info[:3])),
                   scope='native_synthetic_components_only', production_lan='not_tested',
                   real_agent_client='not_tested', real_system_sleep='not_tested', passed=False)
    try:
        out = output_directory(args.directory)
        if args.phase in ('tests', 'release-tests'):
            return 0 if backend_tests(release=args.phase == 'release-tests') else 1
        if args.phase == 'prepare':
            prepare(out)
        elif args.phase == 'exercise':
            exercise(out, summary)
            summary['passed'] = True
        else:
            cleanup(out)
        return 0
    except BaseException as error:
        # No raw exception message/traceback: those can include identities/paths.
        summary['failure_type'] = type(error).__name__
        summary['failure_causes'] = error_codes(error)
        if isinstance(error, AcceptanceFailure):
            summary['failure_check'] = str(error)  # Internally fixed labels only.
        if isinstance(error, core.ShareError):
            summary['failure_code'] = error.code
        if args.phase != 'exercise':
            print('Native phase failed: ' + summary['failure_type'], flush=True)
        return 1
    finally:
        if args.phase == 'exercise':
            print('NATIVE_SUMMARY_JSON=' + json.dumps(summary, sort_keys=True), flush=True)


if __name__ == '__main__':
    sys.exit(main())
