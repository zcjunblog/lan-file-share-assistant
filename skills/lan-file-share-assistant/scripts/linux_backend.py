"""Linux native metadata and suspend-inclusive clock; no remote probes or iproute dependency."""
import errno
from pathlib import Path
import os
import socket
import struct
import time

from core import ShareError, rfc1918


def runtime_available():
    if os.name!='posix' or not hasattr(os,'O_NOFOLLOW') or getattr(time,'CLOCK_BOOTTIME',None) is None:
        raise ShareError('platform_unverified','Linux后端需要POSIX安全文件原语及CLOCK_BOOTTIME。','使用具备这些能力的本机Linux/Python3.9+环境后复检。')
    continuous_seconds()


def continuous_seconds():
    clock_id=getattr(time,'CLOCK_BOOTTIME',None)
    gettime=getattr(time,'clock_gettime',None)
    if clock_id is None or gettime is None:
        raise ShareError('clock_backend_unverified','无法核对Linux含休眠连续时钟。','检查内核及Python的CLOCK_BOOTTIME支持，不降级使用普通monotonic。')
    try:
        return gettime(clock_id)
    except (OSError,ValueError):
        raise ShareError('clock_backend_unverified','Linux原生含休眠时钟调用失败。') from None


def _address(name):
    import fcntl  # Not imported when policy tests run on Windows.
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
        value=fcntl.ioctl(sock.fileno(),0x8915,struct.pack('256s',name.encode('ascii')))
    return socket.inet_ntoa(value[20:24])


def interfaces(sysfs_root=None,address_reader=None):
    root=Path('/sys/class/net') if sysfs_root is None else Path(sysfs_root)
    reader=_address if address_reader is None else address_reader
    try:
        names=sorted(p.name for p in root.iterdir())
        result=[]
        for name in names:
            p=root/name
            # OS hardware association is metadata only, never proof of file host ownership.
            if not (p/'device').exists():continue
            if len(name.encode('ascii'))>15:continue
            state=(p/'operstate').read_text().strip()
            kind=(p/'type').read_text().strip()
            flags=int((p/'flags').read_text().strip(),0)
            if state!='up' or kind!='1' or not flags&1 or flags&8:continue
            try:address=reader(name)
            except OSError as error:
                if error.errno in (errno.EADDRNOTAVAIL,errno.ENODEV):continue
                raise
            if rfc1918(address):result.append({'interface':name,'address':address})
        return result
    except (OSError,ValueError,UnicodeError):
        raise ShareError('interface_ambiguous','无法完整读取Linux活动物理接口信息。','检查/sys/class/net和本机接口读取权限，明确物理网络后复检；不自动更改VPN或路由。') from None
