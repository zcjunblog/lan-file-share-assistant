"""Owned detached sessions; private local control and verified publication."""
import errno
import hmac
import http.client
import os
from pathlib import Path
import secrets
import shutil
import threading
import time
import json
import re

from core import Deadline, ShareError, create_private, digest, identifier, load, private_mkdir, save, snapshot, utc, workspace
from http_service import ShareServer
from preflight import LIMITATIONS, launch, run

TERMINAL = ('expired', 'stopped', 'failed')
SENSITIVE_FILES = ('secrets.json', 'request.json', 'source-manifest.json', 'control.json', 'qr.png', 'qr.svg')


def atomic_residue(name):
    return re.fullmatch(r'\.write-[a-f0-9]{32}', name) is not None


def resources_removed(directory):
    try:
        names = [path.name for path in directory.iterdir()]
    except OSError:
        return False
    return not any(name == 'snapshots' or name in SENSITIVE_FILES or atomic_residue(name) for name in names)


def directory_for(root, session_id):
    return root / ('share-' + identifier(session_id))


def clean(directory):
    for name in ('snapshots',):
        target = directory / name
        if target.exists():
            shutil.rmtree(target)
    for name in SENSITIVE_FILES:
        (directory / name).unlink(missing_ok=True)
    for path in directory.iterdir():
        if atomic_residue(path.name):
            path.unlink(missing_ok=True)


def start(req, root_path, authorized_paths, host_attestation, probe_id):
    normalized, report, manifest = run(req, root_path, authorized_paths, host_attestation, probe_id)
    if not report['can_start']:
        return {'preflight': report, 'state': 'blocked', 'can_publish': False}
    root = workspace(root_path)
    session_id, owner = secrets.token_hex(16), secrets.token_hex(32)
    directory = directory_for(root, session_id)
    private_mkdir(directory)
    state = dict(schema_version='1.0', session_id=session_id, owner_instance=owner,
                 request_digest=digest(normalized), state='preparing', created_at=utc(),
                 ready_at=None, expires_at=None, bind_address=normalized['bind_address'], port=None,
                 files=[], title=normalized['title'], last_error=None, heartbeat_at=time.time())
    launching = False
    try:
        save(directory / 'state.json', state)
        save(directory / 'secrets.json', {'access_token': secrets.token_hex(32), 'control_token': secrets.token_hex(32)})
        save(directory / 'source-manifest.json', manifest)
        save(directory / 'request.json', {'request': normalized, 'host_attestation': host_attestation,
                                         'admitted_at': time.time(), 'probe_id': probe_id})
        launching = True
        launch('_worker', root, session_id)
    except (OSError, ShareError) as error:
        reason = error.code if isinstance(error, ShareError) else 'execution_forbidden' if launching else 'insufficient_space' if error.errno == errno.ENOSPC else 'local_setup_failed'
        try:
            clean(directory)
        except OSError:
            reason = 'cleanup_incomplete'
        state.update(state='failed', last_error=reason)
        try:
            save(directory / 'state.json', state)
        except (OSError, ShareError):
            pass  # A full/unwritable volume must not prevent credential revocation.
        return {'session_id': session_id, 'state': 'failed', 'can_publish': False, 'reason_code': reason,
                'summary': '本机准备或执行失败，未开放分享。',
                'remediation': ['检查专用目录空间、权限和程序执行条件后重新预检。'],
                'temporary_resources_removed': resources_removed(directory)}
    # Large copies stay preparing; no unverified URL is exposed.
    until = time.monotonic() + 2
    while time.monotonic() < until:
        current = load(directory / 'state.json')
        if current['state'] != 'preparing':
            break
        time.sleep(.05)
    result = status(root, session_id)
    result['preflight'] = report
    return result


def control_valid(directory, state, control_token):
    try:
        value = load(directory / 'control.json')
        return (value['schema_version'] == '1.0' and value['session_id'] == state['session_id'] and
                hmac.compare_digest(value['owner_instance'], state['owner_instance']) and
                hmac.compare_digest(value['control_token'], control_token) and
                0 <= time.time() - value['requested_at'] <= 30)
    except (OSError, KeyError, ValueError, TypeError):
        return False


