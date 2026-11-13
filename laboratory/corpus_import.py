"""Bounded offline import of published claims. Never calls an extractor or provider."""
from datetime import datetime, timezone
from contextlib import closing
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import uuid

FORMAT = 'drift-corpus-bundle-v1'
STORAGE = 'vv-frontier-corpus-v1'
FILES = {'papers.jsonl.gz': 20000, 'claims.jsonl.gz': 100000,
         'assignments.jsonl.gz': 100000, 'topics.jsonl.gz': 1000}
MAX_COMPRESSED = 32 * 1024 ** 2
MAX_EXPANDED = 200 * 1024 ** 2
PAPER_ID = re.compile(r'20\d{2}\.emnlp-main\.\d+')
HEX = re.compile('[0-9a-f]{64}')
REVISION = '134d196f7c45ef0f3aebcef9f0a06ca98ae95e31'
UPSTREAM_SHA = {
    'papers.parquet': '4219147b113a328a696f20e0548758787ed1e5410dc2dd7d4ff3342a6d1b6c26',
    'claims.parquet': 'aa56a6c2aeddbe0911a4214b4e8b7cba82c5da1c12190bbafd7e22d37a770bb1',
    'clusters.parquet': '205c7f867301466f0619e6bd7a32730d3629fc77090201031829e51c048f65de',
    'cluster_summary.parquet': 'a0bb64b949e2496b5b2b02c367fbd68e23c2fcdf449a6f9b9d8992047fe0db6f'}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def linked(path):
    return path.is_symlink() or (os.name == 'nt' and path.exists() and bool(path.stat().st_file_attributes & 1024))


def text(value, maximum=10000, empty=False):
    if not isinstance(value, str) or len(value) > maximum or '\0' in value or (not empty and not value.strip()):
        raise ValueError('Некорректное текстовое поле корпуса.')
    return value


def year(value):
    if type(value) is not int or not 2020 <= value <= 2025:
        raise ValueError('Год не входит в снимок EMNLP 2020–2025.')
    return value


def read_manifest(bundle):
    path = bundle / 'manifest.json'
    if linked(bundle) or linked(path) or path.stat().st_size > 512 * 1024:
        raise ValueError('Некорректный манифест корпуса.')
    value = json.loads(path.read_text(encoding='utf-8'))
    if (value.get('format') != FORMAT or value.get('dataset_id') != 'drift-emnlp-2020-2025'
            or value.get('revision') != REVISION or value.get('source_hashes') != UPSTREAM_SHA
            or set(value.get('files', {})) != set(FILES)):
        raise ValueError('Нужен подготовленный снимок корпуса Drift Inspector EMNLP.')
    provenance = value.get('provenance', {})
    dataset_url = 'https://huggingface.co/datasets/Hamyrappy/emnlp-2020-2025-atomic-claims'
    if (provenance.get('origin') != 'external_extraction' or provenance.get('license') != 'CC-BY-4.0'
            or provenance.get('dataset_url') not in {dataset_url, dataset_url + '/tree/' + value['revision']}
            or provenance.get('paper_url') != 'https://aclanthology.org/2026.emnlp-demos.13/'
            or not isinstance(provenance.get('publisher'), str) or len(provenance['publisher']) > 1000):
        raise ValueError('Не зафиксированы происхождение и лицензия внешнего извлечения.')
    for name, maximum in FILES.items():
        path, record = bundle / name, value['files'][name]
        if (linked(path) or type(record.get('rows')) is not int or not 0 < record['rows'] <= maximum
                or type(record.get('bytes')) is not int or not 0 < record['bytes'] <= MAX_COMPRESSED
                or not HEX.fullmatch(str(record.get('sha256', '')))
                or path.stat().st_size != record['bytes'] or sha(path) != record['sha256']):
            raise ValueError('Файл корпуса не совпадает с манифестом: ' + name)
    return value


