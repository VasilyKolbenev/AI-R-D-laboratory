"""Read-only exploration of an immutable, externally extracted corpus snapshot."""
from contextlib import closing, contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading

from .corpus_import import FILES, HEX, STORAGE, encoded, linked, sha


def small_json(path):
    if linked(path) or path.stat().st_size > 1024 * 1024:
        raise ValueError('Некорректный манифест корпуса.')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Некорректный манифест корпуса.')
    return value


def verify_snapshot(folder):
    if linked(folder) or not HEX.fullmatch(folder.name):
        raise ValueError('Некорректный каталог снимка корпуса.')
    saved = small_json(folder / 'manifest.json')
    bundle = saved.get('bundle', {})
    if (saved.get('format') != STORAGE or saved.get('snapshot_id') != folder.name
            or hashlib.sha256(encoded(bundle)).hexdigest() != folder.name
            or set(bundle.get('files', {})) != set(FILES)):
        raise ValueError('Контрольная сумма манифеста корпуса не совпала.')
    database = folder / 'corpus.sqlite3'
    if (linked(database) or type(saved.get('database_bytes')) is not int
            or not 0 < saved['database_bytes'] <= 256 * 1024 ** 2
            or database.stat().st_size != saved['database_bytes']
            or sha(database) != saved.get('database_sha256')):
        raise ValueError('База корпуса повреждена.')
    for name in FILES:
        path, expected = folder / 'inputs' / name, bundle['files'][name]
        if linked(folder / 'inputs') or linked(path) or path.stat().st_size != expected['bytes'] or sha(path) != expected['sha256']:
            raise ValueError('Исходный снимок корпуса повреждён.')
    with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
        db.execute('PRAGMA trusted_schema=OFF')
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or db.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Корпус не прошёл проверку целостности.')
        row = db.execute("SELECT value FROM meta WHERE key='overview'").fetchone()
        if row is None or json.loads(row[0]) != saved.get('overview'):
            raise ValueError('Метаданные корпуса отличаются от базы.')
    return saved


def verify_corpora(data_dir):
    """Validate optional sidecars during a full operational backup/restore drill."""
    root = Path(data_dir) / 'corpora'
    if not root.exists():
        return 0
    if linked(root):
        raise ValueError('Каталог корпуса не должен быть ссылкой.')
    if not (root / 'active.json').is_file():
        raise ValueError('Нет активного снимка корпуса.')
    identifier = small_json(root / 'active.json').get('snapshot_id', '')
    if not HEX.fullmatch(identifier):
        raise ValueError('Некорректный активный снимок корпуса.')
    count = 0
    for folder in root.iterdir():
        if folder.is_dir() and HEX.fullmatch(folder.name):
            verify_snapshot(folder)
            count += 1
    if not (root / identifier).is_dir():
        raise ValueError('Активный снимок корпуса отсутствует.')
    return count


