"""One explicitly approved, local lexical benchmark with immutable receipts.

Preparing a plan only verifies local data. Only ``start`` can enter the engine,
after an atomic approval and a durable intent. An interrupted intent is never
retried, including after restoring a database backup.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import copy
import hashlib
import importlib
import io
import json
import math
from pathlib import Path
import platform
import re
import sys
import threading
import time
import zipfile

from .research_assets import Assets, MAX_BYTES, canonical, identity

SOURCE_URL = 'https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/scifact.zip'
OFFICIAL_ARCHIVE_MD5 = '5f7d1de60b170fc8027bb7898e2efca1'
DATASET_PARTS = ('sources', 'lexical', 'scifact')
FILE_LIMITS = {'corpus.jsonl': 100 * 1024 * 1024,
               'queries.jsonl': 8 * 1024 * 1024,
               'qrels/test.tsv': 2 * 1024 * 1024}
LIMITS = {'max_documents': 6000, 'max_test_queries': 350, 'top_k': 100,
          'repetitions': 6, 'timeout_seconds': 180, 'estimated_peak_ram_mib': 512,
          'external_model_calls': 0, 'monetary_api_cost_usd': 0,
          'local_energy_cost_usd': None}
LICENSES = {'annotations': 'CC BY 4.0', 'corpus': 'ODC-By 1.0 (S2ORC)',
            'source': 'https://github.com/allenai/scifact/blob/master/LICENSE.md',
            'citation': 'Wadden et al. (EMNLP 2020); BEIR, Thakur et al. (NeurIPS 2021)'}
SCOPE = 'BEIR SciFact test: TF-IDF cosine versus BM25 lexical retrieval only'
NOTICE = ('Только локальное лексическое извлечение SciFact; результат не подтверждает '
          'QDRec, память агентов или качество ответов RAG. Незавершённый intent '
          'не повторяется автоматически. Стоимость локальной энергии не измерена.')
_LOCKS, _ACTIVE, _GUARD = {}, set(), threading.Lock()


def _sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else
                          value.encode('utf-8')).hexdigest()


def _digest(value):
    return _sha(canonical(value))


def _exact(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError('Неизвестные или отсутствующие поля лексического протокола.')


def _hash(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('Некорректная SHA-256 лексического артефакта.')


def _text(value, maximum=256):
    if (not isinstance(value, str) or not 1 <= len(value) <= maximum or
            any(ord(char) < 32 for char in value)):
        raise ValueError('Некорректное текстовое поле лексического артефакта.')


def _integer(value, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError('Нарушена целочисленная граница лексического протокола.')


def _number(value, lower=0, upper=1e12):
    if type(value) not in (int, float) or not math.isfinite(value) or not lower <= value <= upper:
        raise ValueError('Метрика должна быть конечным числом в допустимых границах.')


def _stamp(value=None):
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    if not isinstance(value, str) or len(value) > 80:
        raise ValueError('Некорректное время лексического артефакта.')
    if datetime.fromisoformat(value).tzinfo is None:
        raise ValueError('Время лексического артефакта требует часового пояса.')
    return value


def _engine():
    return importlib.import_module('.lexical_engine', __package__)


def _protocol():
    result = copy.deepcopy(_engine().PROTOCOL)
    result['repeats'] = 6
    result['max_elapsed_seconds'] = 180.0
    result['test_only'] = False
    return result


def _engine_identity():
    module = _engine()
    return {'module': 'laboratory.lexical_engine', 'version': module.VERSION,
            'sha256': _sha(Path(module.__file__).read_bytes())}


def _runtime():
    return {'implementation': platform.python_implementation(),
            'version': platform.python_version(), 'cache_tag': sys.implementation.cache_tag,
            'platform': platform.platform(), 'machine': platform.machine(),
            'executable_sha256': _sha(Path(sys.executable).read_bytes())}


def validate_manifest(value):
    _exact(value, {'version', 'dataset', 'source_url', 'archive_sha256', 'archive_md5',
                   'files', 'query_ids', 'counts'})
    if (value['version'] != 'lexical-dataset-v1' or value['dataset'] != 'beir-scifact' or
            value['source_url'] != SOURCE_URL or value['archive_md5'] != OFFICIAL_ARCHIVE_MD5):
        raise ValueError('Разрешён только фиксированный официальный архив BEIR SciFact.')
    _hash(value['archive_sha256'])
    _exact(value['files'], FILE_LIMITS)
    for name, maximum in FILE_LIMITS.items():
        row = value['files'][name]
        _exact(row, {'sha256', 'bytes', 'records'})
        _hash(row['sha256'])
        _integer(row['bytes'], 1, maximum)
        _integer(row['records'], 1, 30000)
    counts = value['counts']
    _exact(counts, {'documents', 'queries', 'test_queries', 'qrels'})
    _integer(counts['documents'], 1, LIMITS['max_documents'])
    _integer(counts['queries'], 1, 30000)
    _integer(counts['test_queries'], 1, LIMITS['max_test_queries'])
    _integer(counts['qrels'], counts['test_queries'], 30000)
    ids = value['query_ids']
    if not isinstance(ids, list) or len(ids) != counts['test_queries']:
        raise ValueError('Нужен полный упорядоченный список уникальных test query IDs.')
    for value_id in ids:
        _text(value_id)
    if len(set(ids)) != len(ids) or ids != sorted(ids):
        raise ValueError('Test query IDs должны быть уникальны и упорядочены.')
    if (counts['queries'] < counts['test_queries'] or
            value['files']['corpus.jsonl']['records'] != counts['documents'] or
            value['files']['queries.jsonl']['records'] != counts['queries'] or
            value['files']['qrels/test.tsv']['records'] != counts['qrels']):
        raise ValueError('Размеры файлов и полные счётчики датасета расходятся.')


def _safe_file(root, name):
    """Only named members beneath the fixed store root; no links or alternate path."""
    if name not in {*FILE_LIMITS, 'scifact.zip', 'manifest.json'}:
        raise ValueError('Произвольный путь к датасету запрещён.')
    path = root.joinpath(*name.split('/'))
    anchor = root.parents[2]
    for part in [path, *path.parents]:
        if part.is_symlink():
            raise ValueError('Символьные ссылки в локальном датасете запрещены.')
        if part == anchor:
            break
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Фиксированный файл локального датасета отсутствует или перенаправлен.')
    if not root.resolve().is_relative_to(anchor.resolve()):
        raise ValueError('Локальный датасет выходит за фиксированную папку хранилища.')
    return path


def _verify_archive(root, manifest):
    archive = _safe_file(root, 'scifact.zip')
    if not 1 <= archive.stat().st_size <= 64 * 1024 * 1024:
        raise ValueError('Архив SciFact превышает фиксированный предел.')
    data = archive.read_bytes()
    if (_sha(data) != manifest['archive_sha256'] or
            hashlib.md5(data).hexdigest() != OFFICIAL_ARCHIVE_MD5):
        raise ValueError('Официальный архив SciFact изменился; выполнение запрещено.')
    with zipfile.ZipFile(io.BytesIO(data)) as zipped:
        for name, row in manifest['files'].items():
            with zipped.open('scifact/' + name) as member:
                data = member.read(row['bytes'] + 1)
            if len(data) != row['bytes'] or _sha(data) != row['sha256']:
                raise ValueError('Локальные файлы не соответствуют официальному архиву.')


def _dataset(root, manifest):
    """Parse exactly the bytes whose hashes were approved, before engine entry."""
    validate_manifest(manifest)
    _verify_archive(root, manifest)
    content = {}
    for name, maximum in FILE_LIMITS.items():
        path = _safe_file(root, name)
        if path.stat().st_size > maximum:
            raise ValueError('Локальный файл превышает предел до чтения.')
        raw = path.read_bytes()
        if len(raw) != manifest['files'][name]['bytes'] or _sha(raw) != manifest['files'][name]['sha256']:
            raise ValueError('Датасет изменился; требуется новый план и новый апрув.')
        content[name] = raw.decode('utf-8')
    corpus, corpus_ids, all_queries = [], set(), {}
    for name in ('corpus.jsonl', 'queries.jsonl'):
        records = [json.loads(line) for line in content[name].splitlines() if line.strip()]
        if len(records) != manifest['files'][name]['records']:
            raise ValueError('Число JSONL записей не совпало с планом.')
        for row in records:
            allowed = {'_id', 'title', 'text', 'metadata'} if name == 'corpus.jsonl' else {'_id', 'text', 'metadata'}
            if not isinstance(row, dict) or set(row) - allowed or not {'_id', 'text'} <= set(row):
                raise ValueError('Повреждена фиксированная запись BEIR.')
            identifier = row['_id']
            _text(identifier)
            if not isinstance(row['text'], str) or len(row['text']) > 1000000:
                raise ValueError('Повреждён или слишком велик текст BEIR.')
            if name == 'corpus.jsonl':
                if (identifier in corpus_ids or not isinstance(row.get('title', ''), str) or
                        len(row.get('title', '')) > 100000):
                    raise ValueError('Повторяется документ или повреждён заголовок BEIR.')
                corpus_ids.add(identifier)
                corpus.append({'_id': identifier, 'title': row.get('title', ''), 'text': row['text']})
            else:
                if identifier in all_queries:
                    raise ValueError('Повторяется query ID BEIR.')
                all_queries[identifier] = row['text']
    lines = [line for line in content['qrels/test.tsv'].splitlines() if line.strip()]
    if not lines or lines.pop(0).split('\t') != ['query-id', 'corpus-id', 'score']:
        raise ValueError('Некорректный заголовок официальных test qrels.')
    if len(lines) != manifest['counts']['qrels']:
        raise ValueError('Число test qrels не совпало с планом.')
    qrels = {}
    for line in lines:
        cells = line.split('\t')
        if len(cells) != 3:
            raise ValueError('Повреждена строка test qrels.')
        qid, did, score = cells
        _text(qid)
        _text(did)
        if qid not in all_queries or did not in corpus_ids or did in qrels.setdefault(qid, {}):
            raise ValueError('Test qrel повторяется или ссылается на отсутствующий текст.')
        if not re.fullmatch('[0-9]{1,2}', score) or not 0 <= int(score) <= 20:
            raise ValueError('Недопустимая оценка релевантности test qrel.')
        qrels[qid][did] = int(score)
    if (sorted(qrels) != manifest['query_ids'] or
            any(not any(score > 0 for score in rows.values()) for rows in qrels.values())):
        raise ValueError('Test queries неполны или не имеют положительного judgment.')
    return corpus, {qid: all_queries[qid] for qid in manifest['query_ids']}, qrels


def _run_engine(corpus, queries, qrels, protocol, cancel):
    return _engine().run(corpus, queries, qrels, protocol, cancel=cancel)


@contextmanager
def _active(key):
    with _GUARD:
        _ACTIVE.add(key)
    try:
        yield
    finally:
        with _GUARD:
            _ACTIVE.discard(key)


class LexicalBenchmark:
    def __init__(self, store):
        self.store, self.assets = store, Assets(store)
        self.root = Path(store.data_dir).joinpath(*DATASET_PARTS)
        self.key = str(Path(store.data_dir).resolve())
        with _GUARD:
            self.lock = _LOCKS.setdefault(self.key, threading.RLock())

    def prepare(self, manifest):
        manifest = copy.deepcopy(manifest)
        _dataset(self.root, manifest)
        payload = {'version': 'lexical-plan-v1', 'scope': SCOPE, 'manifest': manifest,
                   'protocol': _protocol(), 'limits': copy.deepcopy(LIMITS),
                   'licenses': copy.deepcopy(LICENSES),
                   'engine': _engine_identity(), 'runtime': _runtime(), 'notice': NOTICE}
        asset = self.assets.put('lexical_plan', payload)
        return {**asset, 'plan_id': asset['id'], 'plan_hash': _digest(payload)}

    def _all(self, kind):
        return self.assets.list(kind, limit=10000)

    def list(self):
        plans = self._all('lexical_plan')[:200]
        indexes = {kind: {} for kind in ('lexical_approval', 'lexical_intent', 'lexical_result')}
        for kind, index in indexes.items():
            for asset in self._all(kind):
                index.setdefault(asset['payload']['plan_id'], asset)
        result = []
        for plan in plans:
            plan_id = plan['id']
            status = self._status(plan, *(indexes[kind].get(plan_id) for kind in indexes))
            receipt = status.pop('result')
            raw = receipt['raw'] if receipt else None
            result.append({**plan, **status, 'origin': receipt['origin'] if receipt else None,
                           'scope': SCOPE, 'metrics': raw['metrics'] if raw else None,
                           'counts': raw['counts'] if raw else None})
        return result

    def status(self, plan_id=None):
        if plan_id is None:
            return [{key: value for key, value in asset.items() if key not in
                     {'payload', 'kind', 'created_at', 'id'}} for asset in self.list()[:100]]
        plan = self.assets.get(plan_id)
        if plan['kind'] != 'lexical_plan':
            raise ValueError('Выбран не лексический план.')
        approval = next((row for row in self._all('lexical_approval')
                         if row['payload']['plan_id'] == plan_id), None)
        intent = next((row for row in self._all('lexical_intent')
                       if row['payload']['plan_id'] == plan_id), None)
        result = next((row for row in self._all('lexical_result')
                       if row['payload']['plan_id'] == plan_id), None)
        return self._status(plan, approval, intent, result)

    def _status(self, plan, approval, intent, result):
        plan_id = plan['id']
        with _GUARD:
            active = (self.key, plan_id) in _ACTIVE
        state = (result['payload']['status'] if result else 'running' if active else
                 'outcome_unknown' if approval or intent else 'planned')
        return {'plan_id': plan_id, 'plan_hash': _digest(plan['payload']), 'status': state,
                'completed': state == 'completed',
                'passed': result['payload']['passed'] if result else None,
                'approval_id': approval['id'] if approval else None,
                'intent_id': intent['id'] if intent else None,
                'result_id': result['id'] if result else None,
                'result': result['payload'] if result else None, 'notice': NOTICE}

    def start(self, plan_id, plan_hash, consent, command_id, cancel_event=None):
        if consent is not True:
            raise ValueError('Нужен отдельный явный апрув точного локального лексического плана.')
        _hash(plan_id)
        _hash(plan_hash)
        _text(command_id, 100)
        if len(command_id) < 8:
            raise ValueError('Слишком короткий ID команды лексического запуска.')
        cancel = cancel_event or threading.Event()
        with self.lock:
            asset = self.assets.get(plan_id)
            if asset['kind'] != 'lexical_plan' or _digest(asset['payload']) != plan_hash:
                raise ValueError('Точный лексический план изменился; нужен новый апрув.')
            plan = asset['payload']
            validate_asset('lexical_plan', plan)
            if any(row['payload']['plan_id'] == plan_id for row in self._all('lexical_approval')):
                return self.status(plan_id)
            if plan['engine'] != _engine_identity() or plan['runtime'] != _runtime():
                raise ValueError('Код или Python runtime изменились; нужен новый план и апрув.')
            corpus, queries, qrels = _dataset(self.root, plan['manifest'])
            approval_payload = {'version': 'lexical-approval-v1', 'plan_id': plan_id,
                'plan_hash': plan_hash, 'consent': True, 'command_id': command_id,
                'approved_at': _stamp(), **_approval_hashes(plan)}
            try:
                approval = self.assets.claim('lexical_approval', approval_payload,
                                             'lexical-approval:' + plan_id)
            except ValueError:
                if any(row['payload']['plan_id'] == plan_id for row in self._all('lexical_approval')):
                    return self.status(plan_id)
                raise
            with _active((self.key, plan_id)):
                intent = self.assets.claim('lexical_intent', {
                    'version': 'lexical-intent-v1', 'plan_id': plan_id,
                    'plan_hash': plan_hash, 'approval_id': approval['id'],
                    'input_sha256': _digest({'manifest': plan['manifest'], 'protocol': plan['protocol']}),
                    'started_at': _stamp()}, 'lexical-intent:' + plan_id)
                started = time.monotonic()
                raw, state, error = None, 'cancelled' if cancel.is_set() else 'completed', ''
                if state == 'completed':
                    try:
                        # Recheck after the durable intent as well: approval is
                        # authority for these exact bytes, implementation and runtime.
                        current = {**plan, 'engine': _engine_identity(), 'runtime': _runtime()}
                        if any(approval['payload'][key] != value for key, value in _approval_hashes(current).items()):
                            raise ValueError('Одобренный код или Python runtime изменились перед engine.')
                        corpus, queries, qrels = _dataset(self.root, plan['manifest'])
                        raw = _run_engine(corpus, queries, qrels, copy.deepcopy(plan['protocol']), cancel)
                        _validate_result_data(raw, plan)
                        if time.monotonic() - started > plan['limits']['timeout_seconds']:
                            raise TimeoutError('Локальный срок выполнения истёк.')
                    except Exception:
                        raw, state = None, 'cancelled' if cancel.is_set() else 'failed'
                        error = ('Лексический benchmark остановлен; измерение не завершено, '
                                 'автоматического повтора нет.')
                payload = {'version': 'lexical-result-v1', 'origin': 'executed_local_lexical',
                    'source_algorithm_version': plan['engine']['version'], 'scope': SCOPE,
                    'plan_id': plan_id, 'plan_hash': plan_hash, 'approval_id': approval['id'],
                    'intent_id': intent['id'], 'manifest': plan['manifest'],
                    'status': state, 'completed': state == 'completed',
                    'passed': raw['passed'] if raw is not None else None,
                    'raw': raw, 'raw_sha256': _digest(raw) if raw is not None else None,
                    'metrics_sha256': _digest(raw['metrics']) if raw is not None else None,
                    'rankings_sha256': _digest(raw['rankings']) if raw is not None else None,
                    'elapsed_seconds': max(0, time.monotonic() - started),
                    'external_model_calls': 0, 'monetary_api_cost_usd': 0,
                    'local_energy_cost_usd': None, 'error': error,
                    'finished_at': _stamp(), 'notice': NOTICE}
                if len(canonical(payload).encode('utf-8')) > MAX_BYTES:
                    payload.update(status='failed', completed=False, passed=None, raw=None,
                                   raw_sha256=None, metrics_sha256=None, rankings_sha256=None,
                                   error='Результат превысил 4 МиБ; завершение не подтверждено.')
                self.assets.claim('lexical_result', payload, 'lexical-result:' + plan_id)
            return self.status(plan_id)


def _approval_hashes(plan):
    return {'manifest_sha256': _digest(plan['manifest']),
            'protocol_sha256': _digest(plan['protocol']),
            'engine_sha256': _digest(plan['engine']), 'runtime_sha256': _digest(plan['runtime'])}


def _validate_result_data(raw, plan=None):
    """The engine's strict validator is augmented with frozen-dataset checks."""
    module = _engine()
    module.validate_result(raw, plan['protocol'] if plan is not None else None)
    # The engine schema is fixed; arbitrary imported payloads cannot become receipts.
    _exact(raw, {'schema_version', 'engine_version', 'completed', 'passed', 'metrics',
                 'per_query', 'outcomes', 'rankings', 'timings', 'environment', 'protocol', 'counts'})
    if (raw['schema_version'] != 'lexical-retrieval-v1' or raw['completed'] is not True or
            type(raw['passed']) is not bool or raw['engine_version'] != module.VERSION):
        raise ValueError('Некорректное завершённое локальное измерение.')
    if plan is not None:
        manifest = plan['manifest']
        ids = manifest['query_ids']
        if (raw['engine_version'] != plan['engine']['version'] or raw['protocol'] != plan['protocol'] or
                sorted(raw['per_query']) != ids or
                raw['counts'] != {'documents': manifest['counts']['documents'],
                                  'queries': manifest['counts']['test_queries'],
                                  'judgments': manifest['counts']['qrels']}):
            raise ValueError('Измерение не покрывает точный замороженный план.')
        for arm in ('tfidf', 'bm25'):
            if sorted(raw['rankings'][arm]) != ids or any(
                    len(rows) != min(100, manifest['counts']['documents'])
                    for rows in raw['rankings'][arm].values()):
                raise ValueError('Сохранены не все top-100 для обеих конфигураций.')
        environment, runtime = raw['environment'], plan.get('runtime')
        if runtime is not None and any(environment[field] != runtime[key] for field, key in (
                ('python_version', 'version'), ('python_implementation', 'implementation'),
                ('platform', 'platform'), ('machine', 'machine'))):
            raise ValueError('Измерение получено в другом Python runtime.')


