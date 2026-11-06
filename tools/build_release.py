#!/usr/bin/env python3
"""Build deterministic, source-only standard and WorkBuddy release candidates."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import zipfile
from distribution import ROOT, SOURCE, NAME, skill_info, source_files, workbuddy_entry


def atomic_write(path, data):
    fd, temporary = tempfile.mkstemp(prefix='.release-write-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        os.replace(temporary, str(path))
    finally:
        Path(temporary).unlink(missing_ok=True)


def build(out=None):
    fields, body, version = skill_info()
    files = source_files()
    marketplace = workbuddy_entry(fields, body, version)  # Validate both before writing either.
    dest = Path(out) if out is not None else ROOT / 'releases' / version
    if dest.resolve() == SOURCE.resolve() or SOURCE.resolve() in dest.resolve().parents:
        raise ValueError('Release destination cannot overlap Skill source')
    if dest.is_symlink() or dest.exists() and not dest.is_dir():
        raise ValueError('Release destination must be a real directory')
    names = [NAME + '-' + version + '.zip', NAME + '-workbuddy-' + version + '.zip',
             'manifest.json', 'SHA256SUMS']
    if any((dest / n).is_symlink() or (dest / n).exists() and not (dest / n).is_file() for n in names):
        raise ValueError('Existing release artifacts must be ordinary files')
    dest.mkdir(parents=True, exist_ok=True)
    packages = []
    for profile in ('standard', 'workbuddy'):
        suffix = '' if profile == 'standard' else '-workbuddy'
        archive = dest / (NAME + suffix + '-' + version + '.zip')
        entries = []
        fd, temporary = tempfile.mkstemp(prefix='.release-zip-', dir=str(dest))
        try:
            with os.fdopen(fd, 'w+b') as stream, zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
                for path in files:
                    rel = path.relative_to(SOURCE).as_posix()
                    data = marketplace if profile == 'workbuddy' and rel == 'SKILL.md' else path.read_bytes()
                    info = zipfile.ZipInfo(NAME + '/' + rel, (2026, 11, 6, 0, 0, 0))
                    info.create_system = 3
                    info.external_attr = 0o100644 << 16
                    bundle.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
                    entries.append({'path': rel, 'sha256': hashlib.sha256(data).hexdigest()})
            os.replace(temporary, str(archive))
        finally:
            Path(temporary).unlink(missing_ok=True)
        with zipfile.ZipFile(archive) as bundle:
            if bundle.testzip() is not None:
                raise ValueError('Archive integrity check failed')
        packages.append({'profile': profile, 'archive': archive.name, 'bytes': archive.stat().st_size,
                         'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'files': entries})
    manifest = {'name': NAME, 'version': version, 'stage': 'release_candidate_not_submitted', 'packages': packages}
    atomic_write(dest / 'manifest.json', (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    atomic_write(dest / 'SHA256SUMS', ''.join(p['sha256'] + '  ' + p['archive'] + '\n' for p in packages).encode('utf-8'))
    return {'version': version, 'directory': str(dest.resolve()),
            'packages': [{k: v for k, v in p.items() if k != 'files'} for p in packages]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    print(json.dumps(build(parser.parse_args().out), ensure_ascii=False, indent=2))
