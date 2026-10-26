"""Immutable, content-addressed research data in the existing local database."""
from datetime import datetime, timezone
import hashlib
import importlib
import json
import re

TABLES = ('research_assets', 'research_asset_claims')
KINDS = {
    'source_capture': 'evidence_archive',
    'evidence_assessment': 'evidence_validation',
    'measurement': 'research_workbench',
    'experiment_plan': 'research_experiments',
    'experiment_approval': 'research_experiments',
    'experiment_intent': 'research_experiments',
    'experiment_observation': 'research_experiments',
    'lexical_plan': 'lexical_benchmark',
    'lexical_approval': 'lexical_benchmark',
    'lexical_intent': 'lexical_benchmark',
    'lexical_result': 'lexical_benchmark',
    'evaluation_case': 'research_evaluation',
    'evaluation_annotation': 'research_evaluation',
    'public_dossier': 'research_public',
}
MAX_BYTES = 4 * 1024 * 1024
CAPTURE_BUDGET = 50 * 1024 * 1024


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def identity(kind, payload):
    return hashlib.sha256(canonical({'kind': kind, 'payload': payload}).encode()).hexdigest()


def validate_payload(kind, payload):
    if kind not in KINDS or not isinstance(payload, dict):
        raise ValueError('Неизвестный тип исследовательского артефакта.')
    encoded = canonical(payload)
    if len(encoded.encode('utf-8')) > MAX_BYTES:
        raise ValueError('Исследовательский артефакт превышает 4 МиБ.')
    module = importlib.import_module('.' + KINDS[kind], __package__)
    module.validate_asset(kind, payload)


