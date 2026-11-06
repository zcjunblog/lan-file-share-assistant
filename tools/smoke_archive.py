#!/usr/bin/env python3
"""Opt-in synthetic archive acceptance; prepare/start/verify are separate calls.

Private state stays under outputs/m4. No canonical runtime modules are imported:
each CLI executes only the independently extracted package with the given Python.
"""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit
import zipfile
from distribution import ROOT, NAME, SOURCE, skill_info, source_files, workbuddy_entry

MARKER = {'tool': 'lan-skill-archive-smoke', 'schema': 1}
PAYLOAD = ('Synthetic release acceptance only.\n合成资料：需求确认书与操作说明。\n' * 100).encode('utf-8')


def require(value, label):
    if not value:
        error = RuntimeError(label)
        error.native_stage = label  # Fixed labels only; safe in hosted test diagnostics.
        raise error


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def directory(value):
    path = ROOT / value
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'physical_smoke_directory_required')
    path = path.resolve()
    require((ROOT / 'outputs/m4').resolve() in path.parents, 'ignored_m4_directory_required')
    return path


def invoke(record, *args, success=True):
    result = subprocess.run([record['python'], record['cli'], *args], cwd=record['cwd'],
                            capture_output=True, text=True, timeout=20)
    value = json.loads(result.stdout)
    if success and result.returncode:
        raise RuntimeError('extracted_cli_' + (value.get('reason_code') or 'failed'))
    return value


def prepare(out, python):
    require(not out.exists(), 'fresh_smoke_directory_required')
    fields, body, version = skill_info()
    release = ROOT / 'releases' / version
    manifest = read(release / 'manifest.json')
    require(manifest.get('name') == NAME and manifest.get('version') == version and
            manifest.get('stage') == 'release_candidate_not_submitted', 'release_identity')
    packages = manifest.get('packages')
    require(isinstance(packages, list) and len(packages) == 2 and
            {p.get('profile') for p in packages} == {'standard', 'workbuddy'}, 'two_unique_release_profiles')
    canonical = {p.relative_to(SOURCE).as_posix(): p.read_bytes() for p in source_files()}
    out.mkdir(parents=True, mode=0o700)
    interpreter = str(Path(python).absolute())
    write(out / '.archive-smoke-owner', {**MARKER, 'directory': str(out), 'python': interpreter, 'version': version})
    records = []
    for package in packages:
        require(package['profile'] in ('standard', 'workbuddy'), 'known_profile')
        archive = release / package['archive']
        require(archive.parent == release and archive.name == package['archive'], 'archive_path')
        require(hashlib.sha256(archive.read_bytes()).hexdigest() == package['sha256'], 'archive_sha256')
        target = out / (package['profile'] + ' 解压与独立运行')
        target.mkdir(mode=0o700)
        expected = dict(canonical)
        if package['profile'] == 'workbuddy':
            expected['SKILL.md'] = workbuddy_entry(fields, body, version)
        with zipfile.ZipFile(archive) as bundle:
            require(bundle.testzip() is None, 'zip_integrity')
            require(set(bundle.namelist()) == {NAME + '/' + p for p in expected}, 'exact_archive_entries')
            require(len(bundle.namelist()) == len(expected), 'no_duplicate_entries')
            for rel, data in expected.items():
                require(bundle.read(NAME + '/' + rel) == data, 'extracted_source_bytes')
                require(str(Path.home()).encode() not in data, 'no_developer_home')
                item = bundle.getinfo(NAME + '/' + rel)
                require((item.external_attr >> 16) & 0o170000 == 0o100000, 'only_regular_entries')
            bundle.extractall(target)
        fixture = target / '合成验收资料.txt'
        fixture.write_bytes(PAYLOAD)
        record = {'profile': package['profile'], 'archive_sha256': package['sha256'],
                  'files_verified': len(expected), 'python': interpreter,
                  'cli': str(target / NAME / 'scripts/lan_share.py'), 'cwd': str(target),
                  'runtime': str(target / '私有运行目录'), 'fixture': str(fixture)}
        records.append(record)
    write(out / 'proof.json', {'version': version, 'records': records})
    for record in records:
        probe = invoke(record, 'probe', '--work-dir', record['runtime'])
        record['probe_id'] = probe['probe_id']
        write(out / 'proof.json', {'version': version, 'records': records})
    print(json.dumps({'prepared_profiles': len(records), 'source_and_archive_hashes_match': True,
                      'no_file_service_started': True}))