def validate_asset(kind, payload):
    if not isinstance(payload, dict):
        raise ValueError('Лексический артефакт должен быть объектом.')
    if kind == 'lexical_plan':
        _exact(payload, {'version', 'scope', 'manifest', 'protocol', 'limits', 'licenses', 'engine', 'runtime', 'notice'})
        if (payload['version'] != 'lexical-plan-v1' or payload['scope'] != SCOPE or
                canonical(payload['limits']) != canonical(LIMITS) or
                payload['licenses'] != LICENSES or
                canonical(payload['protocol']) != canonical(_protocol()) or payload['notice'] != NOTICE):
            raise ValueError('Лексический план должен содержать полный фиксированный протокол.')
        validate_manifest(payload['manifest'])
        _exact(payload['engine'], {'module', 'version', 'sha256'})
        if payload['engine']['module'] != 'laboratory.lexical_engine' or payload['engine']['version'] != _engine().VERSION:
            raise ValueError('Произвольный исполняемый модуль запрещён.')
        _hash(payload['engine']['sha256'])
        _exact(payload['runtime'], {'implementation', 'version', 'cache_tag', 'platform', 'machine', 'executable_sha256'})
        for name, value in payload['runtime'].items():
            _hash(value) if name == 'executable_sha256' else _text(value, 1000)
        return
    if kind == 'lexical_approval':
        _exact(payload, {'version', 'plan_id', 'plan_hash', 'consent', 'command_id',
                         'approved_at', 'manifest_sha256', 'protocol_sha256', 'engine_sha256', 'runtime_sha256'})
        if payload['version'] != 'lexical-approval-v1' or payload['consent'] is not True:
            raise ValueError('Нужен явный апрув точного лексического плана.')
        _text(payload['command_id'], 100)
        if len(payload['command_id']) < 8:
            raise ValueError('Повреждён ID команды лексического запуска.')
        _stamp(payload['approved_at'])
        for key in ('plan_id', 'plan_hash', 'manifest_sha256', 'protocol_sha256', 'engine_sha256', 'runtime_sha256'):
            _hash(payload[key])
        return
    if kind == 'lexical_intent':
        _exact(payload, {'version', 'plan_id', 'plan_hash', 'approval_id', 'input_sha256', 'started_at'})
        if payload['version'] != 'lexical-intent-v1':
            raise ValueError('Некорректная версия лексического intent.')
        for key in ('plan_id', 'plan_hash', 'approval_id', 'input_sha256'):
            _hash(payload[key])
        _stamp(payload['started_at'])
        return
    if kind != 'lexical_result':
        raise ValueError('Неизвестный лексический артефакт.')
    _exact(payload, {'version', 'origin', 'source_algorithm_version', 'scope', 'plan_id', 'plan_hash',
        'approval_id', 'intent_id', 'manifest', 'status', 'completed', 'passed', 'raw', 'raw_sha256',
        'metrics_sha256', 'rankings_sha256', 'elapsed_seconds', 'external_model_calls',
        'monetary_api_cost_usd', 'local_energy_cost_usd', 'error', 'finished_at', 'notice'})
    if (payload['version'] != 'lexical-result-v1' or payload['origin'] != 'executed_local_lexical' or
            payload['scope'] != SCOPE or payload['source_algorithm_version'] != _engine().VERSION or
            payload['notice'] != NOTICE or type(payload['completed']) is not bool or
            payload['status'] not in {'completed', 'failed', 'cancelled'} or
            payload['completed'] != (payload['status'] == 'completed') or
            type(payload['external_model_calls']) is not int or payload['external_model_calls'] != 0 or
            type(payload['monetary_api_cost_usd']) not in (int, float) or
            payload['monetary_api_cost_usd'] != 0 or payload['local_energy_cost_usd'] is not None):
        raise ValueError('Неверное происхождение, область или стоимость лексического результата.')
    for key in ('plan_id', 'plan_hash', 'approval_id', 'intent_id'):
        _hash(payload[key])
    validate_manifest(payload['manifest'])
    _number(payload['elapsed_seconds'])
    _stamp(payload['finished_at'])
    if not isinstance(payload['error'], str) or len(payload['error']) > 1000:
        raise ValueError('Некорректная ошибка лексического выполнения.')
    raw = payload['raw']
    if payload['completed']:
        _validate_result_data(raw, {'manifest': payload['manifest'], 'protocol': _protocol(),
                                   'engine': {'version': payload['source_algorithm_version']}})
        if (type(payload['passed']) is not bool or payload['passed'] != raw['passed'] or payload['error'] or
                payload['raw_sha256'] != _digest(raw) or
                payload['metrics_sha256'] != _digest(raw['metrics']) or
                payload['rankings_sha256'] != _digest(raw['rankings'])):
            raise ValueError('Контрольные суммы метрик или ранжирования не совпали.')
    elif any(payload[key] is not None for key in ('raw', 'passed', 'raw_sha256', 'metrics_sha256', 'rankings_sha256')):
        raise ValueError('Незавершённое выполнение не имеет завершённых метрик.')