def worker(root, session_id):
    os.umask(0o077)
    directory = directory_for(root, session_id)
    state = load(directory / 'state.json')
    server, thread = None, None
    outcome = 'failed'
    try:
        admission = load(directory / 'request.json')
        if not 0 <= time.time() - admission['admitted_at'] < 30:
            raise ShareError('preflight_expired', '启动凭证过时，未开放分享。')
        req = admission['request']
        manifest = load(directory / 'source-manifest.json')
        started = time.monotonic()
        secret = load(directory / 'secrets.json')

        def progress():
            if control_valid(directory, state, secret['control_token']):
                raise ShareError('stop_requested', '准备阶段已响应停止。')
            if time.monotonic() - started > 120:
                raise ShareError('preparation_timeout', '文件准备超过120秒，未开放分享。', '减少本次文件大小或数量后重试。')
            state['heartbeat_at'] = time.time()
            save(directory / 'state.json', state)

        files = snapshot(manifest, directory / 'snapshots', progress)
        progress()
        # All dynamic checks refreshed after copying, before bind/listen. The running
        # worker was admitted using the just-observed cross-call probe.
        normalized, report, latest = run(req, root, req['file_paths'], admission['host_attestation'], worker_verified=True, reserved_bytes=sum(f['size_bytes'] for f in manifest))
        save(directory / 'preflight.json', report)
        if not report['can_start'] or latest != manifest or normalized != req:
            raise ShareError('source_changed' if latest != manifest else 'preflight_failed', '准备后复检未通过，未开放分享。')
        secret = load(directory / 'secrets.json')
        deadline = Deadline(req['ttl_seconds'])
        state.update(files=files, ready_at=utc(), expires_at=utc(deadline.wall))
        server = ShareServer((req['bind_address'], req['port']), directory, state, secret['access_token'], deadline)
        state['port'] = server.server_address[1]
        url = 'http://%s:%d/s/%s/' % (state['bind_address'], state['port'], secret['access_token'])
        import segno
        qr = segno.make_qr(url, error='m')
        for kind in ('png', 'svg'):
            target = directory / ('qr.' + kind)
            descriptor = create_private(target)
            os.close(descriptor)
            qr.save(str(target), scale=8, border=4)
            os.chmod(str(target), 0o600)
        if deadline.due():
            raise ShareError('startup_expired', '启动准备时已达到截止时间。')
        server.server_activate()
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
        thread.start()
        if not verified_health(state, secret['access_token'], verify_files=True):
            raise ShareError('health_unverified', '启动自检未通过，未发布链接。')
        state.update(state='ready', heartbeat_at=time.time())
        save(directory / 'state.json', state)
        while True:
            if deadline.due():
                outcome = 'expired'
                break
            if control_valid(directory, state, secret['control_token']):
                outcome = 'stopped'
                break
            if not thread.is_alive():
                raise ShareError('lifecycle_unavailable', '服务线程意外停止。')
            state['heartbeat_at'] = time.time()
            save(directory / 'state.json', state)
            time.sleep(.1)
    except ShareError as e:
        if e.code == 'stop_requested':
            outcome = 'stopped'
        else:
            state['last_error'] = e.code
            state['error_summary'] = e.message
            state['remediation'] = [e.remedy]
    except OSError as e:
        state['last_error'] = 'insufficient_space' if e.errno == errno.ENOSPC else 'local_io_failed'
        state['error_summary'] = '本机读写或绑定失败，分享已终止。'
        state['remediation'] = ['检查指定文件、私有目录空间、权限与端口后重新预检。']
    except Exception as e:
        # Record only error type: messages can contain paths, tokens or addresses.
        state['last_error'] = 'startup_' + type(e).__name__.lower()
    finally:
        state['state'] = 'stopping'
        try:
            save(directory / 'state.json', state)
        except (OSError, ShareError):
            state['last_error'] = 'state_write_failed'
        if server:
            if thread and thread.is_alive():
                server.revoke()
                thread.join(timeout=1)
            else:
                server.server_close()
        try:
            clean(directory)
        except OSError:
            state['last_error'] = 'cleanup_incomplete'
            outcome = 'failed'
        state.update(state=outcome, ended_at=utc(), heartbeat_at=time.time(), files=[])
        save(directory / 'state.json', state)


