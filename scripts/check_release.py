#!/usr/bin/env python3
"""Validate skill packaging and scan candidate files/history for common secret/private-data patterns.

This bounded local scan supplements, not replaces, human review and GitHub secret scanning.
"""
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = [
    re.compile(r'gh[pousr]_[A-Za-z0-9_]{25,}'),
    re.compile(r'eyJ[A-Za-z0-9_-]{30,}\.[A-Za-z0-9_-]{30,}\.[A-Za-z0-9_-]{15,}'),
    re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'),
    re.compile(r'(?i)(?:PHY|FIS)\d{6,}@'),
    re.compile(r'(?i)@[a-z0-9.-]*xmu\.edu\.my'),
    re.compile(r'(?i)(?:sk-proj-|sk-ant-)[A-Za-z0-9_-]{20,}'),
]
FORBIDDEN_PARTS = {'mail', 'cache', 'journals', 'mail-organisation', 'attachments', 'runtime', '.venv', 'receipts', 'plans', '.pi'}
FORBIDDEN_NAMES = {'config.json', 'pump.json', 'pump-status.json', 'session-token', '.owa-token', 'oauth-cache.json', 'outlook-mail-pump.user.js'}


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def scan(data, label, failures):
    text = data.decode('utf-8', errors='replace')
    if any(pattern.search(text) for pattern in PATTERNS):
        failures.append('Possible secret/private identifier: ' + label)


def main():
    failures = []
    files = git('ls-files', '--cached', '--others', '--exclude-standard', '-z').decode().split('\0')
    files = [p for p in files if p]
    for name in files:
        p = ROOT / name
        if set(Path(name).parts) & FORBIDDEN_PARTS or p.name in FORBIDDEN_NAMES or p.name.endswith('.user.js') or p.suffix in ('.pdf', '.jpg', '.png', '.log', '.token'):
            failures.append('Runtime/private/binary path in release: ' + name)
        if p.is_symlink():
            failures.append('Symlink in release: ' + name)
        if p.is_file():
            scan(p.read_bytes(), name, failures)
    # Scan all committed blobs, including deleted historical files, not just HEAD.
    seen = set()
    for line in git('rev-list', '--objects', '--all').decode().splitlines():
        oid = line.split(' ', 1)[0]
        if oid in seen:
            continue
        seen.add(oid)
        if git('cat-file', '-t', oid).strip() == b'blob':
            scan(git('cat-file', '-p', oid), 'history blob ' + oid, failures)
    package = json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))
    assert package['pi']['skills'] == ['./skills/outlook-mail']
    skill = ROOT / 'skills/outlook-mail/SKILL.md'
    text = skill.read_text(encoding='utf-8')
    assert text.startswith('---\n')
    frontmatter = text.split('---', 2)[1]
    assert re.search(r'^name: outlook-mail$', frontmatter, re.M)
    description = re.search(r'^description: (.+)$', frontmatter, re.M).group(1)
    assert len(description) <= 1024
    assert (skill.parent / 'scripts/run.py').is_file()
    # Validate local Markdown links without fetching external pages.
    for name in files:
        p = ROOT / name
        if p.suffix == '.md' and p.is_file():
            for link in re.findall(r'\]\(([^)]+)\)', p.read_text(encoding='utf-8')):
                if '://' not in link and not link.startswith('#'):
                    target = link.split('#', 1)[0]
                    if target and not (p.parent / target).exists():
                        failures.append(f'Broken local Markdown link: {name} -> {target}')
    if failures:
        print('\n'.join(sorted(set(failures))))
        return 1
    print(f'Release checks passed: {len(files)} candidate files; complete committed blob history scanned; portable skill/links valid.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
