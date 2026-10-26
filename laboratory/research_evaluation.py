"""Immutable human annotations; pending outputs never become automatic gold."""
from copy import deepcopy
import hashlib
import json
import re

from .research_assets import Assets, canonical

LABELS = {
    'factual_support': {'supported', 'unsupported', 'uncertain', 'ungraded'},
    'number_extraction': {'correct', 'incorrect', 'ungraded'},
    'comparability': {'correct', 'incorrect', 'ungraded'},
    'reader_comprehension': {'clear', 'unclear', 'ungraded'}}
POSITIVE = {'factual_support': 'supported', 'number_extraction': 'correct',
            'comparability': 'correct', 'reader_comprehension': 'clear'}
NOTICE = ('Оценки задаёт человек по конкретному отчёту и исходникам. Покрытие и четыре '
          'измерения раздельны; тесты приложения и согласие моделей не являются gold.')


def _sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _hash(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('Неверная контрольная сумма корпуса.')


def _text(value, maximum):
    if not isinstance(value, str) or len(value) > maximum or '\x00' in value:
        raise ValueError('Повреждён текст аннотации.')
    return value


class Evaluation:
    def __init__(self, store):
        self.store, self.assets = store, Assets(store)

    def seed(self, runs):
        if not isinstance(runs, list) or len(runs) > 1000:
            raise ValueError('Нужен ограниченный список существующих исследований.')
        result = []
        for run in runs:
            if run.get('status') != 'completed' or not isinstance(run.get('output'), str):
                continue
            plan = run.get('plan') or {}
            payload = {
                'version': 'evaluation-case-v1', 'run_id': run['id'], 'status': 'pending',
                'output_sha256': _sha(run['output']),
                'source_hashes': sorted(source['content_hash'] for source in
                                        plan.get('sources', []) if source.get('content_hash')),
                'document_hashes': sorted(document['sha256'] for document in
                                          (plan.get('evidence_bundle') or {}).get(
                                              'documents', []) if document.get('sha256')),
                'dimensions': list(LABELS), 'report_excerpt': run['output'][:1500],
                'origin': 'existing_report_ungraded', 'notice': NOTICE}
            payload['input_sha256'] = _sha(canonical({key: payload[key] for key in (
                'run_id', 'output_sha256', 'source_hashes', 'document_hashes')}))
            result.append(self.assets.put('evaluation_case', payload))
        return result

    def annotate(self, values):
        allowed = {'case_id', 'annotator', 'labels', 'notes', 'supersedes'}
        if not isinstance(values, dict) or set(values) - allowed:
            raise ValueError('Аннотация должна быть явным человеческим вводом.')
        case = self.assets.get(values.get('case_id'))
        if case['kind'] != 'evaluation_case':
            raise ValueError('Выбран не кейс исследовательского корпуса.')
        previous = [row for row in self.assets.list('evaluation_annotation', limit=10000)
                    if row['payload']['case_id'] == case['id']]
        latest = max(previous, key=lambda row: row['payload']['revision']) if previous else None
        predecessor = values.get('supersedes')
        if predecessor != (latest['id'] if latest else None):
            raise ValueError('Аннотация уже менялась; укажите точного предшественника.')
        labels = values.get('labels', {})
        if not isinstance(labels, dict) or set(labels) - set(LABELS):
            raise ValueError('Неизвестные измерения качества.')
        payload = {
            'version': 'evaluation-annotation-v1', 'case_id': case['id'],
            'input_sha256': case['payload']['input_sha256'],
            'output_sha256': case['payload']['output_sha256'],
            'origin': 'human', 'annotator': values.get('annotator', ''),
            'labels': {key: labels.get(key, 'ungraded') for key in LABELS},
            'notes': values.get('notes', ''), 'supersedes': predecessor,
            'revision': latest['payload']['revision'] + 1 if latest else 1}
        return self.assets.claim('evaluation_annotation', payload,
                                 'evaluation:' + case['id'] + ':' + (predecessor or 'first'))

    def summary(self, run_id=None):
        cases = [row for row in self.assets.list('evaluation_case', limit=10000)
                 if run_id is None or row['payload']['run_id'] == run_id]
        selected = {row['id'] for row in cases}
        annotations = [row for row in self.assets.list('evaluation_annotation', limit=10000)
                       if row['payload']['case_id'] in selected]
        latest = {}
        for row in annotations:
            case_id = row['payload']['case_id']
            if (case_id not in latest or
                    row['payload']['revision'] > latest[case_id]['payload']['revision']):
                latest[case_id] = row
        metrics = {}
        for dimension, positive in POSITIVE.items():
            observed = [row['payload']['labels'][dimension] for row in latest.values()]
            graded = [value for value in observed if value not in {'ungraded', 'uncertain'}]
            count = sum(value == positive for value in graded)
            metrics[dimension] = {
                'graded': len(graded), 'positive': count,
                'rate': count / len(graded) if graded else None,
                'uncertain': observed.count('uncertain'),
                'ungraded': len(cases) - len(graded) - observed.count('uncertain'),
                'basis': 'latest_human_annotation_only'}
        return {'cases': deepcopy(cases), 'annotations': deepcopy(annotations),
                'metrics': metrics, 'coverage': {'case_count': len(cases),
                    'annotated_cases': len(latest), 'pending_cases': len(cases) - len(latest)},
                'notice': NOTICE}


def validate_asset(kind, payload):
    if not isinstance(payload, dict):
        raise ValueError('Повреждён объект корпуса.')
    if kind == 'evaluation_case':
        fields = {'version', 'run_id', 'status', 'output_sha256', 'source_hashes',
                  'document_hashes', 'dimensions', 'report_excerpt', 'origin', 'notice',
                  'input_sha256'}
        if (set(payload) != fields or payload['version'] != 'evaluation-case-v1' or
                payload['status'] != 'pending' or
                payload['origin'] != 'existing_report_ungraded' or
                payload['dimensions'] != list(LABELS) or
                not re.fullmatch('[0-9a-f]{32}', str(payload['run_id']))):
            raise ValueError('Кейс должен оставаться исходным неразмеченным отчётом.')
        for key in ('source_hashes', 'document_hashes'):
            if not isinstance(payload[key], list) or len(payload[key]) > 30:
                raise ValueError('Повреждён набор исходников кейса.')
            for value in payload[key]:
                _hash(value)
        _hash(payload['output_sha256'])
        _text(payload['report_excerpt'], 1500)
        _text(payload['notice'], 1000)
        expected = _sha(canonical({key: payload[key] for key in (
            'run_id', 'output_sha256', 'source_hashes', 'document_hashes')}))
        if payload['input_sha256'] != expected:
            raise ValueError('Входные данные корпуса изменились.')
    elif kind == 'evaluation_annotation':
        fields = {'version', 'case_id', 'input_sha256', 'output_sha256', 'origin',
                  'annotator', 'labels', 'notes', 'supersedes', 'revision'}
        if (set(payload) != fields or payload['version'] != 'evaluation-annotation-v1' or
                payload['origin'] != 'human' or type(payload['revision']) is not int or
                not 1 <= payload['revision'] <= 10000):
            raise ValueError('Аннотация должна иметь человеческое происхождение и версию.')
        for key in ('case_id', 'input_sha256', 'output_sha256'):
            _hash(payload[key])
        if payload['supersedes'] is not None:
            _hash(payload['supersedes'])
        if not _text(payload['annotator'], 160).strip():
            raise ValueError('Назовите автора человеческой аннотации.')
        _text(payload['notes'], 4000)
        labels = payload['labels']
        if (not isinstance(labels, dict) or set(labels) != set(LABELS) or
                any(not isinstance(labels[key], str) or labels[key] not in LABELS[key]
                    for key in LABELS)):
            raise ValueError('Неверные отдельные измерения качества.')
    else:
        raise ValueError('Неизвестный тип корпуса качества.')


def validate_backup(db):
    assets = {row['id']: {'kind': row['kind'], 'payload': json.loads(row['payload'])}
              for row in db.execute("SELECT * FROM research_assets WHERE kind IN "
                                    "('evaluation_case','evaluation_annotation')")}
    children = set()
    claims = {row['claim_key']: row['asset_id'] for row in db.execute(
        'SELECT claim_key,asset_id FROM research_asset_claims')}
    for asset_id, asset in assets.items():
        payload = asset['payload']
        if asset['kind'] == 'evaluation_case':
            run = db.execute('SELECT output,status,plan FROM runs WHERE id=?',
                             (payload['run_id'],)).fetchone()
            if (not run or run['status'] != 'completed' or
                    _sha(run['output']) != payload['output_sha256']):
                raise ValueError('Кейс корпуса не связан с сохранённым отчётом.')
            plan = json.loads(run['plan'])
            expected_sources = sorted(source['content_hash'] for source in plan.get(
                'sources', []) if source.get('content_hash'))
            expected_documents = sorted(document['sha256'] for document in
                                        (plan.get('evidence_bundle') or {}).get(
                                            'documents', []) if document.get('sha256'))
            if (payload['source_hashes'] != expected_sources or
                    payload['document_hashes'] != expected_documents or
                    payload['report_excerpt'] != run['output'][:1500]):
                raise ValueError('Входные исходники корпуса не соответствуют отчёту.')
            continue
        case = assets.get(payload['case_id'])
        if (not case or case['kind'] != 'evaluation_case' or
                any(payload[key] != case['payload'][key] for key in (
                    'input_sha256', 'output_sha256'))):
            raise ValueError('Человеческая аннотация не связана с точным входом кейса.')
        predecessor = assets.get(payload['supersedes'])
        if payload['supersedes'] is None:
            if payload['revision'] != 1:
                raise ValueError('У аннотации отсутствует предшественник.')
        elif (not predecessor or predecessor['kind'] != 'evaluation_annotation' or
              predecessor['payload']['case_id'] != payload['case_id'] or
              predecessor['payload']['revision'] + 1 != payload['revision']):
            raise ValueError('Повреждена цепочка человеческих аннотаций.')
        key = (payload['case_id'], payload['supersedes'])
        if key in children:
            raise ValueError('Цепочка человеческих аннотаций разветвлена.')
        children.add(key)
        claim = 'evaluation:' + payload['case_id'] + ':' + (payload['supersedes'] or 'first')
        if claims.get(claim) != asset_id:
            raise ValueError('Аннотация не имеет однократной регистрации версии.')