class Corpus:
    def __init__(self, data_dir):
        self.root = Path(data_dir) / 'corpora'
        self.lock, self.cached = threading.RLock(), None

    def _active(self):
        pointer = self.root / 'active.json'
        if not pointer.exists():
            return None
        if linked(self.root):
            raise ValueError('Каталог корпуса не должен быть ссылкой.')
        identifier = small_json(pointer).get('snapshot_id', '')
        if not HEX.fullmatch(str(identifier)):
            raise ValueError('Некорректный активный снимок корпуса.')
        folder = self.root / identifier
        # Detect changed bytes/manifest metadata rather than serving a stale hash.
        paths = [folder / 'manifest.json', folder / 'corpus.sqlite3',
                 *(folder / 'inputs' / name for name in FILES)]
        key = (identifier, tuple((p.stat().st_size, p.stat().st_mtime_ns) for p in paths))
        with self.lock:
            if self.cached is None or self.cached[0] != key:
                self.cached = (key, verify_snapshot(folder))
            return folder, self.cached[1]

    @contextmanager
    def _connection(self):
        active = self._active()
        if active is None:
            raise ValueError('Корпус ещё не импортирован.')
        folder, saved = active
        db = sqlite3.connect((folder / 'corpus.sqlite3').resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA trusted_schema=OFF')
        try:
            yield db, saved
        finally:
            db.close()

    def overview(self):
        if self._active() is None:
            return {'available': False, 'status': 'not_imported', 'corpus': None, 'topics': [],
                    'message': 'Импортируйте готовый корпус Drift Inspector локальным инструментом. Новые модели для этого не нужны.'}
        with self._connection() as (db, saved):
            topics = []
            for row in db.execute('SELECT * FROM topics ORDER BY topic_id=-1,topic_id'):
                trajectory = [dict(point) for point in db.execute(
                    'SELECT year,numerator,denominator,share FROM topic_year WHERE topic_id=? ORDER BY year', (row['topic_id'],))]
                topics.append({'id': row['topic_id'], 'name': row['name'], 'full_name': row['full_name'],
                    'description': row['description'], 'papers': row['published_papers'],
                    'claims': row['published_claims'], 'is_noise': row['topic_id'] == -1,
                    'trajectory': trajectory, 'delta_pp': trajectory[-1]['share'] - trajectory[0]['share']})
            return {'available': True, 'status': 'ready', 'corpus': {
                **saved['overview'], 'snapshot_id': saved['snapshot_id'], 'imported_at': saved['imported_at']}, 'topics': topics}

    def topic(self, identifier, year=None, cohort='numerator', offset=0, limit=20):
        if (type(identifier) is not int or not -1 <= identifier <= 1000
                or cohort not in {'numerator', 'denominator'}
                or type(offset) is not int or not 0 <= offset <= 20000
                or type(limit) is not int or not 1 <= limit <= 100
                or (year is not None and (type(year) is not int or not 2020 <= year <= 2025))):
            raise ValueError('Некорректный фильтр корпуса.')
        with self._connection() as (db, saved):
            topic = db.execute('SELECT topic_id AS id,name FROM topics WHERE topic_id=?', (identifier,)).fetchone()
            if topic is None:
                raise ValueError('Тема не найдена.')
            where, params = 'p.in_analytic_sample=1', []
            if year is not None:
                where += ' AND p.year=?'
                params.append(year)
            denominator = db.execute('SELECT COUNT(*) FROM papers p WHERE ' + where, params).fetchone()[0]
            match = 'EXISTS(SELECT 1 FROM assignments a WHERE a.paper_id=p.paper_id AND a.topic_id=?)'
            numerator = db.execute('SELECT COUNT(*) FROM papers p WHERE ' + where + ' AND ' + match, [*params, identifier]).fetchone()[0]
            if cohort == 'numerator':
                where += ' AND ' + match
                params.append(identifier)
            rows = db.execute('SELECT p.paper_id,p.title,p.year,p.url,(SELECT COUNT(*) FROM assignments a '
                'WHERE a.paper_id=p.paper_id AND a.topic_id=?) AS claim_count FROM papers p WHERE ' + where +
                ' ORDER BY p.year,p.paper_id LIMIT ? OFFSET ?', [identifier, *params, limit, offset]).fetchall()
            return {'snapshot_id': saved['snapshot_id'], 'topic': dict(topic), 'year': year, 'cohort': cohort,
                'numerator': numerator, 'denominator': denominator,
                'total': numerator if cohort == 'numerator' else denominator, 'offset': offset,
                'limit': limit, 'items': [dict(row) for row in rows]}

    def paper(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch(r'20\d{2}\.emnlp-main\.\d+', identifier):
            raise ValueError('Некорректный идентификатор статьи.')
        with self._connection() as (db, saved):
            row = db.execute('SELECT paper_id,title,year,abstract,url,in_analytic_sample,venue,track,authors '
                             'FROM papers WHERE paper_id=?', (identifier,)).fetchone()
            if row is None:
                raise ValueError('Статья не найдена.')
            paper = dict(row)
            paper['in_analytic_sample'] = bool(paper['in_analytic_sample'])
            paper['authors'] = json.loads(paper['authors'])
            claims = []
            for item in db.execute('SELECT c.*,a.topic_id,t.name AS topic_name FROM claims c '
                    'LEFT JOIN assignments a USING(claim_id) LEFT JOIN topics t ON t.topic_id=a.topic_id '
                    'WHERE c.paper_id=? ORDER BY c.claim_id', (identifier,)):
                claims.append({**dict(item), 'origin': 'external_extraction',
                    'supporting_quote': None, 'validation_state': 'imported_unverified'})
            return {'paper': paper, 'claims': claims, 'provenance': saved['overview']['provenance'],
                    'snapshot_id': saved['snapshot_id']}
