"""M1 protocol reference checker. No OS probing, files read from requests, or sharing."""
from datetime import datetime
import hashlib
import ipaddress
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
CHECK_IDS = {'host_context', 'runtime', 'source_files', 'workspace', 'qr', 'interface', 'bind', 'lifecycle'}
UNSUPPORTED = {'host_context': {'remote_host_only', 'execution_forbidden'},
               'runtime': {'execution_forbidden'}, 'lifecycle': {'lifecycle_unavailable'}}


def structural_errors(value, name):
    from jsonschema import Draft202012Validator
    schema = json.loads((ROOT/'schemas'/name).read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(schema)
    return [str(error.message) for error in Draft202012Validator(schema).iter_errors(value)]


def is_rfc1918(value):
    try:
        address = ipaddress.IPv4Address(value)
    except (ValueError, TypeError):
        return False
    return any(address in ipaddress.IPv4Network(network) for network in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))


def request_errors(value):
    errors = structural_errors(value, 'request.schema.json')
    if errors:
        return errors
    for path in value['file_paths']:
        posix = PurePosixPath(path)
        windows = PureWindowsPath(path)
        if '\x00' in path or '\r' in path or '\n' in path or '*' in path or '?' in path:
            errors.append('File paths cannot contain controls or wildcard syntax')
        if not (posix.is_absolute() or (windows.is_absolute() and not str(windows.drive).startswith('\\'))):
            errors.append('Expected a local absolute physical file path')
        if '..' in posix.parts or '..' in windows.parts:
            errors.append('Parent traversal is not allowed')
        if path.startswith('//'):
            errors.append('Network paths are not local file paths')
    if value['bind_address'] is not None and not is_rfc1918(value['bind_address']):
        errors.append('Bind address must be explicit RFC1918 IPv4')
    return errors


def classify(checks):
    ids = [check['id'] for check in checks]
    if set(ids) != CHECK_IDS or len(ids) != len(CHECK_IDS):
        return 'needs_action'
    for check in checks:
        if check['status'] == 'fail' and check['reason_code'] in UNSUPPORTED.get(check['id'], set()):
            return 'unsupported'
    return 'supported' if all(check['status'] == 'pass' for check in checks) else 'needs_action'


def utc(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z', value):
        raise ValueError('Expected UTC timestamp ending in Z')
    return datetime.fromisoformat(value[:-1]+'+00:00')


def request_fingerprint(request):
    encoded = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def report_errors(value, *, allow_fixture=False, now=None, request=None):
    errors = structural_errors(value, 'preflight.schema.json')
    if errors:
        return errors
    calculated = classify(value['checks'])
    ids = [check['id'] for check in value['checks']]
    if len(set(ids)) != len(CHECK_IDS):
        errors.append('Missing or duplicated critical check')
    if value['result'] != calculated or value['can_start'] != (calculated == 'supported'):
        errors.append('Overall result must match all critical checks')
    if request is not None:
        if request_errors(request) or value['request_digest'] != request_fingerprint(request):
            errors.append('Preflight does not belong to this valid request')
    for check in value['checks']:
        if check['evidence'] == 'fixture' and not allow_fixture:
            errors.append('Fixtures are not production evidence')
        if check['status'] == 'pass' and (check['evidence'] == 'not_tested' or check['reason_code'] != 'ok'):
            errors.append('A passing check requires tested evidence and ok reason')
        if check['status'] != 'pass' and check['reason_code'] == 'ok':
            errors.append('A non-passing check needs an actual reason')
    try:
        checked, valid = utc(value['checked_at']), utc(value['valid_until'])
        if (valid-checked).total_seconds() != 30:
            errors.append('Preflight lifetime must be 30 seconds')
        if now is not None and (now < checked or now >= valid):
            errors.append('Preflight is stale or the clock moved backwards')
    except (ValueError, TypeError):
        errors.append('Invalid UTC report time')
    return errors


def expired(wall_now, mono_now, wall_deadline, mono_deadline):
    """Reference deadline rule, not a running expiry controller."""
    return wall_now >= wall_deadline or mono_now >= mono_deadline


if __name__ == '__main__':
    print('M1 contract helper: run python -m unittest discover -s tests -v')
    sys.exit(0)