def verified_health(state, access_token, verify_files=False):
    challenge = secrets.token_hex(16)
    connection = http.client.HTTPConnection(state['bind_address'], state['port'], timeout=1)
    try:
        connection.request('GET', '/s/' + access_token + '/health', headers={'X-Lan-Challenge': challenge})
        response = connection.getresponse()
        payload = json.loads(response.read(4096))
        if response.status != 200 or any(payload.get(k) != state[k] for k in ('session_id', 'owner_instance', 'request_digest')) or payload.get('challenge') != challenge:
            return False
        # Verify access to each snapshot before revealing a share link.
        for item in state['files'] if verify_files else []:
            connection.close()
            connection = http.client.HTTPConnection(state['bind_address'], state['port'], timeout=1)
            connection.request('HEAD', '/s/' + access_token + '/files/' + item['file_id'])
            response = connection.getresponse()
            if response.status != 200 or response.getheader('Content-Length') != str(item['size_bytes']):
                return False
            response.read()
        return True
    except (OSError, ValueError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def status(root, session_id):
    directory = directory_for(root, session_id)
    try:
        state = load(directory / 'state.json')
    except ValueError:
        return {'session_id': session_id, 'state': 'unverified_stale', 'can_publish': False,
                'reason_code': 'state_unreadable',
                'remediation': '会话状态损坏，无法核验归属；保留私有目录，不恢复链接或按PID停止进程。'}
    except OSError:
        raise ShareError('session_missing', '找不到本项目会话。') from None
    result = {'session_id': session_id, 'state': state['state'], 'can_publish': False,
              'receiver_status': 'not_tested'}
    if state['state'] in TERMINAL:
        result.update(reason_code=state['last_error'], temporary_resources_removed=resources_removed(directory))
        if state.get('error_summary'):
            result.update(summary=state['error_summary'], remediation=state['remediation'])
        if state['state'] == 'failed' and (directory / 'preflight.json').exists():
            result['preflight'] = load(directory / 'preflight.json')
        return result
    age = time.time() - state['heartbeat_at']
    if not 0 <= age <= 3:
        result.update(state='unverified_stale', reason_code='heartbeat_stale', remediation='未核实进程，不能展示链接；不要按PID或端口终止其他进程。')
        return result
    if state['state'] != 'ready':
        return result
    try:
        secret = load(directory / 'secrets.json')
        healthy = verified_health(state, secret['access_token'])
    except (OSError, KeyError, ValueError):
        healthy = False
    if not healthy:
        result.update(state='unverified_stale', reason_code='health_unverified')
        return result
    # The authoritative service has answered; re-read to avoid publishing a known terminal state.
    if load(directory / 'state.json')['state'] != 'ready':
        return status(root, session_id)
    result.update(can_publish=True, url='http://%s:%s/s/%s/' % (state['bind_address'], state['port'], secret['access_token']),
                  qr_png=str(directory / 'qr.png'), qr_svg=str(directory / 'qr.svg'), expires_at=state['expires_at'],
                  files=[{k: f[k] for k in ('download_name', 'size_bytes', 'sha256')} for f in state['files']],
                  limitations=LIMITATIONS)
    return result


def stop(root, session_id):
    directory = directory_for(root, session_id)
    try:
        state = load(directory / 'state.json')
    except (ValueError, OSError):
        return status(root, session_id)
    if state['state'] in TERMINAL:
        return status(root, session_id)
    if state['state'] not in ('ready', 'preparing') or not 0 <= time.time() - state['heartbeat_at'] <= 3:
        return {'session_id': session_id, 'state': 'unverified_stale', 'can_publish': False,
                'reason_code': 'owner_unverified', 'remediation': '无法核验正在服务的会话；不要按PID或端口停止其他进程。'}
    secret = load(directory / 'secrets.json')
    if state['state'] == 'ready' and not verified_health(state, secret['access_token']):
        return {'session_id': session_id, 'state': 'unverified_stale', 'can_publish': False, 'reason_code': 'owner_unverified'}
    save(directory / 'control.json', dict(schema_version='1.0', session_id=session_id,
         owner_instance=state['owner_instance'], control_token=secret['control_token'], requested_at=time.time()))
    until = time.monotonic() + 3
    while time.monotonic() < until:
        if load(directory / 'state.json')['state'] in TERMINAL:
            break
        time.sleep(.05)
    return status(root, session_id)
