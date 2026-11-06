"""Bounded HTTP access to an immutable opaque-ID map, never a filesystem router."""
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import html
import json
from pathlib import Path
import re
import socket
from socketserver import ThreadingMixIn
import threading
from urllib.parse import quote
from core import open_private_binary


def size_label(value):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if value < 1024 or unit == 'GB':
            return ('%d' % value if unit == 'B' else '%.1f' % value) + ' ' + unit
        value /= 1024


def page(title, files, prefix, expiry):
    parts = []
    for item in files:
        parts.append('<article class="file"><svg class="file-icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M5 2h9l5 5v15H5zM14 2v6h5M8 13h8M8 17h6"/></svg><div class="details"><div class="name">%s</div><div class="size">%s</div></div><a class="download" href="%sfiles/%s" download>下载文件</a></article>' % (html.escape(item['download_name']), size_label(item['size_bytes']), prefix, item['file_id']))
    template = (Path(__file__).parent.parent / 'assets' / 'download.html').read_text(encoding='utf-8')
    # Single-pass interpolation: user text cannot introduce a template placeholder.
    values = {'TITLE': html.escape(title), 'COUNT': str(len(files)),
              'TOTAL': size_label(sum(f['size_bytes'] for f in files)), 'ISO': html.escape(expiry), 'FILES': ''.join(parts)}
    return re.sub(r'@@(TITLE|COUNT|TOTAL|ISO|FILES)@@', lambda m: values[m[1]], template).encode('utf-8')


class ShareServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = False
    request_queue_size = 8

    def __init__(self, address, directory, state, token, deadline):
        self.directory, self.state, self.token, self.deadline = directory, state, token, deadline
        self.revoked = threading.Event()
        self.active, self.lock = set(), threading.Lock()
        self.slots, self.downloads = threading.BoundedSemaphore(8), threading.BoundedSemaphore(2)
        super().__init__(address, Handler, bind_and_activate=False)
        try:
            self.server_bind()  # Actual specific address; no listen before final preparation.
            self.authority = '%s:%s' % self.server_address
            self.prefix = '/s/' + token + '/'
            self.body = page(state['title'], state['files'], self.prefix, state['expires_at'])
        except Exception:
            self.server_close()
            raise

    def valid(self):
        return not self.revoked.is_set() and not self.deadline.due()

    def get_request(self):
        sock, address = super().get_request()
        sock.settimeout(.75)
        with self.lock:
            self.active.add(sock)
        return sock, address

    def close_request(self, request):
        with self.lock:
            self.active.discard(request)
        super().close_request(request)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.close_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        pass  # No URLs, source paths or tokens in exception logs.

    def revoke(self):
        self.revoked.set()
        with self.lock:
            for sock in list(self.active):
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        self.shutdown()
        self.server_close()


class Handler(BaseHTTPRequestHandler):
    server_version = 'LocalShare'
    sys_version = ''

    def log_message(self, *args):
        pass

    def send_error(self, code, message=None, explain=None):
        self.reply(code, b'Request unavailable', 'text/plain; charset=utf-8')

    def reply(self, code, data=b'', content_type='application/json', extra=()):
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.headers_safe(extra)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(data)

    def headers_safe(self, extra=()):
        self.send_header('Cache-Control', 'no-store, max-age=0')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        script = self.server.body.split(b'<script>', 1)[1].split(b'</script>', 1)[0]
        import base64
        script_hash = base64.b64encode(hashlib.sha256(script).digest()).decode('ascii')
        self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; script-src 'sha256-%s'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'; connect-src 'none'" % script_hash)
        for name, value in extra:
            self.send_header(name, value)
        self.send_header('Connection', 'close')
        self.close_connection = True

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        srv = self.server
        if not srv.valid():
            self.reply(410)
            return
        if self.headers.get_all('Host', []) != [srv.authority]:
            self.reply(403)
            return
        if self.headers.get('Origin') not in (None, 'http://' + srv.authority):
            self.reply(403)
            return
        match = re.fullmatch(r'/s/([a-f0-9]{64})/(|health|files/([a-f0-9]{32}))', self.path)
        if not match or not hmac.compare_digest(match[1], srv.token):
            self.reply(404)
            return
        if match[2] == 'health':
            challenge = self.headers.get('X-Lan-Challenge', '')
            if not re.fullmatch('[a-f0-9]{32}', challenge):
                self.reply(400)
                return
            data = json.dumps({'session_id': srv.state['session_id'], 'owner_instance': srv.state['owner_instance'],
                               'challenge': challenge, 'request_digest': srv.state['request_digest'], 'state': 'ready'}).encode()
            self.reply(200, data)
            return
        if match[2] == '':
            self.reply(200, srv.body, 'text/html; charset=utf-8')
            return
        item = next((f for f in srv.state['files'] if f['file_id'] == match[3]), None)
        if item is None:
            self.reply(404)
            return
        if not srv.downloads.acquire(blocking=False):
            self.reply(503, extra=[('Retry-After', '1')])
            return
        try:
            # This relative path was generated by us; never derived from the URL.
            with open_private_binary(srv.directory / item['snapshot_relative_path']) as stream:
                if not srv.valid():
                    self.reply(410)
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Content-Length', str(item['size_bytes']))
                name = quote(item['download_name'], safe='')
                self.headers_safe([('Content-Disposition', "attachment; filename=\"download\"; filename*=UTF-8''" + name)])
                self.end_headers()
                if self.command == 'HEAD':
                    return
                while srv.valid():
                    data = stream.read(1024 * 1024)
                    if not data or not srv.valid():
                        break
                    self.wfile.write(data)
        except (OSError, ConnectionError):
            pass
        finally:
            srv.downloads.release()
