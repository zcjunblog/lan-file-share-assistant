"""Fail-closed native Windows primitives; importable without Windows DLLs.

No source writes, ACL rewriting of existing directories, network changes or
third-party Windows dependencies. See docs/windows-backend-notes.md.
"""
import ctypes
import ipaddress
import json
import ntpath
import os
from pathlib import Path
import re
import secrets
import subprocess

from core import ShareError


def validate_path(path):
    """Accept only unambiguous DOS-drive absolute paths, before normalizing."""
    if (not isinstance(path, str) or not path or len(path) > 4096 or
            any(ord(c) < 32 or ord(c) == 127 for c in path)):
        raise ShareError('source_invalid', '需要无控制字符的本机绝对物理路径。')
    value = path.replace('/', '\\')
    if not re.match(r'^[A-Za-z]:\\', value) or any(c in value[2:] for c in ':*?[]<>|"'):
        raise ShareError('source_invalid', '拒绝UNC、设备、备用数据流和非绝对路径。')
    components = value[3:].split('\\')
    if value == value[:3]:
        components = []
    for component in components:
        stem = component.split('.')[0].rstrip(' ').upper()
        if (not component or component in ('.', '..') or component.endswith((' ', '.')) or
                stem in ('CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$', 'CLOCK$') or
                re.fullmatch(r'(COM|LPT)[1-9¹²³]', stem)):
            raise ShareError('source_invalid', '路径含遍历、DOS保留名或尾随点/空格。')
    return value[0].upper() + value[1:]


