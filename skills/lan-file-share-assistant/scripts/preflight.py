"""Actual eight-check production admission, independent of M1 fixture tooling."""
import errno
import io
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time

from core import (ContinuousClock, ShareError, digest, identifier, inspect_sources,
                  interfaces, load, physical, rfc1918, save, utc, workspace)

LIMITATIONS = ['HTTP未加密，仅用于可信局域网。', '接收端连通性、路由隔离及防火墙尚未验证。',
               '已下载副本无法撤回；到期会中断未完成传输。', '本次只核对当前宿主；不保证宿主结束任务后仍保留进程。']


def validate_request(req, authorized_paths):
    fields = {'schema_version', 'title', 'file_paths', 'ttl_seconds', 'bind_address', 'port', 'host_context', 'transport'}
    if not isinstance(req, dict) or set(req) != fields or req['schema_version'] != '1.0' or req['transport'] != 'http':
        raise ShareError('request_invalid', '请求字段或传输方式无效；首版仅支持HTTP。')
    if not isinstance(req['title'], str) or not 1 <= len(req['title'].strip()) <= 120 or any(ord(c) < 32 for c in req['title']):
        raise ShareError('request_invalid', '标题应为1至120个非控制字符。')
    for key, low, high in [('ttl_seconds', 60, 3600), ('port', 1024, 65535)]:
        v = req[key]
        if type(v) is not int or (not low <= v <= high and not (key == 'port' and v == 0)):
            raise ShareError('request_invalid', '有效期为60至3600秒；端口为0或1024至65535。')
    paths = req['file_paths']
    if not isinstance(paths, list) or not 1 <= len(paths) <= 20 or any(not isinstance(p, str) for p in paths):
        raise ShareError('source_invalid', '需要1至20个明确文件。')
    for p in paths:
        physical(p)
    if len(set(paths)) != len(paths) or authorized_paths is None or set(paths) != set(authorized_paths):
        raise ShareError('scope_unconfirmed', '请求文件范围与独立授予的文件范围不一致。', '仅传入用户明确指定的文件；配置文件不能自我授权。')
    host = req['host_context']
    if (not isinstance(host, dict) or set(host) != {'kind', 'evidence'} or
        host['kind'] not in ('local', 'remote', 'unknown') or
        host['evidence'] not in ('user_confirmed', 'desktop_adapter', 'none') or
        host['kind'] == 'local' and host['evidence'] == 'none'):
        raise ShareError('request_invalid', '本机宿主需要独立的用户确认或桌面适配器依据。')
    if req['bind_address'] is not None and not rfc1918(req['bind_address']):
        raise ShareError('address_invalid', '仅接受本机物理接口的RFC1918 IPv4地址。')


def start_probe(root):
    ContinuousClock()
    root = workspace(root)
    probe_id = secrets.token_hex(16)
    directory = root / ('probe-' + probe_id)
    directory.mkdir(mode=0o700)
    save(directory / 'owner.json', {'nonce': secrets.token_hex(32), 'started_at': time.time()})
    launch('_probe', root, probe_id)
    return {'probe_id': probe_id, 'expires_in_seconds': 60, 'file_service_started': False,
            'next_step': '在下一次独立工具调用中，使用此probe_id执行preflight或start。'}


def launch(command, root, item_id):
    return subprocess.Popen([sys.executable, str(Path(__file__).with_name('lan_share.py')), command,
                             '--work-dir', str(root), '--id', item_id], stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
                            close_fds=True)


def probe_worker(root, probe_id):
    directory = root / ('probe-' + identifier(probe_id))
    owner = load(directory / 'owner.json')
    clock = ContinuousClock()
    end = clock.now() + 60
    while time.time() < owner['started_at'] + 60 and clock.now() < end:
        save(directory / 'heartbeat.json', {'nonce': owner['nonce'], 'at': time.time()})
        if (directory / 'stop').exists():
            break
        time.sleep(.1)
    save(directory / 'done.json', {'nonce': owner['nonce'], 'at': time.time()})


def verify_probe(root, probe_id):
    if not probe_id:
        raise ShareError('lifecycle_unverified', '尚未验证当前宿主的跨调用进程存活与受控停止。', '先运行probe，再在下一次独立工具调用中携带probe_id复检。')
    directory = root / ('probe-' + identifier(probe_id))
    try:
        owner = load(directory / 'owner.json')
        receipt = directory / 'receipt.json'
        if receipt.exists():
            info = load(receipt)
            if info['nonce'] == owner['nonce'] and 0 <= time.time() - info['verified_at'] < 30:
                return
        began = time.time()
        until = time.monotonic() + 2
        while time.monotonic() < until:
            hb = load(directory / 'heartbeat.json')
            if hb['nonce'] == owner['nonce'] and began < hb['at'] <= time.time() and time.time() - owner['started_at'] < 60:
                save(directory / 'stop', {'nonce': owner['nonce']})
                while time.monotonic() < until:
                    if (directory / 'done.json').exists() and load(directory / 'done.json')['nonce'] == owner['nonce']:
                        save(receipt, {'nonce': owner['nonce'], 'verified_at': time.time()})
                        return
                    time.sleep(.05)
            time.sleep(.05)
    except (OSError, ValueError, KeyError):
        pass
    raise ShareError('lifecycle_unverified', '进程探针无新心跳、未完成受控停止或凭证已过时。', '重新运行probe，在下一次工具调用的60秒内复检；不要复用M1记录。')


