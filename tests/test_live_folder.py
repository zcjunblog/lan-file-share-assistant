"""A live drop folder publishes only its stable, eligible contents."""
from contextlib import closing
import http.client
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/lan-file-share-assistant/scripts'))
from core import Deadline, private_mkdir, utc
from http_service import ShareServer
from live_folder import LiveFolder


class LiveFolderTests(unittest.TestCase):
    def test_same_link_updates_and_revokes_old_file_ids(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            folder = private_mkdir(root / 'shared-files')
            live = LiveFolder(folder)
            state = {'title': '合成共享目录', 'files': [], 'expires_at': utc(time.time() + 60)}
            server = ShareServer(('127.0.0.1', 0), root, state, secrets.token_hex(32), Deadline(60), folder=live)
            server.server_activate()
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                def get(suffix=''):
                    with closing(http.client.HTTPConnection(*server.server_address, timeout=2)) as conn:
                        conn.request('GET', server.prefix + suffix)
                        response = conn.getresponse()
                        return response.status, response.read()

                # Mock only the elapsed quiet period. File and HTTP operations are real.
                with patch('live_folder.time.monotonic') as clock:
                    clock.return_value = 100
                    self.assertIn('暂无可下载文件', get()[1].decode())
                    file = folder / '合成.txt'
                    file.write_bytes(b'first version')
                    sub = folder / 'private-subfolder'
                    sub.mkdir()
                    (sub / 'nested.txt').write_bytes(b'not shared')
                    (folder / '.hidden.txt').write_bytes(b'not shared')
                    outside = root / 'outside.txt'
                    outside.write_bytes(b'not shared')
                    os.link(outside, folder / 'hardlink.txt')
                    if os.name == 'posix':
                        (folder / 'symlink.txt').symlink_to(outside)
                    clock.return_value = 102
                    self.assertNotIn('合成.txt', get()[1].decode())
                    clock.return_value = 104
                    status, body = get()
                    self.assertEqual(status, 200)
                    page = body.decode()
                    self.assertIn('合成.txt', page)
                    for blocked in ('nested.txt', '.hidden.txt', 'hardlink.txt', 'symlink.txt'):
                        self.assertNotIn(blocked, page)
                    first = live.files()[0]['file_id']
                    self.assertEqual(get('files/' + first), (200, b'first version'))
                    file.write_bytes(b'replacement version')
                    self.assertEqual(get('files/' + first)[0], 404)
                    clock.return_value = 106
                    self.assertNotIn('合成.txt', get()[1].decode())
                    clock.return_value = 108
                    self.assertIn('合成.txt', get()[1].decode())
                    second = live.files()[0]['file_id']
                    self.assertNotEqual(first, second)
                    self.assertEqual(get('files/' + second), (200, b'replacement version'))
                    file.unlink()
                    self.assertEqual(get('files/' + second)[0], 404)
                    clock.return_value = 110
                    self.assertIn('暂无可下载文件', get()[1].decode())
                    folder.rename(root / 'original-folder')
                    private_mkdir(folder)
                    (folder / 'replacement-folder.txt').write_bytes(b'not granted')
                    clock.return_value = 112
                    self.assertIn('目录已被移动或替换', get()[1].decode())
                    clock.return_value = 114
                    self.assertNotIn('replacement-folder.txt', get()[1].decode())
            finally:
                server.revoke()
                thread.join(2)
