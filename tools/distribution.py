"""One audited source for both portable release profiles. No runtime dependency."""
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
NAME = 'lan-file-share-assistant'
SOURCE = ROOT / 'skills' / NAME
ROOT_FILES = {'SKILL.md', 'VERSION', 'requirements.txt'}
DIRECTORIES = {'scripts': {'.py'}, 'references': {'.md'},
               'assets': {'.html', '.svg', '.png'}, 'agents': {'.yaml'}}
RESOURCE_FILES = ROOT_FILES | {
    'scripts/core.py', 'scripts/http_service.py', 'scripts/lan_share.py',
    'scripts/linux_backend.py', 'scripts/windows_backend.py', 'scripts/preflight.py', 'scripts/session.py',
    'references/runtime.md', 'assets/download.html', 'assets/icon.svg', 'assets/icon-512.png',
    'agents/openai.yaml',
}
PROFILE_FIELDS = {'display_name', 'display_name_en', 'description_zh', 'description_en',
                  'author', 'examples_zh', 'examples_en'}


def source_files(source=SOURCE):
    source = Path(source)
    if source.is_symlink():
        raise ValueError('Skill source cannot be a symlink')
    files = []
    for path in sorted(source.rglob('*')):
        if path.is_symlink():
            raise ValueError('Symlink in Skill source')
        if '__pycache__' in path.parts or path.suffix == '.pyc':
            continue
        rel = path.relative_to(source)
        if path.is_dir():
            if rel.parts[0] not in DIRECTORIES:
                raise ValueError('Unexpected Skill directory: ' + rel.as_posix())
            continue
        if not path.is_file():
            raise ValueError('Nonregular Skill resource')
        allowed = rel.as_posix() in RESOURCE_FILES
        if not allowed or path.stat().st_size > 1024 * 1024:
            raise ValueError('Unexpected or oversized Skill resource: ' + rel.as_posix())
        files.append(path)
    inventory = {path.resolve() for path in files}
    if {p.relative_to(source).as_posix() for p in files} != RESOURCE_FILES:
        raise ValueError('Missing required source files')
    for path in files:
        if path.suffix == '.md':
            for link in re.findall(r'\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
                if link.startswith(('https:', 'http:', '#', 'mailto:')):
                    continue
                target = (path.parent / link.split('#', 1)[0].strip('<>')).resolve()
                if source.resolve() not in target.parents or target not in inventory:
                    raise ValueError('Missing or escaping resource link')
    ui = source / 'agents/openai.yaml'
    if ui.is_file():
        for icon in re.findall(r'^\s+icon_(?:small|large):\s*(".*")\s*$', ui.read_text(encoding='utf-8'), re.M):
            target = (source / json.loads(icon)).resolve()
            if source.resolve() not in target.parents or target not in inventory:
                raise ValueError('Icon reference must resolve to a packaged resource')
    return files


def skill_info(source=SOURCE):
    text = (source / 'SKILL.md').read_text(encoding='utf-8')
    parts = text.split('---\n', 2)
    if len(parts) != 3 or parts[0]:
        raise ValueError('Expected YAML frontmatter')
    fields = {}
    for line in parts[1].splitlines():
        key, value = line.split(':', 1)
        if key in fields:
            raise ValueError('Duplicate frontmatter field')
        fields[key] = json.loads(value.strip()) if value.strip().startswith('"') else value.strip()
    if set(fields) != {'name', 'description'} or fields['name'] != NAME:
        raise ValueError('Canonical Skill requires standard name/description only')
    if not isinstance(fields['description'], str) or not 1 <= len(fields['description']) <= 1024:
        raise ValueError('Invalid description')
    version = (source / 'VERSION').read_text(encoding='utf-8').strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Invalid version')
    return fields, parts[2], version


def marketplace_profile():
    return json.loads((ROOT / 'distribution/workbuddy.json').read_text(encoding='utf-8'))


def workbuddy_entry(fields, body, version):
    profile = marketplace_profile()
    if not isinstance(profile, dict) or set(profile) != PROFILE_FIELDS:
        raise ValueError('Unexpected or missing marketplace metadata fields')
    for key in PROFILE_FIELDS - {'examples_zh', 'examples_en'}:
        if not isinstance(profile[key], str) or not profile[key].strip():
            raise ValueError('Invalid marketplace scalar')
    examples = [profile[key] for key in ('examples_zh', 'examples_en')]
    if any(not isinstance(items, list) or not items or
           any(not isinstance(item, str) or not item.strip() for item in items) for items in examples):
        raise ValueError('Examples must be nonempty lists of nonempty strings')
    if len(examples[0]) != len(examples[1]):
        raise ValueError('Bilingual example counts must match')
    values = {**fields, **profile, 'version': version}
    return ('---\n' + '\n'.join(key + ': ' + json.dumps(value, ensure_ascii=False)
                               for key, value in values.items()) + '\n---\n' + body).encode('utf-8')
