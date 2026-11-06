"""Deterministic private-file primitives. Runtime dependencies: stdlib + Segno."""
import ctypes
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import time


class ShareError(Exception):
    def __init__(self, code, message, remedy='修复后重新执行预检。'):
        self.code, self.message, self.remedy = code, message, remedy
        super().__init__(message)


def utc(stamp=None):
    return datetime.fromtimestamp(time.time() if stamp is None else stamp, timezone.utc).isoformat().replace('+00:00', 'Z')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def save(path, value):
    """Atomic private writes; callers own the containing private directory."""
    path = Path(path)
    temp = path.with_name('.write-' + secrets.token_hex(16))
    fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
        os.replace(str(temp), str(path))
    finally:
        temp.unlink(missing_ok=True)


def load(path):
    with open(path, encoding='utf-8') as stream:
        return json.load(stream)


def physical(path):
    p = Path(path)
    if (not isinstance(path, str) or len(path) > 4096 or path.startswith('//') or not p.is_absolute() or '..' in p.parts or
            any(ord(c) < 32 or ord(c) == 127 for c in path) or any(c in path for c in '*?[')):
        raise ShareError('source_invalid', '需要无通配符的本机绝对物理路径。', '明确逐项文件路径；符号链接请提供已授权的实际物理路径。')
    return p


def safe_open(path):
    """Walk every POSIX component without following symlinks, including parents."""
    p = physical(str(path))
    if os.name != 'posix' or not hasattr(os, 'O_NOFOLLOW'):
        raise ShareError('platform_unverified', '当前平台尚无已实现的安全文件打开后端。', '使用已验证的本机macOS环境；不要降级为跟随符号链接。')
    dfd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in p.parts[1:-1]:
            newfd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dfd)
            os.close(dfd)
            dfd = newfd
        fd = os.open(p.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=dfd)
    finally:
        os.close(dfd)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise ShareError('source_invalid', '仅接受普通文件，拒绝目录、管道和设备。')
    return fd


