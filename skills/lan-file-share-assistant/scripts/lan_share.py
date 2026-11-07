#!/usr/bin/env python3
"""CLI arguments are the concrete grant; arbitrary request JSON is not accepted."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from core import ShareError, interfaces, workspace
import preflight
import session


def main():
    parser = argparse.ArgumentParser(description='局域网文件分享助手：先检测，再分享。标准输出可能包含私有链接，请勿公开。')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('interfaces', help='只读取本机候选接口，不监听端口')
    for command in ('probe', '_probe', '_worker', 'preflight', 'start', 'quick-folder', 'status', 'stop'):
        p = sub.add_parser(command)
        p.add_argument('--work-dir', required=True, help='独立私有任务目录的物理绝对路径')
        if command in ('_probe', '_worker', 'status', 'stop'):
            p.add_argument('--id', required=True)
        if command == 'status':
            p.add_argument('--wait-seconds', type=int, choices=range(16), default=0,
                           help='在本次调用内等待准备完成，最长15秒')
        if command in ('preflight', 'start', 'quick-folder'):
            if command != 'quick-folder':
                scope = p.add_mutually_exclusive_group(required=True)
                scope.add_argument('--file', action='append', help='每项必须已获用户授权；使用绝对物理路径')
                scope.add_argument('--folder', action='store_true', help='创建空共享文件夹，放入其中的顶层文件自动分享')
                if command == 'start':
                    lifecycle = p.add_mutually_exclusive_group()
                    lifecycle.add_argument('--probe-id')
                    lifecycle.add_argument('--chat', action='store_true',
                                           help='内置启动探针，待独立status调用核验后再交付')
                else:
                    p.add_argument('--probe-id')
            else:
                p.add_argument('--open-local', action='store_true', help='在 Windows 打开本机文件夹和二维码')
            p.add_argument('--title', default='文件分享')
            p.add_argument('--ttl-seconds', type=int, default=600)
            p.add_argument('--bind-address')
            p.add_argument('--port', type=int, default=0)
            p.add_argument('--host-kind', choices=['local', 'remote', 'unknown'], default='unknown')
            p.add_argument('--host-evidence', choices=['user_confirmed', 'desktop_adapter', 'none'], default='none')
    args = parser.parse_args()
    if args.command == 'interfaces':
        return {'candidates': interfaces(), 'receiver_status': 'not_tested'}
    root = Path(args.work_dir)
    if args.command == '_probe':
        preflight.probe_worker(workspace(root), args.id)
        return None
    if args.command == '_worker':
        session.worker(workspace(root), args.id)
        return None
    if args.command == 'probe':
        return preflight.start_probe(root)
    if args.command == 'status':
        return session.wait_status(workspace(root), args.id, args.wait_seconds)
    if args.command == 'stop':
        return session.stop(workspace(root), args.id)
    direct = args.command == 'quick-folder'
    paths = [] if direct or args.folder else args.file
    request = dict(schema_version='1.0', title=args.title, file_paths=paths,
                   ttl_seconds=args.ttl_seconds, bind_address=args.bind_address, port=args.port,
                   host_context={'kind': args.host_kind, 'evidence': args.host_evidence}, transport='http')
    attestation = dict(request['host_context'])  # CLI caller must establish this independently.
    if direct or args.folder:
        request['folder_mode'] = True
    if direct:
        if attestation != {'kind': 'local', 'evidence': 'user_confirmed'}:
            raise ShareError('host_unconfirmed', '请在保存文件的电脑终端直接开启共享文件夹。')
        preflight.validate_request(request, paths)
        return quick_folder(request, root, attestation, args.open_local)
    if args.command == 'start':
        return session.start(request, root, paths, attestation, args.probe_id, chat=args.chat)
    return {'preflight': preflight.run(request, root, paths, attestation, args.probe_id)[1], 'can_publish': False}


def quick_folder(request, root, attestation, open_local):
    """Direct local invocation. Agent hosts still use independent tool calls."""
    began = time.monotonic()
    probe = preflight.start_probe(root)
    result = session.start(request, root, [], attestation, probe['probe_id'])
    session_id = result.get('session_id')
    if session_id and result['state'] not in session.TERMINAL:
        report = result.get('preflight')
        until = time.monotonic() + 16
        while True:
            result = session.status(root, session_id)
            if result['state'] in session.TERMINAL or result['can_publish'] or time.monotonic() >= until:
                break
            time.sleep(.1)
        if report and 'preflight' not in result:
            result['preflight'] = report
        if result['can_publish'] and open_local and sys.platform == 'win32':
            startup_ms = round((time.monotonic() - began) * 1000)
            for key in ('shared_folder', 'qr_png'):
                try:
                    os.startfile(result[key])
                except OSError:
                    result.setdefault('open_local_failed', []).append(key)
            print('共享文件夹：' + result['shared_folder'])
            print('扫码图片：' + result['qr_png'])
            print('下载链接：' + result['url'])
            print('启动耗时：%d ms' % startup_ms)
            print('截止时间：' + result['expires_at'], flush=True)
            try:
                input('按回车提前停止分享。到期会自动关闭。')
            except (EOFError, KeyboardInterrupt):
                pass
            stopped = session.stop(root, session_id)
            stopped.update(startup_ms=startup_ms, worker_ready_ms=result.get('worker_ready_ms'),
                           preflight=result.get('preflight'))
            return stopped
    return result


if __name__ == '__main__':
    os.umask(0o077)
    try:
        began = time.monotonic()
        result = main()
        if result is not None:
            result['command_ms'] = round((time.monotonic() - began) * 1000)
            print(json.dumps(result, ensure_ascii=False, indent=2))
    except ShareError as error:
        print(json.dumps({'state': 'blocked', 'can_publish': False, 'reason_code': error.code,
                          'summary': error.message, 'remediation': [error.remedy]}, ensure_ascii=False))
        sys.exit(2)
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps({'state': 'blocked', 'can_publish': False, 'reason_code': 'local_operation_failed',
                          'summary': '本机操作失败（%s），未确认分享可用。' % type(error).__name__,
                          'remediation': ['检查专用目录、参数、依赖与本机权限后复检。']}, ensure_ascii=False))
        sys.exit(2)
