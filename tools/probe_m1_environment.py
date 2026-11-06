"""Bounded M1 feasibility observations. Never listens, serves, or reads user files."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import secrets
import socket
import stat
import subprocess
import sys
import tempfile
import time


def save_new(path, value):
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def interfaces():
    """Read only OS interface metadata. Do not use DNS or contact a remote host."""
    from m1_contract import is_rfc1918
    if sys.platform != 'darwin':
        return {'status': 'not_tested', 'candidates': [], 'reason': 'Only macOS adapter evaluated in M1'}
    hardware = subprocess.run(['/usr/sbin/networksetup', '-listallhardwareports'], capture_output=True, text=True, timeout=5)
    info = subprocess.run(['/sbin/ifconfig', '-a'], capture_output=True, text=True, timeout=5)
    if hardware.returncode or info.returncode:
        return {'status': 'failed', 'candidates': [], 'reason': 'OS interface command failed'}
    physical = set(re.findall(r'^Device: (\S+)$', hardware.stdout, re.MULTILINE))
    candidates = []
    device, active = None, False
    for line in info.stdout.splitlines():
        match = re.match(r'^(\S+): flags=.*<([^>]+)>', line)
        if match:
            device, flags = match.groups()
            active = 'UP' in flags.split(',') and 'RUNNING' in flags.split(',')
        match = re.match(r'\s+inet (\S+) ', line)
        if match and active and device in physical and is_rfc1918(match.group(1)):
            candidates.append({'interface': device, 'address': match.group(1)})
    return {'status': 'observed', 'candidates': candidates, 'candidate_count': len(candidates),
            'selection': 'not_selected', 'receiver_reachability': 'not_tested'}


def binds(candidates):
    rows = []
    for row in [{'interface': 'loopback-probe-only', 'address': '127.0.0.1'}, *candidates[:3]]:
        item = {'interface': row['interface'], 'address': row['address'], 'listened': False}
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as first:
                first.bind((row['address'], 0))
                address, port = first.getsockname()
                item.update(status='bound_and_closed', port=port)
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as conflict:
                    try:
                        conflict.bind((address, port))
                        item['collision_rejected'] = False
                    except OSError as error:
                        import errno
                        item['collision_rejected'] = error.errno == errno.EADDRINUSE
        except OSError as error:
            item.update(status='failed', error_type=type(error).__name__, errno=error.errno)
        rows.append(item)
    return rows


def files_probe(work):
    with tempfile.TemporaryDirectory(prefix='synthetic-', dir=work) as directory:
        path = Path(directory)/'合成资料.txt'
        data = ('M1合成资料，仅用于本机读写与快照验证。\n'*50).encode('utf-8')
        path.write_bytes(data)
        before = path.stat()
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
        with os.fdopen(os.open(str(path), flags), 'rb') as stream:
            opened = os.fstat(stream.fileno())
            content = stream.read()
            path.rename(Path(directory)/'old.txt')
            path.write_bytes(b'replacement fixture')
            replacement_detected = (opened.st_dev, opened.st_ino) != (path.stat().st_dev, path.stat().st_ino)
        link = Path(directory)/'link.txt'
        symlink_checked = False
        try:
            link.symlink_to(path)
            symlink_checked = stat.S_ISLNK(link.lstat().st_mode)
        except (OSError, NotImplementedError):
            pass
        return {'synthetic_only': True, 'workspace_write_read': content == data,
                'ordinary_file': stat.S_ISREG(opened.st_mode), 'replacement_detected': replacement_detected,
                'symlink_lstat_detected': symlink_checked, 'nofollow_flag_available': hasattr(os, 'O_NOFOLLOW'),
                'initial_size_matches': before.st_size == len(content),
                'snapshot_sha256': hashlib.sha256(content).hexdigest()}


def qr_probe(work):
    if importlib.util.find_spec('segno') is None:
        return {'status': 'missing_dependency', 'reason_code': 'dependency_missing',
                'remediation': '在任务虚拟环境准备Segno后复检；不能以仅有Python判断扫码可用。'}
    import segno
    payload = 'https://example.invalid/lan-share-m1?fixture=二维码'
    qr = segno.make_qr(payload, error='m', encoding='utf-8')
    png, svg = work/'synthetic-qr.png', work/'synthetic-qr.svg'
    qr.save(str(png), scale=8, border=4)
    qr.save(str(svg), scale=8, border=4)
    result = {'status': 'generated', 'segno_version': importlib.metadata.version('segno'),
              'synthetic_only': True, 'png_bytes': png.stat().st_size, 'svg_bytes': svg.stat().st_size,
              'independent_decode': 'not_tested'}
    if importlib.util.find_spec('zxingcpp') is not None and importlib.util.find_spec('PIL') is not None:
        import zxingcpp
        from PIL import Image
        with Image.open(png) as picture:
            decoded = zxingcpp.read_barcode(picture.convert('RGB'))
        result['independent_decode'] = 'passed' if decoded is not None and decoded.text == payload else 'failed'
    return result


def environment(out):
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    network = interfaces()
    result = {'scope': 'M1 feasibility only, not production preflight',
              'observed_at': datetime.now(timezone.utc).isoformat(),
              'python': sys.version.split()[0], 'platform': platform.system(),
              'host_relationship': 'not_proven_by_probe', 'network': network,
              'bind_probes': binds(network['candidates']), 'files': files_probe(out), 'qr': qr_probe(out),
              'receiver_reachability': 'not_tested', 'http_service_started': False,
              'background_lifecycle': 'separate bounded probe required'}
    save_new(out/'environment.json', result)
    print(json.dumps({'saved_under_requested_directory': True, 'python': result['python'],
                      'qr_status': result['qr']['status'], 'candidate_count': len(network['candidates']),
                      'no_listener_or_file_service': True}, ensure_ascii=False))


def lifecycle_worker(out, nonce):
    # Fixed short life; no network, no user input, no kill-by-PID control.
    start_wall, start_mono = time.time(), time.monotonic()
    ticks = 0
    while time.time() < start_wall+12 and time.monotonic() < start_mono+12:
        ticks += 1
        temp = out/'heartbeat.tmp'
        temp.write_text(json.dumps({'nonce': nonce, 'ticks': ticks, 'wall': time.time()}))
        temp.replace(out/'heartbeat.json')
        time.sleep(.2)
    save_new(out/'done.json', {'nonce': nonce, 'ticks': ticks, 'ended_wall': time.time(),
                              'elapsed_monotonic': time.monotonic()-start_mono, 'network_used': False})


def lifecycle_start(out):
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    if os.name != 'posix':
        save_new(out/'owner.json', {'status': 'not_tested', 'reason': 'POSIX detached probe only'})
        return
    nonce = secrets.token_hex(16)
    process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '_worker', '--out', str(out.resolve()), '--nonce', nonce],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    save_new(out/'owner.json', {'pid': process.pid, 'nonce': nonce, 'started_wall': time.time(), 'limit_seconds': 12})
    print('Started bounded no-network child; it will exit itself within 12 seconds of scheduling.')


def lifecycle_observe(out):
    observed_after_parent = time.time()
    owner = json.loads((out/'owner.json').read_text())
    wait_until = time.monotonic()+1.5
    while True:
        heartbeat = json.loads((out/'heartbeat.json').read_text())
        if heartbeat['wall'] > observed_after_parent or time.monotonic() >= wait_until:
            break
        time.sleep(.05)
    assert owner['nonce'] == heartbeat['nonce']
    record = {'observed_wall': time.time(), 'heartbeat_after_parent_return': heartbeat['wall'] > observed_after_parent,
              'ticks': heartbeat['ticks'], 'no_network_or_listener': True}
    save_new(out/'observation.json', record)
    print(json.dumps({key: record[key] for key in ('heartbeat_after_parent_return', 'ticks', 'no_network_or_listener')}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', nargs='?', choices=('environment', 'lifecycle-start', 'lifecycle-observe', '_worker'), default='environment')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--nonce')
    args = parser.parse_args()
    if args.mode == 'environment': environment(args.out)
    elif args.mode == 'lifecycle-start': lifecycle_start(args.out)
    elif args.mode == 'lifecycle-observe': lifecycle_observe(args.out)
    else: lifecycle_worker(args.out, args.nonce)


if __name__ == '__main__':
    main()
