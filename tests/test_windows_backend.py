"""Windows path policy plus native synthetic-file/ACL tests (no real shares)."""
import importlib.util
from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/lan-file-share-assistant/scripts'
sys.path.insert(0, str(SCRIPTS))
import core

backend = None
if importlib.util.find_spec('windows_backend'):
    import windows_backend as backend


@contextmanager
def native_stage(name):
    """Expose only fixed stage labels to the scrubbed native CI reporter."""
    try:
        yield
    except Exception as error:
        error.native_stage = name
        raise


class WindowsPathPolicyTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(backend, 'Windows secure backend is not implemented')

    def test_accepts_explicit_local_absolute_unicode_paths(self):
        for path, expected in [(r'C:\Data\合成.txt', r'C:\Data\合成.txt'),
                               ('d:/Data/test.txt', r'D:\Data\test.txt')]:
            with self.subTest(path=path):
                self.assertEqual(backend.validate_path(path), expected)

    def test_rejects_ambiguous_device_stream_and_traversal_paths(self):
        paths = ['', 'relative.txt', 'C:file.txt', r'\file.txt',
                 r'\\server\share\file', r'\\?\C:\file', r'\\.\C:\file',
                 r'C:\data\..\file', r'C:\data\.\file', r'C:\file:stream',
                 r'C:\a*.txt', r'C:\a?.txt', r'C:\a[1].txt', 'C:\\bad\nname',
                 r'C:\dir.\file', r'C:\dir \file', r'C:\NUL.txt',
                 r'C:\COM1', r'C:\lpt9.log', r'C:\con', r'C:\AUX',
                 r'C:\COM¹.txt', r'C:\LPT².txt', r'C:\CON .txt', r'C:\CLOCK$', r'C:\dir\a<.txt',
                 r'C:\dir\a|.txt', r'C:\dir\a".txt', 'C:\\dir\\\x7fname',
                 None, Path('file'), 'C:\\' + 'a' * 4100]
        for path in paths:
            with self.subTest(path=path):
                with self.assertRaises(core.ShareError):
                    backend.validate_path(path)

    @unittest.skipIf(os.name == 'nt', 'Non-Windows fail-closed contract')
    def test_native_backend_fails_closed_on_other_hosts(self):
        with self.assertRaises(core.ShareError):
            backend.runtime_available()

    def test_powershell_diagnostics_extract_only_ids_from_text_clixml_and_safe_markers(self):
        for stderr, expected in [
                ('FullyQualifiedErrorId : CouldNotAutoloadMatchingModule\n', 'CouldNotAutoloadMatchingModule'),
                ('LAN_SHARE_PS_ERROR_ID=CmdletizationQuery_NotFound,Get-NetIPAddress\n',
                 'CmdletizationQuery_NotFound,Get-NetIPAddress'),
                ('#< CLIXML\n<Objs><S S="Error">FullyQualifiedErrorId_x0020_:_x0020_'
                 'NoMatchingMSFTNetAdapterObjectsFound,Get-NetAdapter_x000D__x000A_</S></Objs>',
                 'NoMatchingMSFTNetAdapterObjectsFound,Get-NetAdapter'),
                ('private C:\\somewhere\\data.txt 192.168.1.1', 'unavailable')]:
            with self.subTest(expected=expected):
                self.assertEqual(backend._powershell_error_id(stderr), expected)