def _db_assets(db):
    result = {}
    for row in db.execute("SELECT id,kind,payload FROM research_assets WHERE kind LIKE 'lexical_%'"):
        payload = json.loads(row['payload'])
        validate_asset(row['kind'], payload)
        if identity(row['kind'], payload) != row['id']:
            raise ValueError('Контрольная сумма лексического артефакта не совпала.')
        result[row['id']] = {'kind': row['kind'], 'payload': payload}
    return result


def validate_claim(db, payload):
    """Validate one-shot lexical relationships inside Assets' write transaction."""
    if not isinstance(payload, dict):
        raise ValueError('Некорректная однократная лексическая запись.')
    kind = {'lexical-approval-v1': 'lexical_approval',
            'lexical-intent-v1': 'lexical_intent',
            'lexical-result-v1': 'lexical_result'}.get(payload.get('version'))
    if kind is None:
        raise ValueError('Неизвестная однократная лексическая запись.')
    validate_asset(kind, payload)
    row = db.execute('SELECT id,kind,payload FROM research_assets WHERE id=?', (payload['plan_id'],)).fetchone()
    if not row or row['kind'] != 'lexical_plan':
        raise ValueError('Апрув ссылается не на лексический план.')
    plan = json.loads(row['payload'])
    validate_asset('lexical_plan', plan)
    if identity('lexical_plan', plan) != row['id'] or _digest(plan) != payload['plan_hash']:
        raise ValueError('Апрув не соответствует точному плану, коду, runtime или датасету.')
    for row in db.execute('SELECT payload FROM research_assets WHERE kind=?', (kind,)):
        previous = json.loads(row[0])
        if (previous['plan_id'] == payload['plan_id'] or kind == 'lexical_approval' and
                previous['command_id'] == payload['command_id']):
            raise ValueError('Лексический план или команда уже использованы; повтор запрещён.')
    if kind == 'lexical_approval':
        if any(payload[key] != value for key, value in _approval_hashes(plan).items()):
            raise ValueError('Апрув изменил замороженный датасет, код, runtime или протокол.')
        return

    def parent(asset_id, parent_kind, claim):
        row = db.execute('SELECT id,kind,payload FROM research_assets WHERE id=?', (asset_id,)).fetchone()
        if not row or row['kind'] != parent_kind:
            raise ValueError('Отсутствует предшествующий однократный лексический артефакт.')
        value = json.loads(row['payload'])
        validate_asset(parent_kind, value)
        registered = db.execute('SELECT asset_id FROM research_asset_claims WHERE claim_key=?',
                                (claim + payload['plan_id'],)).fetchone()
        if (identity(parent_kind, value) != asset_id or value['plan_id'] != payload['plan_id'] or
                value['plan_hash'] != payload['plan_hash'] or not registered or registered[0] != asset_id):
            raise ValueError('Однократный предшественник не соответствует точному плану.')
        return value

    approval = parent(payload['approval_id'], 'lexical_approval', 'lexical-approval:')
    if kind == 'lexical_intent':
        if (payload['input_sha256'] != _digest({'manifest': plan['manifest'], 'protocol': plan['protocol']}) or
                datetime.fromisoformat(payload['started_at']) < datetime.fromisoformat(approval['approved_at'])):
            raise ValueError('Intent отличается от одобренных входов или предшествует апруву.')
    else:
        intent = parent(payload['intent_id'], 'lexical_intent', 'lexical-intent:')
        if (intent['approval_id'] != payload['approval_id'] or payload['manifest'] != plan['manifest'] or
                payload['source_algorithm_version'] != plan['engine']['version'] or
                datetime.fromisoformat(payload['finished_at']) < datetime.fromisoformat(intent['started_at'])):
            raise ValueError('Локальный receipt не соответствует своему intent.')
        if payload['completed']:
            if payload['elapsed_seconds'] > plan['limits']['timeout_seconds']:
                raise ValueError('Локальное выполнение превысило одобренный срок.')
            _validate_result_data(payload['raw'], plan)