def records(bundle, manifest, name):
    count, expanded = 0, 0
    with gzip.open(bundle / name, 'rb') as source:
        while True:
            line = source.readline(512 * 1024 + 1)
            if not line:
                break
            expanded += len(line)
            count += 1
            if len(line) > 512 * 1024 or expanded > MAX_EXPANDED or count > manifest['files'][name]['rows']:
                raise ValueError('Превышены границы распаковки корпуса.')
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError('Строка корпуса должна быть объектом.')
            yield value
    if count != manifest['files'][name]['rows']:
        raise ValueError('Количество строк корпуса не совпало.')


def create_database(path, bundle, manifest):
    """Build a new database only; reject a partial or inconsistent study snapshot."""
    with closing(sqlite3.connect(path)) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.executescript('''
            CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE papers(paper_id TEXT PRIMARY KEY,year INTEGER NOT NULL,title TEXT NOT NULL,
                abstract TEXT NOT NULL,url TEXT NOT NULL,venue TEXT,track TEXT,authors TEXT,
                in_analytic_sample INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE claims(claim_id TEXT PRIMARY KEY,paper_id TEXT NOT NULL REFERENCES papers,
                year INTEGER NOT NULL,text TEXT NOT NULL,extractor_model TEXT,prompt_hash TEXT,
                run_id TEXT,created_at TEXT);
            CREATE TABLE topics(topic_id INTEGER PRIMARY KEY,name TEXT NOT NULL,full_name TEXT,
                description TEXT,published_papers INTEGER,published_claims INTEGER);
            CREATE TABLE assignments(claim_id TEXT PRIMARY KEY REFERENCES claims,paper_id TEXT NOT NULL
                REFERENCES papers,year INTEGER NOT NULL,topic_id INTEGER NOT NULL REFERENCES topics);
            CREATE TABLE topic_year(topic_id INTEGER NOT NULL REFERENCES topics,year INTEGER NOT NULL,
                numerator INTEGER NOT NULL,denominator INTEGER NOT NULL,share REAL NOT NULL,
                reported_share REAL NOT NULL,PRIMARY KEY(topic_id,year));
            CREATE INDEX claims_paper ON claims(paper_id);
            CREATE INDEX assignments_topic_year ON assignments(topic_id,year,paper_id);
            CREATE INDEX assignments_paper ON assignments(paper_id);
            CREATE INDEX papers_year ON papers(year,paper_id);
        ''')
        try:
            for row in records(bundle, manifest, 'papers.jsonl.gz'):
                pid = text(row.get('paper_id'), 100)
                if not PAPER_ID.fullmatch(pid):
                    raise ValueError('Некорректный идентификатор статьи.')
                authors = row.get('authors', [])
                if not isinstance(authors, list) or len(authors) > 200:
                    raise ValueError('Некорректный список авторов статьи.')
                for author in authors:
                    text(author, 1000)
                db.execute('INSERT INTO papers VALUES (?,?,?,?,?,?,?,?,0)',
                    (pid, year(row.get('year')), text(row.get('title'), 4000),
                     text(row.get('abstract', ''), 100000, True), 'https://aclanthology.org/' + pid + '/',
                     text(row.get('venue', ''), 200, True), text(row.get('track', ''), 200, True),
                     encoded(authors).decode()))
            reported = {}
            for row in records(bundle, manifest, 'topics.jsonl.gz'):
                tid = row.get('id')
                if type(tid) is not int or not -1 <= tid <= 1000:
                    raise ValueError('Некорректный идентификатор темы.')
                counts = (row.get('papers'), row.get('claims'))
                if any(type(count) is not int or count < 0 for count in counts):
                    raise ValueError('Не зафиксированы авторские количества для темы.')
                db.execute('INSERT INTO topics VALUES (?,?,?,?,?,?)',
                    (tid, text(row.get('name'), 2000), text(row.get('full_name', ''), 4000, True),
                     text(row.get('description', ''), 20000, True), *counts))
                values = row.get('published_years')
                if not isinstance(values, list) or len(values) != 6:
                    raise ValueError('Нужны шесть опубликованных точек тренда.')
                reported[tid] = {}
                for point in values:
                    y, share = year(point.get('year')), point.get('share')
                    if (y in reported[tid] or type(share) not in (int, float)
                            or not math.isfinite(share) or not 0 <= share <= 100):
                        raise ValueError('Некорректная авторская доля темы.')
                    reported[tid][y] = share
            for row in records(bundle, manifest, 'claims.jsonl.gz'):
                db.execute('INSERT INTO claims VALUES (?,?,?,?,?,?,?,?)',
                    (text(row.get('claim_id'), 100), text(row.get('paper_id'), 100), year(row.get('year')),
                     text(row.get('text'), 20000), text(row.get('extractor_model', ''), 1000, True),
                     text(row.get('prompt_hash', ''), 200, True), text(row.get('run_id', ''), 200, True),
                     text(row.get('created_at', ''), 100, True)))
            for row in records(bundle, manifest, 'assignments.jsonl.gz'):
                tid = row.get('topic_id')
                if type(tid) is not int:
                    raise ValueError('Некорректная тема утверждения.')
                db.execute('INSERT INTO assignments VALUES (?,?,?,?)',
                    (text(row.get('claim_id'), 100), text(row.get('paper_id'), 100), year(row.get('year')), tid))
        except sqlite3.IntegrityError as error:
            raise ValueError('Дубликат ID или отсутствующая связь в корпусе.') from error
        if db.execute('SELECT 1 FROM claims c JOIN papers p USING(paper_id) WHERE c.year!=p.year LIMIT 1').fetchone():
            raise ValueError('Год утверждения отличается от года статьи.')
        if db.execute('SELECT 1 FROM assignments a JOIN claims c USING(claim_id) WHERE a.year!=c.year OR a.paper_id!=c.paper_id LIMIT 1').fetchone():
            raise ValueError('Привязка темы не соответствует исходному утверждению.')
        db.execute('UPDATE papers SET in_analytic_sample=1 WHERE paper_id IN (SELECT paper_id FROM assignments)')
        denominators = dict(db.execute('SELECT year,COUNT(*) FROM papers WHERE in_analytic_sample=1 GROUP BY year'))
        if set(denominators) != set(range(2020, 2026)):
            raise ValueError('Аналитическая выборка должна содержать все шесть лет.')
        max_difference = 0.0
        for tid, reference in reported.items():
            actual = db.execute('SELECT COUNT(DISTINCT paper_id),COUNT(*) FROM assignments WHERE topic_id=?', (tid,)).fetchone()
            published = db.execute('SELECT published_papers,published_claims FROM topics WHERE topic_id=?', (tid,)).fetchone()
            if actual != published:
                raise ValueError('Количество статей/утверждений темы не совпало с авторским снимком.')
            for y, denominator in sorted(denominators.items()):
                numerator = db.execute('SELECT COUNT(DISTINCT paper_id) FROM assignments WHERE topic_id=? AND year=?', (tid, y)).fetchone()[0]
                share = numerator * 100 / denominator
                difference = abs(share - reference[y])
                if difference > 0.00005001:
                    raise ValueError('Пересчитанный тренд не совпал с опубликованным снимком.')
                max_difference = max(max_difference, difference)
                db.execute('INSERT INTO topic_year VALUES (?,?,?,?,?,?)', (tid, y, numerator, denominator, share, reference[y]))
        count = lambda sql: db.execute(sql).fetchone()[0]
        overview = {'id': manifest['dataset_id'], 'title': manifest.get('title', 'Drift Inspector · EMNLP 2020–2025'),
            'revision': manifest['revision'], 'counts': {
                'papers': count('SELECT COUNT(*) FROM papers'), 'claims': count('SELECT COUNT(*) FROM claims'),
                'analytic_papers': sum(denominators.values()), 'analytic_claims': count('SELECT COUNT(*) FROM assignments'),
                'topics': count('SELECT COUNT(*) FROM topics WHERE topic_id!=-1'),
                'noise_claims': count('SELECT COUNT(*) FROM assignments WHERE topic_id=-1'),
                'papers_with_claims': count('SELECT COUNT(DISTINCT paper_id) FROM claims')},
            'years': sorted(denominators), 'provenance': manifest['provenance'],
            'reproduction': {'matched': True, 'comparisons': len(reported) * len(denominators),
                'max_abs_diff_pp': max_difference, 'tolerance_pp': 0.00005001,
                'denominators': [{'year': y, 'papers': n} for y, n in sorted(denominators.items())]},
            'notices': [
                'Внешнее машинное извлечение авторов Drift Inspector; новые модели в лаборатории не запускались.',
                'Тренды рассчитаны по фиксированной сбалансированной выборке, а не по всему каталогу статей.',
                'Доля темы = уникальные статьи с темой / все статьи выбранного года в аналитической выборке.',
                'Темы пересекаются; суммы долей не обязаны составлять 100%.',
                'Без привязки к кластеру: вне аналитической выборки. Кластер −1: шум внутри выборки.',
                'Отсутствие импортированных утверждений не означает отсутствие научного вклада.',
                'Дословные цитаты/span не опубликованы в этом наборе; поддержанность утверждений здесь независимо не проверена.']}
        db.execute('INSERT INTO meta VALUES (?,?)', ('overview', encoded(overview).decode()))
        db.commit()
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or db.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Корпус не прошёл проверку целостности.')
    return overview