class _Native:
    """Typed declarations are loaded only on Windows, including 64-bit handles."""
    def __init__(self):
        if os.name != 'nt':
            raise ShareError('platform_unverified', 'Windows安全后端只能在本机Windows运行。')
        from ctypes import wintypes as w
        self.w = w
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        self.a = ctypes.WinDLL('advapi32', use_last_error=True)

        class FileInfo(ctypes.Structure):
            _fields_ = [('attributes', w.DWORD), ('creation', w.FILETIME),
                        ('access', w.FILETIME), ('write', w.FILETIME),
                        ('volume', w.DWORD), ('size_high', w.DWORD), ('size_low', w.DWORD),
                        ('links', w.DWORD), ('index_high', w.DWORD), ('index_low', w.DWORD)]

        class SecurityAttributes(ctypes.Structure):
            _fields_ = [('length', w.DWORD), ('descriptor', ctypes.c_void_p),
                        ('inherit_handle', w.BOOL)]

        class AclSize(ctypes.Structure):
            _fields_ = [('count', w.DWORD), ('used', w.DWORD), ('free', w.DWORD)]

        self.FileInfo, self.SecurityAttributes, self.AclSize = FileInfo, SecurityAttributes, AclSize
        P = ctypes.c_void_p
        declarations = [
            (self.k, 'CreateFileW', [w.LPCWSTR, w.DWORD, w.DWORD, P, w.DWORD, w.DWORD, w.HANDLE], w.HANDLE),
            (self.k, 'CloseHandle', [w.HANDLE], w.BOOL),
            (self.k, 'GetFileInformationByHandle', [w.HANDLE, ctypes.POINTER(FileInfo)], w.BOOL),
            (self.k, 'GetFileType', [w.HANDLE], w.DWORD),
            (self.k, 'GetDriveTypeW', [w.LPCWSTR], w.UINT),
            (self.k, 'GetVolumeInformationW', [w.LPCWSTR, w.LPWSTR, w.DWORD,
                ctypes.POINTER(w.DWORD), ctypes.POINTER(w.DWORD), ctypes.POINTER(w.DWORD),
                w.LPWSTR, w.DWORD], w.BOOL),
            (self.k, 'GetCurrentProcess', [], w.HANDLE),
            (self.k, 'CreateDirectoryW', [w.LPCWSTR, ctypes.POINTER(SecurityAttributes)], w.BOOL),
            (self.k, 'LocalFree', [P], P),
            (self.k, 'GetTickCount64', [], ctypes.c_uint64),
            (self.a, 'OpenProcessToken', [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)], w.BOOL),
            (self.a, 'GetTokenInformation', [w.HANDLE, ctypes.c_int, P, w.DWORD,
                ctypes.POINTER(w.DWORD)], w.BOOL),
            (self.a, 'ConvertSidToStringSidW', [P, ctypes.POINTER(w.LPWSTR)], w.BOOL),
            (self.a, 'ConvertStringSecurityDescriptorToSecurityDescriptorW',
                [w.LPCWSTR, w.DWORD, ctypes.POINTER(P), ctypes.POINTER(w.DWORD)], w.BOOL),
            (self.a, 'GetSecurityInfo', [w.HANDLE, ctypes.c_int, w.DWORD,
                ctypes.POINTER(P), ctypes.POINTER(P), ctypes.POINTER(P),
                ctypes.POINTER(P), ctypes.POINTER(P)], w.DWORD),
            (self.a, 'GetSecurityDescriptorControl', [P, ctypes.POINTER(w.WORD),
                ctypes.POINTER(w.DWORD)], w.BOOL),
            (self.a, 'GetAclInformation', [P, P, w.DWORD, ctypes.c_int], w.BOOL),
            (self.a, 'GetAce', [P, w.DWORD, ctypes.POINTER(P)], w.BOOL),
            (self.a, 'IsValidSid', [P], w.BOOL),
        ]
        for library, name, arguments, result in declarations:
            function = getattr(library, name)
            function.argtypes, function.restype = arguments, result
        self.invalid_handle = ctypes.c_void_p(-1).value
        self.sid = self._process_sid()

    def error(self):
        raise ctypes.WinError(ctypes.get_last_error())

    def sid_text(self, sid):
        if not sid or not self.a.IsValidSid(sid):
            raise ValueError('Invalid SID')
        text = self.w.LPWSTR()
        if not self.a.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            self.error()
        try:
            return text.value
        finally:
            self.k.LocalFree(ctypes.cast(text, ctypes.c_void_p))

    def _process_sid(self):
        token = self.w.HANDLE()
        if not self.a.OpenProcessToken(self.k.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
            self.error()
        try:
            length = self.w.DWORD()
            self.a.GetTokenInformation(token, 1, None, 0, ctypes.byref(length))  # TokenUser
            if not length.value:
                self.error()
            buffer = ctypes.create_string_buffer(length.value)
            if not self.a.GetTokenInformation(token, 1, buffer, length, ctypes.byref(length)):
                self.error()
            return self.sid_text(ctypes.c_void_p.from_buffer(buffer).value)
        finally:
            self.k.CloseHandle(token)

    def volume(self, path):
        root = path[:3]
        # Remote mappings, removable media and non-ACL volumes are unsupported.
        if self.k.GetDriveTypeW(root) != 3:  # DRIVE_FIXED
            raise ValueError('A local fixed volume is required')
        serial, maximum, flags = self.w.DWORD(), self.w.DWORD(), self.w.DWORD()
        if not self.k.GetVolumeInformationW(root, None, 0, ctypes.byref(serial),
                ctypes.byref(maximum), ctypes.byref(flags), None, 0):
            self.error()
        if not flags.value & 0x00000008:  # FILE_PERSISTENT_ACLS
            raise ValueError('Persistent ACL support is required')
        return serial.value

    def descriptor(self, directory):
        descriptor = ctypes.c_void_p()
        inheritance = 'OICI' if directory else ''
        sddl = 'O:' + self.sid + 'D:P(A;' + inheritance + ';FA;;;' + self.sid + ')'
        if not self.a.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, 1, ctypes.byref(descriptor), None):
            self.error()
        return descriptor

    def open(self, path, directory=False, share=1, security=False):
        access = 0x80 if directory else 0x80000000  # FILE_READ_ATTRIBUTES / GENERIC_READ
        if security:
            access |= 0x00020000  # READ_CONTROL
        handle = self.k.CreateFileW(path, access, share, None, 3,
                                   0x00200000 | 0x02000000, None)
        # OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT | BACKUP_SEMANTICS
        if handle == self.invalid_handle:
            self.error()
        try:
            info = self.FileInfo()
            if not self.k.GetFileInformationByHandle(handle, ctypes.byref(info)):
                self.error()
            if (info.attributes & 0x400 or bool(info.attributes & 0x10) != directory or
                    self.k.GetFileType(handle) != 1):  # reparse, directory, FILE_TYPE_DISK
                raise ValueError('Reparse points and non-ordinary objects are refused')
            return handle, info
        except BaseException:
            self.k.CloseHandle(handle)
            raise

    def acl(self, handle, directory=False, protected=False):
        owner, dacl, descriptor = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
        status = self.a.GetSecurityInfo(handle, 1, 0x1 | 0x4, ctypes.byref(owner), None,
                                       ctypes.byref(dacl), None, ctypes.byref(descriptor))
        if status:
            raise ctypes.WinError(status)
        try:
            if self.sid_text(owner) != self.sid or not dacl.value:
                raise ValueError('Owner or null DACL is not private')
            control, revision = self.w.WORD(), self.w.DWORD()
            if not self.a.GetSecurityDescriptorControl(descriptor, ctypes.byref(control), ctypes.byref(revision)):
                self.error()
            if protected and not control.value & 0x1000:  # SE_DACL_PROTECTED
                raise ValueError('Workspace DACL must reject parent inheritance')
            size = self.AclSize()
            if not self.a.GetAclInformation(dacl, ctypes.byref(size), ctypes.sizeof(size), 2):
                self.error()
            if not size.count:
                raise ValueError('No effective user access ACE')
            effective = False
            for index in range(size.count):
                ace = ctypes.c_void_p()
                if not self.a.GetAce(dacl, index, ctypes.byref(ace)):
                    self.error()
                header = ctypes.string_at(ace, 4)
                # Accept only standard allow ACEs for exactly TokenUser, never
                # broad groups, unknown object/callback ACE types or NULL ACLs.
                if header[0] != 0 or int.from_bytes(header[2:4], 'little') < 12:
                    raise ValueError('Unknown or non-allow ACL entry')
                if self.sid_text(ace.value + 8) != self.sid:
                    raise ValueError('ACL grants another principal access')
                mask = ctypes.c_uint32.from_address(ace.value + 4).value
                if not header[1] & 0x08 and mask & 0x001F01FF == 0x001F01FF:
                    effective = True
                    if directory and header[1] & 0x03 != 0x03:
                        raise ValueError('Private directory must propagate its ACL to children')
            if not effective:
                raise ValueError('User full control ACE required')
        finally:
            self.k.LocalFree(descriptor)


