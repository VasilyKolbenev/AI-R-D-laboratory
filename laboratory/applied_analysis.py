"""Fail-closed source-analysis packets and evidence-linked comparison rows.

Checks concern provenance, bounds and observable editorial changes. Neither
schema validity nor agreement between model passes proves scientific truth.
"""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import math
import re

from .research_protocol import (LIMITS, ROLES, canonical, comparison_context,
                                protocol_sha256, validate_protocol)


_ID = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,39}\Z')
BASES = {'unknown', 'hypothesis', 'author_claim', 'external_measurement', 'estimate'}
MEASURED_BASES = {'author_claim', 'external_measurement'}
NOTICE = ('Проверены структура, происхождение ссылок и чисел в сохранённом отчёте, '
          'покрытие замечаний и наблюдаемые исправления. Это машинная редактура, '
          'не независимая проверка первоисточника, научной истины или переносимости.')


def _sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _object(value, allowed, label, required=None):
    if not isinstance(value, dict) or set(value) - set(allowed) or not set(required or ()) <= set(value):
        raise ValueError(label + ': неизвестные или отсутствующие поля.')
    return value


def _text(value, maximum, label, required=True):
    if (not isinstance(value, str) or len(value) > maximum or (required and not value.strip())
            or '<' in value or '>' in value or any(ord(c) < 32 and c not in '\n\t\r' for c in value)):
        raise ValueError(label + ': неверный текст или размер.')
    return value.strip()


def _id(value, label):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(label + ': неверный ID.')
    return value


def _list(value, maximum, label):
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(label + ': неверный список или размер.')
    return value


def _refs(value, known, maximum=8, label='Ссылки'):
    value = _list(value, maximum, label)
    if any(not isinstance(item, str) or item not in known for item in value) or len(set(value)) != len(value):
        raise ValueError(label + ': неизвестная или повторная ссылка.')
    return list(value)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Повторный JSON-ключ.')
        result[key] = value
    return result