@unittest.skipUnless(os.name == 'nt', 'Requires real Windows native APIs')
class WindowsNativeTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(backend)
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.source = self.base / '合成-source.txt'
        self.source.write_bytes(b'synthetic-only\n')

    def tearDown(self):
        self.temp.cleanup()

    def test_optional_private_control_absence_is_missing_but_missing_source_is_invalid(self):
        import session
        root = backend.workspace(self.base / 'private')
        missing = root / 'control.json'
        with self.assertRaises(FileNotFoundError):
            backend.open_private(str(missing))
        self.assertFalse(session.control_valid(root, {'owner_instance': 'synthetic-owner'}, 'synthetic-token'))
        with self.assertRaises(core.ShareError) as caught:
            backend.safe_open(str(missing))
        self.assertEqual(caught.exception.code, 'source_invalid')

    def test_regular_source_descriptor_has_stable_identity_and_readonly_sharing(self):
        fd = backend.safe_open(str(self.source))
        try:
            info = os.fstat(fd)
            self.assertTrue(stat.S_ISREG(info.st_mode))
            self.assertGreater(info.st_ino, 0)
            self.assertEqual((info.st_dev, info.st_ino),
                             (self.source.stat().st_dev, self.source.stat().st_ino))
            self.assertEqual(os.read(fd, 100), b'synthetic-only\n')
            with self.assertRaises(OSError):
                os.write(fd, b'bad')
            with self.assertRaises(OSError):
                self.source.write_bytes(b'bad')
            with self.assertRaises(OSError):
                self.source.unlink()
        finally:
            os.close(fd)
        self.assertEqual(self.source.read_bytes(), b'synthetic-only\n')

    def test_private_read_handle_permits_atomic_replace_and_delete(self):
        root = backend.workspace(self.base / 'private')
        target, replacement = root / 'state.json', root / 'next.json'
        with os.fdopen(backend.create_private(str(target)), 'wb') as stream:
            stream.write(b'old')
        with os.fdopen(backend.create_private(str(replacement)), 'wb') as stream:
            stream.write(b'new')
        fd = backend.open_private(str(target))
        try:
            with native_stage('private_replace_open_target'):
                backend.replace_private(str(replacement), str(target))
            with native_stage('private_read_new_target'):
                self.assertEqual(target.read_bytes(), b'new')
            with native_stage('private_unlink_new_target'):
                target.unlink()
            with native_stage('private_read_old_handle'):
                self.assertEqual(os.read(fd, 100), b'old')
        finally:
            os.close(fd)

    def test_private_workspace_and_children_have_only_current_user_access(self):
        root = backend.workspace(self.base / 'private')
        child = root / 'child.txt'
        with os.fdopen(backend.create_private(str(child)), 'wb') as stream:
            stream.write(b'synthetic')
        backend.check_private(root)
        backend.check_private(child)
        self.assertEqual(backend.workspace(root), root)
        self.assertEqual(json.loads((root / '.lan-share-root').read_text()), {'version': 1})
        # Independent ACL inspection by the operating system, not a backend mock.
        script = ("$ErrorActionPreference='Stop';"
                  "$s=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value;"
                  "$items=@();$paths=ConvertFrom-Json $env:LAN_SHARE_TEST_PATHS;"
                  "foreach($p in $paths){$a=Get-Acl -LiteralPath $p;"
                  "$ids=@($a.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])|"
                  "ForEach-Object {$_.IdentityReference.Value});"
                  "$items+=@{owner=$a.GetOwner([Security.Principal.SecurityIdentifier]).Value;ids=$ids}};"
                  "@{sid=$s;items=$items}|ConvertTo-Json -Depth 6 -Compress")
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                                 script], capture_output=True, text=True,
                                env=dict(os.environ,
                                         PSModulePath=os.path.join(os.environ['SystemRoot'],
                                             'System32', 'WindowsPowerShell', 'v1.0', 'Modules'),
                                         LAN_SHARE_TEST_PATHS=json.dumps([str(root), str(child)])),
                                timeout=15, check=False)
        if result.returncode:
            error = subprocess.CalledProcessError(result.returncode, result.args)
            error.native_stage = 'independent_acl_powershell'
            error.powershell_error_id = backend._powershell_error_id(result.stderr)
            raise error
        acl = json.loads(result.stdout)
        for item in acl['items']:
            self.assertEqual(item['owner'], acl['sid'])
            self.assertEqual(set(item['ids']), {acl['sid']})

    def test_private_replace_creates_new_name_and_refuses_untrusted_targets(self):
        root = backend.workspace(self.base / 'private')
        original, target = root / 'temporary.bin', root / 'state.bin'
        with os.fdopen(backend.create_private(str(original)), 'wb') as stream:
            stream.write(b'synthetic')
        backend.replace_private(str(original), str(target))
        self.assertFalse(original.exists())
        self.assertEqual(target.read_bytes(), b'synthetic')
        backend.check_private(target)
        next_file = root / 'next.bin'
        with os.fdopen(backend.create_private(str(next_file)), 'wb') as stream:
            stream.write(b'replacement')
        child = backend.make_private_dir(root / 'child')
        for destination in (target.parent.parent / 'outside.bin', child / 'state.bin', child):
            with self.assertRaises(core.ShareError):
                backend.replace_private(str(next_file), str(destination))
        subprocess.run(['icacls.exe', str(target), '/grant', '*S-1-1-0:(R)'],
                       capture_output=True, timeout=10, check=True)
        with self.assertRaises(core.ShareError):
            backend.replace_private(str(next_file), str(target))
        self.assertEqual(next_file.read_bytes(), b'replacement')
        self.assertEqual(target.read_bytes(), b'synthetic')

    def test_private_creation_has_explicit_user_owner_and_refuses_existing_objects(self):
        root = backend.workspace(self.base / 'private')
        directory = backend.make_private_dir(root / 'snapshots')
        self.assertEqual(directory, root / 'snapshots')
        backend.check_private(directory)
        file = directory / 'snapshot.bin'
        fd = backend.create_private(str(file))
        try:
            self.assertEqual(os.write(fd, b'synthetic snapshot'), 18)
            with self.assertRaises(OSError):
                os.read(fd, 1)
        finally:
            os.close(fd)
        backend.check_private(file)
        self.assertEqual(file.read_bytes(), b'synthetic snapshot')
        for action in (lambda: backend.make_private_dir(directory),
                       lambda: backend.create_private(str(file)),
                       lambda: backend.create_private(str(directory)),
                       lambda: backend.make_private_dir(file)):
            with self.assertRaises(core.ShareError):
                action()
        self.assertEqual(file.read_bytes(), b'synthetic snapshot')

    def test_private_creation_refuses_unprotected_parent_and_junction(self):
        broad = self.base / 'broad-parent'
        broad.mkdir()
        subprocess.run(['icacls.exe', str(broad), '/grant', '*S-1-1-0:(OI)(CI)(R)'],
                       capture_output=True, timeout=10, check=True)
        with self.assertRaises(core.ShareError):
            backend.create_private(str(broad / 'outside-private.bin'))
        with self.assertRaises(core.ShareError):
            backend.make_private_dir(broad / 'outside-private-dir')
        root = backend.workspace(self.base / 'private')
        junction = root / 'junction'
        subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(junction), str(root)],
                       capture_output=True, timeout=10, check=True)
        try:
            with self.assertRaises(core.ShareError):
                backend.create_private(str(junction / 'file'))
            with self.assertRaises(core.ShareError):
                backend.make_private_dir(junction / 'dir')
        finally:
            junction.rmdir()

    def test_creation_walk_retains_ancestor_rename_guards(self):
        root = backend.workspace(self.base / 'private')
        directory = backend.make_private_dir(root / 'child')
        held = []
        final = backend._walk(str(directory), directory=True, private=True, held=held)
        try:
            # Holding only the final child handle would not prevent renaming its
            # parent. Creation keeps the full chain until CreateFile/Directory.
            with self.assertRaises(OSError):
                root.rename(self.base / 'renamed-private')
        finally:
            api = backend._api()
            api.k.CloseHandle(final)
            for handle in reversed(held):
                api.k.CloseHandle(handle)

    def test_refuses_unmarked_and_broad_acl_directories_and_damaged_marker(self):
        unmarked = self.base / 'unmarked'
        unmarked.mkdir()
        with self.assertRaises(core.ShareError):
            backend.workspace(unmarked)
        root = backend.workspace(self.base / 'private')
        for damaged in ('{"version":2}', '{"version":true}', '{"version":1,"extra":1}', '{broken'):
            (root / '.lan-share-root').write_text(damaged, encoding='utf-8')
            with self.assertRaises(core.ShareError):
                backend.workspace(root)
        (root / '.lan-share-root').write_text('{"version":1}', encoding='utf-8')
        subprocess.run(['icacls.exe', str(root), '/grant', '*S-1-1-0:(OI)(CI)(R)'],
                       capture_output=True, timeout=10, check=True)
        with self.assertRaises(core.ShareError):
            backend.check_private(root)
        with self.assertRaises(core.ShareError):
            backend.workspace(root)

    def test_rejects_ancestor_junction_and_final_directory_reparse(self):
        junction = self.base / 'junction'
        subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(junction), str(self.base)],
                       capture_output=True, timeout=10, check=True)
        try:
            with self.assertRaises(core.ShareError):
                backend.safe_open(str(junction / self.source.name))
            with self.assertRaises(core.ShareError):
                backend.safe_open(str(junction))
            with self.assertRaises(core.ShareError):
                backend.workspace(junction / 'private')
        finally:
            junction.rmdir()

    def test_rejects_final_file_symlink_when_creation_is_available(self):
        alias = self.base / 'alias.txt'
        try:
            alias.symlink_to(self.source)
        except OSError as exc:
            if getattr(exc, 'winerror', None) == 1314:
                self.skipTest('Windows symlink creation privilege is unavailable')
            raise
        with self.assertRaises(core.ShareError):
            backend.safe_open(str(alias))
        with self.assertRaises(core.ShareError):
            backend.open_private(str(alias))

    def test_native_clock_and_detached_process_options(self):
        backend.runtime_available()
        before = backend.continuous_seconds()
        time.sleep(.05)
        self.assertGreater(backend.continuous_seconds(), before)
        options = backend.detached_options()
        process = subprocess.Popen([sys.executable, '-c', 'pass'],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, **options)
        self.assertEqual(process.wait(timeout=10), 0)

    def test_physical_interfaces_are_rfc1918_without_modifying_network(self):
        for item in backend.interfaces():
            self.assertTrue(item['interface'])
            self.assertTrue(core.rfc1918(item['address']))


if __name__ == '__main__':
    unittest.main()
