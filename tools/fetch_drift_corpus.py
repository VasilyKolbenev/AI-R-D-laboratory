"""Fetch and normalize one pinned public Drift Inspector corpus; no model calls.

The laboratory itself needs only the resulting JSONL.gz bundle and stdlib.
Parquet conversion is an explicit operator step using an already installed
DuckDB or PyArrow decoder, optionally supplied via --converter-dir. This tool
never installs packages or runs extraction, embeddings or clustering.
"""
from argparse import ArgumentParser
import gzip
import hashlib
import importlib
import io
import json
import math
from pathlib import Path
import sys
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


REVISION = '134d196f7c45ef0f3aebcef9f0a06ca98ae95e31'
DATASET = 'Hamyrappy/emnlp-2020-2025-atomic-claims'
DATASET_ID = 'drift-emnlp-2020-2025'
ROOT_URL = 'https://huggingface.co/datasets/' + DATASET
SOURCES = {
    'papers.parquet': (5013084, '4219147b113a328a696f20e0548758787ed1e5410dc2dd7d4ff3342a6d1b6c26'),
    'claims.parquet': (1526944, 'aa56a6c2aeddbe0911a4214b4e8b7cba82c5da1c12190bbafd7e22d37a770bb1'),
    'clusters.parquet': (1443218, '205c7f867301466f0619e6bd7a32730d3629fc77090201031829e51c048f65de'),
    'cluster_summary.parquet': (32149, 'a0bb64b949e2496b5b2b02c367fbd68e23c2fcdf449a6f9b9d8992047fe0db6f'),
}
EXPECTED_ROWS = {'papers': 6517, 'claims': 18293, 'assignments': 16576, 'topics': 81}
MAX_FILE = 8 * 1024 * 1024


def digest(data):
    return hashlib.sha256(data).hexdigest()


class DatasetRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        parts = urlsplit(newurl)
        host = (parts.hostname or '').lower()
        approved = (host == 'huggingface.co' or host.endswith('.huggingface.co')
                    or host.endswith('.hf.co') or host.endswith('.xethub.hf.co'))
        if parts.scheme != 'https' or not approved or parts.username or parts.password:
            raise ValueError('Unexpected dataset redirect')
        return super().redirect_request(request, fp, code, message, headers, newurl)


def write_exact(path, raw):
    if path.is_symlink():
        raise ValueError('Refuse to replace a symbolic link: ' + path.name)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError('Existing immutable file differs: ' + str(path))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as handle:
        handle.write(raw)


def fetch_sources(folder, offline=False):
    folder.mkdir(parents=True, exist_ok=True)
    for name, (size, sha256) in SOURCES.items():
        path = folder / name
        if path.is_symlink():
            raise ValueError('Source must not be a symbolic link')
        if path.exists():
            if path.stat().st_size != size:
                raise ValueError('Pinned source size mismatch: ' + name)
            raw = path.read_bytes()
        elif offline:
            raise ValueError('Missing verified source in offline mode: ' + name)
        else:
            url = ROOT_URL + '/resolve/' + REVISION + '/' + name
            request = Request(url, headers={'User-Agent': 'VV-Frontier-corpus-import/1'})
            with build_opener(DatasetRedirects()).open(request, timeout=45) as response:
                raw = response.read(MAX_FILE + 1)
        if len(raw) != size or len(raw) > MAX_FILE or digest(raw) != sha256:
            raise ValueError('Pinned source bytes/hash mismatch: ' + name)
        write_exact(path, raw)


def decoder(directory=None):
    if directory:
        directory = Path(directory).resolve(strict=True)
        if not directory.is_dir():
            raise ValueError('Converter directory must be a directory')
        sys.path.insert(0, str(directory))
    failures = []
    for name in ('duckdb', 'pyarrow.parquet'):
        try:
            return name, importlib.import_module(name)
        except (ImportError, OSError) as error:
            failures.append(type(error).__name__)
    raise ValueError('Parquet decoder unavailable (' + ', '.join(failures) +
                     '). Supply an isolated compatible DuckDB/PyArrow with --converter-dir; no package was installed.')


def read_rows(path, converter):
    name, module = converter
    if name == 'duckdb':
        db = module.connect(':memory:', config={'threads': 2, 'memory_limit': '256MB',
            'autoload_known_extensions': False, 'autoinstall_known_extensions': False})
        try:
            result = db.execute('SELECT * FROM read_parquet(?)', [str(path)])
            columns = [item[0] for item in result.description]
            return [dict(zip(columns, values)) for values in result.fetchall()]
        finally:
            db.close()
    return module.read_table(path).to_pylist()


