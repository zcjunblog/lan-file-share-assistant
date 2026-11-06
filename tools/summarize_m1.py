"""Publish only allowlisted aggregate M1 observations, never local IPs/paths/PIDs."""
import argparse
import json
from pathlib import Path
import subprocess


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def summarize(root):
    profiles = []
    for name in ('system-python', 'with-qr'):
        observed = read(root/name/'environment.json')
        assert observed['http_service_started'] is False
        assert all(row['listened'] is False for row in observed['bind_probes'])
        qr = observed['qr']
        profiles.append({'profile': name, 'python': observed['python'], 'platform': observed['platform'],
                         'qr_status': qr['status'], 'qr_library_version': qr.get('segno_version'),
                         'qr_independent_decode': qr.get('independent_decode', 'not_tested'),
                         'candidate_count': len(observed['network']['candidates']),
                         'bind_and_close_count': sum(row['status']=='bound_and_closed' for row in observed['bind_probes']),
                         'collision_rejection_count': sum(row.get('collision_rejected') is True for row in observed['bind_probes']),
                         'synthetic_read_write': observed['files']['workspace_write_read'],
                         'synthetic_replacement_detected': observed['files']['replacement_detected'],
                         'symlink_detected': observed['files']['symlink_lstat_detected'],
                         'nofollow_available': observed['files']['nofollow_flag_available'],
                         'receiver_reachability': 'not_tested', 'listener_started': False})
    owner = read(root/'lifecycle/owner.json')
    observation = read(root/'lifecycle/observation.json')
    done = read(root/'lifecycle/done.json')
    assert owner['nonce'] == done['nonce']
    assert observation['heartbeat_after_parent_return'] is True
    assert done['network_used'] is False
    assert done['elapsed_monotonic'] >= owner['limit_seconds']-.1
    # Look up only this known probe PID; never signal or stop an unrelated process.
    process = subprocess.run(['/bin/ps', '-p', str(owner['pid']), '-o', 'args='], capture_output=True, text=True, timeout=3)
    owned_running = process.returncode == 0 and owner['nonce'] in process.stdout
    assert not owned_running, 'Wait for the bounded probe to self-exit before publishing evidence'
    return {'stage': 'M1', 'date': '2026-11-06', 'profiles': profiles,
            'bounded_child': {'heartbeat_across_tool_calls': True, 'self_ended': True,
                              'elapsed_seconds': round(done['elapsed_monotonic'], 3),
                              'owned_process_still_running': owned_running, 'network_used': False},
            'limits': {'actual_phone_download': 'not_tested', 'other_clients': 'not_tested',
                       'windows_linux_cloud_sandbox': 'synthetic_cases_only',
                       'sleep_and_clock_changes': 'reference_rule_only',
                       'production_preflight_and_file_service': 'not_implemented',
                       'full_session_background_lifetime': 'not_tested'}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('outputs/m1'))
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
