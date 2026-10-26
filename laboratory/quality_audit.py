"""Read-only deterministic audit of saved source-analysis evidence.

Pass means an observable record check passed, never that a scientific claim is
true. No model, capture, network, subprocess, store write, or approval occurs.
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib

VERSION = 'saved-quality-audit-v1'
STATUSES = ('pass', 'needs_review', 'not_applicable')
NOTICE = ('Аудит проверяет сохранённые основания, числовые привязки, условия и решения критика. '
          'Он не устанавливает научную истинность, подлинность издателя или переносимость и не одобряет публикацию.')
_CONTEXT = ('baseline_version', 'candidate_version', 'dataset', 'evaluation', 'hardware', 'load')
_BINDING_FIELDS = ('evidence_id', 'document_id', 'segment_id', 'quote', 'relation', 'reason')


def _dict(value):
    return value if isinstance(value, dict) else {}


def _list(value):
    return value if isinstance(value, list) else []


def _text(value):
    return value.strip() if isinstance(value, str) else ''


def _sections(data, key):
    for section in _list(data.get('story')):
        if isinstance(section, dict) and section.get('id') == key:
            return [_text(item) for item in _list(section.get('items')) if _text(item)]
    return [_text(item) for item in _list(data.get(key)) if _text(item)]


def _finding(rows, identifier, facet, status, pointer, detail, severity='major', category='record_consistency'):
    rows.append({'id': identifier, 'facet': facet, 'status': status,
                 'severity': severity if status == 'needs_review' else 'info',
                 'category': category, 'evidence_pointer': pointer, 'detail': detail})


def _gate(run, data):
    for candidate, pointer in ((data.get('agent_review'), '/presentation/agent_review'),
                               (run.get('agent_review'), '/run/agent_review'),
                               (_dict(_dict(run.get('raw')).get('orchestration')).get('review'),
                                '/run/raw/orchestration/review')):
        if isinstance(candidate, dict) and candidate:
            return candidate, pointer
    return {}, '/presentation/agent_review'


def audit_saved_quality(run, presentation=None, review=None):
    """Return JSON-safe findings with pointers into {run,presentation,review}.

    Omitted presentation is built from saved input locally. Supplied metadata is
    not trusted as scientific evidence: original bindings are checked again.
    """
    from .presentation import build_presentation, display_report, _clean, _public_url, _literal_numbers
    from .evidence_validation import validate_checks
    from .applied_analysis import validate_applied

    run = _dict(run)
    findings = []
    if presentation is None:
        try:
            presentation = build_presentation(run, review)
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError):
            presentation = {}
    data, plan = _dict(presentation), _dict(run.get('plan'))
    output = run.get('output') if isinstance(run.get('output'), str) else ''
    report = display_report(output)
    gate, gate_pointer = _gate(run, data)
    protocol = _dict(plan.get('research_protocol'))
    modern = protocol.get('version') in ('three-pass-v2', 'three-pass-v3', 'three-pass-v4', 'editor-resume-v1')
    completed = bool(report.strip()) and run.get('status') == 'completed'
    _finding(findings, 'format.saved_report', 'format',
             'pass' if completed else 'needs_review', '/run/output',
             'Сохранён завершённый ответ.' if completed else 'Нет завершённого сохранённого ответа.',
             category='format_validation')
    publication = _dict(data.get('publication_checks'))
    format_ready = publication.get('status') == 'ready' and isinstance(publication.get('issues'), list) and not publication['issues']
    _finding(findings, 'format.publication', 'format', 'pass' if format_ready else 'needs_review',
             '/presentation/publication_checks', 'Сохранённые проверки формата пройдены; это не научная оценка.' if format_ready
             else 'Проверки формата отсутствуют либо содержат незакрытые замечания.', category='format_validation')

    evidence = _list(data.get('evidence'))
    by_id = {row.get('id'): row for row in evidence if isinstance(row, dict) and isinstance(row.get('id'), str)}
    normalized_report = _clean(report)
    report_hash = hashlib.sha256(report.encode('utf-8')).hexdigest()
    provenance = _dict(data.get('provenance'))
    provenance_ok = bool(evidence) and len(by_id) == len(evidence) and provenance.get('report_sha256') == report_hash
    _finding(findings, 'facts.registry', 'facts', 'pass' if provenance_ok else 'needs_review', '/presentation/provenance',
             'Реестр доказательств и хеш относятся к сохранённому основному тексту.' if provenance_ok else
             'Нет непустого уникального реестра доказательств либо хеш основного текста отсутствует/отличается.')
    known_urls = {row['url'] for row in _list(plan.get('sources')) if isinstance(row, dict) and isinstance(row.get('url'), str)}
    known_urls.update(row['source_url'] for row in _list(_dict(gate.get('critic')).get('checked_sources'))
                      if isinstance(row, dict) and isinstance(row.get('source_url'), str))
    for index, row in enumerate(evidence):
        row = _dict(row)
        url, excerpt = _text(row.get('source_url')), _text(row.get('excerpt'))
        linked = bool(_text(row.get('claim')) and excerpt and _clean(excerpt) in normalized_report
                      and _public_url(url) and url in report and url in known_urls)
        _finding(findings, 'facts.report_binding.' + str(index), 'facts', 'pass' if linked else 'needs_review',
                 '/presentation/evidence/' + str(index), 'Утверждение привязано к цитате отчёта и известному публичному URL; истинность не проверена.'
                 if linked else 'Нет полной связки утверждение → цитата отчёта → известный публичный источник.')

    assessment = _dict(data.get('source_validation') or gate.get('source_validation'))
    assessment_pointer = '/presentation/source_validation' if data.get('source_validation') else gate_pointer + '/source_validation'
    checks = _list(assessment.get('checks'))
    applied = _dict(data.get('applied_analysis') or gate.get('applied_analysis'))
    raw_checks = [{key: row.get(key) for key in _BINDING_FIELDS} for row in checks if isinstance(row, dict)]
    recomputed = {'status': 'incomplete', 'checks': [], 'issues': []}
    if modern and assessment:
        recomputed = validate_checks(plan, {'_evidence_checks': raw_checks, '_applied_analysis': applied}, report, evidence)
    bound = bool(evidence and checks and assessment.get('status') == 'ready' and recomputed.get('status') == 'ready')
    _finding(findings, 'sources.original_binding', 'sources', 'pass' if bound else 'needs_review',
             assessment_pointer, 'Цитаты повторно найдены в указанных сохранённых сегментах с теми же URL; это проверка привязки.'
             if bound else 'Нет полной повторно проверяемой привязки к сохранённым оригиналам; ссылка или ready сами по себе недостаточны.')
    documents = _list(_dict(plan.get('evidence_bundle')).get('documents'))
    unread = []
    for index, document in enumerate(documents):
        document = _dict(document)
        if document.get('url') not in [row.get('source_url') for row in by_id.values()]:
            continue
        readable = document.get('status') in ('captured', 'partial') and bool(document.get('segments'))
        if not readable:
            unread.append(index)
            _finding(findings, 'sources.unread.' + str(index), 'sources', 'needs_review',
                     '/run/plan/evidence_bundle/documents/' + str(index), 'У цитируемого документа нет читаемых сохранённых сегментов; чтение оригинала не установлено.')
    for index, check in enumerate(checks):
        if isinstance(check, dict) and check.get('relation') in ('contradicts', 'insufficient'):
            _finding(findings, 'facts.source_relation.' + str(index), 'facts', 'needs_review',
                     assessment_pointer + '/checks/' + str(index),
                     'Сохранённая модельная оценка отмечает противоречие или недостаточную опору; научный вердикт автоматически не выводится.')

    applied_ok, charts = False, []
    if applied:
        try:
            _, charts = validate_applied(plan, applied, evidence, report)
            applied_ok = True
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError):
            pass
    rows = _list(applied.get('rows'))
    comparisons = _list(data.get('comparisons'))
    numeric_rows = [(index, row) for index, row in enumerate(rows) if isinstance(row, dict)
                    and any(_dict(row.get(side)).get('value') is not None for side in ('baseline', 'candidate'))]
    if not rows and not comparisons:
        explained = bool(_list(applied.get('unknowns')) or _text(data.get('numeric_note')))
        _finding(findings, 'numbers.no_pair', 'numbers', 'not_applicable' if explained else 'needs_review',
                 '/presentation/applied_analysis/unknowns', 'Численной пары нет; причина сохранена. Схема механизма допустима без графика эффективности.'
                 if explained else 'Численной пары нет, но причина отсутствия данных явно не сохранена.')
    elif not applied_ok:
        _finding(findings, 'numbers.applied_schema', 'numbers', 'needs_review', '/presentation/applied_analysis',
                 'Прикладные числа/основания не проходят существующую проверку; готовность формата не заменяет её.')
    for index, row in numeric_rows:
        for side in ('baseline', 'candidate'):
            value = _dict(row.get(side)).get('value')
            if value is None:
                continue
            refs = _list(_dict(row.get(side)).get('evidence_ids'))
            literals = _literal_numbers(' '.join(_text(by_id.get(ref, {}).get('excerpt')) for ref in refs if isinstance(ref, str)))
            try:
                literal = type(value) in {int, float} and Decimal(str(value)) in literals
            except (InvalidOperation, TypeError, ValueError):
                literal = False
            original = bound and any(check.get('evidence_id') in refs and check.get('relation') == 'supports'
                                     and Decimal(str(value)) in _literal_numbers(_text(check.get('quote')))
                                     for check in recomputed.get('checks', [])) if literal else False
            _finding(findings, 'numbers.binding.' + str(index) + '.' + side, 'numbers',
                     'pass' if literal and original else 'needs_review',
                     '/presentation/applied_analysis/rows/' + str(index) + '/' + side,
                     'Число присутствует в связанной цитате отчёта и сохранённого оригинала; его смысл и измерение независимо не подтверждены.'
                     if literal and original else 'Число не имеет повторно проверенной дословной опоры в связанном отчёте и оригинале.', severity='blocker')

    def chart_key(row):
        return tuple(row.get(key) for key in ('label', 'unit', 'baseline_label', 'baseline_value', 'result_label', 'result_value', 'conditions'))
    accepted = {chart_key(row): set(row.get('evidence_ids', [])) for row in charts}
    for index, comparison in enumerate(comparisons):
        comparison = _dict(comparison)
        try:
            matches = chart_key(comparison) in accepted and set(comparison.get('evidence_ids', [])) == accepted[chart_key(comparison)]
        except (TypeError, ValueError):
            matches = False
        _finding(findings, 'comparability.chart.' + str(index), 'comparability', 'pass' if matches else 'needs_review',
                 '/presentation/comparisons/' + str(index), 'График точно соответствует разрешённой прикладной строке, единице, условиям и ссылкам.'
                 if matches else 'График не соответствует сопоставимой прикладной строке и её условиям/основаниям.', severity='blocker')
    for index, row in enumerate(rows):
        row = _dict(row)
        if row.get('comparability') in ('unknown', 'not_comparable'):
            _finding(findings, 'comparability.context.' + str(index), 'comparability',
                     'pass' if applied_ok and _text(row.get('comparability_reason')) else 'needs_review',
                     '/presentation/applied_analysis/rows/' + str(index) + '/comparability',
                     'Несопоставимость/неизвестность явно сохранена; такая строка не даёт права ранжировать результаты.')
        else:
            context = _dict(row.get('measurement_context'))
            complete = applied_ok and all(_text(context.get(key)) for key in _CONTEXT)
            _finding(findings, 'comparability.context.' + str(index), 'comparability', 'pass' if complete else 'needs_review',
                     '/presentation/applied_analysis/rows/' + str(index) + '/measurement_context',
                     'Версии, датасет, оценка, оборудование и нагрузка явно записаны; эквивалентность методик независимо не проверена.'
                     if complete else 'Для объявленной сопоставимости не записаны все структурированные условия измерения.')

    fields = ('problem', 'audience', 'use_case', 'public_takeaway', 'next_step')
    usable = all(_text(data.get(key)) and data[key] != 'Не определено в отчёте; нужно уточнить.' for key in fields)
    usable = usable and bool(_sections(data, 'limitations'))
    _finding(findings, 'applicability.recorded', 'applicability', 'pass' if usable else 'needs_review', '/presentation/story',
             'Задача, адресат, сценарий, границы и следующий шаг явно записаны; применимость на практике ещё не подтверждена.'
             if usable else 'Отсутствует явная задача, адресат, сценарий, вывод, следующий шаг либо границы применения.')
    resources = _sections(data, 'resources')
    unknowns = [_text(item) for item in _list(applied.get('unknowns')) if _text(item)]
    self_hosted = _dict(_dict(_dict(plan.get('study_context')).get('task')).get('self_hosted'))
    markers = ('неизвест', 'не определ', 'нужно уточ', 'не указан', 'unknown', 'not reported', 'not known')
    resource_words = ('self-host', 'hardware', 'cost', 'license', 'gpu', 'cpu', 'ram', 'vram',
                      'оборуд', 'ресурс', 'стоим', 'цен', 'лицен', 'развёрт', 'разверт', 'памят')
    explicit_unknown = any(word in ' '.join(resources).casefold() for word in markers)
    explicit_unknown = explicit_unknown or any(any(word in item.casefold() for word in markers)
                                               and any(word in item.casefold() for word in resource_words) for item in unknowns)
    if self_hosted.get('availability') == 'not_applicable':
        self_status, self_detail = 'not_applicable', 'В выбранной задаче self-hosted явно отмечен неприменимым; это не оценка доступности продукта.'
    elif resources and explicit_unknown:
        self_status, self_detail = 'pass', 'Ресурсы и конкретная неизвестность явно сохранены; отсутствующие затраты/оборудование не превращены в подтверждённую пригодность.'
    else:
        self_status, self_detail = 'needs_review', 'Не сохранены явные ресурсы и пробелы self-hosted/полной стоимости; наличие текста не подтверждает пригодность оборудования.'
    _finding(findings, 'self_hosted.unknowns', 'self_hosted', self_status, '/presentation/applied_analysis/unknowns', self_detail)

    critic = _dict(gate.get('critic'))
    issues, dispositions = _list(critic.get('issues')), _list(gate.get('dispositions'))
    if critic.get('version') != 'critic-review-v1' or not isinstance(critic.get('issues'), list):
        _finding(findings, 'critic.coverage', 'critic', 'needs_review' if protocol else 'not_applicable', gate_pointer + '/critic',
                 'Пакет критика не сохранён; отсутствие замечаний не приписано проверке.')
    elif not issues:
        _finding(findings, 'critic.coverage', 'critic', 'pass', gate_pointer + '/critic/issues',
                 'Сохранён явный пустой список замечаний критика; согласие модели не доказывает истинность.')
    for index, issue in enumerate(issues):
        issue = _dict(issue)
        matching = [row for row in dispositions if isinstance(row, dict) and row.get('issue_id') == issue.get('id')]
        disposition = matching[0] if len(matching) == 1 else {}
        excerpt = _text(disposition.get('resolution_excerpt'))
        observable = bool(excerpt and excerpt in report and _text(disposition.get('reason')))
        resolved = disposition.get('status') in ('fixed', 'retained_with_limit') and observable
        if issue.get('severity') == 'blocker':
            resolved = resolved and disposition.get('status') == 'fixed' and len(_text(disposition.get('reason'))) >= 25
        _finding(findings, 'critic.disposition.' + str(index), 'critic', 'pass' if resolved else 'needs_review',
                 gate_pointer + '/critic/issues/' + str(index),
                 'Есть ровно одно решение с дословным наблюдаемым исправлением/ограничением; научная достаточность не установлена.'
                 if resolved else 'Замечание не закрыто ровно одним наблюдаемым исправлением; статус fixed без фрагмента не считается доказательством.',
                 severity=issue.get('severity') if issue.get('severity') in ('minor', 'major', 'blocker') else 'major')
    known_issues = {row['id'] for row in issues if isinstance(row, dict) and isinstance(row.get('id'), str)}
    if any(not isinstance(row, dict) or not isinstance(row.get('issue_id'), str) or row['issue_id'] not in known_issues for row in dispositions):
        _finding(findings, 'critic.orphan_disposition', 'critic', 'needs_review', gate_pointer + '/dispositions',
                 'Есть решение без соответствующего сохранённого замечания.')
    if protocol:
        gate_bound = gate.get('status') == 'ready' and gate.get('final_output_sha256') == hashlib.sha256(output.encode('utf-8')).hexdigest()
        _finding(findings, 'critic.saved_gate', 'critic', 'pass' if gate_bound else 'needs_review', gate_pointer,
                 'Сохранённая машинная проверка связана с текущим финальным ответом.' if gate_bound
                 else 'Обязательная машинная проверка не готова либо не связана с текущим финальным ответом.')
    _finding(findings, 'scope.scientific_truth', 'scientific_ground_truth', 'not_applicable', '/run/output', NOTICE,
             category='scientific_scope')
    level = ('original_segments_bound' if bound and not unread else 'missing_or_unread' if unread or not evidence else 'saved_report_only')
    labels = {'original_segments_bound': 'Цитаты связаны с сохранёнными сегментами; подлинность и истинность не проверены',
              'saved_report_only': 'Опора в сохранённом отчёте; привязка к оригиналу не завершена',
              'missing_or_unread': 'Нет читаемого полного основания для используемых утверждений'}
    counts = {status: sum(row['status'] == status for row in findings) for status in STATUSES}
    return {'version': VERSION, 'scope': 'saved_source_analysis', 'run_id': _text(run.get('id')),
            'independent_verification': False, 'publication_approved': False,
            'status_meaning': 'pass означает только успешные применимые проверки сохранённой записи; это не научный рейтинг',
            'overall_status': 'needs_review' if counts['needs_review'] else 'pass',
            'source_provenance': {'level': level, 'label': labels[level], 'independently_verified': False},
            'findings': findings, 'counts': counts, 'notice': NOTICE}


def summarize_audits(audits):
    """Aggregate observable findings, without scores, ranking, or approval."""
    audits = [audit for audit in _list(audits) if isinstance(audit, dict) and audit.get('version') == VERSION]
    return {'version': VERSION, 'scope': 'saved_source_analysis', 'independent_verification': False,
            'run_count': len(audits),
            'status_counts': {status: sum(audit.get('overall_status') == status for audit in audits) for status in STATUSES},
            'finding_counts': {status: sum(_dict(audit.get('counts')).get(status, 0) for audit in audits) for status in STATUSES},
            'needs_review_run_ids': [audit.get('run_id', '') for audit in audits if audit.get('overall_status') == 'needs_review'],
            'notice': NOTICE}


def _control_fixture():
    """TEST_ONLY synthetic frozen projection; no real report or asset is stored."""
    text = 'TEST_ONLY: Latency is 10 ms for baseline and 8 ms for candidate.'
    url = 'https://example.org/TEST_ONLY-primary'
    output = text + '\n' + url
    digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
    document_id = hashlib.sha256(('TEST_ONLY-document:' + text).encode('utf-8')).hexdigest()
    document = {'asset_id': document_id, 'document_id': document_id, 'source_id': 'TEST_ONLY-source',
                'url': url, 'kind': 'supplied_text', 'origin': 'supplied', 'status': 'captured', 'sha256': digest,
                'segments': [{'id': 's1', 'locator': 'TEST_ONLY paragraph', 'text': text}], 'limitations': []}
    row = {'id': 'm1', 'metric': 'Latency', 'definition': 'TEST_ONLY time per request', 'unit': 'ms', 'direction': 'minimize',
           'baseline': {'label': 'Baseline', 'value': 10, 'basis': 'author_claim', 'evidence_ids': ['e1']},
           'candidate': {'label': 'Candidate', 'value': 8, 'basis': 'author_claim', 'evidence_ids': ['e1']},
           'conditions': 'TEST_ONLY same model, dataset and workload', 'comparability': 'comparable',
           'comparability_reason': 'TEST_ONLY same declared protocol',
           'measurement_context': {key: 'TEST_ONLY recorded ' + key for key in _CONTEXT}}
    check = {'evidence_id': 'e1', 'document_id': document_id, 'segment_id': 's1', 'quote': text,
             'relation': 'supports', 'reason': 'TEST_ONLY recorded literal latency pair'}
    run = {'id': 'TEST_ONLY-supported', 'status': 'completed', 'output': output,
           'plan': {'sources': [{'id': 'TEST_ONLY-source', 'url': url, 'text': text}],
                    'research_protocol': {'version': 'three-pass-v3'},
                    'evidence_bundle': {'version': 'source-bundle-v1', 'documents': [document], 'limitations': []}}}
    data = {'title': 'TEST_ONLY source analysis', 'problem': 'TEST_ONLY slow requests', 'audience': 'TEST_ONLY builders',
            'use_case': 'TEST_ONLY source comparison', 'public_takeaway': 'TEST_ONLY test one workload', 'next_step': 'TEST_ONLY choose the dataset',
            'evidence': [{'id': 'e1', 'claim': 'TEST_ONLY reported latency', 'source_url': url, 'excerpt': text}],
            'provenance': {'mode': 'model_structured', 'report_sha256': hashlib.sha256(output.encode('utf-8')).hexdigest()},
            'publication_checks': {'status': 'ready', 'issues': [], 'numeric_data': 'supported'},
            'source_validation': {'status': 'ready', 'checks': [check]},
            'applied_analysis': {'version': 'applied-comparison-v1', 'rows': [row], 'analogues': [], 'unknowns': ['TEST_ONLY hardware and total cost unknown']},
            'comparisons': [{'label': 'Latency', 'unit': 'ms', 'baseline_label': 'Baseline', 'baseline_value': 10,
                             'result_label': 'Candidate', 'result_value': 8, 'conditions': row['conditions'], 'evidence_ids': ['e1']}],
            'story': [{'id': 'limitations', 'items': ['TEST_ONLY transfer not evaluated']},
                      {'id': 'resources', 'items': ['TEST_ONLY hardware and total cost unknown']}],
            'agent_review': {'status': 'ready', 'final_output_sha256': hashlib.sha256(output.encode('utf-8')).hexdigest(),
                             'critic': {'version': 'critic-review-v1', 'issues': []}, 'dispositions': []}}
    return run, data


def control_corpus():
    """Ten in-memory TEST_ONLY cases with measurable expected detections."""
    cases = []
    def add(identifier, mutate, expected):
        run, data = deepcopy(_control_fixture())
        mutate(run, data)
        run['id'] = identifier
        cases.append({'id': identifier, 'test_only': True, 'run': run, 'presentation': data, 'expected': expected})
    add('TEST_ONLY-supported-numbers', lambda r, p: None,
        {'numbers.binding.0.baseline': 'pass', 'numbers.binding.0.candidate': 'pass', 'sources.original_binding': 'pass'})
    add('TEST_ONLY-number-not-in-quote', lambda r, p: p['applied_analysis']['rows'][0]['candidate'].update(value=7),
        {'numbers.binding.0.candidate': 'needs_review'})
    add('TEST_ONLY-conditions-mismatch', lambda r, p: p['applied_analysis']['rows'][0].update(comparability='not_comparable', comparability_reason='TEST_ONLY different datasets'),
        {'comparability.chart.0': 'needs_review'})
    add('TEST_ONLY-missing-primary', lambda r, p: r['plan']['evidence_bundle'].update(documents=[]),
        {'sources.original_binding': 'needs_review'})
    def unread(run, data):
        run['plan']['evidence_bundle']['documents'][0].update(status='unparseable', segments=[])
    add('TEST_ONLY-unread-text', unread, {'sources.unread.0': 'needs_review', 'sources.original_binding': 'needs_review'})
    def critic(run, data, status):
        data['agent_review']['critic']['issues'] = [{'id': 'i1', 'severity': 'blocker', 'problem': 'TEST_ONLY unsupported improvement'}]
        data['agent_review']['dispositions'] = [{'issue_id': 'i1', 'status': status, 'reason': 'TEST_ONLY requires explicit evidence for improvement'}]
    add('TEST_ONLY-unresolved-critic', lambda r, p: critic(r, p, 'unresolved'), {'critic.disposition.0': 'needs_review'})
    add('TEST_ONLY-unobservable-fixed', lambda r, p: critic(r, p, 'fixed'), {'critic.disposition.0': 'needs_review'})
    def mechanism(run, data):
        data['applied_analysis'].update(rows=[], unknowns=['TEST_ONLY no measured baseline/result pair'])
        data['comparisons'] = []
        data['publication_checks']['numeric_data'] = 'not_provided'
    add('TEST_ONLY-mechanism-no-pair', mechanism, {'numbers.no_pair': 'not_applicable', 'sources.original_binding': 'pass'})
    add('TEST_ONLY-self-host-unknown', lambda r, p: None, {'self_hosted.unknowns': 'pass'})
    add('TEST_ONLY-assessment-missing', lambda r, p: p.pop('source_validation'), {'sources.original_binding': 'needs_review'})
    return cases


def run_control_corpus():
    """Return expected/observed matches; this measures detectors, not science."""
    results = []
    for case in control_corpus():
        audit = audit_saved_quality(case['run'], case['presentation'])
        statuses = {row['id']: row['status'] for row in audit['findings']}
        observed = {identifier: statuses.get(identifier, 'missing') for identifier in case['expected']}
        results.append({'id': case['id'], 'test_only': True, 'expected': case['expected'], 'observed': observed,
                        'matched': observed == case['expected']})
    return {'version': VERSION, 'test_only': True, 'case_count': len(results),
            'matched_case_count': sum(row['matched'] for row in results), 'cases': results,
            'notice': 'TEST_ONLY: измеряется обнаружение заданных дефектов, не научная точность реальных исследований.'}