def validate_backup(db):
    """Validate the complete graph using database contents only, never local files."""
    assets = _db_assets(db)
    claims = {row['claim_key']: row['asset_id'] for row in db.execute(
        'SELECT claim_key,asset_id FROM research_asset_claims')}
    commands, seen = set(), {kind: set() for kind in ('lexical_approval', 'lexical_intent', 'lexical_result')}
    for asset_id, asset in assets.items():
        kind, value = asset['kind'], asset['payload']
        if kind == 'lexical_plan':
            continue
        plan_id = value['plan_id']
        parent = assets.get(plan_id)
        if not parent or parent['kind'] != 'lexical_plan':
            raise ValueError('Лексический артефакт не связан с замороженным планом.')
        plan = parent['payload']
        if plan_id in seen[kind] or value['plan_hash'] != _digest(plan):
            raise ValueError('Повтор лексического выполнения или изменение точного плана.')
        seen[kind].add(plan_id)
        expected_claim = {'lexical_approval': 'lexical-approval:', 'lexical_intent': 'lexical-intent:',
                          'lexical_result': 'lexical-result:'}[kind] + plan_id
        if claims.get(expected_claim) != asset_id:
            raise ValueError('Лексический артефакт не имеет своей однократной регистрации.')
        if kind == 'lexical_approval':
            if value['command_id'] in commands or any(value[key] != check for key, check in _approval_hashes(plan).items()):
                raise ValueError('Повтор команды или изменение одобренных условий.')
            commands.add(value['command_id'])
            continue
        approval = assets.get(value['approval_id'])
        if not approval or approval['kind'] != 'lexical_approval' or approval['payload']['plan_id'] != plan_id:
            raise ValueError('Лексический intent/result не связан с явным апрувом.')
        if kind == 'lexical_intent':
            if (value['input_sha256'] != _digest({'manifest': plan['manifest'], 'protocol': plan['protocol']}) or
                    datetime.fromisoformat(value['started_at']) < datetime.fromisoformat(approval['payload']['approved_at'])):
                raise ValueError('Лексический intent отличается от одобренных входов.')
        else:
            intent = assets.get(value['intent_id'])
            if (not intent or intent['kind'] != 'lexical_intent' or intent['payload']['plan_id'] != plan_id or
                    intent['payload']['approval_id'] != value['approval_id'] or value['manifest'] != plan['manifest'] or
                    value['source_algorithm_version'] != plan['engine']['version'] or
                    datetime.fromisoformat(value['finished_at']) < datetime.fromisoformat(intent['payload']['started_at'])):
                raise ValueError('Локальный receipt не связан с точным предшествующим intent.')
            if value['completed']:
                if value['elapsed_seconds'] > plan['limits']['timeout_seconds']:
                    raise ValueError('Завершение выходит за одобренное время.')
                _validate_result_data(value['raw'], plan)
    for key, asset_id in claims.items():
        if key.startswith(('lexical-approval:', 'lexical-intent:', 'lexical-result:')):
            asset = assets.get(asset_id)
            if not asset:
                raise ValueError('Однократная лексическая регистрация ссылается на чужой артефакт.')
            expected = {'lexical_approval': 'lexical-approval:', 'lexical_intent': 'lexical-intent:',
                        'lexical_result': 'lexical-result:'}.get(asset['kind'])
            if expected is None or key != expected + asset['payload']['plan_id']:
                raise ValueError('Повреждён ключ однократного лексического действия.')