def owned(out):
    marker = read(out / '.archive-smoke-owner')
    require(all(marker.get(k) == v for k, v in MARKER.items()) and
            marker.get('directory') == str(out), 'owned_smoke_required')
    proof = read(out / 'proof.json')
    records = proof.get('records')
    require(proof.get('version') == marker.get('version') and isinstance(records, list) and
            len(records) == 2 and {r.get('profile') for r in records} == {'standard', 'workbuddy'},
            'owned_complete_profiles')
    for record in records:
        target = out / (record['profile'] + ' 解压与独立运行')
        expected = {'cwd': target, 'cli': target / NAME / 'scripts/lan_share.py',
                    'runtime': target / '私有运行目录', 'fixture': target / '合成验收资料.txt'}
        for key, path in expected.items():
            require(record.get(key) == str(path) and
                    not any(p.is_symlink() for p in (path, *path.parents)), 'owned_record_paths')
        require(record.get('python') == marker.get('python') and Path(record['python']).is_absolute(), 'owned_interpreter')
        for key in ('probe_id', 'session_id'):
            if key in record:
                require(isinstance(record[key], str) and re.fullmatch(r'[a-f0-9]{32}', record[key]), 'owned_identifier')
        if record.get('url'):
            state = read(expected['runtime'] / ('share-' + record['session_id']) / 'state.json')
            url = urlsplit(record['url'])
            require(url.scheme == 'http' and url.hostname == state['bind_address'] and url.port == state['port'] and
                    re.fullmatch(r'/s/[a-f0-9]{64}/', url.path) and not url.query and not url.fragment,
                    'owned_listener_address')
    return proof


def start(out):
    proof = owned(out)
    for record in proof['records']:
        value = invoke(record, 'start', '--work-dir', record['runtime'], '--probe-id', record['probe_id'],
                       '--file', record['fixture'], '--title', '发布候选合成验收', '--ttl-seconds', '60',
                       '--host-kind', 'local', '--host-evidence', 'desktop_adapter')
        record['session_id'] = value['session_id']
        require(value['state'] in ('ready', 'preparing'), 'production_start')
        require(all(c['status'] == 'pass' for c in value['preflight']['checks']), 'eight_preflight_checks')
        write(out / 'proof.json', proof)
    print(json.dumps({'started_profiles': len(proof['records']), 'independent_status_pending': True}))


def closed(url):
    parsed = urlsplit(url)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(.3)
        return connection.connect_ex((parsed.hostname, parsed.port)) != 0


def wait_expired(record):
    until = time.monotonic() + 70
    while time.monotonic() < until:
        final = invoke(record, 'status', '--work-dir', record['runtime'], '--id', record['session_id'])
        if final['state'] == 'expired':
            return final
        # At the deadline HTTP health is already revoked while the worker is
        # completing cleanup. Never publish this transitional result; wait for
        # the bounded, explicit expired state and check resources afterwards.
        require(final['state'] in ('ready', 'stopping', 'unverified_stale'), 'expiry_state')
        time.sleep(.3)
    raise RuntimeError('expiry_terminal_timeout')