def run(req, root_path, authorized_paths, host_attestation, probe_id=None, worker_verified=False, reserved_bytes=0):
    """host_attestation is supplied by the caller, never read from a request file."""
    validate_request(req, authorized_paths)
    normalized = dict(req)
    checks, manifest, root = [], [], None

    def check(item, operation, evidence='observed'):
        try:
            summary = operation()
            checks.append(dict(id=item, status='pass', reason_code='ok', summary=summary,
                               evidence=evidence, remediation=[]))
        except ShareError as e:
            checks.append(dict(id=item, status='fail', reason_code=e.code, summary=e.message,
                               evidence='observed', remediation=[e.remedy]))
        except (OSError, ValueError, ImportError) as e:
            checks.append(dict(id=item, status='fail', reason_code=item + '_unavailable',
                               summary='本机检查未成功（%s）；未开放文件服务。' % type(e).__name__,
                               evidence='observed', remediation=['检查本机依赖、文件及执行权限后重新预检。']))

    def host():
        context = req['host_context']
        if context['kind'] == 'remote':
            raise ShareError('remote_host_only', '运行环境在远端，不能代表用户电脑提供局域网文件。', '请在拥有文件的本机Agent执行。')
        if context['kind'] != 'local' or context != host_attestation:
            raise ShareError('host_unconfirmed', '尚无独立依据证明程序运行于拥有文件的本机。', '确认执行位置；由实际桌面适配器或用户提供本机依据后复检。')
        return '调用方已依据%s确认本机执行位置。' % context['evidence']

    def runtime():
        if sys.version_info < (3, 9) or sys.platform != 'darwin' or not hasattr(os, 'O_NOFOLLOW'):
            raise ShareError('platform_unverified', '当前M2仅放行已实现的macOS/Python3.9+后端。', '使用已验证平台；Windows/Linux适配尚未完成。')
        return 'Python版本与本机安全文件原语可用。'

    def sources():
        nonlocal manifest
        manifest = inspect_sources(req['file_paths'])
        return '已按独立授权范围核对%d个普通文件。' % len(manifest)

    def work():
        nonlocal root
        root = workspace(root_path)
        if any(root == Path(p) or root in Path(p).parents for p in req['file_paths']):
            raise ShareError('source_invalid', '待分享文件不能位于本项目运行状态目录内。')
        total = sum(f['size_bytes'] for f in manifest)
        reserve = max(0, total - reserved_bytes) + max(64 * 1024 ** 2, total // 10)
        if shutil.disk_usage(str(root)).free < reserve:
            raise ShareError('insufficient_space', '专用目录可用空间不足以保存快照及余量。', '选择有足够空间的专用目录后复检。')
        return '专用私有目录可写，快照空间余量满足当前文件。'

    def qr():
        try:
            import segno
            code = segno.make_qr('https://example.invalid/preflight', error='m')
            for kind in ('png', 'svg'):
                stream = io.BytesIO()
                code.save(stream, kind=kind, scale=4, border=4)
                if not stream.getvalue():
                    raise ValueError()
        except ImportError:
            raise ShareError('dependency_missing', '当前解释器缺少Segno，不能生成可扫码二维码。', '在项目虚拟环境安装requirements.txt，再用同一解释器复检。') from None
        except Exception:
            raise ShareError('qr_generation_failed', '本地二维码PNG/SVG生成失败。') from None
        return '当前解释器能本地生成标准二维码PNG与SVG。'

    def network():
        candidates = interfaces()
        address = req['bind_address']
        if address is None and len(candidates) == 1:
            address = candidates[0]['address']
        if address is None or address not in [r['address'] for r in candidates]:
            raise ShareError('interface_ambiguous', '无法确定唯一活动物理局域网接口。', '运行interfaces查看候选，确认用途后通过--bind-address选择；不要修改VPN或绑定所有接口。')
        normalized['bind_address'] = address
        return '已选定本机活动物理接口上的RFC1918地址。'

    def bind():
        if normalized['bind_address'] is None or not any(c['id'] == 'interface' and c['status'] == 'pass' for c in checks):
            raise ShareError('address_invalid', '未确定可用接口，未尝试绑定。')
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind((normalized['bind_address'], req['port']))
        except OSError as e:
            raise ShareError('port_in_use' if e.errno == errno.EADDRINUSE else 'bind_denied',
                             '所选端口占用或本机拒绝绑定。', '使用端口0自动分配或选择其他端口；不要停止不属于本项目的进程。') from None
        return '选定接口绑定探针成功，已关闭探针；尚未监听。'

    def lifecycle():
        ContinuousClock()
        if not worker_verified:
            if root is None:
                raise ShareError('lifecycle_unverified', '私有工作目录不可用，无法核验进程探针。')
            verify_probe(root, probe_id)
        return '原生含休眠时钟可调用，跨调用进程心跳与受控停止已核验。'

    check('host_context', host, req['host_context']['evidence'] if req['host_context']['kind'] == 'local' else 'observed')
    check('runtime', runtime)
    check('source_files', sources)
    check('workspace', work)
    check('qr', qr)
    check('interface', network)
    check('bind', bind)
    check('lifecycle', lifecycle)
    failed = [c for c in checks if c['status'] != 'pass']
    unsupported = any(c['reason_code'] in ('remote_host_only', 'execution_forbidden', 'lifecycle_unavailable') for c in failed)
    now = time.time()
    report = dict(schema_version='1.0', preflight_id=secrets.token_hex(16), request_digest=digest(normalized),
                  checked_at=utc(now), valid_until=utc(now + 30), result='unsupported' if unsupported else 'needs_action' if failed else 'supported',
                  can_start=not failed, can_publish=False, checks=checks, receiver_status='not_tested', limitations=LIMITATIONS)
    return normalized, report, manifest
