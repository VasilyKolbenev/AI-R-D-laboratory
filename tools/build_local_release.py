"""Build a deterministic, source-only Windows alpha archive from the Git index.

This is a packaging check, not a credential audit or research-quality guarantee.
No installed runtime, local evidence, credentials or Python environment is copied.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile

ROOT_FILES = {
    '.gitattributes', '.gitignore', 'AGENTS.md', 'CLAUDE.md', 'README.md',
    'LOCAL-START.txt', 'Open-Laboratory.cmd', 'Stop-Laboratory.cmd',
    'Setup-Laboratory.cmd', 'requirements.txt', 'LICENSE', 'SECURITY.md',
    'CONTRIBUTING.md', 'THIRD_PARTY_NOTICES.md', 'CHANGELOG.md',
}
PUBLIC_DOCS = {
    'docs/getting-started.md', 'docs/pilot.md', 'docs/operations.md',
    'docs/architecture.md', 'docs/research-evidence.md', 'docs/research/lexical-pilot.md',
}
PREFIXES = ('laboratory/', 'tests/', 'tools/', 'deliverables/',
            'docs/releases/', '.github/')
FORBIDDEN_PARTS = {
    '.git', '.venv', 'venv', 'node_modules', '__pycache__', '.lab-data',
    '.lab-tools', '.lab-backups', '.lab-operations', 'outputs', '.tmp',
    'test-results', 'playwright-report', 'qa-output',
}
FORBIDDEN_SUFFIXES = {'.sqlite', '.sqlite3', '.db', '.pem', '.key', '.pyc', '.pyo', '.log'}
SECRET_PATTERNS = (
    re.compile(rb'-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----'),
    re.compile(rb'\bgh[pousr]_[A-Za-z0-9_]{30,}'),
    re.compile(rb'\bgithub_pat_[A-Za-z0-9_]{40,}'),
    re.compile(rb'\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{25,}'),
    re.compile(rb'\b[0-9]{7,12}:[A-Za-z0-9_-]{30,}'),
)
OWNER_PATH = re.compile(rb'(?i)(?:[a-z]:[\\/]User' + rb's[\\/]|/User' + rb's/)[^\s/\\<>"\']+')
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
STAMP = (2026, 1, 1, 0, 0, 0)
REQUIRED = {
    'README.md', 'LICENSE', 'SECURITY.md', 'THIRD_PARTY_NOTICES.md',
    'Setup-Laboratory.cmd', 'Open-Laboratory.cmd', 'Stop-Laboratory.cmd',
    'requirements.txt', 'docs/getting-started.md', 'docs/pilot.md', 'docs/architecture.md',
    'laboratory/__init__.py', 'laboratory/__main__.py', 'laboratory/server.py',
    'tools/setup_local.py',
}


class ReleaseError(ValueError):
    """A release invariant failed. Messages never include matched secret values."""


def git(root: Path, *args: str) -> bytes:
    try:
        return subprocess.check_output(['git', '-C', str(root), *args],
                                       stderr=subprocess.PIPE)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReleaseError('A readable Git checkout and Git executable are required.') from exc


def selected(name: str) -> bool:
    return name in ROOT_FILES or name in PUBLIC_DOCS or name.startswith(PREFIXES)


def validate_name(name: str) -> None:
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name:
        raise ReleaseError('Unsafe archive path: ' + name)
    parts = {part.lower() for part in path.parts}
    if parts & FORBIDDEN_PARTS or any(part.startswith('.env') for part in parts):
        raise ReleaseError('Runtime or credential path is tracked: ' + name)
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise ReleaseError('Runtime or credential extension is tracked: ' + name)
    lowered = name.lower()
    if 'owner-approval' in lowered or 'encoder.json' in lowered:
        raise ReleaseError('Private installation artifact is tracked: ' + name)


def validate_content(name: str, data: bytes) -> None:
    if len(data) > MAX_FILE_BYTES:
        raise ReleaseError('Release file exceeds the source-only size bound: ' + name)
    if OWNER_PATH.search(data):
        raise ReleaseError('Personal profile path found; inspect this source file: ' + name)
    for pattern in SECRET_PATTERNS:
        matches = pattern.findall(data)
        # Clearly labelled synthetic API keys are used by transport tests only.
        if name.startswith('tests/'):
            matches = [value for value in matches if not value.startswith(b'sk-TEST_ONLY-')]
        if matches:
            raise ReleaseError('Possible credential found; inspect this source file: ' + name)


def collect(root: Path) -> tuple[str, dict[str, bytes]]:
    root = root.resolve()
    # Git status can report a stat-only modification for a CRLF checkout even
    # when normalized Git diffs are empty. Check both reviewed index and work
    # tree content, so a staged change cannot be hidden by an opposite edit.
    if (git(root, 'diff', '--cached', '--name-only', 'HEAD', '--').strip()
            or git(root, 'diff', '--name-only', '--').strip()):
        raise ReleaseError('Commit reviewed source changes before building the release.')
    revision = git(root, 'rev-parse', 'HEAD').decode('ascii').strip()
    items: dict[str, bytes] = {}
    total = 0
    for record in git(root, 'ls-files', '--stage', '-z').split(b'\0'):
        if not record:
            continue
        meta, raw_name = record.split(b'\t', 1)
        name = raw_name.decode('utf-8')
        validate_name(name)
        if not selected(name):
            continue
        mode, oid, stage = meta.decode('ascii').split()
        if mode not in {'100644', '100755'} or stage != '0':
            raise ReleaseError('Symlink, submodule or unresolved index entry: ' + name)
        path = root.joinpath(*PurePosixPath(name).parts)
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ReleaseError('Release file leaves the source root: ' + name)
        # Git stores canonical reviewed bytes. Working-tree CRLF conversion must
        # not produce a different release for the same commit on another host.
        size = int(git(root, 'cat-file', '-s', oid).decode('ascii').strip())
        if size > MAX_FILE_BYTES:
            raise ReleaseError('Release file exceeds the source-only size bound: ' + name)
        data = git(root, 'cat-file', 'blob', oid)
        validate_content(name, data)
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise ReleaseError('Release exceeds the source-only size bound.')
        items[name] = data
    missing = sorted(REQUIRED - items.keys())
    if missing:
        raise ReleaseError('Required release files are missing from Git: ' + ', '.join(missing))
    return revision, dict(sorted(items.items()))


def version_from(data: bytes) -> str:
    match = re.search(rb'^__version__\s*=\s*[\'"]([^\'"]+)[\'"]', data, re.M)
    if not match:
        raise ReleaseError('Application version is not declared.')
    version = match.group(1).decode('ascii')
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:-alpha\.\d+)?', version):
        raise ReleaseError('Unexpected release version format.')
    return version


def build(root: Path, destination: Path) -> dict:
    revision, files = collect(root)
    version = version_from(files['laboratory/__init__.py'])
    folder = 'ai-rd-laboratory-v' + version
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / (folder + '-windows-x64.zip')
    manifest = {
        'format': 'ai-rd-local-source-release-v1', 'version': version,
        'source_commit': revision, 'platform_scope': 'Windows x64 local single-owner alpha',
        'manifest_note': 'Hashes cover every packaged source file; this manifest is not self-hashed.',
        'files': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
    }
    manifest_data = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')
    payload = {**files, 'RELEASE-MANIFEST.json': manifest_data}
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for name, data in sorted(payload.items()):
            item = zipfile.ZipInfo(folder + '/' + name, STAMP)
            item.create_system = 3
            item.external_attr = 0o100644 << 16
            item.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(item, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    sums = destination / 'SHA256SUMS.txt'
    sums.write_text(digest + '  ' + archive.name + '\n', encoding='ascii')
    return {'version': version, 'source_commit': revision, 'archive': str(archive.resolve()),
            'sha256': digest, 'source_files': len(files), 'size_bytes': archive.stat().st_size,
            'checksums': str(sums.resolve())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, default=Path('dist'))
    args = parser.parse_args()
    try:
        result = build(args.root, args.output)
    except ReleaseError as exc:
        parser.exit(1, 'Release refused: ' + str(exc) + '\n')
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