def verify(out):
    import zxingcpp
    from PIL import Image
    proof = owned(out)
    summaries = []
    for record in proof['records']:
        status = invoke(record, 'status', '--work-dir', record['runtime'], '--id', record['session_id'])
        require(status['state'] == 'ready' and status['can_publish'], 'independent_ready_health')
        with Image.open(status['qr_png']) as picture:
            code = zxingcpp.read_barcode(picture.convert('RGB'))
        require(code is not None and code.text == status['url'], 'independent_qr_decode')
        record['url'] = status['url']
        write(out / 'proof.json', proof)
        state = read(Path(record['runtime']) / ('share-' + record['session_id']) / 'state.json')
        parsed = urlsplit(status['url'])
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
        try:
            connection.request('GET', parsed.path + 'files/' + state['files'][0]['file_id'])
            response = connection.getresponse()
            data = response.read()
            require(response.status == 200 and data == PAYLOAD, 'complete_http_download')
            require(hashlib.sha256(data).hexdigest() == state['files'][0]['sha256'], 'http_snapshot_sha256')
            require(response.getheader('Cache-Control') == 'no-store, max-age=0', 'no_store')
        finally:
            connection.close()
        require(Path(record['fixture']).read_bytes() == PAYLOAD, 'source_unchanged')
        row = {'profile': record['profile'], 'archive_sha256': record['archive_sha256'],
               'source_files_verified': record['files_verified'], 'eight_checks_passed': True,
               'cross_invocation_probe_and_health': True, 'independent_qr_decode': True,
               'download_bytes': len(PAYLOAD), 'http_source_snapshot_sha256_match': True}
        if record['profile'] == 'standard':
            stopped = invoke(record, 'stop', '--work-dir', record['runtime'], '--id', record['session_id'])
            require(stopped['state'] == 'stopped' and stopped['temporary_resources_removed'], 'early_stop_cleanup')
            require(closed(status['url']), 'stopped_listener_closed')
            row.update(terminal_state='stopped', listener_closed=True, private_resources_removed=True)
        else:
            final = wait_expired(record)
            require(final['state'] == 'expired' and final['temporary_resources_removed'], 'real_expiry_cleanup')
            require(closed(status['url']), 'expired_listener_closed')
            row.update(terminal_state='expired', ttl_seconds=60, listener_closed=True, private_resources_removed=True)
        summaries.append(row)
    result = {'version': proof['version'], 'platform': sys.platform, 'passed': True,
              'runtime_python': subprocess.check_output([proof['records'][0]['python'], '--version'], text=True).strip(),
              'decoder_in_runtime_environment': False, 'profiles': summaries,
              'physical_receiver_tested': False, 'marketplace_parse_tested': False,
              'installed_agent_tested': False, 'real_system_sleep_tested': False}
    evidence = ROOT / 'evidence/m4'
    evidence.mkdir(parents=True, exist_ok=True)
    write(evidence / 'archive-smoke.json', result)
    print(json.dumps({'profiles_passed': len(summaries), 'real_expiry_passed': True, 'passed': True}))


def cleanup(out):
    if not out.exists():
        return
    proof = owned(out)
    for record in proof['records']:
        if record.get('session_id'):
            value = invoke(record, 'stop', '--work-dir', record['runtime'], '--id', record['session_id'])
            require(value['state'] in ('expired', 'stopped') and value['temporary_resources_removed'], 'owned_session_terminal')
            if record.get('url'):
                require(closed(record['url']), 'owned_listener_closed')
        elif record.get('probe_id'):
            probe = Path(record['runtime']) / ('probe-' + record['probe_id'])
            if not (probe / 'done.json').exists():
                owner = read(probe / 'owner.json')
                write(probe / 'stop', {'nonce': owner['nonce']})
                until = time.monotonic() + 3
                while time.monotonic() < until and not (probe / 'done.json').exists(): time.sleep(.05)
                require((probe / 'done.json').exists(), 'owned_probe_stopped')
    shutil.rmtree(out)
    print(json.dumps({'owned_smoke_resources_removed': True}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['prepare', 'start', 'verify', 'cleanup'])
    parser.add_argument('--directory', default='outputs/m4/archive-smoke')
    parser.add_argument('--python', default=sys.executable)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        out = directory(args.directory)
        if args.phase == 'prepare': prepare(out, args.python)
        else: {'start': start, 'verify': verify, 'cleanup': cleanup}[args.phase](out)
    except Exception as error:
        # State remains private and owned for cleanup; do not dump raw exceptions.
        result = {'passed': False, 'error_class': type(error).__name__}
        if type(error) is RuntimeError and re.fullmatch(r'[a-z_]{1,96}', str(error)):
            result['failure_check'] = str(error)
        print(json.dumps(result))
        sys.exit(1)