def import_bundle(bundle, data_dir):
    bundle, root = Path(bundle).resolve(), Path(data_dir) / 'corpora'
    manifest = read_manifest(bundle)
    snapshot_id = hashlib.sha256(encoded(manifest)).hexdigest()
    if linked(root):
        raise ValueError('Каталог корпуса не должен быть ссылкой.')
    root.mkdir(parents=True, exist_ok=True)
    if linked(root / 'tmp'):
        raise ValueError('Временный каталог корпуса не должен быть ссылкой.')
    destination = root / snapshot_id
    if destination.exists():
        from .corpus import verify_snapshot
        saved = verify_snapshot(destination)
        created = False
    else:
        staging = root / 'tmp' / uuid.uuid4().hex
        staging.mkdir(parents=True, exist_ok=False)
        try:
            overview = create_database(staging / 'corpus.sqlite3', bundle, manifest)
            (staging / 'inputs').mkdir()
            for name in FILES:
                shutil.copyfile(bundle / name, staging / 'inputs' / name)
                if sha(staging / 'inputs' / name) != manifest['files'][name]['sha256']:
                    raise ValueError('Входные файлы изменились во время импорта.')
            saved = {'format': STORAGE, 'snapshot_id': snapshot_id, 'bundle': manifest,
                     'imported_at': datetime.now(timezone.utc).isoformat(),
                     'database_sha256': sha(staging / 'corpus.sqlite3'),
                     'database_bytes': (staging / 'corpus.sqlite3').stat().st_size, 'overview': overview}
            (staging / 'manifest.json').write_bytes(encoded(saved))
            try:
                staging.rename(destination)
            except FileExistsError:
                from .corpus import verify_snapshot
                saved = verify_snapshot(destination)
                created = False
            else:
                created = True
        finally:
            if staging.exists() and staging.resolve().is_relative_to((root / 'tmp').resolve()):
                shutil.rmtree(staging)
    active = root / 'active.json'
    if linked(active):
        raise ValueError('Указатель корпуса не должен быть ссылкой.')
    if active.is_file() and json.loads(active.read_text(encoding='utf-8')) == {'snapshot_id': snapshot_id}:
        return {'created': created, 'snapshot_id': snapshot_id, **saved['overview'], 'new_model_calls': 0}
    pointer = root / ('.pending-' + uuid.uuid4().hex + '.json')
    try:
        pointer.write_bytes(encoded({'snapshot_id': snapshot_id}))
        pointer.replace(root / 'active.json')
    finally:
        pointer.unlink(missing_ok=True)
    return {'created': created, 'snapshot_id': snapshot_id, **saved['overview'], 'new_model_calls': 0}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--data-dir', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(import_bundle(args.bundle, args.data_dir), ensure_ascii=True))


if __name__ == '__main__':
    main()
