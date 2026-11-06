"""Release invariants: portable source, deterministic ZIPs, metadata rejection."""
import importlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))


class DistributionTests(unittest.TestCase):
    def setUp(self):
        self.dist = importlib.import_module('distribution')
        self.builder = importlib.import_module('build_release')

    def test_both_profiles_have_identical_resources_and_repeatable_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            a = self.builder.build(Path(temp) / 'first')
            b = self.builder.build(Path(temp) / 'second')
            self.assertEqual([p['sha256'] for p in a['packages']], [p['sha256'] for p in b['packages']])
            unpacked = []
            for package in a['packages']:
                with zipfile.ZipFile(Path(a['directory']) / package['archive']) as archive:
                    self.assertIsNone(archive.testzip())
                    entries = {n: archive.read(n) for n in archive.namelist()}
                    self.assertTrue(all(n.startswith(self.dist.NAME + '/') for n in entries))
                    self.assertFalse(any('__pycache__' in n or '..' in Path(n).parts for n in entries))
                    self.assertIn(self.dist.NAME + '/assets/download.html', entries)
                    self.assertIn(self.dist.NAME + '/VERSION', entries)
                    unpacked.append(entries)
            entry = self.dist.NAME + '/SKILL.md'
            self.assertNotEqual(unpacked[0].pop(entry), unpacked[1].pop(entry))
            self.assertEqual(unpacked[0], unpacked[1])

    def test_mismatched_empty_or_overriding_marketplace_metadata_is_rejected(self):
        fields, body, version = self.dist.skill_info()
        profile = json.loads((ROOT / 'distribution/workbuddy.json').read_text(encoding='utf-8'))
        mutations = [{'examples_en': ['one']}, {'examples_zh': [], 'examples_en': []},
                     {'examples_en': ['', 'two', 'three']}, {'examples_en': 'wrong type'},
                     {'name': 'other-skill'}, {'version': '9.9.9'}]
        for change in mutations:
            with self.subTest(change=change), patch.object(self.dist, 'marketplace_profile', return_value={**profile, **change}):
                with self.assertRaises(ValueError):
                    self.dist.workbuddy_entry(fields, body, version)

    def test_unexpected_resources_and_symlinks_cannot_enter_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'source'
            shutil.copytree(self.dist.SOURCE, source, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            secret = source / 'secrets.json'
            secret.write_text('{}')
            with self.assertRaises(ValueError): self.dist.source_files(source)
            secret.unlink()
            (source / 'scripts' / 'outside.py').symlink_to(ROOT / 'Agent.md')
            with self.assertRaises(ValueError): self.dist.source_files(source)

    def test_packaged_internal_links_cannot_escape_or_point_to_missing_files(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'source'
            shutil.copytree(self.dist.SOURCE, source, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            for link in ('../Agent.md', 'references/not-there.md'):
                (source / 'SKILL.md').write_text('[bad](' + link + ')', encoding='utf-8')
                with self.assertRaises(ValueError): self.dist.source_files(source)

    def test_icon_metadata_cannot_reference_absent_or_external_resources(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'source'
            shutil.copytree(self.dist.SOURCE, source, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            (source / 'assets/icon-512.png').unlink()
            with self.assertRaises(ValueError): self.dist.source_files(source)

    def test_smoke_accepts_successful_terminal_response_with_null_reason(self):
        smoke = importlib.import_module('smoke_archive')
        record = {'python': 'unused', 'cli': 'unused', 'cwd': '.'}
        value = {'state': 'stopped', 'reason_code': None}
        process = SimpleNamespace(returncode=0, stdout=json.dumps(value))
        with patch.object(smoke.subprocess, 'run', return_value=process):
            self.assertEqual(smoke.invoke(record, 'stop'), value)

    def test_build_refuses_symlink_artifacts_without_touching_targets(self):
        _, _, version = self.dist.skill_info()
        names = [self.dist.NAME + '-' + version + '.zip', self.dist.NAME + '-workbuddy-' + version + '.zip',
                 'manifest.json', 'SHA256SUMS']
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp).resolve()
            sentinel = base / 'sentinel'; sentinel.write_bytes(b'keep unchanged')
            for i, name in enumerate(names):
                out = base / str(i); out.mkdir()
                (out / name).symlink_to(sentinel)
                with self.subTest(name=name):
                    with self.assertRaises(ValueError): self.builder.build(out)
                    self.assertEqual(sentinel.read_bytes(), b'keep unchanged')

    def test_unregistered_png_is_rejected_even_with_an_allowed_extension(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'source'
            shutil.copytree(self.dist.SOURCE, source, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            (source / 'assets/share-qr-private.png').write_bytes(b'synthetic private QR sentinel')
            with self.assertRaises(ValueError): self.dist.source_files(source)

    def test_markdown_link_to_excluded_cache_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'source'
            shutil.copytree(self.dist.SOURCE, source, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            cache = source / 'scripts/__pycache__/cached.pyc'; cache.parent.mkdir(); cache.write_bytes(b'cache')
            entry = source / 'SKILL.md'
            entry.write_text(entry.read_text(encoding='utf-8') + '\n[cache](scripts/__pycache__/cached.pyc)\n', encoding='utf-8')
            with self.assertRaises(ValueError): self.dist.source_files(source)

    def test_smoke_rejects_incomplete_profile_manifest_before_any_process(self):
        smoke = importlib.import_module('smoke_archive')
        _, _, version = self.dist.skill_info()
        manifest = json.loads((ROOT / 'releases' / version / 'manifest.json').read_text())
        with tempfile.TemporaryDirectory() as temp:
            for i, packages in enumerate([[], manifest['packages'][:1]]):
                with self.subTest(count=len(packages)), patch.object(smoke, 'read', return_value={**manifest, 'packages': packages}), \
                     patch.object(smoke, 'invoke', return_value={'probe_id': 'a' * 32}) as invoke:
                    with self.assertRaises(RuntimeError): smoke.prepare(Path(temp) / str(i), sys.executable)
                    invoke.assert_not_called()

    def test_copied_or_redirected_smoke_proof_is_not_owned(self):
        smoke = importlib.import_module('smoke_archive')
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp).resolve() / 'original'
            with patch.object(smoke, 'invoke', return_value={'probe_id': 'a' * 32}):
                smoke.prepare(out, sys.executable)
            copy = out.parent / 'copied'; shutil.copytree(out, copy)
            with self.subTest(case='copied'):
                with self.assertRaises(RuntimeError): smoke.owned(copy)
            proof = smoke.read(out / 'proof.json')
            proof['records'][0]['runtime'] = str(out.parent / 'unowned')
            smoke.write(out / 'proof.json', proof)
            with self.subTest(case='redirected'):
                with self.assertRaises(RuntimeError): smoke.owned(out)

    def test_expiry_acceptance_waits_through_revocation_and_health_transition(self):
        smoke = importlib.import_module('smoke_archive')
        rows = [{'state': 'ready'}, {'state': 'unverified_stale', 'can_publish': False},
                {'state': 'stopping', 'can_publish': False}, {'state': 'expired', 'can_publish': False}]
        with patch.object(smoke, 'invoke', side_effect=rows), patch.object(smoke.time, 'sleep'):
            final = smoke.wait_expired({'runtime': 'unused', 'session_id': 'a' * 32})
            self.assertEqual(final['state'], 'expired')


if __name__ == '__main__':
    unittest.main()