def identity(info):
    return [info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def inspect_sources(paths):
    if not 1 <= len(paths) <= 20 or len(set(paths)) != len(paths):
        raise ShareError('source_invalid', '每次需要1至20个不重复的指定文件。')
    result, aliases, total = [], set(), 0
    try:
        for path in paths:
            fd = safe_open(path)
            try:
                info = os.fstat(fd)
                key = (info.st_dev, info.st_ino)
                if key in aliases or info.st_size > 2 * 1024 ** 3:
                    raise ShareError('source_invalid', '文件存在物理重复，或单个文件超过2GiB。')
                aliases.add(key)
                total += info.st_size
                result.append({'path': path, 'identity': identity(info), 'size_bytes': info.st_size})
            finally:
                os.close(fd)
    except OSError:
        raise ShareError('source_invalid', '指定文件不存在、不可读或路径含符号链接。', '检查所选文件的物理路径和读取权限。') from None
    if total > 5 * 1024 ** 3:
        raise ShareError('source_invalid', '所选文件总量超过5GiB。')
    return result


def workspace(path):
    """Do not chmod or adopt a general user directory."""
    if os.name != 'posix':
        raise ShareError('platform_unverified', '当前平台未实现私有目录与安全文件后端。', '请使用已验证的macOS环境；Windows/Linux支持仍待完成。')
    p = physical(str(path))
    if str(p.resolve()) != str(p):
        raise ShareError('workspace_unwritable', '工作目录必须使用不含符号链接的物理路径。')
    if not p.exists():
        p.mkdir(mode=0o700)  # parent must already exist; no broad directory creation
        save(p / '.lan-share-root', {'version': 1})
    info = p.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ShareError('workspace_unwritable', '工作目录需要本用户所有、权限0700的专用目录。', '选择新的专用任务目录，不修改其他资料目录权限。')
    if not (p / '.lan-share-root').is_file():
        raise ShareError('workspace_unwritable', '拒绝接管未标记的已有目录。', '指定尚不存在的独立任务目录。')
    test = p / ('.check-' + secrets.token_hex(8))
    save(test, {'write': True})
    test.unlink()
    return p


def identifier(value):
    if not re.fullmatch('[a-f0-9]{32}', value or ''):
        raise ShareError('invalid_identifier', '会话或探针标识无效。')
    return value


def rfc1918(address):
    try:
        ip = ipaddress.IPv4Address(address)
        return any(ip in ipaddress.IPv4Network(net) for net in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
    except (ValueError, TypeError):
        return False


def interfaces():
    """Only macOS physical adapters are admitted in the first verified backend."""
    if sys.platform != 'darwin':
        raise ShareError('platform_unverified', 'M2仅实现并验证macOS网卡与安全文件后端。', '此平台暂不能启动；后续需验证平台适配，不能以私有IP推断支持。')
    try:
        hw = subprocess.run(['/usr/sbin/networksetup', '-listallhardwareports'], capture_output=True, text=True, timeout=5, check=True).stdout
        data = subprocess.run(['/sbin/ifconfig', '-a'], capture_output=True, text=True, timeout=5, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        raise ShareError('interface_ambiguous', '无法读取本机接口信息。', '检查本机执行权限后复检。') from None
    hardware = set(re.findall(r'^Device: (\S+)$', hw, re.M))
    result, device, active = [], None, False
    for line in data.splitlines():
        m = re.match(r'^(\S+): flags=.*<([^>]+)>', line)
        if m:
            device, flags = m.groups()
            active = {'UP', 'RUNNING'}.issubset(set(flags.split(',')))
        m = re.match(r'\s+inet (\S+) ', line)
        if m and active and device in hardware and rfc1918(m.group(1)):
            result.append({'interface': device, 'address': m.group(1)})
    return result


class ContinuousClock:
    """macOS native suspend-inclusive clock. No monotonic fallback."""
    def __init__(self):
        if sys.platform != 'darwin':
            raise ShareError('clock_backend_unverified', '当前平台连续计时后端尚未验证。', '切换到已验证平台，不以普通monotonic替代休眠计时。')
        try:
            lib = ctypes.CDLL('/usr/lib/libSystem.B.dylib')
            class Timebase(ctypes.Structure):
                _fields_ = [('numer', ctypes.c_uint32), ('denom', ctypes.c_uint32)]
            base = Timebase()
            lib.mach_timebase_info.argtypes = [ctypes.POINTER(Timebase)]
            if lib.mach_timebase_info(ctypes.byref(base)) or not base.denom:
                raise ValueError()
            lib.mach_continuous_time.restype = ctypes.c_uint64
            lib.mach_continuous_time.argtypes = []
            self.tick = lib.mach_continuous_time
            self.scale = base.numer / base.denom / 1e9
            self.library = lib
            self.now()
        except (AttributeError, OSError, ValueError):
            raise ShareError('clock_backend_unverified', '无法核对包含休眠的原生连续计时能力。') from None

    def now(self):
        return self.tick() * self.scale


class Deadline:
    def __init__(self, ttl, clock=None):
        self.clock = clock or ContinuousClock()
        self.wall = time.time() + ttl
        self.continuous = self.clock.now() + ttl

    def due(self):
        return time.time() >= self.wall or self.clock.now() >= self.continuous


def snapshot(manifest, directory, progress=None):
    """Create read-only session copies; neither serve nor later reopen sources."""
    directory.mkdir(mode=0o700)
    result = []
    for source in manifest:
        try:
            fd = safe_open(source['path'])
        except (OSError, ShareError):
            raise ShareError('source_changed', '来源在准备期间变得不可安全读取，已阻止分享。') from None
        file_id = secrets.token_hex(16)
        destination = directory / (file_id + '.bin')
        h, size = hashlib.sha256(), 0
        try:
            if identity(os.fstat(fd)) != source['identity']:
                raise ShareError('source_changed', '文件在预检后改变，已阻止分享。')
            outfd = os.open(str(destination), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(outfd, 'wb') as target:
                while True:
                    data = os.read(fd, 1024 * 1024)
                    if not data:
                        break
                    size += len(data)
                    if size > source['size_bytes']:
                        raise ShareError('source_changed', '文件在快照期间增长，已阻止分享。')
                    target.write(data)
                    h.update(data)
                    if progress:
                        progress()
            if size != source['size_bytes'] or identity(os.fstat(fd)) != source['identity']:
                raise ShareError('source_changed', '文件在快照期间改变，已阻止分享。')
            try:
                checkfd = safe_open(source['path'])
            except (OSError, ShareError):
                raise ShareError('source_changed', '原路径在准备期间改变，已阻止分享。') from None
            try:
                if identity(os.fstat(checkfd)) != source['identity']:
                    raise ShareError('source_changed', '原路径在快照期间被替换，已阻止分享。')
            finally:
                os.close(checkfd)
            result.append({'file_id': file_id, 'download_name': Path(source['path']).name,
                           'size_bytes': size, 'sha256': h.hexdigest(),
                           'snapshot_relative_path': 'snapshots/' + destination.name})
        finally:
            os.close(fd)
    return result
