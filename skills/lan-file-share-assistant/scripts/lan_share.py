#!/usr/bin/env python3
"""CLI arguments are the concrete grant; arbitrary request JSON is not accepted."""
import argparse
import json
import os
from pathlib import Path
import sys
from core import ShareError, interfaces, workspace
import preflight
import session


def main():
    parser = argparse.ArgumentParser(description='局域网文件分享助手：先检测，再分享。标准输出可能包含私有链接，请勿公开。')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('interfaces', help='只读取本机候选接口，不监听端口')
    for command in ('probe', '_probe', '_worker', 'preflight', 'start', 'status', 'stop'):
        p = sub.add_parser(command)
        p.add_argument('--work-dir', required=True, help='独立私有任务目录的物理绝对路径')
        if command in ('_probe', '_worker', 'status', 'stop'):
            p.add_argument('--id', required=True)
        if command in ('preflight', 'start'):
            p.add_argument('--file', action='append', required=True, help='每项必须已获用户授权；使用绝对物理路径')
            p.add_argument('--title', default='文件分享')
            p.add_argument('--ttl-seconds', type=int, default=600)
            p.add_argument('--bind-address')
            p.add_argument('--port', type=int, default=0)
            p.add_argument('--host-kind', choices=['local', 'remote', 'unknown'], default='unknown')
            p.add_argument('--host-evidence', choices=['user_confirmed', 'desktop_adapter', 'none'], default='none')
            p.add_argument('--probe-id')
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
    if args.command in ('status', 'stop'):
        return getattr(session, args.command)(workspace(root), args.id)
    request = dict(schema_version='1.0', title=args.title, file_paths=args.file,
                   ttl_seconds=args.ttl_seconds, bind_address=args.bind_address, port=args.port,
                   host_context={'kind': args.host_kind, 'evidence': args.host_evidence}, transport='http')
    attestation = dict(request['host_context'])  # CLI caller must establish this independently.
    if args.command == 'start':
        return session.start(request, root, args.file, attestation, args.probe_id)
    return {'preflight': preflight.run(request, root, args.file, attestation, args.probe_id)[1], 'can_publish': False}


if __name__ == '__main__':
    os.umask(0o077)
    try:
        result = main()
        if result is not None:
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
