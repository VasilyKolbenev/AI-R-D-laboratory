"""Exact original-segment bindings, distinct from model semantic judgments."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import re

from .evidence_archive import validate_bundle


NOTICE = ('Проверены точная цитата в замороженном сегменте и привязка к URL источника. '
          'Семантическая связь supports/contradicts/insufficient — оценка модели, '
          'не независимое доказательство истинности, причинности или сопоставимости.')
_HASH = re.compile(r'[0-9a-f]{64}\Z')
_ID = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,59}\Z')
_FIELDS = {'evidence_id', 'document_id', 'segment_id', 'quote', 'relation', 'reason'}


def _numbers(text):
    result = set()
    pattern = r'(?<![\w.,])[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?(?!\w|[.,]\d)'
    for token in re.findall(pattern, text):
        try:
            number = Decimal(token.replace(',', '.'))
            if number.is_finite():
                result.add(number)
        except InvalidOperation:
            pass
    return result


def _text(value, limit, label):
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(ord(c) < 32 and c not in '\n\r\t' for c in value)):
        raise ValueError(label + ': неверный текст или размер.')
    return value


def _checks(value):
    if not isinstance(value, list) or len(value) > 16:
        raise ValueError('Допустимо до 16 привязок к оригинальным сегментам.')
    result, seen = [], set()
    for row in value:
        if not isinstance(row, dict) or set(row) != _FIELDS:
            raise ValueError('Неверная форма привязки к источнику.')
        for key in ('evidence_id', 'segment_id'):
            if not isinstance(row[key], str) or not _ID.fullmatch(row[key]):
                raise ValueError('Неверный ID привязки к источнику.')
        if (not isinstance(row['document_id'], str) or not _HASH.fullmatch(
                row['document_id']) or row['relation'] not in {
                    'supports', 'contradicts', 'insufficient'}):
            raise ValueError('Неверный документ или семантическая оценка модели.')
        _text(row['quote'], 4000, 'Цитата')
        _text(row['reason'], 700, 'Обоснование модели')
        key = (row['evidence_id'], row['document_id'], row['segment_id'], row['quote'])
        if key in seen:
            raise ValueError('Повторная привязка к одному фрагменту.')
        seen.add(key)
        result.append(deepcopy(row))
    return result


def validate_checks(plan, parsed, report, evidence):
    """Validate frozen source provenance, never infer a semantic verdict."""
    result = {'status': 'incomplete', 'checks': [], 'issues': [], 'notice': NOTICE}
    protocol = plan.get('research_protocol') or {}
    if protocol.get('version') not in {
            'three-pass-v2', 'three-pass-v3', 'three-pass-v4', 'editor-resume-v1'}:
        result['status'] = 'legacy'
        result['notice'] = 'Исторический протокол: новая проверка оригиналов не приписана.'
        return result
    try:
        bundle = plan.get('evidence_bundle')
        validate_bundle(bundle, plan.get('sources'))
        if not isinstance(parsed, dict) or not isinstance(report, str):
            raise ValueError('Нет итогового пакета для проверки источников.')
        raw_checks = parsed.get('_evidence_checks', parsed.get('evidence_checks'))
        checks = _checks(raw_checks)
        if not isinstance(evidence, list) or len(evidence) > 30:
            raise ValueError('Неверный реестр итоговых доказательств.')
        by_evidence = {}
        for row in evidence:
            if (not isinstance(row, dict) or not isinstance(row.get('id'), str)
                    or row['id'] in by_evidence):
                raise ValueError('Неверное или повторное итоговое доказательство.')
            by_evidence[row['id']] = row
        documents = {row['asset_id']: row for row in bundle['documents']}
        for row in checks:
            if row['evidence_id'] not in by_evidence:
                raise ValueError('Привязка ссылается на неизвестное итоговое доказательство.')
            document = documents.get(row['document_id'])
            if not document or document['status'] not in {'captured', 'partial'}:
                raise ValueError('Оригинал отсутствует либо текст не извлечён.')
            url = by_evidence[row['evidence_id']].get('source_url')
            if not url or url != document.get('url'):
                raise ValueError('URL доказательства не совпадает с точным документом.')
            segments = {segment['id']: segment for segment in document['segments']}
            segment = segments.get(row['segment_id'])
            if segment is None or row['quote'] not in segment['text']:
                raise ValueError('Дословная цитата не найдена в указанном сегменте оригинала.')
            result['checks'].append({**row, 'literal_quote': True, 'source_bound': True,
                                     'assessment_origin': 'model_judgment',
                                     'capture_origin': document.get('origin', 'unknown'),
                                     'capture_status': document['status'],
                                     'locator': segment['locator']})
        covered = {check['evidence_id'] for check in result['checks']}
        if set(by_evidence) - covered:
            raise ValueError('Итоговое доказательство не связано с оригинальной цитатой.')
        applied = parsed.get('_applied_analysis', parsed.get('applied_analysis')) or {}
        rows = applied.get('rows', [])
        if not isinstance(rows, list) or len(rows) > 3:
            raise ValueError('Неверный список количественных сравнений.')
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('Неверная строка количественного сравнения.')
            for side_name in ('baseline', 'candidate'):
                side = row.get(side_name)
                if not isinstance(side, dict):
                    raise ValueError('Нет baseline или кандидата в количественной строке.')
                value = side.get('value')
                if value is None:
                    continue
                if type(value) not in {int, float} or not math.isfinite(value):
                    raise ValueError('Числовой показатель должен быть конечным числом.')
                refs = side.get('evidence_ids')
                if (not isinstance(refs, list) or not refs or len(refs) > 4
                        or any(not isinstance(ref, str) or ref not in by_evidence
                               for ref in refs) or len(set(refs)) != len(refs)):
                    raise ValueError('Число не связано с точным итоговым доказательством.')
                matches = [check for check in result['checks']
                           if check['evidence_id'] in refs
                           and check['relation'] == 'supports'
                           and Decimal(str(value)) in _numbers(check['quote'])]
                if not matches:
                    raise ValueError('Число стороны сравнения отсутствует в её цитате оригинала.')
        result['status'] = 'ready'
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError) as exc:
        result['issues'].append(str(exc)[:1000] or 'Проверка оригиналов не завершена.')
    return result


def validate_asset(kind, payload):
    """Pure schema check for an immutable recorded source assessment."""
    if kind != 'evidence_assessment':
        raise ValueError('Неподдерживаемый вид оценки доказательств.')
    fields = {'version', 'run_id', 'report_sha256', 'bundle_sha256',
              'status', 'checks', 'issues', 'notice'}
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ValueError('Неверная форма сохранённой оценки оригиналов.')
    if (payload['version'] != 'evidence-assessment-v1'
            or payload['status'] not in {'ready', 'incomplete', 'legacy'}
            or not isinstance(payload['run_id'], str)
            or not re.fullmatch(r'[0-9a-f]{32}', payload['run_id'])):
        raise ValueError('Неверные версия, исследование или статус оценки.')
    for key in ('report_sha256', 'bundle_sha256'):
        if not isinstance(payload[key], str) or not _HASH.fullmatch(payload[key]):
            raise ValueError('Неверная контрольная сумма оценки.')
    if not isinstance(payload['checks'], list) or len(payload['checks']) > 16:
        raise ValueError('Неверное число проверенных привязок.')
    extra = {'literal_quote', 'source_bound', 'assessment_origin', 'capture_origin',
             'capture_status', 'locator'}
    for row in payload['checks']:
        if not isinstance(row, dict) or set(row) != _FIELDS | extra:
            raise ValueError('Неверная сохранённая привязка.')
        _checks([{key: row[key] for key in _FIELDS}])
        if (row['literal_quote'] is not True or row['source_bound'] is not True
                or row['assessment_origin'] != 'model_judgment'
                or row['capture_origin'] not in {'supplied', 'fetched', 'unknown'}
                or row['capture_status'] not in {'captured', 'partial'}):
            raise ValueError('Оценка не должна приписывать независимую семантическую проверку.')
        _text(row['locator'], 120, 'Место источника')
    if (not isinstance(payload['issues'], list) or len(payload['issues']) > 20
            or any(not isinstance(item, str) or len(item) > 1000
                   for item in payload['issues'])):
        raise ValueError('Неверные ограничения проверки источников.')
    _text(payload['notice'], 1000, 'Границы проверки')
    if payload['status'] == 'ready' and payload['issues']:
        raise ValueError('Готовая оценка не может скрывать ошибки привязки.')


def assessment_payload(run, result):
    """Create a separately versioned record without mutating the original run."""
    bundle = run['plan'].get('evidence_bundle')
    encoded = json.dumps(bundle, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False)
    payload = {'version': 'evidence-assessment-v1', 'run_id': run['id'],
               'report_sha256': hashlib.sha256(run['output'].encode('utf-8')).hexdigest(),
               'bundle_sha256': hashlib.sha256(encoded.encode('utf-8')).hexdigest(),
               **{key: deepcopy(result[key])
                  for key in ('status', 'checks', 'issues', 'notice')}}
    validate_asset('evidence_assessment', payload)
    return payload
