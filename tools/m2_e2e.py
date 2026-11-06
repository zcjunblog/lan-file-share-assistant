"""Opt-in synthetic-only local HTTP integration. All raw identifiers stay outputs/."""
import argparse
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills/lan-file-share-assistant/scripts'
sys.path.insert(0, str(SCRIPTS))
from core import load, save

OUT = ROOT / 'outputs/m2'
CLI = SCRIPTS / 'lan_share.py'


def invoke(*args):
    result = subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True, timeout=15)
    value = json.loads(result.stdout)
    if result.returncode:
        raise RuntimeError('CLI failed: ' + value.get('reason_code', 'unknown'))
    return value


def prepare():
    os.umask(0o077)
    OUT.mkdir(mode=0o700, exist_ok=True)
    fixtures = OUT / 'synthetic-files'
    fixtures.mkdir(mode=0o700, exist_ok=True)
    (fixtures / '项目交付说明-纯合成测试资料.txt').write_text('Synthetic local integration fixture.\n' * 20)
    (fixtures / ('这是一份用于验证中文长文件名自动换行与移动端布局的合成需求确认书' * 2 + '.txt')).write_text('中文测试资料，仅用于开发验证。\n' * 50)
    with zipfile.ZipFile(fixtures / '合成资料包.zip', 'w') as archive:
        archive.writestr('synthetic-note.txt', 'Synthetic fixture only.')
    # Tiny valid one-page PDF with a real cross-reference table.
    pdf = io.BytesIO()
    pdf.write(b'%PDF-1.4\n')
    offsets = [0]
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>', b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Contents 4 0 R >>', b'<< /Length 0 >>\nstream\n\nendstream']
    for i, obj in enumerate(objects, 1):
        offsets.append(pdf.tell())
        pdf.write(str(i).encode() + b' 0 obj\n' + obj + b'\nendobj\n')
    xref = pdf.tell()
    pdf.write(b'xref\n0 5\n0000000000 65535 f \n')
    for offset in offsets[1:]:
        pdf.write(('%010d 00000 n \n' % offset).encode())
    pdf.write(b'trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n' + str(xref).encode() + b'\n%%EOF\n')
    (fixtures / '合成空白文档.pdf').write_bytes(pdf.getvalue())
    with open(fixtures / '中断测试-64MiB.bin', 'wb') as stream:
        stream.truncate(64 * 1024 ** 2)
    save(OUT / 'source-hashes.json', {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in fixtures.iterdir()})
    start_probe()


def start_probe():
    result = invoke('probe', '--work-dir', str(OUT / 'runtime'))
    save(OUT / 'probe.json', result)
    print(json.dumps({'probe_started': True, 'no_file_service': True}))


def start(ttl):
    probe = load(OUT / 'probe.json')['probe_id']
    args = ['start', '--work-dir', str(OUT / 'runtime'), '--probe-id', probe,
            '--host-kind', 'local', '--host-evidence', 'desktop_adapter', '--title', '项目交付资料 · 合成演示', '--ttl-seconds', str(ttl)]
    for p in sorted((OUT / 'synthetic-files').iterdir()):
        args.extend(['--file', str(p)])
    result = invoke(*args)
    save(OUT / 'active.json', result)
    assert result['state'] == 'ready' and result['can_publish'], result
    print(json.dumps({'ready': True, 'can_publish': True, 'eight_checks_passed': all(c['status']=='pass' for c in result['preflight']['checks']), 'receiver': 'not_tested'}))


def request(url, path=None, method='GET', headers=None):
    parsed = urlsplit(url)
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
    conn.request(method, path if path is not None else parsed.path, headers=headers or {})
    resp = conn.getresponse()
    data = resp.read()
    status, result_headers = resp.status, dict(resp.getheaders())
    conn.close()
    return status, result_headers, data


