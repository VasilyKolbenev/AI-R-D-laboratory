"""Local observations, explicit compatibility and assumption-labelled recipes."""
from copy import deepcopy
import hashlib
import json
import math
import re

from .research_assets import Assets, canonical

VERSION = 'measurement-v1'
BASES = {'unknown', 'hypothesis', 'author_claim', 'external_measurement', 'estimate'}
NOTICE = ('Записи сохраняют происхождение и условия. Анализ источника не является '
          'измерением лаборатории; неизвестные условия не доказывают сопоставимость.')


def _sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _number(value, maximum=1e15, nullable=True):
    if value is None and nullable:
        return value
    if type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= maximum:
        raise ValueError('Нужно конечное неотрицательное число или неизвестное null.')
    return value


def _text(value, maximum=2000):
    if not isinstance(value, str) or len(value) > maximum or '\x00' in value:
        raise ValueError('Неверный текст или размер поля.')
    return value


def cost_scenarios(inputs):
    if not isinstance(inputs, dict):
        raise ValueError('Укажите предположения расчёта.')
    allowed = {'requests', 'input_tokens', 'output_tokens', 'input_usd_per_million',
               'output_usd_per_million', 'fixed_cost_usd', 'assumption_note'}
    if set(inputs) - allowed:
        raise ValueError('Неизвестные предположения стоимости.')
    count = inputs.get('requests', 1)
    if type(count) is not int or not 1 <= count <= 1_000_000:
        raise ValueError('Количество запросов должно быть целым от 1 до 1000000.')
    values = {key: _number(inputs.get(key)) for key in allowed -
              {'requests', 'assumption_note'}}
    fixed = values['fixed_cost_usd']
    known = all(values[key] is not None for key in (
        'input_tokens', 'output_tokens', 'input_usd_per_million', 'output_usd_per_million'))
    variable = (count * (values['input_tokens'] * values['input_usd_per_million'] +
                        values['output_tokens'] * values['output_usd_per_million']) /
                1_000_000) if known else None
    total_known = known and fixed is not None
    return {'version': 'cost-assumptions-v1', 'status': 'assumption_based',
            'assumptions': {'requests': count, **values,
                            'note': _text(inputs.get('assumption_note', ''), 1000)},
            'variable_cost_usd': variable,
            'estimated_cost_usd': fixed + variable if total_known else None,
            'formula': 'fixed + requests * (input_tokens * input_rate + '
                       'output_tokens * output_rate) / 1000000',
            'sensitivity': [{'volume_factor': factor,
                             'estimated_cost_usd': fixed + variable * factor
                             if total_known else None}
                            for factor in (.5, 1, 2)],
            'notice': 'Цены и объём введены владельцем; это оценка, не платёж и не потолок.'}


def compatibility(left, right):
    keys = ('definition', 'unit', 'direction', 'model_version', 'dataset',
            'evaluation', 'hardware', 'load')
    if any(not left.get(key) or not right.get(key) for key in keys):
        return {'status': 'unknown',
                'reason': 'Версия, данные, оборудование или нагрузка неизвестны.'}
    differences = [key for key in keys if left[key] != right[key]]
    return {'status': 'incompatible' if differences else 'compatible',
            'reason': ', '.join(differences) if differences else 'Все явные условия совпадают.'}