def initialize(store):
    with store.connect() as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS research_assets(
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL,
                created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS research_assets_kind ON research_assets(kind);
            CREATE TABLE IF NOT EXISTS research_asset_claims(
                claim_key TEXT PRIMARY KEY,
                asset_id TEXT NOT NULL REFERENCES research_assets(id));
        ''')


class Assets:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def _row(row):
        if row is None:
            raise ValueError('Исследовательский артефакт не найден.')
        result = dict(row)
        result['payload'] = json.loads(result['payload'])
        if identity(result['kind'], result['payload']) != result['id']:
            raise ValueError('Контрольная сумма артефакта не совпала.')
        return result

    def get(self, asset_id):
        if not isinstance(asset_id, str) or not re.fullmatch('[0-9a-f]{64}', asset_id):
            raise ValueError('Некорректный идентификатор артефакта.')
        with self.store.connect() as db:
            return self._row(db.execute(
                'SELECT * FROM research_assets WHERE id=?', (asset_id,)).fetchone())

    def list(self, kind=None, limit=100):
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise ValueError('Некорректный предел списка артефактов.')
        if kind is not None and kind not in KINDS:
            raise ValueError('Неизвестный тип исследовательского артефакта.')
        with self.store.connect() as db:
            query = 'SELECT * FROM research_assets'
            values = []
            if kind is not None:
                query += ' WHERE kind=?'
                values.append(kind)
            query += ' ORDER BY created_at DESC,rowid DESC LIMIT ?'
            return [self._row(row) for row in db.execute(query, [*values, limit])]

    def _insert(self, db, kind, payload):
        asset_id = identity(kind, payload)
        encoded = canonical(payload)
        exists = db.execute('SELECT 1 FROM research_assets WHERE id=?', (asset_id,)).fetchone()
        if not exists and kind == 'source_capture':
            used = db.execute("SELECT COALESCE(SUM(length(CAST(payload AS BLOB))),0) "
                              "FROM research_assets WHERE kind='source_capture'").fetchone()[0]
            if used + len(encoded.encode('utf-8')) > CAPTURE_BUDGET:
                raise ValueError('Архив источников достиг локального предела 50 МиБ.')
        db.execute('INSERT OR IGNORE INTO research_assets VALUES (?,?,?,?)',
                   (asset_id, kind, encoded, datetime.now(timezone.utc).isoformat()))
        return self._row(db.execute(
            'SELECT * FROM research_assets WHERE id=?', (asset_id,)).fetchone())

    def put(self, kind, payload):
        if kind in {'lexical_approval', 'lexical_intent', 'lexical_result'}:
            raise ValueError('Результат CPU-проверки требует связанного однократного журнала.')
        validate_payload(kind, payload)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            return self._insert(db, kind, payload)

    def claim(self, kind, payload, claim_key):
        validate_payload(kind, payload)
        if (not isinstance(claim_key, str) or not 1 <= len(claim_key) <= 300
                or any(ord(char) < 32 for char in claim_key)):
            raise ValueError('Некорректный ключ однократного действия.')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if kind == 'experiment_approval':
                from .research_experiments import validate_claim
                validate_claim(db, payload)
            if kind in {'lexical_approval', 'lexical_intent', 'lexical_result'}:
                from .lexical_benchmark import validate_claim
                expected = {'lexical_approval': 'lexical-approval:',
                            'lexical_intent': 'lexical-intent:',
                            'lexical_result': 'lexical-result:'}[kind] + payload['plan_id']
                if claim_key != expected:
                    raise ValueError('Неверный ключ однократной CPU-проверки.')
                validate_claim(db, payload)
            if db.execute('SELECT 1 FROM research_asset_claims WHERE claim_key=?',
                          (claim_key,)).fetchone():
                raise ValueError('Действие уже зарегистрировано; повтор запрещён.')
            result = self._insert(db, kind, payload)
            db.execute('INSERT INTO research_asset_claims VALUES (?,?)',
                       (claim_key, result['id']))
            return result


def validate_backup_table(table, row, db):
    if table == 'research_assets':
        if not isinstance(row, dict) or set(row) != {'id', 'kind', 'payload', 'created_at'}:
            raise ValueError('Повреждена запись исследовательского архива.')
        if not isinstance(row['payload'], str):
            raise ValueError('Повреждено содержимое исследовательского архива.')
        payload = json.loads(row['payload'])
        validate_payload(row['kind'], payload)
        if identity(row['kind'], payload) != row['id']:
            raise ValueError('Контрольная сумма исследовательского архива не совпала.')
        stamp = datetime.fromisoformat(row['created_at'])
        if stamp.tzinfo is None:
            raise ValueError('Время артефакта не содержит часовой пояс.')
    elif table == 'research_asset_claims':
        if (not isinstance(row, dict) or set(row) != {'claim_key', 'asset_id'}
                or not isinstance(row['claim_key'], str) or not 1 <= len(row['claim_key']) <= 300
                or any(ord(char) < 32 for char in row['claim_key'])
                or not db.execute('SELECT 1 FROM research_assets WHERE id=?',
                                  (row['asset_id'],)).fetchone()):
            raise ValueError('Повреждена запись однократного действия.')
    else:
        raise ValueError('Неизвестная таблица исследовательского архива.')


def validate_backup(db):
    size = db.execute("SELECT COALESCE(SUM(length(CAST(payload AS BLOB))),0) "
                      "FROM research_assets WHERE kind='source_capture'").fetchone()[0]
    if size > CAPTURE_BUDGET:
        raise ValueError('Архив источников превышает локальный предел.')
    for row in db.execute('SELECT payload FROM research_assets'):
        payload = json.loads(row[0])
        run_id = payload.get('run_id')
        if run_id is not None and not db.execute(
                'SELECT 1 FROM runs WHERE id=?', (run_id,)).fetchone():
            raise ValueError('Артефакт ссылается на отсутствующий отчёт.')
    from .evidence_archive import validate_bundle
    for row in db.execute('SELECT plan FROM runs'):
        plan = json.loads(row[0])
        bundle = plan.get('evidence_bundle')
        if bundle is None:
            continue
        validate_bundle(bundle, plan['sources'])
        for document in bundle['documents']:
            captured = db.execute('SELECT kind,payload FROM research_assets WHERE id=?',
                                  (document['asset_id'],)).fetchone()
            if not captured or captured[0] != 'source_capture':
                raise ValueError('В плане отсутствует сохранённый оригинал источника.')
            payload = json.loads(captured[1])
            if any(document[key] != payload[key] for key in (
                    'source_id', 'url', 'kind', 'sha256', 'origin')):
                raise ValueError('Снимок документа отличается от архивного оригинала.')
            if (document['status'] != payload['status']
                    and not (document['status'] == 'partial'
                             and payload['status'] in {'captured', 'partial'})):
                raise ValueError('Статус выдержки не соответствует оригиналу.')
            original = {segment['id']: segment for segment in payload['segments']}
            if any(segment != original.get(segment['id']) for segment in document['segments']):
                raise ValueError('Выдержка в плане отличается от архивного сегмента.')
    for name in ('research_workbench', 'research_evaluation', 'research_experiments', 'lexical_benchmark'):
        importlib.import_module('.' + name, __package__).validate_backup(db)