_native = None


def _api():
    global _native
    if _native is None:
        try:
            _native = _Native()
        except (AttributeError, OSError, ValueError) as exc:
            raise ShareError('platform_unverified', '无法初始化Windows原生安全API。') from exc
    return _native


def _walk(path, directory=False, share=1, private=False, protected=False, held=None):
    """Hold non-write/non-delete ancestor handles until the final open finishes.

    Denying directory write sharing also prevents reparse-point mutations while
    walking. A preexisting incompatible writable handle makes opening fail.
    """
    api = _api()
    handles = []
    try:
        volume = api.volume(path)
        pieces = path[3:].split('\\') if path[3:] else []
        ancestors = [path[:3]]
        for index in range(1, len(pieces)):
            ancestors.append(path[:3] + '\\'.join(pieces[:index]))
        # The root itself is also final for drive-root requests.
        if not pieces:
            ancestors = []
        for ancestor in ancestors:
            handle, info = api.open(ancestor, directory=True)
            handles.append(handle)
            if info.volume != volume:
                raise ValueError('Volume changed while opening path')
        handle, info = api.open(path, directory=directory, share=share, security=private)
        handles.append(handle)
        if info.volume != volume:
            raise ValueError('Volume changed while opening path')
        if private:
            api.acl(handle, directory=directory, protected=protected)
        result = handles.pop()
        if held is not None:
            held.extend(handles)
            handles = []
        return result
    finally:
        for handle in reversed(handles):
            api.k.CloseHandle(handle)


def _read_fd(path, private):
    path = validate_path(path)
    api, handle = _api(), None
    try:
        handle = _walk(path, share=7 if private else 1, private=private)
        import msvcrt
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY | os.O_NOINHERIT)
        handle = None  # descriptor now owns it, including close-on-error
        return fd
    except (OSError, ValueError) as exc:
        raise ShareError('workspace_unwritable' if private else 'source_invalid',
                         '文件不存在、权限不符、被写入占用或路径含重解析点。') from exc
    finally:
        if handle is not None:
            api.k.CloseHandle(handle)