def _block(text, tag, maximum=14_000):
    pattern = re.compile(r'<' + tag + r'>\s*(.*?)\s*</' + tag + r'>', re.S | re.I)
    blocks = pattern.findall(text)
    if (len(blocks) != 1 or len(re.findall(r'<' + tag + r'>', text, re.I)) != 1
            or len(re.findall(r'</' + tag + r'>', text, re.I)) != 1
            or len(blocks[0].encode('utf-8')) > maximum):
        raise ValueError(tag + ': нужен ровно один ограниченный полный блок.')
    value = json.loads(blocks[0], object_pairs_hook=_unique,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Нечисловая константа.')))
    if not isinstance(value, dict):
        raise ValueError(tag + ': нужен JSON-объект.')
    return value


def _prefix_web_search(plan):
    if (plan.get('research_protocol') or {}).get('version') == 'editor-resume-v1':
        from .research_continuation import validate_plan
        validate_plan(plan)
        return plan['continuation']['parent_web_search']
    return bool(plan.get('web_search'))


def _research(plan, text):
    from .presentation import _public_url, display_report
    value = _block(text, 'lab_research')
    _object(value, {'version', 'claims', 'metric_ids', 'analogue_ids'}, 'Пакет исследователя',
            {'version', 'claims', 'metric_ids', 'analogue_ids'})
    if value['version'] != 'research-packet-v1':
        raise ValueError('Неизвестная версия пакета исследователя.')
    source_ids = {item['id'] for item in plan.get('sources', [])}
    source_urls = {item.get('url') for item in plan.get('sources', []) if item.get('url')}
    claims, known = [], set()
    prose = display_report(text)
    for row in _list(value['claims'], 8, 'Утверждения исследователя'):
        _object(row, {'id', 'claim', 'source_ids', 'source_urls'}, 'Утверждение',
                {'id', 'claim', 'source_ids', 'source_urls'})
        identifier = _id(row['id'], 'Утверждение')
        if identifier in known or identifier in source_ids:
            raise ValueError('ID утверждения повторяется или совпадает с исходником.')
        refs = _refs(row['source_ids'], source_ids, 6, 'Исходники утверждения')
        urls = _list(row['source_urls'], 5, 'URL утверждения')
        if (any(not isinstance(url, str) or not _public_url(url) or url not in prose
                or (not _prefix_web_search(plan) and url not in source_urls) for url in urls)
                or len(set(urls)) != len(urls) or (not refs and not urls)):
            raise ValueError('Утверждение не связано с доступным исходником или явным публичным URL.')
        claims.append({'id': identifier, 'claim': _text(row['claim'], 500, 'Утверждение'),
                       'source_ids': refs, 'source_urls': list(urls)})
        known.add(identifier)
    context = comparison_context(plan)
    metric_ids = _refs(value['metric_ids'], {row['id'] for row in context['metric_checklist']}, 8, 'Метрики исследователя')
    analogue_ids = _refs(value['analogue_ids'], {row['memory_id'] for row in context['analogues']}, 5, 'Аналоги исследователя')
    return {'version': value['version'], 'claims': claims, 'metric_ids': metric_ids, 'analogue_ids': analogue_ids}


def _critic(plan, research, text):
    from .presentation import _public_url, display_report
    value = _block(text, 'lab_critic')
    grounded = (plan.get('research_protocol') or {}).get('version') in {
        'three-pass-v2', 'three-pass-v3', 'three-pass-v4', 'editor-resume-v1'}
    extras = {'counter_evidence', 'independent_conclusion'} if grounded else set()
    _object(value, {'version', 'issues', 'checked_sources'} | extras, 'Пакет критика', {'version', 'issues'} | extras)
    if value['version'] != 'critic-review-v1':
        raise ValueError('Неизвестная версия пакета критика.')
    claim_ids = {row['id'] for row in research['claims']}
    known_refs = claim_ids | {row['id'] for row in plan.get('sources', [])}
    checked, checked_ids = [], set()
    for row in _list(value.get('checked_sources', []), 2, 'Проверенные источники критика'):
        fields = {'id', 'source_url', 'locator', 'excerpt', 'claim', 'limitations'}
        _object(row, fields, 'Источник критика', fields)
        identifier = _id(row['id'], 'Источник критика')
        url = row['source_url']
        if (not _prefix_web_search(plan) or identifier in known_refs | checked_ids
                or not isinstance(url, str) or not _public_url(url) or len(url) > 350
                or url not in display_report(text)):
            raise ValueError('Внешний источник критика не разрешён, повторяется или не указан явно.')
        if row.get('excerpt') not in display_report(text):
            raise ValueError('Выдержка проверки критика отсутствует в его обычном ответе.')
        checked.append({'id': identifier, 'source_url': url,
                        **{key: _text(row[key], maximum, 'Источник критика: ' + key)
                           for key, maximum in [('locator', 120), ('excerpt', 500), ('claim', 500), ('limitations', 300)]}})
        checked_ids.add(identifier)
    known_refs |= checked_ids
    issues, identifiers = [], set()
    for row in _list(value['issues'], 8, 'Замечания критика'):
        fields = {'id', 'severity', 'target', 'problem', 'evidence_ids', 'required_change'}
        _object(row, fields, 'Замечание критика', fields)
        identifier = _id(row['id'], 'Замечание')
        if identifier in identifiers or row['severity'] not in {'blocker', 'major', 'minor'} or row['target'] not in claim_ids | {'report'}:
            raise ValueError('Повторный ID, неизвестная важность или предмет замечания.')
        issues.append({'id': identifier, 'severity': row['severity'], 'target': row['target'],
                       'problem': _text(row['problem'], 700, 'Проблема'),
                       'required_change': _text(row['required_change'], 700, 'Исправление'),
                       'evidence_ids': _refs(row['evidence_ids'], known_refs, label='Основания критика')})
        identifiers.add(identifier)
    result = {'version': value['version'], 'issues': issues, 'checked_sources': checked}
    if grounded:
        counter = _object(value['counter_evidence'], {'status', 'sources', 'limitations'},
                          'Поиск опровержений', {'status', 'sources', 'limitations'})
        if counter['status'] not in {'found', 'not_found', 'not_searched'}:
            raise ValueError('Неизвестный исход поиска опровержений.')
        urls = _list(counter['sources'], 2, 'Источники опровержений')
        available = {item['source_url'] for item in checked}
        available.update(item['url'] for item in plan.get('evidence_bundle', {}).get('documents', []))
        if (any(not isinstance(url, str) or not _public_url(url) or url not in available for url in urls)
                or (counter['status'] == 'found' and not urls)
                or (not _prefix_web_search(plan) and counter['status'] != 'not_searched')):
            raise ValueError('Поиск опровержений не связан с доступными основаниями.')
        result['counter_evidence'] = {
            'status': counter['status'], 'sources': urls,
            'limitations': _text(counter['limitations'], 500, 'Ограничения поиска')}
        result['independent_conclusion'] = _text(
            value['independent_conclusion'], 1200, 'Независимый вывод критика')
    return result


def validate_applied(plan, value, evidence, report):
    """Normalize a table and derive only the supported measured chart pairs."""
    from .presentation import _clean, _literal_numbers
    fields = {'version', 'rows', 'analogues', 'unknowns'}
    _object(value, fields, 'Прикладное сравнение', fields)
    if value['version'] != 'applied-comparison-v1':
        raise ValueError('Неизвестная версия прикладного сравнения.')
    by_id = {row['id']: row for row in evidence}
    rows, charts, identifiers = [], [], set()
    for item in _list(value['rows'], 3, 'Прикладные строки'):
        row_fields = {'id', 'metric', 'definition', 'unit', 'direction', 'baseline', 'candidate',
                      'conditions', 'comparability', 'comparability_reason'}
        grounded = (plan.get('research_protocol') or {}).get('version') in {
            'three-pass-v2', 'three-pass-v3', 'three-pass-v4', 'editor-resume-v1'}
        allowed_fields = row_fields | ({'measurement_context'} if grounded else set())
        _object(item, allowed_fields, 'Строка сравнения', row_fields)
        identifier = _id(item['id'], 'Строка')
        if identifier in identifiers:
            raise ValueError('Повторный ID строки сравнения.')
        identifiers.add(identifier)
        row = {'id': identifier}
        for key, maximum in [('metric', 120), ('definition', 400), ('unit', 40), ('conditions', 500), ('comparability_reason', 400)]:
            row[key] = _clean(_text(item[key], maximum, 'Сравнение: ' + key))
            if not row[key] or re.search(r'https?://', row[key], re.I):
                raise ValueError('URL разрешены только в реестре доказательств.')
        if item['direction'] not in {'maximize', 'minimize', 'descriptive'} or item['comparability'] not in {'comparable', 'not_comparable', 'unknown'}:
            raise ValueError('Неизвестное направление или сопоставимость.')
        row.update(direction=item['direction'], comparability=item['comparability'])
        if grounded and 'measurement_context' in item:
            fields = {'baseline_version', 'candidate_version', 'dataset', 'evaluation',
                      'hardware', 'load'}
            context = _object(item['measurement_context'], fields, 'Условия измерения', fields)
            row['measurement_context'] = {
                key: None if value is None else _text(value, 240, 'Условия: ' + key)
                for key, value in context.items()}

        for side in ('baseline', 'candidate'):
            original = _object(item[side], {'label', 'value', 'basis', 'evidence_ids'}, side,
                               {'label', 'value', 'basis', 'evidence_ids'})
            label = _clean(_text(original['label'], 80, side + ': название'))
            if not label or re.search(r'https?://', label, re.I) or original['basis'] not in BASES:
                raise ValueError('Неверное происхождение или название сравниваемого значения.')
            number = original['value']
            refs = _refs(original['evidence_ids'], set(by_id), 4, side + ': доказательства')
            if number is not None:
                if (type(number) not in {int, float} or not math.isfinite(number) or not 0 <= number <= 1e100
                        or original['basis'] == 'unknown' or not refs):
                    raise ValueError('Число должно иметь известное происхождение и связанное доказательство.')
                literals = _literal_numbers(' '.join(by_id[ref]['excerpt'] for ref in refs))
                if Decimal(str(number)) not in literals:
                    raise ValueError('Число прикладного сравнения отсутствует в связанном фрагменте отчёта.')
            row[side] = {'label': label, 'value': number, 'basis': original['basis'], 'evidence_ids': refs}
        measured = all(row[side]['value'] is not None and row[side]['basis'] in MEASURED_BASES for side in ('baseline', 'candidate'))
        if row['comparability'] == 'comparable' and measured:
            charts.append({'label': row['metric'], 'unit': row['unit'],
                           'baseline_label': row['baseline']['label'], 'baseline_value': row['baseline']['value'],
                           'result_label': row['candidate']['label'], 'result_value': row['candidate']['value'],
                           'conditions': row['conditions'],
                           'evidence_ids': list(dict.fromkeys(row['baseline']['evidence_ids'] + row['candidate']['evidence_ids']))})
        rows.append(row)
    context = comparison_context(plan)
    selected = {(row['memory_id'], row['memory_version']) for row in context['analogues']}
    analogues, seen = [], set()
    for item in _list(value['analogues'], 5, 'Аналогичные исследования'):
        fields = {'memory_id', 'memory_version', 'relation', 'relevance', 'conditions_difference'}
        _object(item, fields, 'Аналог', fields)
        if (not isinstance(item['memory_id'], str) or type(item['memory_version']) is not int
                or (item['memory_id'], item['memory_version']) not in selected
                or (item['memory_id'], item['memory_version']) in seen
                or item['relation'] not in {'supports', 'contradicts', 'extends', 'context'}):
            raise ValueError('Аналог не выбран в одобренной памяти, версия неверна или запись повторяется.')
        seen.add((item['memory_id'], item['memory_version']))
        analogues.append({'memory_id': item['memory_id'], 'memory_version': item['memory_version'], 'relation': item['relation'],
                          'relevance': _text(item['relevance'], 400, 'Применимость аналога'),
                          'conditions_difference': _text(item['conditions_difference'], 400, 'Различия условий аналога')})
    if seen != selected:
        raise ValueError('Не рассмотрены все выбранные аналоги; нерелевантные явно отметьте как context.')
    unknowns = [_text(item, 400, 'Неизвестные данные') for item in _list(value['unknowns'], 8, 'Неизвестные данные')]
    if not rows and not unknowns:
        raise ValueError('Отсутствие измеримых сравнений требует конкретного объяснения неизвестных данных.')
    return {'version': value['version'], 'rows': rows, 'analogues': analogues, 'unknowns': unknowns}, charts


def _tokens(text):
    return {word[:6] for word in re.findall(r'[^\W_]{5,}', text.casefold())}


def _dispositions(value, critic, research, report, evidence):
    by_issue = {row['id']: row for row in critic['issues']}
    by_claim = {row['id']: row for row in research['claims']}
    by_evidence = {row['id']: row for row in evidence}
    result, seen = [], set()
    for row in _list(value, 8, 'Решения проверяющего'):
        _object(row, {'issue_id', 'status', 'reason', 'resolution_excerpt', 'resolution_evidence_ids'},
                'Решение проверяющего', {'issue_id', 'status', 'reason'})
        issue_id = row['issue_id']
        if (not isinstance(issue_id, str) or issue_id not in by_issue or issue_id in seen
                or row['status'] not in {'fixed', 'retained_with_limit', 'unresolved'}):
            raise ValueError('Решение ссылается на неизвестное/повторное замечание или статус.')
        seen.add(issue_id)
        reason = _text(row['reason'], 700, 'Причина решения')
        excerpt = _text(row.get('resolution_excerpt', ''), 500, 'Фрагмент исправления', False)
        refs = _refs(row.get('resolution_evidence_ids', []), set(by_evidence), 4, 'Основания исправления')
        if excerpt and excerpt not in report:
            raise ValueError('Фрагмент исправления отсутствует дословно в финальном отчёте.')
        issue = by_issue[issue_id]
        if issue['severity'] == 'blocker':
            if row['status'] != 'fixed':
                raise ValueError('Блокирующее замечание не устранено: ' + issue_id + '.')
            claim = by_claim.get(issue['target'])
            related = _tokens((claim or {}).get('claim', '') + ' ' + issue['problem'] + ' ' + issue['required_change'])
            if not excerpt or len(reason) < 25 or not (related & _tokens(reason)) or not (related & _tokens(excerpt)):
                raise ValueError('Статус fixed требует конкретной причины и дословного целевого исправления: ' + issue_id + '.')
            if claim and claim['claim'] in report:
                new_support = [by_evidence[ref] for ref in refs
                               if by_evidence[ref]['source_url'] not in claim['source_urls']
                               and _tokens(claim['claim']) & _tokens(by_evidence[ref]['claim'])]
                if not new_support:
                    raise ValueError('Исходное блокируемое утверждение сохранено без нового связанного основания: ' + issue_id + '.')
        result.append({'issue_id': issue_id, 'status': row['status'], 'reason': reason,
                       'resolution_excerpt': excerpt, 'resolution_evidence_ids': refs})
    if seen != set(by_issue):
        raise ValueError('Нет ровно одного решения по каждому замечанию критика.')
    return result


def validate_final(plan, phase_texts):
    """Return a bounded deterministic gate; never throw for untrusted packets."""
    final = phase_texts[-1] if isinstance(phase_texts, list) and phase_texts and isinstance(phase_texts[-1], str) else ''
    protocol = plan.get('research_protocol') if isinstance(plan, dict) else None
    try:
        recipe_hash = protocol_sha256(protocol)
    except (ValueError, TypeError, RecursionError):
        recipe_hash = ''
    result = {'status': 'incomplete', 'issues': [], 'critic': {'version': 'critic-review-v1', 'issues': []},
              'dispositions': [], 'applied_analysis': {'version': 'applied-comparison-v1', 'rows': [], 'analogues': [], 'unknowns': []},
              'comparisons': [], 'final_output_sha256': _sha(final), 'protocol_sha256': recipe_hash,
              'phase_output_sha256s': [_sha(item) for item in phase_texts if isinstance(item, str)] if isinstance(phase_texts, list) else [],
              'notice': NOTICE}
    try:
        validate_protocol(protocol)
        if not isinstance(phase_texts, list) or len(phase_texts) != 3:
            raise ValueError('Нужны результаты ровно трёх отдельных проходов.')
        for index, text in enumerate(phase_texts):
            if not isinstance(text, str) or not text.strip() or len(text) > LIMITS[ROLES[index] + '_output_chars']:
                raise ValueError('Ответ прохода отсутствует или превышает одобренный лимит.')
        research = _research(plan, phase_texts[0])
        critic = _critic(plan, research, phase_texts[1])
        result['critic'] = critic
        from .presentation import _structured, _auto_support, _public_url, _URL, display_report
        parsed, warnings = _structured(final)
        if not parsed or warnings:
            raise ValueError('Финальный блок оформления не прошёл структурную проверку.')
        report = display_report(final)
        allowed = {_public_url(url) for url in _URL.findall(report)} - {''}
        evidence, original_charts, support_issues = _auto_support(parsed.get('_auto_evidence', []), parsed.get('_auto_comparisons', []), report, allowed)
        if support_issues:
            raise ValueError('; '.join(support_issues))
        original_sources = {item.get('url') for item in plan.get('sources', []) if item.get('url')}
        researcher_urls = set(original_sources)
        for claim in research['claims']:
            researcher_urls.update(claim['source_urls'])
        researcher_urls.update(item['source_url'] for item in critic['checked_sources'])
        if any(row['source_url'] not in researcher_urls for row in evidence):
            raise ValueError('Финальный проверяющий добавил источник, отсутствующий в исследовательском пакете.')
        applied, charts = validate_applied(plan, parsed.get('_applied_analysis'), evidence, report)
        result['applied_analysis'] = applied
        # An editor may remove/qualify data, but cannot manufacture a fresh
        # measured value just by repeating it in the final report and excerpt.
        from .presentation import _literal_numbers
        sources = {row['id']: row for row in plan.get('sources', [])}
        upstream_numbers = {}
        for claim in research['claims']:
            urls = set(claim['source_urls']) | {sources[ref].get('url') for ref in claim['source_ids']}
            claim_numbers = _literal_numbers(claim['claim'])
            for url in urls:
                numbers = claim_numbers
                if not _prefix_web_search(plan):
                    # Resolve this exact URL to its own supplied text. A claim
                    # citing A and B cannot transfer a number found only in A
                    # to evidence whose provenance says B.
                    originals = _literal_numbers(' '.join(source.get('text', '') for source in sources.values()
                                                         if source.get('url') == url))
                    numbers = claim_numbers & originals
                upstream_numbers.setdefault(url, set()).update(numbers)
        for checked in critic['checked_sources']:
            upstream_numbers.setdefault(checked['source_url'], set()).update(_literal_numbers(checked['excerpt']))
        by_evidence = {row['id']: row for row in evidence}
        for row in applied['rows']:
            for side in ('baseline', 'candidate'):
                value = row[side]['value']
                if value is not None and not any(Decimal(str(value)) in upstream_numbers.get(by_evidence[ref]['source_url'], set())
                                                 for ref in row[side]['evidence_ids']):
                    raise ValueError('Финальный проверяющий добавил число без основания в предыдущих проходах и исходных данных.')
        # The final comparisons list cannot create a second, unvetted chart path.
        def chart_key(row):
            return tuple(row[key] for key in ('label', 'unit', 'baseline_label', 'baseline_value', 'result_label', 'result_value'))
        available = {chart_key(row): row for row in charts}
        for row in original_charts:
            accepted = available.get(chart_key(row))
            if (not accepted or set(row['evidence_ids']) != set(accepted['evidence_ids'])
                    or row['conditions'] != accepted['conditions']):
                raise ValueError('График не соответствует сопоставимой прикладной строке и её основаниям.')
        result['comparisons'] = charts
        result['dispositions'] = _dispositions(parsed.get('_review_dispositions'), critic, research, report, evidence)
        if plan.get('evidence_bundle') is not None:
            from .evidence_validation import validate_checks
            source_validation = validate_checks(plan, parsed, report, evidence)
            result['source_validation'] = source_validation
            if source_validation['status'] != 'ready':
                raise ValueError('; '.join(source_validation.get('issues', [])))
        result['status'] = 'ready'
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError) as exc:
        result['issues'].append(str(exc)[:1200] or 'Неполная машинная проверка.')
    return result