class Workbench:
    def __init__(self, store):
        self.store, self.assets = store, Assets(store)

    def ingest(self, run, presentation):
        if (run.get('status') != 'completed' or
                (presentation.get('publication_checks') or {}).get('status') != 'ready' or
                (presentation.get('agent_review') or {}).get('status') != 'ready'):
            return []
        plan = run.get('plan') or {}
        task = (plan.get('study_context') or {}).get('task') or {}
        evidence = {row['id']: row for row in presentation.get('evidence', [])}
        documents = (plan.get('evidence_bundle') or {}).get('documents', [])
        results = []
        for row in (presentation.get('applied_analysis') or {}).get('rows', [])[:3]:
            for side in ('baseline', 'candidate'):
                item = row[side]
                matching = task.get('baseline') if side == 'baseline' else next((
                    entry for entry in task.get('candidates', [])
                    if entry.get('name') == item['label']), {})
                context = row.get('measurement_context') or {}
                version = context.get(side + '_version') or (matching or {}).get('version')
                def known(value):
                    return None if not value or str(value).strip().casefold() in {
                        'unknown', 'неизвестно', 'неизвестен', 'not_reported'} else value
                payload = {
                    'version': VERSION, 'run_id': run['id'],
                    'output_sha256': _sha(run['output']), 'row_id': row['id'], 'side': side,
                    'metric': row['metric'], 'definition': row['definition'], 'unit': row['unit'],
                    'direction': row['direction'], 'label': item['label'], 'value': item['value'],
                    'basis': item['basis'], 'model_version': known(version),
                    'dataset': known(context.get('dataset') or task.get('dataset')),
                    'evaluation': known(context.get('evaluation') or task.get('evaluation')),
                    'hardware': known(context.get('hardware')), 'load': known(context.get('load')),
                    'conditions': row['conditions'], 'comparability': row['comparability'],
                    'uncertainty': list((presentation.get('applied_analysis') or {}).get(
                        'unknowns', []))[:8],
                    'evidence_ids': list(item['evidence_ids']),
                    'source_urls': sorted({evidence[ref]['source_url']
                                           for ref in item['evidence_ids'] if ref in evidence}),
                    'source_documents': [
                        {key: document.get(key) for key in ('asset_id', 'url', 'sha256')}
                        for document in documents if document.get('url') in {
                            evidence[ref]['source_url'] for ref in item['evidence_ids']
                            if ref in evidence}],
                    'origin': 'stored_source_analysis', 'notice': NOTICE}
                payload['condition_sha256'] = _sha(canonical({key: payload[key] for key in (
                    'definition', 'unit', 'direction', 'model_version', 'dataset',
                    'evaluation', 'hardware', 'load', 'conditions')}))
                results.append(self.assets.put('measurement', payload))
        return results

    def measurements(self, query=''):
        query = _text(query, 300).casefold().strip()
        return [row for row in self.assets.list('measurement', limit=10000)
                if not query or query in canonical(row['payload']).casefold()]

    def selected(self, run_ids):
        if (not isinstance(run_ids, list) or len(run_ids) > 8 or
                any(not isinstance(value, str) or not re.fullmatch('[0-9a-f]{32}', value)
                    for value in run_ids)):
            raise ValueError('Выберите не более 8 точных ID исследований.')
        selected_ids = list(dict.fromkeys(run_ids))
        rows = [row for row in self.measurements() if row['payload']['run_id'] in selected_ids]
        if len(rows) > 24:
            raise ValueError('Выбранный реестр превышает 24 записи; уменьшите выбор до апрува.')
        return {'version': 'registry-context-v1', 'run_ids': selected_ids,
                'measurements': [{'asset_id': row['id'], **deepcopy(row['payload'])}
                                 for row in rows], 'notice': NOTICE}

    def impacts(self):
        latest, originals = {}, {}
        for asset in self.assets.list('source_capture', limit=10000):
            payload = asset['payload']
            originals[asset['id']] = asset
            if (payload.get('origin') == 'fetched' and
                    payload.get('status') in {'captured', 'partial'} and
                    payload.get('raw_b64') and payload.get('url') and payload.get('sha256')):
                latest.setdefault(payload['url'], asset)
        result = []
        for item in self.measurements():
            for original in item['payload']['source_documents']:
                captured = originals.get(original.get('asset_id'))
                if not captured or captured['payload'].get('origin') != 'fetched':
                    continue
                current = latest.get(original.get('url'))
                if current and original.get('sha256') != current['payload']['sha256']:
                    result.append({'measurement_id': item['id'],
                                   'run_id': item['payload']['run_id'], 'url': original['url'],
                                   'previous_sha256': original.get('sha256'),
                                   'current_sha256': current['payload']['sha256'],
                                   'status': 'source_changed_requires_review',
                                   'notice': 'Архив изменился; прежний вывод не переписан.'})
        return result

    def recipe(self, run, presentation):
        task = ((run.get('plan') or {}).get('study_context') or {}).get('task') or {}
        rows = (presentation.get('applied_analysis') or {}).get('rows', [])
        metrics = task.get('metrics', [])
        criteria = []
        for row in rows or [{'metric': metric['name'], **metric} for metric in metrics]:
            owner = next((metric for metric in metrics if metric.get('name') == row['metric'] or
                          metric.get('definition') == row['definition']), {})
            target = owner.get('target') or None
            criteria.append({'metric': row['metric'], 'definition': row['definition'],
                             'unit': row['unit'], 'direction': row['direction'],
                             'threshold': target, 'expected': owner.get('expected') or None,
                             'status': 'owner_target_not_result' if target else
                             'owner_threshold_required'})
        return {'version': 'decision-recipe-v1', 'run_id': run['id'],
                'execution': 'not_executed', 'task': task.get('business_goal') or
                (run.get('plan') or {}).get('question', ''),
                'acceptance_criteria': criteria, 'owner_success_criteria':
                task.get('success_criteria', ''), 'conditions': [row['conditions'] for row in rows],
                'candidates': deepcopy(task.get('candidates', [])),
                'unknowns': deepcopy((presentation.get('applied_analysis') or {}).get(
                    'unknowns', [])), 'next_steps': [presentation.get('next_step',
                    'Владелец задаёт общие кейсы, критерии и точный бюджет эксперимента.')],
                'notice': 'Рецепт проверки; импорт и выполнение имеют отдельный явный апрув.'}


