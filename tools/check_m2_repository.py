"""Read-only pre-sync privacy/link audit. Never print matched secret values."""
import ipaddress
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def main():
    paths = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT).decode().split('\0')
    paths = [p for p in paths if p and (ROOT / p).is_file()]
    forbidden = {str(Path.home()).encode()}
    for p in (ROOT / 'outputs/m2').rglob('*.json'):
        try:
            value = json.loads(p.read_text())
        except (ValueError, OSError):
            continue
        def visit(v):
            if isinstance(v, dict):
                for key, item in v.items():
                    if key in ('access_token', 'control_token', 'owner_instance', 'nonce') and isinstance(item, str):
                        forbidden.add(item.encode())
                    if key == 'bind_address' and isinstance(item, str):
                        forbidden.add(item.encode())
                    if key == 'url' and isinstance(item, str):
                        parsed = urlsplit(item)
                        forbidden.add(item.encode())
                        if parsed.hostname:
                            forbidden.add(parsed.hostname.encode())
                        match = re.search('/s/([a-f0-9]{64})/', parsed.path)
                        if match:
                            forbidden.add(match[1].encode())
                    visit(item)
            elif isinstance(v, list):
                for item in v:
                    visit(item)
        visit(value)
    failures = []
    for rel in paths:
        p = ROOT / rel
        data = p.read_bytes()
        if any(item and item in data for item in forbidden):
            failures.append((rel, 'private_value'))
        if p.suffix == '.md':
            for target in re.findall(r'\]\(([^)]+)\)', data.decode('utf-8')):
                if target.startswith(('http:', 'https:', '#', 'mailto:')):
                    continue
                local = target.split('#')[0].strip('<>')
                if local and not (p.parent / local).exists():
                    failures.append((rel, 'broken_local_link'))
    ignored = ['outputs/m2/synthetic-files/合成空白文档.pdf', 'outputs/m2/active.json',
               'outputs/m2/runtime/share-test/secrets.json', 'sessions/private.json', 'share-qr-private.png']
    for rel in ignored:
        if subprocess.run(['git', 'check-ignore', '-q', rel], cwd=ROOT).returncode:
            failures.append((rel, 'not_ignored'))
    assert not failures, 'Repository audit failed: ' + repr(failures)
    print(json.dumps({'private_values_absent': True, 'local_markdown_links_valid': True,
                      'private_runtime_paths_ignored': True, 'publishable_files_checked': len(paths)}))


if __name__ == '__main__':
    main()