def validate_phase(plan, index, phase_texts):
    """Stop successors when the current phase packet cannot be trusted."""
    if index == 2:
        return validate_final(plan, phase_texts)
    result = {'status': 'incomplete', 'issues': []}
    try:
        validate_protocol(plan.get('research_protocol'))
        if (type(index) is not int or index not in {0, 1} or not isinstance(phase_texts, list)
                or len(phase_texts) != index + 1):
            raise ValueError('Неверный порядок проверки прохода.')
        for phase_index, text in enumerate(phase_texts):
            if not isinstance(text, str) or not text.strip() or len(text) > LIMITS[ROLES[phase_index] + '_output_chars']:
                raise ValueError('Ответ прохода отсутствует или превышает одобренный лимит.')
        research = _research(plan, phase_texts[0])
        if index == 1:
            result['critic'] = _critic(plan, research, phase_texts[1])
        result['status'] = 'ready'
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError) as exc:
        result['issues'].append(str(exc)[:1200] or 'Неполная проверка прохода.')
    return result


def presentation_gate(run, parsed, report, evidence):
    """Verify a stored three-pass outcome and revalidate final visible rows."""
    plan = run.get('plan') or {}
    if not plan.get('research_protocol'):
        return None
    issues = []
    summary = run.get('agent_review')
    pipeline = run.get('agent_pipeline') or {}
    raw = run.get('raw') or {}
    if not summary and isinstance(raw, dict):
        summary = (raw.get('orchestration') or {}).get('review')
    if not pipeline and isinstance(raw, dict):
        pipeline = raw.get('orchestration') or {}
    result = {'status': 'incomplete', 'issues': issues, 'critic': {}, 'dispositions': [],
              'applied_analysis': {'version': 'applied-comparison-v1', 'rows': [], 'analogues': [], 'unknowns': []},
              'comparisons': [], 'notice': NOTICE}
    try:
        validate_protocol(plan['research_protocol'])
        if not isinstance(summary, dict) or summary.get('status') != 'ready':
            raise ValueError('Три прохода не завершили обязательную машинную проверку.')
        if (summary.get('protocol_sha256') != protocol_sha256(plan['research_protocol'])
                or summary.get('final_output_sha256') != _sha(run.get('output', ''))):
            raise ValueError('Проверка не связана с текущим протоколом и финальным ответом.')
        phases = pipeline.get('phases')
        resume = plan['research_protocol']['version'] == 'editor-resume-v1'
        if resume:
            from .research_continuation import validate_plan, reused_view
            validate_plan(plan)
            if pipeline.get('reused_phases') != reused_view(plan):
                raise ValueError('Сохранённые этапы не совпадают с checkpoint.')
        roles = ['reviewer'] if resume else ROLES
        expected_hashes = ([row['output_sha256'] for row in plan['continuation']['prefix']]
                           if resume else [])
        if (pipeline.get('status') != 'completed' or pipeline.get('dispatched_calls') != len(roles)
                or not isinstance(phases, list) or len(phases) != len(roles)
                or any(not isinstance(row, dict) or type(row.get('index')) is not int or row.get('index') != index
                       or row.get('role') != roles[index] or row.get('status') != 'completed'
                       or row.get('dispatched') is not True
                       or not re.fullmatch(r'[0-9a-f]{64}', str(row.get('output_sha256', '')))
                       for index, row in enumerate(phases))
                or phases[-1]['output_sha256'] != summary['final_output_sha256']
                or expected_hashes + [row['output_sha256'] for row in phases] != summary.get('phase_output_sha256s')):
            raise ValueError('Нет трёх последовательно завершённых проходов с контрольными суммами.')
        applied, charts = validate_applied(plan, parsed.get('_applied_analysis'), evidence, report)
        if applied != summary.get('applied_analysis') or charts != summary.get('comparisons'):
            raise ValueError('Итоговые прикладные данные отличаются от проверенного результата.')
        if parsed.get('_review_dispositions') is None:
            raise ValueError('В итоговом ответе отсутствуют решения по замечаниям.')
        # Source-of-truth summary was produced with all three persisted outputs.
        # Require the same final dispositions; no editorial overlay can waive it.
        normalized = []
        for row in parsed['_review_dispositions']:
            normalized.append({**row, 'resolution_excerpt': row.get('resolution_excerpt', ''),
                               'resolution_evidence_ids': row.get('resolution_evidence_ids', [])})
        if normalized != summary.get('dispositions'):
            raise ValueError('Решения проверяющего отличаются от сохранённой проверки.')
        if plan.get('evidence_bundle') is not None:
            from .evidence_validation import validate_checks
            source_validation = validate_checks(plan, parsed, report, evidence)
            if source_validation != summary.get('source_validation'):
                raise ValueError('Привязки к первоисточникам отличаются от проверенного результата.')
            if source_validation['status'] != 'ready':
                raise ValueError('Привязки к первоисточникам не завершены.')
        result.update(deepcopy(summary))
        result['applied_analysis'], result['comparisons'] = applied, charts
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError) as exc:
        issues.append(str(exc)[:1200] or 'Неполная проверка трёх проходов.')
        if isinstance(summary, dict):
            result['critic'] = deepcopy(summary.get('critic') or {})
            result['dispositions'] = deepcopy(summary.get('dispositions') or [])
            for issue in summary.get('issues', [])[:8] if isinstance(summary.get('issues'), list) else []:
                if isinstance(issue, str) and issue not in issues:
                    issues.append(issue[:1200])
    return result