def safe_open(path):
    """Read-only disk-file descriptor, denying source write/delete sharing."""
    return _read_fd(path, False)


def open_private(path):
    """Private runtime reads permit heartbeat replacement and expiry unlink."""
    return _read_fd(path, True)


def create_private(path):
    """Exclusively create a user-owned runtime file; never open a source writeably.

    Explicit owner is essential: elevated tokens may otherwise default to the
    Administrators group even inside a correctly protected parent directory.
    """
    value = validate_path(str(path))
    target = Path(value)
    api, parent, handle = _api(), None, None
    ancestors = []
    descriptor = ctypes.c_void_p()
    try:
        if target.parent == target:
            raise ValueError('A volume root cannot be a private file')
        parent = _walk(str(target.parent), directory=True, private=True, held=ancestors)
        descriptor = api.descriptor(False)
        security = api.SecurityAttributes(ctypes.sizeof(api.SecurityAttributes), descriptor, False)
        handle = api.k.CreateFileW(value, 0x40000000 | 0x00020000, 7,
                                  ctypes.byref(security), 1, 0x00200000, None)
        # GENERIC_WRITE | READ_CONTROL; CREATE_NEW is atomic and refuses existing
        # symlinks, hardlinks, ordinary files and directories without touching them.
        if handle == api.invalid_handle:
            handle = None
            api.error()
        info = api.FileInfo()
        if not api.k.GetFileInformationByHandle(handle, ctypes.byref(info)):
            api.error()
        if (info.attributes & (0x400 | 0x10) or api.k.GetFileType(handle) != 1 or
                info.volume != api.volume(value)):
            raise ValueError('New private object must be an ordinary same-volume file')
        api.acl(handle, protected=True)
        import msvcrt
        fd = msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_BINARY | os.O_NOINHERIT)
        handle = None
        return fd
    except (OSError, ValueError) as exc:
        raise ShareError('workspace_unwritable', '无法在私有目录独占创建本用户所有的运行文件。') from exc
    finally:
        if handle is not None:
            api.k.CloseHandle(handle)
        if parent is not None:
            api.k.CloseHandle(parent)
        for ancestor in reversed(ancestors):
            api.k.CloseHandle(ancestor)
        if descriptor.value:
            api.k.LocalFree(descriptor)


def make_private_dir(path):
    """Create one new private child directory with explicit TokenUser ownership."""
    value = validate_path(str(path))
    target = Path(value)
    api, parent, handle = _api(), None, None
    ancestors = []
    descriptor = ctypes.c_void_p()
    try:
        if target.parent == target:
            raise ValueError('A volume root cannot be a private child directory')
        parent = _walk(str(target.parent), directory=True, private=True, held=ancestors)
        descriptor = api.descriptor(True)
        security = api.SecurityAttributes(ctypes.sizeof(api.SecurityAttributes), descriptor, False)
        if not api.k.CreateDirectoryW(value, ctypes.byref(security)):
            api.error()
        handle = _walk(value, directory=True, private=True, protected=True)
        return target
    except (OSError, ValueError) as exc:
        raise ShareError('workspace_unwritable', '无法在私有目录独占创建本用户所有的子目录。') from exc
    finally:
        if handle is not None:
            api.k.CloseHandle(handle)
        if parent is not None:
            api.k.CloseHandle(parent)
        for ancestor in reversed(ancestors):
            api.k.CloseHandle(ancestor)
        if descriptor.value:
            api.k.LocalFree(descriptor)


def check_private(path):
    value = validate_path(str(path))
    api, handle = _api(), None
    try:
        # lstat chooses object kind only; _walk rechecks it on a native handle.
        directory = Path(value).is_dir()
        handle = _walk(value, directory=directory, private=True)
    except (OSError, ValueError) as exc:
        raise ShareError('workspace_unwritable', '需要本用户所有且仅授权本用户的Windows私有对象。') from exc
    finally:
        if handle is not None:
            api.k.CloseHandle(handle)