def authors(value):
    if value is None:
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [name.strip() for name in value.split(';') if name.strip()]
        value = parsed if isinstance(parsed, list) else [value]
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
        raise ValueError('Unexpected authors schema')
    return list(value)


def normalize(tables):
    papers = [{**{key: row[key] for key in ('paper_id', 'year', 'title', 'abstract', 'url', 'venue', 'track')},
               'authors': authors(row.get('authors'))} for row in tables['papers']]
    claims = [{**{key: row[key] for key in ('claim_id', 'paper_id', 'year', 'extractor_model',
               'prompt_hash', 'run_id', 'created_at')}, 'text': row['atomic_claim']} for row in tables['claims']]
    assignments = [{**{key: row[key] for key in ('claim_id', 'paper_id', 'year')},
                    'topic_id': row['cluster']} for row in tables['clusters']]
    topics = []
    for row in tables['cluster_summary']:
        years = []
        for year in range(2020, 2026):
            share = float(row['df_pct_' + str(year)])
            if not math.isfinite(share) or not 0 <= share <= 100:
                raise ValueError('Invalid published topic share')
            years.append({'year': year, 'share': share})
        topics.append({'id': row['cluster'], 'name': row['cluster_short_name'],
                       'full_name': row['cluster_full_name'], 'description': row.get('cluster_description') or '',
                       'papers': row['n_papers'], 'claims': row['n_claims'], 'published_years': years})
    result = {'papers': papers, 'claims': claims, 'assignments': assignments, 'topics': topics}
    for kind, rows in result.items():
        if len(rows) != EXPECTED_ROWS[kind]:
            raise ValueError('Unexpected pinned row count for ' + kind)
    return result


def gzip_jsonl(rows, key):
    payload = ''.join(json.dumps(row, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False) + '\n' for row in sorted(rows, key=lambda row: row[key])).encode('utf-8')
    stream = io.BytesIO()
    # Empty filename avoids embedding local paths; mtime=0 makes repeated builds exact.
    with gzip.GzipFile(fileobj=stream, filename='', mode='wb', mtime=0, compresslevel=9) as compressed:
        compressed.write(payload)
    return stream.getvalue()


def build_bundle(output, source_dir, converter):
    tables = {name.removesuffix('.parquet'): read_rows(source_dir / name, converter) for name in SOURCES}
    records = normalize(tables)
    files = {}
    for name, rows in records.items():
        filename = name + '.jsonl.gz'
        key = {'papers': 'paper_id', 'claims': 'claim_id', 'assignments': 'claim_id', 'topics': 'id'}[name]
        raw = gzip_jsonl(rows, key)
        write_exact(output / filename, raw)
        files[filename] = {'sha256': digest(raw), 'bytes': len(raw), 'rows': len(rows)}
    manifest = {'format': 'drift-corpus-bundle-v1', 'dataset_id': DATASET_ID, 'revision': REVISION,
        'title': 'Drift Inspector · EMNLP 2020–2025',
        'provenance': {'dataset_url': ROOT_URL + '/tree/' + REVISION,
            'paper_url': 'https://aclanthology.org/2026.emnlp-demos.13/',
            'license': 'CC-BY-4.0',
            'publisher': 'Karimov, Ostarkov, Poroshina, Frolov and Panchenko; source abstracts: ACL Anthology',
            'origin': 'external_extraction', 'revision': REVISION},
        'source_hashes': {name: values[1] for name, values in SOURCES.items()}, 'files': files}
    raw = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')
    write_exact(output / 'manifest.json', raw)
    return manifest


def main(argv=None):
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path, help='New or byte-identical normalized bundle directory')
    parser.add_argument('--upstream-dir', type=Path, help='Retained official Parquet bytes; defaults to OUTPUT/upstream')
    parser.add_argument('--converter-dir', type=Path, help='Explicit isolated DuckDB/PyArrow installation, never auto-installed')
    parser.add_argument('--offline', action='store_true', help='Require already downloaded hash-matching source files')
    args = parser.parse_args(argv)
    if args.output.is_symlink() or (args.upstream_dir and args.upstream_dir.is_symlink()):
        raise ValueError('Bundle directories must not be symbolic links')
    output = args.output.resolve()
    source_dir = (args.upstream_dir or output / 'upstream').resolve()
    if output.is_symlink() or source_dir.is_symlink():
        raise ValueError('Bundle directories must not be symbolic links')
    convert = decoder(args.converter_dir)
    fetch_sources(source_dir, args.offline)
    manifest = build_bundle(output, source_dir, convert)
    print(json.dumps({'dataset_id': manifest['dataset_id'], 'revision': REVISION,
                      'files': manifest['files'], 'new_model_calls': 0}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
