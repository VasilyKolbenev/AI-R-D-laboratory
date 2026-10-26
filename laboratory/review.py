"""Versioned editorial review, decision journal and evidence-linked cost notes.

This module never calls a provider or edits a provider's report. Automatic report
journals remain unscored; manual quality scores describe editorial review only.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import re
from urllib.parse import parse_qsl, urlsplit

from .study import _url


TABLES = ('research_review_revisions',)
MAX_BODY_CHARS = 50_000
TERMINAL = {'completed', 'failed', 'cancelled', 'outcome_unknown'}
CRITERIA = (
    ('task', 'Задача и адресат', 'Понятно, для кого и какую прикладную задачу разбираем.'),
    ('mechanism', 'Механизм и baseline', 'Объяснено, что меняется и с каким решением сравниваем.'),
    ('evidence', 'Доказательства и условия', 'Ключевые выводы связаны с источниками; авторские результаты отделены от наших замеров.'),
    ('applicability', 'Применимость и затраты', 'Указаны ограничения, ресурсы, полная стоимость и неизвестные данные.'),
    ('communication', 'Логика и конкретный следующий шаг', 'Вывод относится к названному применению; текст и визуал объясняют ход рассуждения.'),
)
EDITORIAL_TEXT = {'title': 180, 'problem': 1400, 'audience': 800, 'use_case': 1000,
                  'public_takeaway': 1400, 'next_step': 1200}
EDITORIAL_LISTS = {'mechanism': (3, 500), 'findings': (5, 1200), 'limitations': (5, 1000), 'resources': (5, 1000)}
COMPARISON_TEXT = {'label': 180, 'unit': 60, 'baseline_label': 120, 'result_label': 120, 'conditions': 1600}
BASIS = {'saved_report', 'local_record', 'editor_assessment', 'missing'}
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,59}\Z')
_RUN_ID = re.compile(r'[0-9a-f]{32}\Z')
_TOKEN = re.compile(r'[0-9]{6,20}:[A-Za-z0-9_-]{20,200}')
AUTOMATIC_NOTE = 'Автоматическая проверка структуры; ручной оценки не было'


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def _object(value, allowed, label):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ValueError(label + ': неверные или неизвестные поля.')
    return value


def _text(value, label, maximum, required=False):
    if not isinstance(value, str):
        raise ValueError(label + ': нужен текст.')
    value = value.replace('\r\n', '\n').strip()
    if len(value) > maximum or (required and not value) or any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise ValueError(label + ': неверная длина или управляющие символы.')
    return value


def _id(value, label='Идентификатор'):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(label + ': нужны латинские буквы, цифры, дефис или подчёркивание; до 60 символов.')
    return value


def _run_id(value):
    if not isinstance(value, str) or not _RUN_ID.fullmatch(value):
        raise ValueError('Некорректный идентификатор исследования.')
    return value


def _ids(value, maximum=12):
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError('Слишком много ссылок на доказательства.')
    result = [_id(item, 'Доказательство') for item in value]
    if len(result) != len(set(result)):
        raise ValueError('Ссылки на доказательства повторяются.')
    return result


def _number(value, label, maximum):
    if value is None:
        return None
    if type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= maximum:
        raise ValueError(label + ': нужно неотрицательное число или null, если неизвестно.')
    return value


def _public_url(value):
    value = _url(value, 'URL доказательства')
    if value and (_TOKEN.search(value) or any(re.search(r'token|secret|password|signature|credential|api.?key|auth|session', key, re.I)
                                            for key, _ in parse_qsl(urlsplit(value).query))):
        raise ValueError('URL доказательства не должен содержать секреты или подписанные параметры.')
    return value


def template():
    return {'decisions': [], 'evidence': [],
            'costs': {'related_run_ids': [], 'human_minutes': None, 'money_amount': None, 'currency': '', 'notes': ''},
            'rubric': {key: {'score': None, 'note': '', 'evidence_ids': []} for key, _, _ in CRITERIA},
            'editorial': {}}


def schema():
    return {'schema_version': 1, 'template': template(),
            'criteria': [{'id': key, 'label': label, 'description': description} for key, label, description in CRITERIA],
            'score_labels': [{'score': 0, 'label': 'Не раскрыто'}, {'score': 1, 'label': 'Частично'}, {'score': 2, 'label': 'Достаточно для цели разбора'}],
            'evidence_basis': [
                {'id': 'saved_report', 'label': 'Утверждение в сохранённом отчёте'},
                {'id': 'local_record', 'label': 'Проверенная локальная запись'},
                {'id': 'editor_assessment', 'label': 'Редакторская оценка'},
                {'id': 'missing', 'label': 'Недостающие данные'}],
            'editorial_fields': {'text': EDITORIAL_TEXT, 'lists': {key: {'items': count, 'item_chars': size} for key, (count, size) in EDITORIAL_LISTS.items()},
                                 'comparisons': {'items': 3, 'text': COMPARISON_TEXT,
                                                 'numeric_fields': ['baseline_value', 'result_value'],
                                                 'evidence_required': True}},
            'notice': 'Ручная рубрика качества отчёта, не вероятность истинности, не оценка технологии и не автоматическое разрешение публикации.',
            'limits': {'body_chars': MAX_BODY_CHARS, 'decisions': 20, 'evidence': 30, 'related_runs': 8}}


def _editorial(value, evidence_ids=None):
    value = _object(value, set(EDITORIAL_TEXT) | set(EDITORIAL_LISTS) | {'visual_kind', 'comparisons'}, 'Редакционная версия')
    if not value:
        return {}
    result = {key: _text(value.get(key, ''), key, maximum) for key, maximum in EDITORIAL_TEXT.items()}
    visual_kind = value.get('visual_kind', '')
    if not isinstance(visual_kind, str) or visual_kind not in {'', 'generic', 'replay_tree'}:
        raise ValueError('Редакционная версия: неизвестная схема объяснения.')
    result['visual_kind'] = visual_kind
    for key, (count, maximum) in EDITORIAL_LISTS.items():
        items = value.get(key, [])
        if not isinstance(items, list) or len(items) > count or (key == 'mechanism' and items and len(items) != 3):
            raise ValueError('Редакционная версия: неверное число элементов ' + key + '.')
        result[key] = [_text(item, key, maximum, True) for item in items]
    if any('<' in item or '>' in item or _TOKEN.search(item) for item in [*result.values()] if isinstance(item, str)):
        raise ValueError('Редакционная версия должна содержать обычный текст без HTML или секретов.')
    for key in EDITORIAL_LISTS:
        if any('<' in item or '>' in item or _TOKEN.search(item) for item in result[key]):
            raise ValueError('Редакционная версия должна содержать обычный текст без HTML или секретов.')
    if 'comparisons' in value:
        comparisons = value['comparisons']
        if not isinstance(comparisons, list) or len(comparisons) > 3:
            raise ValueError('Допустимо до 3 графиков сравнения.')
        result['comparisons'] = []
        for row in comparisons:
            row = _object(row, set(COMPARISON_TEXT) | {'baseline_value', 'result_value', 'evidence_ids'}, 'Сравнение')
            comparison = {key: _text(row.get(key, ''), 'Сравнение: ' + key, maximum, True)
                          for key, maximum in COMPARISON_TEXT.items()}
            if any('<' in text or '>' in text or _TOKEN.search(text) for text in comparison.values()):
                raise ValueError('Сравнение должно содержать обычный текст без HTML или секретов.')
            for field in ('baseline_value', 'result_value'):
                number = _number(row.get(field), 'Сравнение: ' + field, 1e100)
                if number is None:
                    raise ValueError('Для графика нужны оба численных значения; неизвестное число не заменяется нулём.')
                comparison[field] = number
            refs = _ids(row.get('evidence_ids', []))
            if not refs or not set(refs) <= (evidence_ids or set()):
                raise ValueError('График должен ссылаться на существующее доказательство.')
            comparison['evidence_ids'] = refs
            result['comparisons'].append(comparison)
    if len(_json(result)) > 20_000:
        raise ValueError('Редакционная версия превышает 20 000 символов.')
    return result


def _body(value):
    value = _object(value, set(template()) | {'origin'}, 'Журнал исследования')
    decisions, evidence = value.get('decisions', []), value.get('evidence', [])
    if not isinstance(decisions, list) or len(decisions) > 20 or not isinstance(evidence, list) or len(evidence) > 30:
        raise ValueError('Допустимо до 20 решений и 30 доказательств.')
    result = {'decisions': [], 'evidence': []}
    for row in evidence:
        row = _object(row, {'id', 'claim', 'basis', 'locator', 'source_url', 'excerpt', 'limitations'}, 'Доказательство')
        basis = row.get('basis')
        if not isinstance(basis, str) or basis not in BASIS:
            raise ValueError('Укажите происхождение доказательства; ссылка не равна независимой проверке.')
        result['evidence'].append({'id': _id(row.get('id'), 'Доказательство'),
                                   'claim': _text(row.get('claim', ''), 'Утверждение', 2000, True),
                                   'basis': basis, 'locator': _text(row.get('locator', ''), 'Раздел или локальная запись', 1200, True),
                                   'source_url': _public_url(row.get('source_url', '')),
                                   'excerpt': _text(row.get('excerpt', ''), 'Фрагмент', 2400),
                                   'limitations': _text(row.get('limitations', ''), 'Ограничения', 2000)})
    evidence_ids = {row['id'] for row in result['evidence']}
    if len(evidence_ids) != len(result['evidence']):
        raise ValueError('Идентификаторы доказательств повторяются.')
    for row in decisions:
        row = _object(row, {'id', 'target', 'action', 'reason', 'evidence_ids', 'conditions', 'next_step'}, 'Решение')
        result['decisions'].append({'id': _id(row.get('id'), 'Решение'),
                                    'target': _text(row.get('target', ''), 'Предмет проверки или вывод', 1000, True),
                                    'action': _text(row.get('action', ''), 'Что решено', 1600, True),
                                    'reason': _text(row.get('reason', ''), 'Почему', 2400, True),
                                    'evidence_ids': _ids(row.get('evidence_ids', [])),
                                    'conditions': _text(row.get('conditions', ''), 'Условия пересмотра', 2000),
                                    'next_step': _text(row.get('next_step', ''), 'Следующий шаг', 1600)})
    if len({row['id'] for row in result['decisions']}) != len(result['decisions']):
        raise ValueError('Идентификаторы решений повторяются.')
    for row in result['decisions']:
        if not set(row['evidence_ids']) <= evidence_ids:
            raise ValueError('Решение ссылается на отсутствующее доказательство.')
    costs = _object(value.get('costs', {}), {'related_run_ids', 'human_minutes', 'money_amount', 'currency', 'notes'}, 'Расходы')
    related = costs.get('related_run_ids', [])
    if not isinstance(related, list) or len(related) > 8:
        raise ValueError('Можно связать до 8 дополнительных запусков.')
    related = [_run_id(item) for item in related]
    if len(related) != len(set(related)):
        raise ValueError('Связанные запуски повторяются.')
    money = _number(costs.get('money_amount'), 'Денежные затраты', 1_000_000_000)
    currency = _text(costs.get('currency', ''), 'Валюта', 8)
    if currency and not re.fullmatch(r'[A-Z]{3}', currency):
        raise ValueError('Для денежной суммы используйте код валюты из 3 заглавных латинских букв.')
    if money is not None and not currency:
        raise ValueError('Укажите валюту введённой суммы.')
    result['costs'] = {'related_run_ids': related,
                       'human_minutes': _number(costs.get('human_minutes'), 'Ручное время', 1_000_000),
                       'money_amount': money, 'currency': currency,
                       'notes': _text(costs.get('notes', ''), 'Заметки о расходах', 3000)}
    rubric = _object(value.get('rubric', template()['rubric']), {key for key, _, _ in CRITERIA}, 'Рубрика')
    if set(rubric) != {key for key, _, _ in CRITERIA}:
        raise ValueError('Рубрика должна содержать все 5 критериев; неизвестная оценка — null.')
    result['rubric'] = {}
    for key, _, _ in CRITERIA:
        row = _object(rubric[key], {'score', 'note', 'evidence_ids'}, 'Критерий ' + key)
        score = row.get('score')
        if score is not None and (type(score) is not int or score not in {0, 1, 2}):
            raise ValueError('Оценка критерия: 0, 1, 2 или null.')
        note = _text(row.get('note', ''), 'Обоснование оценки', 1800, score is not None)
        refs = _ids(row.get('evidence_ids', []))
        if not set(refs) <= evidence_ids:
            raise ValueError('Оценка ссылается на отсутствующее доказательство.')
        if score == 2 and not refs:
            raise ValueError('Для максимального балла нужна ссылка на основание в журнале.')
        result['rubric'][key] = {'score': score, 'note': note, 'evidence_ids': refs}
    result['editorial'] = _editorial(value.get('editorial', {}), evidence_ids)
    if 'origin' in value:
        if value['origin'] != 'automatic_report':
            raise ValueError('Неизвестное происхождение журнала.')
        if result['editorial'] or any(row['score'] is not None for row in result['rubric'].values()):
            raise ValueError('Автоматический журнал не содержит редакторской версии или ручных баллов.')
        result['origin'] = 'automatic_report'
    if len(_json(result)) > MAX_BODY_CHARS:
        raise ValueError('Журнал превышает 50 000 символов.')
    return result


def _links(db, run_id, body):
    row = db.execute('SELECT status FROM runs WHERE id=?', (run_id,)).fetchone()
    if not row or row[0] not in TERMINAL:
        raise ValueError('Журнал доступен для завершённого или остановленного исследования.')
    for related in body['costs']['related_run_ids']:
        if related == run_id:
            raise ValueError('Основной запуск нельзя повторно включать в связанные расходы.')
        if not db.execute('SELECT 1 FROM runs WHERE id=?', (related,)).fetchone():
            raise ValueError('Связанный запуск расходов не найден.')


def _item(row):
    return {'run_id': row['run_id'], 'version': row['version'], 'body': json.loads(row['body']), 'created_at': row['created_at']}


def _quality(body):
    values = [body['rubric'][key]['score'] for key, _, _ in CRITERIA]
    automatic = body.get('origin') == 'automatic_report'
    return {'total': sum(values) if all(value is not None for value in values) else None,
            'maximum': 10, 'scored': sum(value is not None for value in values), 'criteria_count': 5,
            'kind': 'automatic_unscored' if automatic else 'manual_editorial_review', 'publish_approved': False,
            'notice': AUTOMATIC_NOTE + '. Это не проверка истинности и не разрешение публикации.' if automatic else schema()['notice']}


def _run_cost(db, run_id):
    row = db.execute('SELECT id,status,approved_at,finished_at,usage,raw FROM runs WHERE id=?', (run_id,)).fetchone()
    if not row:
        raise ValueError('Исследование расходов не найдено.')
    usage = json.loads(row['usage'])
    raw = json.loads(row['raw'])
    elapsed = None
    if row['approved_at'] and row['finished_at']:
        try:
            seconds = (datetime.fromisoformat(row['finished_at']) - datetime.fromisoformat(row['approved_at'])).total_seconds()
            elapsed = seconds if seconds >= 0 else None
        except (ValueError, TypeError):
            pass
    observed = {key: value for key, value in usage.items() if type(value) in {int, float} and math.isfinite(value) and value >= 0}
    pipeline = raw.get('orchestration') if isinstance(raw.get('orchestration'), dict) else None
    invocations = (None if pipeline.get('uncertain_calls') else pipeline.get('dispatched_calls')) if pipeline else (1 if raw.get('dispatched') is True else None)
    return {'run_id': run_id, 'status': row['status'], 'elapsed_seconds': elapsed,
            'usage': observed, 'cli_invocations': invocations,
            'reserved_cli_invocations': pipeline.get('reserved_calls') if pipeline else None,
            'usage_coverage': pipeline.get('usage_coverage') if pipeline else None,
            'money_amount': None, 'currency': None,
            'origin': 'stored_run_record', 'api_request_count': None}


class Review:
    def __init__(self, store):
        self.store = store

    def initialize(self):
        with self.store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS research_review_revisions(run_id TEXT NOT NULL REFERENCES runs(id),version INTEGER NOT NULL CHECK(version>0),body TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(run_id,version))')

    @staticmethod
    def schema():
        return schema()

    def get(self, run_id):
        _run_id(run_id)
        with self.store.connect() as db:
            if not db.execute('SELECT 1 FROM runs WHERE id=?', (run_id,)).fetchone():
                raise ValueError('Исследование не найдено.')
            rows = db.execute('SELECT * FROM research_review_revisions WHERE run_id=? ORDER BY version DESC', (run_id,)).fetchall()
            history = [_item(row) for row in rows]
            current = history[0] if history else None
            body = current['body'] if current else template()
            primary = _run_cost(db, run_id)
            related = [_run_cost(db, value) for value in body['costs']['related_run_ids']]
            totals = {}
            for item in [primary, *related]:
                for key, value in item['usage'].items():
                    totals[key] = totals.get(key, 0) + value
            elapsed = [item['elapsed_seconds'] for item in [primary, *related]]
            return {'run_id': run_id, 'current': current, 'history': history,
                    'quality': _quality(body),
                    'costs': {'primary': primary, 'related': related,
                              'total_usage': totals, 'total_elapsed_seconds': sum(elapsed) if all(value is not None for value in elapsed) else None,
                              'manual': deepcopy(body['costs']),
                              'notice': 'Токены и время взяты из сохранённых запусков. Вход включает кеш по формату CLI; деньги и число API-запросов не вычисляются из токенов. Ручные суммы и время — отдельные заметки владельца.'}}

    def save(self, run_id, values):
        _run_id(run_id)
        values = _object(values, {'expected_version', 'body'}, 'Сохранение журнала')
        if type(values.get('expected_version')) is not int or values['expected_version'] < 0:
            raise ValueError('Укажите ожидаемую версию журнала.')
        value = deepcopy(values.get('body'))
        if isinstance(value, dict) and value.get('origin') == 'automatic_report':
            value.pop('origin')
        body = _body(value)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            _links(db, run_id, body)
            current = db.execute('SELECT max(version) FROM research_review_revisions WHERE run_id=?', (run_id,)).fetchone()[0] or 0
            if current != values['expected_version']:
                raise ValueError('Журнал уже изменён. Обновите его перед сохранением.')
            db.execute('INSERT INTO research_review_revisions VALUES (?,?,?,?)', (run_id, current + 1, _json(body), _now()))
        return self.get(run_id)

    def seed_automatic(self, run_id):
        """Record the existing answer's structural checks once; never call a model.

        Any prior journal wins, including one written while the presentation was
        being parsed. Legacy/malformed outputs do not acquire invented evidence
        or a retrospective manual review.
        """
        _run_id(run_id)
        with self.store.connect() as db:
            if db.execute('SELECT 1 FROM research_review_revisions WHERE run_id=?', (run_id,)).fetchone():
                return {'status': 'existing'}
        run = self.store.run(run_id)
        if run.get('status') != 'completed':
            return {'status': 'skipped', 'reason': 'run_not_completed'}
        from .presentation import build_presentation
        data = build_presentation(run)
        provenance = data.get('provenance', {})
        if provenance.get('mode') != 'model_structured' or provenance.get('presentation_block_valid') is not True:
            return {'status': 'skipped', 'reason': 'no_valid_structured_report'}
        try:
            checks = _object(data.get('publication_checks'),
                             {'status', 'issues', 'automatic', 'numeric_data', 'notice', 'agent_review_status'}, 'Проверка оформления')
            if 'agent_review_status' in checks and checks['agent_review_status'] not in {'ready', 'incomplete'}:
                raise ValueError('Повреждено состояние трёхпроходной проверки.')
            if checks.get('automatic') is not True or checks.get('status') not in {'ready', 'incomplete'}:
                raise ValueError('Нет автоматической проверки структуры.')
            if checks.get('numeric_data') not in {'supported', 'not_provided', 'rejected'}:
                raise ValueError('Неизвестный результат проверки численных сравнений.')
            issues = checks.get('issues', [])
            if not isinstance(issues, list) or len(issues) > 20:
                raise ValueError('Неверные замечания проверки.')
            issues = [_text(item, 'Замечание проверки', 500, True) for item in issues]
            notice = _text(checks.get('notice', ''), 'Основание автоматической проверки', 1000, True)
            body = template()
            body['origin'] = 'automatic_report'
            evidence = data.get('evidence', [])
            if not isinstance(evidence, list):
                raise ValueError('Неверные доказательства отчёта.')
            for item in evidence:
                item = _object(item, {'id', 'claim', 'source_url', 'locator', 'excerpt', 'limitations', 'basis'}, 'Доказательство отчёта')
                if item.get('basis', 'saved_report') != 'saved_report':
                    raise ValueError('Автоматическое основание должно происходить из отчёта.')
                if not _public_url(item.get('source_url', '')) or not _text(item.get('excerpt', ''), 'Фрагмент отчёта', 2400, True):
                    raise ValueError('Автоматическому доказательству нужны источник и фрагмент отчёта.')
                body['evidence'].append({key: item.get(key, '') for key in
                                         ('id', 'claim', 'source_url', 'locator', 'excerpt', 'limitations')})
                body['evidence'][-1]['basis'] = 'saved_report'
            comparisons = data.get('comparisons', [])
            if not isinstance(comparisons, list) or len(comparisons) > 3:
                raise ValueError('Неверные сравнения отчёта.')
            if comparisons and checks['numeric_data'] != 'supported':
                raise ValueError('Противоречивый результат проверки сравнений.')
            for index, comparison in enumerate(comparisons):
                if not isinstance(comparison, dict):
                    raise ValueError('Неверное сравнение отчёта.')
                if not _ids(comparison.get('evidence_ids', [])):
                    raise ValueError('Выбранному сравнению нужно доказательство.')
                body['decisions'].append({
                    'id': 'comparison_' + str(index + 1),
                    'target': comparison.get('label', ''),
                    'action': 'Включить численное сравнение в черновик',
                    'reason': notice,
                    'evidence_ids': comparison.get('evidence_ids', []),
                    'conditions': comparison.get('conditions', ''), 'next_step': ''})
            if issues or not comparisons:
                numeric_reason = {'supported': 'Сохранены только сравнения, прошедшие структурную проверку.',
                                  'not_provided': 'Численные сравнения не предоставлены в структурированном ответе.',
                                  'rejected': 'Численные сравнения не прошли структурную проверку.'}[checks['numeric_data']]
                body['decisions'].append({
                    'id': 'omitted_comparison', 'target': 'Границы данных для черновика',
                    'action': 'Не добавлять отсутствующие или отклонённые проверкой данные',
                    'reason': '\n'.join([numeric_reason, *issues, notice])[:2400],
                    'evidence_ids': [], 'conditions': '', 'next_step': ''})
            for row in body['rubric'].values():
                row['note'] = AUTOMATIC_NOTE
            body = _body(body)
        except (ValueError, TypeError, RecursionError):
            return {'status': 'skipped', 'reason': 'invalid_automatic_journal'}
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM research_review_revisions WHERE run_id=?', (run_id,)).fetchone():
                return {'status': 'existing'}
            status = db.execute('SELECT status FROM runs WHERE id=?', (run_id,)).fetchone()
            if not status or status[0] != 'completed':
                return {'status': 'skipped', 'reason': 'run_not_completed'}
            _links(db, run_id, body)
            db.execute('INSERT INTO research_review_revisions VALUES (?,?,?,?)', (run_id, 1, _json(body), _now()))
        return {'status': 'inserted', 'version': 1}


def _timestamp(value):
    if not isinstance(value, str) or len(value) > 60:
        raise ValueError('Некорректная дата версии журнала.')
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError('Некорректная дата версии журнала.') from None
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError('Дата журнала должна быть в UTC.')


def validate_backup_table(table, row, db):
    if table != TABLES[0] or not isinstance(row, dict) or set(row) != {'run_id', 'version', 'body', 'created_at'}:
        raise ValueError('Повреждена структура журнала в резервной копии.')
    _run_id(row['run_id'])
    if type(row['version']) is not int or row['version'] < 1:
        raise ValueError('Повреждена версия журнала.')
    _timestamp(row['created_at'])
    if not isinstance(row['body'], str) or len(row['body']) > MAX_BODY_CHARS:
        raise ValueError('Повреждён размер журнала.')
    try:
        original = json.loads(row['body'])
    except (ValueError, TypeError, RecursionError):
        raise ValueError('Повреждён JSON журнала.') from None
    body = _body(original)
    if body != original:
        raise ValueError('Неполный или повреждённый журнал.')
    _links(db, row['run_id'], body)


def validate_backup(db):
    for minimum, maximum, count in db.execute('SELECT min(version),max(version),count(*) FROM research_review_revisions GROUP BY run_id'):
        if minimum != 1 or maximum != count:
            raise ValueError('История версий журнала неполна.')
    for row in db.execute('SELECT * FROM research_review_revisions'):
        validate_backup_table(TABLES[0], dict(row), db)


def has_user_data(db):
    return bool(db.execute('SELECT 1 FROM research_review_revisions LIMIT 1').fetchone())