def workspace(path):
    value = validate_path(str(path))
    target = Path(value)
    api, parent_handle, descriptor, root_handle = _api(), None, ctypes.c_void_p(), None
    ancestors = []
    created = False
    try:
        if target.parent == target:
            raise ValueError('A volume root cannot be a workspace')
        # Parent must exist; this never creates a directory tree or changes an
        # existing directory's ACL. Hold it through creation and marker setup.
        parent_handle = _walk(str(target.parent), directory=True, held=ancestors)
        if not target.exists():
            descriptor = api.descriptor(True)
            security = api.SecurityAttributes(ctypes.sizeof(api.SecurityAttributes), descriptor, False)
            if not api.k.CreateDirectoryW(value, ctypes.byref(security)):
                api.error()
            created = True
        root_handle = _walk(value, directory=True, private=True, protected=True)
        marker = target / '.lan-share-root'
        if created:
            fd = create_private(str(marker))
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump({'version': 1}, stream)
        fd = open_private(str(marker))
        with os.fdopen(fd, 'r', encoding='utf-8') as stream:
            # Bound input before parsing an existing, possibly damaged marker.
            content = stream.read(4097)
            marker_data = json.loads(content)
            if (len(content) > 4096 or marker_data != {'version': 1} or
                    not isinstance(marker_data, dict) or type(marker_data.get('version')) is not int):
                raise ValueError('Invalid workspace marker')
        probe = target / ('.check-' + secrets.token_hex(8))
        try:
            fd = create_private(str(probe))
            os.close(fd)
            check_private(probe)
        finally:
            probe.unlink(missing_ok=True)
        return target
    except (OSError, ValueError) as exc:
        raise ShareError('workspace_unwritable', '拒绝未标记、重解析或非本用户专用DACL工作目录。',
                         '选择本机支持持久ACL卷上的新专用目录，不修改已有资料目录权限。') from exc
    finally:
        if root_handle is not None:
            api.k.CloseHandle(root_handle)
        if parent_handle is not None:
            api.k.CloseHandle(parent_handle)
        for ancestor in reversed(ancestors):
            api.k.CloseHandle(ancestor)
        if descriptor.value:
            api.k.LocalFree(descriptor)


def runtime_available():
    _api()
    import msvcrt
    if not callable(msvcrt.open_osfhandle) or not hasattr(os, 'O_NOINHERIT'):
        raise ShareError('platform_unverified', 'Windows运行时缺少安全描述符转换能力。')
    continuous_seconds()


# Constant script, no file names, addresses or user-supplied shell fragments.
_INTERFACES_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$result = @()
foreach ($adapter in @(Get-NetAdapter -Physical | Where-Object {$_.Status -eq 'Up'})) {
    foreach ($ip in @(Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4)) {
        if ($ip.AddressState -eq 'Preferred') {
            $result += @{interface=[string]$adapter.Name;address=[string]$ip.IPAddress}
        }
    }
}
ConvertTo-Json -InputObject @($result) -Compress
"""


def interfaces():
    _api()
    try:
        system_root = os.environ.get('SystemRoot', r'C:\Windows')
        executable = ntpath.join(system_root, r'System32\WindowsPowerShell\v1.0\powershell.exe')
        process = subprocess.run([executable, '-NoProfile', '-NonInteractive', '-Command',
                                  _INTERFACES_SCRIPT], capture_output=True, timeout=10, check=True,
                                 creationflags=0x08000000)
        if len(process.stdout) > 1024 * 1024:
            raise ValueError('Unexpected interface output size')
        rows = json.loads(process.stdout.decode('utf-8-sig'))
        if not isinstance(rows, list):
            raise ValueError('Unexpected interface output')
        result, seen = [], set()
        networks = [ipaddress.IPv4Network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')]
        for row in rows:
            name, address = row['interface'], row['address']
            if not isinstance(name, str) or not name or not isinstance(address, str):
                raise ValueError('Unexpected interface entry')
            ip = ipaddress.IPv4Address(address)
            if any(ip in network for network in networks) and (name, address) not in seen:
                result.append({'interface': name, 'address': address})
                seen.add((name, address))
        return result
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as exc:
        raise ShareError('interface_ambiguous', '无法核对Windows活动物理网卡与IPv4地址。',
                         '检查PowerShell NetAdapter/NetTCPIP读取能力后重新预检；不要修改防火墙。') from exc


def continuous_seconds():
    return _api().k.GetTickCount64() / 1000.0


def detached_options():
    _api()
    # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP (no POSIX session option).
    return {'creationflags': 0x00000008 | 0x00000200}
