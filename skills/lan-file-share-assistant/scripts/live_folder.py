"""Read-only, nonrecursive catalog for a single app-created drop directory."""
from contextlib import contextmanager
import os
import secrets
import stat
import sys
import threading
import time

from core import ShareError, identity, safe_open

MAX_ENTRIES = 256
QUIET_SECONDS = 2


@contextmanager
def open_folder(path):
    if sys.platform == 'win32':
        import windows_backend
        with windows_backend.hold_private_directory(path) as key:
            yield str(path), key
        return
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ShareError('folder_unavailable', '共享目录需要当前用户的私有权限。')
        yield fd, (info.st_dev, info.st_ino)
    finally:
        os.close(fd)


def eligible(info):
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and
            not getattr(info, 'st_file_attributes', 0) & 0x402 and
            info.st_size <= 2 * 1024 ** 3)


class LiveFolder:
    def __init__(self, path):
        self.path = path
        with open_folder(path) as (_, key):
            self.key = key
        self.lock = threading.Lock()
        self.observed = {}
        self.published = {}
        self.last_scan = None
        self.notice = ''

    @contextmanager
    def folder(self):
        with open_folder(self.path) as (handle, key):
            if key != self.key:
                raise ShareError('folder_unavailable', '共享目录已被移动或替换，请重新开启。')
            yield handle

    def scan(self):
        entries = {}
        with self.folder() as handle, os.scandir(handle) as listing:
            for index, entry in enumerate(listing):
                if index >= MAX_ENTRIES:
                    raise ShareError('folder_capacity', '目录条目过多，请移走部分内容后重试。')
                name = entry.name
                if (name.startswith(('.', '~$')) or name.lower().endswith(('.tmp', '.part', '.crdownload', '.download')) or
                        any(ord(c) < 32 or ord(c) == 127 or c in '*?[' for c in name)):
                    continue
                try:
                    name.encode('utf-8')
                    info = entry.stat(follow_symlinks=False)
                    if sys.platform == 'win32':
                        if not stat.S_ISREG(info.st_mode) or info.st_file_attributes & 0x402:
                            continue
                        # Windows path stat and descriptor stat can report different
                        # metadata. Use the same safe native open as download.
                        fd = safe_open(self.path / name)
                        try:
                            info = os.fstat(fd)
                        finally:
                            os.close(fd)
                    if eligible(info):
                        entries[name] = identity(info)
                except (FileNotFoundError, UnicodeEncodeError, ShareError):
                    continue  # The entry disappeared, is still open for writing or is unsafe.
        if len(entries) > 20 or sum(item[3] for item in entries.values()) > 5 * 1024 ** 3:
            raise ShareError('folder_capacity', '共享文件夹最多20个文件、合计5GiB，请移走部分文件。')
        return entries

    def files(self):
        """The browser polls this view; no agent or always-running scanner is needed."""
        with self.lock:
            now = time.monotonic()
            if self.last_scan is None or now - self.last_scan >= 1:
                self.last_scan = now
                try:
                    current = self.scan()
                    observed, published = {}, {}
                    for name, stamp in sorted(current.items()):
                        previous = self.observed.get(name)
                        since, file_id = previous[1:] if previous and previous[0] == stamp else (now, secrets.token_hex(16))
                        observed[name] = (stamp, since, file_id)
                        if now - since >= QUIET_SECONDS:
                            published[file_id] = dict(file_id=file_id, download_name=name,
                                                      size_bytes=stamp[3], identity=stamp)
                    self.observed, self.published = observed, published
                    self.notice = '正在等待新文件写入稳定。' if len(observed) != len(published) else ''
                except (OSError, ShareError) as error:
                    self.observed, self.published = {}, {}
                    self.notice = error.message if isinstance(error, ShareError) else '暂时无法读取共享文件夹。'
            return list(self.published.values())

    def open_file(self, item):
        with self.folder() as handle:
            if sys.platform == 'win32':
                fd = safe_open(self.path / item['download_name'])
            else:
                fd = os.open(item['download_name'], os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=handle)
            try:
                if not self.unchanged(fd, item):
                    raise ShareError('source_changed', '文件已更新或移出，请刷新下载页。')
                return os.fdopen(fd, 'rb')
            except BaseException:
                os.close(fd)
                raise

    @staticmethod
    def unchanged(fd, item):
        info = os.fstat(fd)
        return eligible(info) and identity(info) == item['identity']