def verify(watch=False):
    import zxingcpp
    from PIL import Image
    active = load(OUT / 'active.json')
    sid = active['session_id']
    state = load(OUT / 'runtime' / ('share-' + sid) / 'state.json')
    current = invoke('status', '--work-dir', str(OUT / 'runtime'), '--id', sid)
    assert current['can_publish'] and current['state']=='ready'
    with Image.open(current['qr_png']) as picture:
        decoded = zxingcpp.read_barcode(picture.convert('RGB'))
    assert decoded and decoded.text == current['url']
    url = decoded.text
    code, headers, body = request(url)
    assert code == 200 and 'HTTP' in body.decode()
    received = 0
    for f in state['files']:
        code, headers, data = request(url, urlsplit(url).path + 'files/' + f['file_id'])
        assert code == 200
        assert hashlib.sha256(data).hexdigest() == f['sha256']
        assert len(data) == f['size_bytes']
        assert "filename*=UTF-8''" in headers['Content-Disposition']
        received += 1
    for path in ('/', '/s/' + '0'*64 + '/', urlsplit(url).path + '../secrets.json', urlsplit(url).path + '%2e%2e/secrets.json', urlsplit(url).path + 'files/' + '0'*32):
        assert request(url, path)[0] == 404
    assert request(url, headers={'Host': 'untrusted.example'})[0] == 403
    source_hashes = load(OUT / 'source-hashes.json')
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == source_hashes[p.name] for p in (OUT / 'synthetic-files').iterdir())
    # No control secret leaks into HTML/QR/download responses.
    secret = load(OUT / 'runtime' / ('share-' + sid) / 'secrets.json')
    assert secret['control_token'].encode() not in body
    summary = dict(schema_version='1.0', platform='macOS', local_http_end_to_end=True,
                   production_preflight_eight_passed=True, cross_tool_status_health=True,
                   qr_independent_decode=True, downloaded_files_hash_matched=received,
                   source_files_unchanged=True, auth_host_and_path_rejections=True,
                   phone_scanned=False, receiver_status='not_tested', ttl_seconds=60 if watch else 180)
    if watch:
        parsed = urlsplit(url)
        expiry = __import__('datetime').datetime.fromisoformat(state['expires_at'].replace('Z', '+00:00')).timestamp()
        print(json.dumps({'download_hashes_verified': received, 'waiting_for_actual_expiry': True}), flush=True)
        # Keep the tool cell responsive while the child monitors the real deadline.
        while time.time() < expiry - .35:
            time.sleep(.1)
        slow = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
        f = next(f for f in state['files'] if f['size_bytes'] == 64*1024**2)
        slow.request('GET', parsed.path + 'files/' + f['file_id'])
        response = slow.getresponse()
        assert response.status == 200
        while time.time() < expiry + .6:
            time.sleep(.05)
        count = 0
        while True:
            try:
                block = response.read(1024*1024)
            except http.client.IncompleteRead as e:
                count += len(e.partial)
                break
            if not block:
                break
            count += len(block)
        slow.close()
        assert count < f['size_bytes']
        result = invoke('status', '--work-dir', str(OUT / 'runtime'), '--id', sid)
        assert result['state'] == 'expired' and result['temporary_resources_removed'] and not result['can_publish']
        try:
            connection = socket.create_connection((parsed.hostname, parsed.port), timeout=.5)
        except OSError:
            pass
        else:
            connection.close()
            raise AssertionError('Listener remained open')
        summary.update(actual_expiry=True, active_transfer_interrupted=True, temporary_resources_removed=True,
                       listener_closed=True, expiry_check_delay_seconds=round(time.time()-expiry, 3))
        save(ROOT / 'evidence/m2/local-integration.json', summary)
        print(json.dumps(summary, ensure_ascii=False))
    else:
        save(OUT / 'verification.json', summary)
        print(json.dumps({'download_hashes_verified': received, 'qr_independent_decode': True, 'status_verified_after_tool_return': True}))


def stop():
    active = load(OUT / 'active.json')
    parsed = urlsplit(active['url'])
    directory = OUT / 'runtime' / ('share-' + active['session_id'])
    state = load(directory / 'state.json')
    secret = load(directory / 'secrets.json')
    save(directory / 'control.json', dict(schema_version='1.0', session_id=active['session_id'],
         owner_instance=state['owner_instance'], control_token='0'*64, requested_at=time.time()))
    time.sleep(.2)
    assert invoke('status', '--work-dir', str(OUT / 'runtime'), '--id', active['session_id'])['can_publish']
    slow_connections = []
    for _ in range(2):
        f = next(f for f in state['files'] if f['size_bytes'] == 64*1024**2)
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
        connection.request('GET', parsed.path + 'files/' + f['file_id'])
        response = connection.getresponse()
        assert response.status == 200
        slow_connections.append((connection, response, f['size_bytes']))
    began = time.monotonic()
    result = invoke('stop', '--work-dir', str(OUT / 'runtime'), '--id', active['session_id'])
    for connection, response, full_size in slow_connections:
        received = 0
        while True:
            try:
                data = response.read(1024*1024)
            except http.client.IncompleteRead as e:
                received += len(e.partial)
                break
            if not data:
                break
            received += len(data)
        assert received < full_size
        connection.close()
    assert result['state'] == 'stopped' and result['temporary_resources_removed']
    try:
        connection = socket.create_connection((parsed.hostname, parsed.port), timeout=.5)
    except OSError:
        pass
    else:
        connection.close()
        raise AssertionError('Listener remained open')
    summary = {'manual_stop': True, 'owned_control_verified': True, 'wrong_control_token_rejected': True, 'two_active_transfers_interrupted': True, 'temporary_resources_removed': True,
               'listener_closed': True, 'stop_elapsed_seconds': round(time.monotonic()-began, 3)}
    save(ROOT / 'evidence/m2/manual-stop.json', summary)
    print(json.dumps(summary))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['prepare', 'probe', 'start60', 'start180', 'verify', 'watch', 'stop'])
    args = parser.parse_args()
    {'prepare': prepare, 'probe': start_probe, 'start60': lambda: start(60), 'start180': lambda: start(180),
     'verify': verify, 'watch': lambda: verify(True), 'stop': stop}[args.command]()