def validate_asset(kind, payload):
    fields = {
        'version', 'run_id', 'output_sha256', 'row_id', 'side', 'metric', 'definition',
        'unit', 'direction', 'label', 'value', 'basis', 'model_version', 'dataset', 'hardware',
        'load', 'evaluation', 'conditions', 'comparability', 'uncertainty',
        'evidence_ids', 'source_urls',
        'source_documents', 'origin', 'notice', 'condition_sha256'}
    if kind != 'measurement' or not isinstance(payload, dict) or set(payload) != fields:
        raise ValueError('Повреждена схема измерительной записи.')
    if (payload['version'] != VERSION or payload['side'] not in {'baseline', 'candidate'} or
            payload['basis'] not in BASES or payload['origin'] != 'stored_source_analysis' or
            payload['direction'] not in {'minimize', 'maximize', 'descriptive'} or
            payload['comparability'] not in {'comparable', 'not_comparable', 'unknown'}):
        raise ValueError('Неизвестное происхождение или условия записи.')
    if not re.fullmatch('[0-9a-f]{32}', str(payload['run_id'])):
        raise ValueError('Повреждена ссылка на исследование.')
    for key in ('output_sha256', 'condition_sha256'):
        if not re.fullmatch('[0-9a-f]{64}', str(payload[key])):
            raise ValueError('Повреждена контрольная сумма записи.')
    for key in ('row_id', 'metric', 'definition', 'unit', 'label', 'conditions', 'notice'):
        _text(payload[key])
    for key in ('model_version', 'dataset', 'evaluation', 'hardware', 'load'):
        if payload[key] is not None:
            _text(payload[key])
    _number(payload['value'], 1e100)
    for key, maximum in [('uncertainty', 8), ('evidence_ids', 4), ('source_urls', 4),
                         ('source_documents', 12)]:
        if not isinstance(payload[key], list) or len(payload[key]) > maximum:
            raise ValueError('Превышен размер происхождения записи.')
    for key in ('uncertainty', 'evidence_ids', 'source_urls'):
        for value in payload[key]:
            _text(value, 2000)
    for document in payload['source_documents']:
        if (not isinstance(document, dict) or set(document) != {'asset_id', 'url', 'sha256'} or
                any(not re.fullmatch('[0-9a-f]{64}', str(document[key]))
                    for key in ('asset_id', 'sha256'))):
            raise ValueError('Повреждено исходное происхождение записи.')
        _text(document['url'], 1000)
    expected = _sha(canonical({key: payload[key] for key in (
        'definition', 'unit', 'direction', 'model_version', 'dataset',
        'evaluation', 'hardware', 'load', 'conditions')}))
    if payload['condition_sha256'] != expected:
        raise ValueError('Условия записи не соответствуют её контрольной сумме.')


def validate_backup(db):
    for row in db.execute("SELECT payload FROM research_assets WHERE kind='measurement'"):
        payload = json.loads(row[0])
        run = db.execute('SELECT output,status FROM runs WHERE id=?',
                         (payload['run_id'],)).fetchone()
        if (not run or run['status'] != 'completed' or
                _sha(run['output']) != payload['output_sha256']):
            raise ValueError('Измерительная запись не связана с исходным завершённым отчётом.')
        for document in payload['source_documents']:
            source = db.execute('SELECT kind,payload FROM research_assets WHERE id=?',
                                (document.get('asset_id'),)).fetchone()
            if (not source or source['kind'] != 'source_capture' or
                    json.loads(source['payload']).get('sha256') != document.get('sha256') or
                    json.loads(source['payload']).get('url') != document.get('url')):
                raise ValueError('Происхождение измерительной записи повреждено.')
