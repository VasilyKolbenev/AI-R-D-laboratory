"""Explicit bounded Responses experiments, immutable intents and no paid retries."""
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import re
import threading
import time

from .research_assets import Assets, canonical
from .telegram import _dpapi

ENDPOINT = 'https://api.openai.com/v1/responses'
MAX_REQUESTS = 20
MAX_RESPONSE_BYTES = 256 * 1024
STOP_CRITERIA = {
    'Stop on first failed or uncertain request', 'Stop on failed or uncertain request',
    'first_failure_or_uncertain', 'cancel_or_deadline'}
_LOCKS, _ACTIVE, _LOCK_GUARD = {}, set(), threading.Lock()


@contextmanager
def _active(key):
    with _LOCK_GUARD:
        _ACTIVE.add(key)
    try:
        yield
    finally:
        with _LOCK_GUARD:
            _ACTIVE.discard(key)


def _sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _stamp():
    return datetime.now(timezone.utc).isoformat()


def _text(value, maximum=1000, required=False):
    if (not isinstance(value, str) or len(value) > maximum or '\x00' in value or
            (required and not value.strip())):
        raise ValueError('Неверный текст или размер поля эксперимента.')
    return value


def _integer(value, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError('Неверная целочисленная граница эксперимента.')
    return value


def _number(value, maximum=1e12):
    if value is not None and (type(value) not in {int, float} or
                              not math.isfinite(value) or not 0 <= value <= maximum):
        raise ValueError('Нужно конечное неотрицательное число или null.')
    return value


def _hash(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('Неверная контрольная сумма эксперимента.')


def _model(value):
    if not isinstance(value, str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._:/-]{0,100}', value):
        raise ValueError('Владелец должен явно указать допустимый идентификатор модели.')
    return value


def _transport(endpoint, headers, body, timeout):
    """Fixed HTTPS endpoint; direct TLS, no proxies, redirect handling or tools."""
    if endpoint != ENDPOINT:
        raise ValueError('Поддерживается только фиксированный Responses endpoint.')
    deadline = time.monotonic() + timeout
    connection = http.client.HTTPSConnection('api.openai.com', timeout=timeout)
    try:
        connection.request('POST', '/v1/responses', canonical(body).encode('utf-8'), headers)
        response = connection.getresponse()
        if (response.status != 200 or
                response.getheader('Content-Encoding', 'identity') != 'identity'):
            raise ValueError('API отказал или вернул неподдерживаемый ответ; повтора нет.')
        raw = bytearray()
        while len(raw) <= MAX_RESPONSE_BYTES:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Общий срок ответа API истёк.')
            if connection.sock:
                connection.sock.settimeout(remaining)
            chunk = response.read(min(8192, MAX_RESPONSE_BYTES + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError('API превысил ограничение размера ответа.')
        value = json.loads(raw.decode('utf-8'), parse_constant=lambda _: None)
        if not isinstance(value, dict):
            raise ValueError('API вернул некорректный объект.')
        value['_raw_sha256'] = hashlib.sha256(raw).hexdigest()
        return value
    finally:
        connection.close()


def _body(plan, item):
    case = next(row for row in plan['cases'] if row['id'] == item['case_id'])
    arm = plan[item['arm']]
    return {'model': arm['model'], 'input': [
        {'role': 'developer', 'content': arm['instructions']},
        {'role': 'user', 'content': case['input']}],
        'tools': [], 'store': False, 'max_output_tokens': plan['max_output_tokens']}


class Experiments:
    def __init__(self, store, transport=None):
        self.store, self.assets = store, Assets(store)
        self.transport = transport or _transport
        self.secret_path = Path(store.data_dir) / '.experiment-openai-key.dpapi'
        with _LOCK_GUARD:
            self.lock = _LOCKS.setdefault(str(Path(store.data_dir).resolve()), threading.RLock())

    def _secret(self):
        try:
            key = _dpapi(self.secret_path.read_bytes(), decrypt=True).decode('utf-8')
            if not 20 <= len(key) <= 512 or not re.fullmatch('[!-~]+', key):
                raise ValueError('Неверный ключ.')
            return key
        except Exception:
            raise ValueError('Ключ API не настроен или недоступен через Windows DPAPI.') from None

    def config(self):
        try:
            self._secret()
            configured = True
        except ValueError:
            configured = False
        return {'configured': configured,
                'model': self.store.get_setting('experiment_openai_model_v1', '')}

    def configure(self, api_key, model):
        model = _model(model)
        if (not isinstance(api_key, str) or not 20 <= len(api_key) <= 512 or
                not re.fullmatch('[!-~]+', api_key)):
            raise ValueError('Введите API key без пробелов; вход CLI не используется.')
        if api_key in model:
            raise ValueError('Ключ API нельзя использовать как идентификатор модели.')
        with self.lock:
            try:
                encrypted = _dpapi(api_key.encode('utf-8'))
                temporary = self.secret_path.with_suffix('.tmp')
                temporary.write_bytes(encrypted)
                os.replace(temporary, self.secret_path)
            except Exception:
                raise ValueError('Windows DPAPI не смог сохранить ключ API.') from None
            self.store.set_setting('experiment_openai_model_v1', model)
        return self.config()

    def _assert_no_secret(self, payload):
        try:
            key = self._secret()
        except ValueError:
            return
        if key in canonical(payload):
            raise ValueError('Ключ API нельзя сохранять в исследовательском артефакте.')

    def plan(self, values):
        allowed = {'cases', 'baseline', 'candidate', 'repetitions', 'max_requests',
                   'timeout_seconds', 'max_output_tokens', 'max_input_chars', 'metrics',
                   'stop_criteria', 'pricing'}
        if not isinstance(values, dict) or set(values) - allowed:
            raise ValueError('Неизвестные поля; произвольный endpoint или код запрещены.')
        cases = values.get('cases')
        if not isinstance(cases, list) or not 1 <= len(cases) <= 10:
            raise ValueError('Выберите от 1 до 10 фиксированных кейсов.')
        maximum = _integer(values.get('max_input_chars', 8000), 1, 16000)
        normalized, identifiers = [], set()
        for row in cases:
            if not isinstance(row, dict) or set(row) - {'id', 'input', 'expected'}:
                raise ValueError('Кейс содержит неизвестные поля.')
            identifier = _text(row.get('id'), 80, True)
            if not re.fullmatch('[A-Za-z0-9_-]+', identifier) or identifier in identifiers:
                raise ValueError('ID кейса повторяется или недопустим.')
            identifiers.add(identifier)
            normalized.append({'id': identifier, 'input': _text(row.get('input'), maximum, True),
                               'expected': _text(row.get('expected'), 8000)
                               if row.get('expected') is not None else None})
        default_model = self.config()['model']
        payload = {'version': 'experiment-plan-v1', 'endpoint': ENDPOINT, 'cases': normalized}
        for arm in ('baseline', 'candidate'):
            row = values.get(arm)
            if not isinstance(row, dict) or set(row) - {'label', 'model', 'instructions'}:
                raise ValueError('Нужны обе фиксированные конфигурации эксперимента.')
            payload[arm] = {'label': _text(row.get('label'), 160, True),
                            'model': _model(row.get('model') or default_model),
                            'instructions': _text(row.get('instructions', ''), 4000)}
            if any(len(row['input']) + len(payload[arm]['instructions']) > maximum
                   for row in normalized):
                raise ValueError('Кейс и инструкции вместе превышают max_input_chars.')
        payload.update(
            repetitions=_integer(values.get('repetitions', 1), 1, 10),
            max_requests=_integer(values.get('max_requests', 2), 2, MAX_REQUESTS),
            timeout_seconds=_integer(values.get('timeout_seconds', 60), 5, 240),
            max_output_tokens=_integer(values.get('max_output_tokens', 128), 16, 4096),
            max_input_chars=maximum, metrics=values.get('metrics', ['latency_ms']),
            stop_criteria=values.get('stop_criteria', ['Stop on failed or uncertain request']),
            pricing=values.get('pricing', {}), credential_fingerprint=None)
        payload['schedule'] = [
            {'index': index, **item} for index, item in enumerate(
                {'case_id': case['id'], 'arm': arm, 'repetition': repetition}
                for case in normalized for repetition in range(payload['repetitions'])
                for arm in ('baseline', 'candidate'))]
        try:
            payload['credential_fingerprint'] = _sha(self._secret())
        except ValueError:
            pass
        self._assert_no_secret(payload)
        asset = self.assets.put('experiment_plan', payload)
        return {**asset, 'plan_id': asset['id'], 'plan_hash': _sha(canonical(payload))}

    def _all(self, kind):
        return self.assets.list(kind, limit=10000)

    def list(self):
        kinds = {'experiment_plan', 'experiment_observation'}
        return [row for row in self.assets.list(limit=10000) if row['kind'] in kinds][:200]

    def status(self, plan_id=None):
        if plan_id is None:
            return [self.status(row['id']) for row in self._all('experiment_plan')[:100]]
        plan = self.assets.get(plan_id)
        if plan['kind'] != 'experiment_plan':
            raise ValueError('Выбран не план эксперимента.')
        observations = [row for row in self._all('experiment_observation')
                        if row['payload'].get('plan_id') == plan_id]
        terminal = next((row for row in observations
                         if row['payload']['origin'] == 'execution_summary'), None)
        if terminal:
            by_id = {row['id']: row for row in observations
                     if row['payload']['origin'] == 'executed_api'}
            return {**terminal['payload'], 'id': terminal['id'],
                    'observations': [by_id[asset_id] for asset_id in
                                     terminal['payload']['observation_ids']]}
        intents = [row for row in self._all('experiment_intent')
                   if row['payload']['plan_id'] == plan_id]
        approved = any(row['payload']['plan_id'] == plan_id
                       for row in self._all('experiment_approval'))
        with _LOCK_GUARD:
            running = (str(Path(self.store.data_dir).resolve()), plan_id) in _ACTIVE
        state = 'running' if running else 'outcome_unknown' if approved else 'planned'
        return {'plan_id': plan_id, 'status': state,
                'reserved_requests': len(plan['payload']['schedule']) if approved else 0,
                'dispatched_requests': len(intents), 'observations': observations,
                'notice': 'Незавершённый intent не повторяется автоматически.'}

    def start(self, plan_id, plan_hash, consent, command_id, cancel_event=None):
        if consent is not True:
            raise ValueError('Для API эксперимента требуется отдельное явное подтверждение.')
        if not isinstance(command_id, str) or not 8 <= len(command_id) <= 100:
            raise ValueError('Неверный ID команды эксперимента.')
        cancel = cancel_event or threading.Event()
        active_key = (str(Path(self.store.data_dir).resolve()), plan_id)
        with self.lock, _active(active_key):
            asset = self.assets.get(plan_id)
            plan = asset['payload']
            if asset['kind'] != 'experiment_plan' or _sha(canonical(plan)) != plan_hash:
                raise ValueError('Точный план изменился; нужен новый апрув.')
            previous = [row for row in self._all('experiment_approval')
                        if row['payload']['plan_id'] == plan_id]
            if previous:
                return self.status(plan_id)
            key = self._secret()
            if plan['credential_fingerprint'] != _sha(key):
                raise ValueError('Ключ API изменился; пересоберите план перед апрувом.')
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            approvals = self._all('experiment_approval')
            if any(row['payload']['command_id'] == command_id for row in approvals):
                raise ValueError('ID команды уже использован для другого эксперимента.')
            reserved = sum(row['payload']['reserved_requests'] for row in approvals
                           if datetime.fromisoformat(row['payload']['approved_at']) >= cutoff)
            if reserved + len(plan['schedule']) > MAX_REQUESTS:
                raise ValueError('Достигнут отдельный лимит 20 API запросов за 24 часа.')
            approval = self.assets.claim('experiment_approval', {
                'version': 'experiment-approval-v1', 'plan_id': plan_id, 'plan_hash': plan_hash,
                'consent': True, 'command_id': command_id, 'approved_at': _stamp(),
                'reserved_requests': len(plan['schedule'])}, 'experiment-execution:' + plan_id)
            started = time.monotonic()
            deadline = started + plan['timeout_seconds']
            observations, intents = [], []
            state = 'completed'
            for item in plan['schedule']:
                if cancel.is_set() or time.monotonic() >= deadline:
                    state = 'cancelled' if cancel.is_set() else 'failed'
                    break
                body = _body(plan, item)
                intent = self.assets.claim('experiment_intent', {
                    'version': 'experiment-intent-v1', 'plan_id': plan_id,
                    'approval_id': approval['id'], 'plan_hash': plan_hash, **item,
                    'request_sha256': _sha(canonical(body)), 'endpoint': ENDPOINT,
                    'started_at': _stamp()}, 'experiment-request:' + plan_id + ':' +
                    str(item['index']))
                intents.append(intent['id'])
                began = time.monotonic()
                try:
                    response = self.transport(ENDPOINT, {
                        'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
                        body, max(.01, min(30, deadline - began)))
                    if not isinstance(response, dict):
                        raise ValueError('Некорректный ответ API.')
                    output = ''.join(content.get('text', '') for row in response.get('output', [])
                                     if isinstance(row, dict) and row.get('type') == 'message'
                                     for content in row.get('content', [])
                                     if isinstance(content, dict) and
                                     content.get('type') == 'output_text')
                    output = _text(output.replace(key, '[REDACTED]'), 32000)
                    state = 'completed' if response.get('status') == 'completed' else 'failed'
                    usage = {name: value for name, value in (response.get('usage') or {}).items()
                             if name in {'input_tokens', 'output_tokens', 'total_tokens'} and
                             type(value) in {int, float} and math.isfinite(value) and value >= 0}
                    raw_hash = response.get('_raw_sha256') or _sha(canonical(response))
                    error = '' if state == 'completed' else 'API не подтвердил полное завершение.'
                except Exception:
                    state, output, usage, raw_hash = 'outcome_unknown', '', {}, None
                    error = 'API запрос мог состояться; повтор запрещён, детали исключения скрыты.'
                elapsed = max(0, (time.monotonic() - began) * 1000)
                if state == 'completed' and time.monotonic() > deadline:
                    state, error = 'failed', 'Общий срок эксперимента истёк; ответ сохранён.'
                expected = next(row['expected'] for row in plan['cases']
                                if row['id'] == item['case_id'])
                observation = self.assets.claim('experiment_observation', {
                    'version': 'experiment-observation-v1', 'origin': 'executed_api',
                    'plan_id': plan_id, 'intent_id': intent['id'], **item, 'status': state,
                    'output': output, 'output_sha256': _sha(output), 'raw_sha256': raw_hash,
                    'latency_ms': elapsed, 'usage': usage, 'actual_cost_usd': None,
                    'metrics': {'latency_ms': elapsed, 'exact_match':
                        output.strip() == expected.strip() if expected is not None and
                        state == 'completed' else None}, 'error': error, 'finished_at': _stamp()},
                    'experiment-result:' + plan_id + ':' + str(item['index']))
                observations.append(observation['id'])
                if state != 'completed':
                    break
            summary = {
                'version': 'experiment-summary-v1', 'origin': 'execution_summary',
                'plan_id': plan_id, 'approval_id': approval['id'], 'status': state,
                'reserved_requests': len(plan['schedule']), 'dispatched_requests': len(intents),
                'intent_ids': intents, 'observation_ids': observations,
                'elapsed_seconds': max(0, time.monotonic() - started),
                'actual_cost_usd': None, 'finished_at': _stamp(),
                'notice': 'Измерены API ответы/время; exact_match не доказывает научную истину. '
                          'Цены являются предположениями; это не денежный потолок.'}
            terminal = self.assets.claim('experiment_observation', summary,
                                         'experiment-finish:' + plan_id)
            return {**terminal['payload'], 'id': terminal['id']}

    def imports(self, values):
        if not isinstance(values, dict) or set(values) - {'plan_id', 'observations', 'note'}:
            raise ValueError('Неверный импорт наблюдений.')
        self._assert_no_secret(values)
        payload = {'version': 'experiment-import-v1', 'origin': 'imported_not_executed_here',
                   'plan_id': values.get('plan_id'), 'observations': values.get('observations'),
                   'raw_sha256': _sha(canonical(values.get('observations'))),
                   'note': values.get('note', ''),
                   'notice': 'Данные импортированы владельцем; приложение их не исполняло.'}
        return self.assets.put('experiment_observation', payload)


def validate_asset(kind, payload):
    if not isinstance(payload, dict):
        raise ValueError('Повреждён объект эксперимента.')
    if kind == 'experiment_plan':
        _validate_plan(payload)
        return
    if kind == 'experiment_approval':
        fields = {'version', 'plan_id', 'plan_hash', 'consent', 'command_id',
                  'approved_at', 'reserved_requests'}
        if (set(payload) != fields or payload['version'] != 'experiment-approval-v1' or
                payload['consent'] is not True):
            raise ValueError('Повреждён явный апрув эксперимента.')
        _hash(payload['plan_id'])
        _hash(payload['plan_hash'])
        _text(payload['command_id'], 100, True)
        _integer(payload['reserved_requests'], 2, MAX_REQUESTS)
        if datetime.fromisoformat(payload['approved_at']).tzinfo is None:
            raise ValueError('Апрув не содержит часового пояса.')
        return
    if kind == 'experiment_intent':
        fields = {'version', 'plan_id', 'approval_id', 'plan_hash', 'index', 'case_id',
                  'arm', 'repetition', 'request_sha256', 'endpoint', 'started_at'}
        if (set(payload) != fields or payload['version'] != 'experiment-intent-v1' or
                payload['endpoint'] != ENDPOINT):
            raise ValueError('Повреждён однократный intent эксперимента.')
        for key in ('plan_id', 'approval_id', 'plan_hash', 'request_sha256'):
            _hash(payload[key])
        _validate_index(payload)
        datetime.fromisoformat(payload['started_at'])
        return
    if kind != 'experiment_observation':
        raise ValueError('Неизвестный тип эксперимента.')
    origin = payload.get('origin')
    if origin == 'imported_not_executed_here':
        fields = {'version', 'origin', 'plan_id', 'observations', 'raw_sha256', 'note', 'notice'}
        if set(payload) != fields or payload['version'] != 'experiment-import-v1':
            raise ValueError('Повреждена форма импорта наблюдений.')
        _hash(payload['raw_sha256'])
        if payload['plan_id'] is not None:
            _hash(payload['plan_id'])
        rows = payload['observations']
        if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
            raise ValueError('Допустимо от 1 до 100 импортированных наблюдений.')
        for row in rows:
            if not isinstance(row, dict) or set(row) != {
                    'case_id', 'arm', 'repetition', 'output', 'latency_ms', 'metrics'}:
                raise ValueError('Повреждён импорт наблюдения.')
            _validate_index({**row, 'index': 0})
            _text(row['output'], 32000)
            _number(row['latency_ms'])
            if not isinstance(row['metrics'], dict) or len(row['metrics']) > 8:
                raise ValueError('Превышено число импортируемых метрик.')
            for key, value in row['metrics'].items():
                _text(key, 100)
                _number(value)
        if _sha(canonical(rows)) != payload['raw_sha256']:
            raise ValueError('Контрольная сумма импортированных данных не совпала.')
        _text(payload['note'], 2000)
        return
    if origin == 'execution_summary':
        fields = {'version', 'origin', 'plan_id', 'approval_id', 'status', 'reserved_requests',
                  'dispatched_requests', 'intent_ids', 'observation_ids', 'elapsed_seconds',
                  'actual_cost_usd', 'finished_at', 'notice'}
        if set(payload) != fields or payload['version'] != 'experiment-summary-v1':
            raise ValueError('Повреждён исход эксперимента.')
        _integer(payload['reserved_requests'], 2, MAX_REQUESTS)
        _integer(payload['dispatched_requests'], 0, MAX_REQUESTS)
        for key in ('intent_ids', 'observation_ids'):
            if not isinstance(payload[key], list) or len(payload[key]) > MAX_REQUESTS:
                raise ValueError('Превышена граница журнала эксперимента.')
            for value in payload[key]:
                _hash(value)
        _hash(payload['approval_id'])
        _number(payload['elapsed_seconds'])
    elif origin == 'executed_api':
        fields = {'version', 'origin', 'plan_id', 'intent_id', 'index', 'case_id', 'arm',
                  'repetition', 'status', 'output', 'output_sha256', 'raw_sha256',
                  'latency_ms', 'usage', 'actual_cost_usd', 'metrics', 'error', 'finished_at'}
        if set(payload) != fields or payload['version'] != 'experiment-observation-v1':
            raise ValueError('Повреждено наблюдение API.')
        _validate_index(payload)
        _hash(payload['intent_id'])
        _text(payload['output'], 32000)
        if payload['output_sha256'] != _sha(payload['output']):
            raise ValueError('Выход эксперимента изменился.')
        if payload['raw_sha256'] is not None:
            _hash(payload['raw_sha256'])
        _number(payload['latency_ms'])
        if not isinstance(payload['usage'], dict) or len(payload['usage']) > 20:
            raise ValueError('Повреждён расход API.')
        for value in payload['usage'].values():
            _number(value)
        if not isinstance(payload['metrics'], dict) or set(payload['metrics']) != {
                'latency_ms', 'exact_match'}:
            raise ValueError('Повреждены метрики API.')
        exact = payload['metrics']['exact_match']
        if exact is not None and type(exact) is not bool:
            raise ValueError('Точное совпадение должно быть наблюдаемым boolean или null.')
        _text(payload['error'], 1000)
    else:
        raise ValueError('Происхождение наблюдения неизвестно.')
    _hash(payload['plan_id'])
    if payload['status'] not in {'completed', 'failed', 'outcome_unknown', 'cancelled'}:
        raise ValueError('Неизвестный исход эксперимента.')
    if payload['actual_cost_usd'] is not None:
        raise ValueError('Фактическая стоимость не вычисляется из числа запросов.')
    datetime.fromisoformat(payload['finished_at'])


def _validate_index(payload):
    _integer(payload['index'], 0, MAX_REQUESTS - 1)
    _integer(payload['repetition'], 0, 9)
    _text(payload['case_id'], 80, True)
    if payload['arm'] not in {'baseline', 'candidate'}:
        raise ValueError('Нужна baseline или candidate конфигурация.')


def _validate_plan(payload):
    fields = {'version', 'endpoint', 'cases', 'baseline', 'candidate', 'repetitions',
              'max_requests', 'timeout_seconds', 'max_output_tokens', 'max_input_chars',
              'metrics', 'stop_criteria', 'pricing', 'credential_fingerprint', 'schedule'}
    if (set(payload) != fields or payload['version'] != 'experiment-plan-v1' or
            payload['endpoint'] != ENDPOINT):
        raise ValueError('Повреждён фиксированный план эксперимента.')
    _integer(payload['repetitions'], 1, 10)
    _integer(payload['max_requests'], 2, MAX_REQUESTS)
    _integer(payload['timeout_seconds'], 5, 240)
    _integer(payload['max_output_tokens'], 16, 4096)
    _integer(payload['max_input_chars'], 1, 16000)
    cases = payload['cases']
    if not isinstance(cases, list) or not 1 <= len(cases) <= 10:
        raise ValueError('Превышено число кейсов эксперимента.')
    identifiers = set()
    for case in cases:
        if not isinstance(case, dict) or set(case) != {'id', 'input', 'expected'}:
            raise ValueError('Повреждён кейс плана.')
        if case['id'] in identifiers:
            raise ValueError('Повторный ID кейса.')
        identifiers.add(_text(case['id'], 80, True))
        _text(case['input'], payload['max_input_chars'], True)
        if case['expected'] is not None:
            _text(case['expected'], 8000)
    for arm in ('baseline', 'candidate'):
        row = payload[arm]
        if not isinstance(row, dict) or set(row) != {'label', 'model', 'instructions'}:
            raise ValueError('Повреждена конфигурация API.')
        _model(row['model'])
        _text(row['label'], 160, True)
        _text(row['instructions'], 4000)
        if any(len(case['input']) + len(row['instructions']) > payload['max_input_chars']
               for case in cases):
            raise ValueError('Вход превышает замороженный бюджет символов.')
    expected = [{'index': index, **item} for index, item in enumerate(
        {'case_id': case['id'], 'arm': arm, 'repetition': repetition}
        for case in cases for repetition in range(payload['repetitions'])
        for arm in ('baseline', 'candidate'))]
    if payload['schedule'] != expected or len(expected) > payload['max_requests']:
        raise ValueError('Полное расписание превышает бюджет; выборочное усечение запрещено.')
    if (not isinstance(payload['metrics'], list) or not payload['metrics'] or
            set(payload['metrics']) - {'latency_ms', 'exact_match', 'output_tokens'}):
        raise ValueError('Поддерживаются только latency_ms, exact_match и output_tokens.')
    if (not isinstance(payload['stop_criteria'], list) or
            not 1 <= len(payload['stop_criteria']) <= 8):
        raise ValueError('Укажите условия остановки; ошибка всегда останавливает выполнение.')
    for text in payload['stop_criteria']:
        _text(text, 500, True)
        if text not in STOP_CRITERIA:
            raise ValueError('Неподдерживаемый критерий остановки; '
                             'произвольные правила не исполняются.')
    pricing = payload['pricing']
    if not isinstance(pricing, dict) or set(pricing) - {
            'input_usd_per_million', 'output_usd_per_million',
            'estimated_input_tokens_per_request'}:
        raise ValueError('Цены должны быть явными предположениями владельца.')
    for value in pricing.values():
        _number(value)
    if payload['credential_fingerprint'] is not None:
        _hash(payload['credential_fingerprint'])


def validate_backup(db):
    assets = {row['id']: {'kind': row['kind'], 'payload': json.loads(row['payload'])}
              for row in db.execute("SELECT * FROM research_assets WHERE kind LIKE 'experiment_%'")}
    seen_commands, seen_plans, seen_intents, seen_results = set(), set(), set(), set()
    claims = {row['claim_key']: row['asset_id'] for row in db.execute(
        'SELECT claim_key,asset_id FROM research_asset_claims')}
    for asset_id, asset in assets.items():
        kind, payload = asset['kind'], asset['payload']
        if kind == 'experiment_plan':
            continue
        plan_id = payload.get('plan_id')
        if plan_id is None and payload.get('origin') == 'imported_not_executed_here':
            continue
        parent = assets.get(plan_id)
        if not parent or parent['kind'] != 'experiment_plan':
            raise ValueError('Наблюдение не связано с замороженным планом.')
        plan = parent['payload']
        if kind == 'experiment_approval':
            if (payload['plan_hash'] != _sha(canonical(plan)) or plan_id in seen_plans or
                    payload['command_id'] in seen_commands or
                    payload['reserved_requests'] != len(plan['schedule'])):
                raise ValueError('Повреждён однократный апрув API эксперимента.')
            seen_plans.add(plan_id)
            seen_commands.add(payload['command_id'])
            if claims.get('experiment-execution:' + plan_id) != asset_id:
                raise ValueError('Апрув эксперимента не имеет однократной регистрации.')
        elif kind == 'experiment_intent':
            approval = assets.get(payload['approval_id'])
            key = (plan_id, payload['index'])
            if (not approval or approval['kind'] != 'experiment_approval' or
                    approval['payload']['plan_id'] != plan_id or key in seen_intents or
                    payload['index'] >= len(plan['schedule']) or
                    any(payload[name] != plan['schedule'][payload['index']][name]
                        for name in ('index', 'arm', 'case_id', 'repetition')) or
                    payload['request_sha256'] != _sha(canonical(_body(plan, payload))) or
                    payload['plan_hash'] != _sha(canonical(plan))):
                raise ValueError('Intent не соответствует одобренному запросу.')
            seen_intents.add(key)
            claim = 'experiment-request:' + plan_id + ':' + str(payload['index'])
            if claims.get(claim) != asset_id:
                raise ValueError('Intent API не имеет однократной регистрации.')
        elif payload.get('origin') == 'executed_api':
            intent = assets.get(payload['intent_id'])
            key = (plan_id, payload['index'])
            if (not intent or intent['kind'] != 'experiment_intent' or
                    intent['payload']['plan_id'] != plan_id or key in seen_results or
                    any(payload[name] != intent['payload'][name]
                        for name in ('index', 'arm', 'case_id', 'repetition'))):
                raise ValueError('Исход API не соответствует однократному intent.')
            seen_results.add(key)
            if claims.get('experiment-result:' + plan_id + ':' + str(payload['index'])) != asset_id:
                raise ValueError('Исход API не имеет однократной регистрации.')
        elif payload.get('origin') == 'execution_summary':
            approval = assets.get(payload['approval_id'])
            if (not approval or approval['payload'].get('plan_id') != plan_id or
                    payload['dispatched_requests'] != len(payload['intent_ids']) or
                    len(payload['observation_ids']) != len(payload['intent_ids']) or
                    payload['reserved_requests'] != len(plan['schedule'])):
                raise ValueError('Итог эксперимента не соответствует журналу.')
            if claims.get('experiment-finish:' + plan_id) != asset_id:
                raise ValueError('Итог API не имеет однократной регистрации.')
            for index, intent_id in enumerate(payload['intent_ids']):
                intent = assets.get(intent_id)
                observed = assets.get(payload['observation_ids'][index])
                if (not intent or not observed or
                        observed['payload'].get('intent_id') != intent_id or
                        intent['payload'].get('plan_id') != plan_id or
                        intent['payload'].get('index') != index):
                    raise ValueError('Итог ссылается на неправильный исход API.')
            if payload['status'] == 'completed' and (
                    len(payload['intent_ids']) != len(plan['schedule']) or
                    any(assets[value]['payload']['status'] != 'completed'
                        for value in payload['observation_ids'])):
                raise ValueError('Завершение требует обе конфигурации на полном расписании.')
    for plan_id, parent in assets.items():
        if parent['kind'] != 'experiment_plan':
            continue
        intents = sorted((row['payload'] for row in assets.values()
                          if row['kind'] == 'experiment_intent' and
                          row['payload']['plan_id'] == plan_id), key=lambda row: row['index'])
        results = {row['payload']['index']: row['payload'] for row in assets.values()
                   if row['payload'].get('origin') == 'executed_api' and
                   row['payload']['plan_id'] == plan_id}
        for index, intent in enumerate(intents):
            if intent['index'] != index or (index and (
                    index - 1 not in results or results[index - 1]['status'] != 'completed')):
                raise ValueError('Вызов API отправлен после неопределённого или плохого исхода.')


def validate_claim(db, payload):
    """Called by Assets.claim inside BEGIN IMMEDIATE before approval insertion."""
    validate_asset('experiment_approval', payload)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    previous = [json.loads(row[0]) for row in db.execute(
        "SELECT payload FROM research_assets WHERE kind='experiment_approval'")]
    if any(row['plan_id'] == payload['plan_id'] or
           row['command_id'] == payload['command_id'] for row in previous):
        raise ValueError('Эксперимент или команда уже одобрены; повтор запрещён.')
    reserved = sum(row['reserved_requests'] for row in previous
                   if datetime.fromisoformat(row['approved_at']) >= cutoff)
    if reserved + payload['reserved_requests'] > MAX_REQUESTS:
        raise ValueError('Достигнут атомарный предел 20 API запросов за 24 часа.')
