"""Read-only depth of a saved study, without a scientific score or new calls.

The current store can record source analysis and bounded Responses API cases.
Neither schema records execution of the technology discussed by a source study.
Separate local lexical benchmark receipts do not validate unrelated reports;
``locally_tested`` remains unavailable for these source-analysis projections.
"""
from collections import Counter
from decimal import Decimal, InvalidOperation
import math
import re


VERSION = 'readiness-v1'
NOTICE = ('Глубина определяется сохранёнными основаниями, а не завершением CLI или '
          'согласием агентов. Внешние числа и ответы Responses не подтверждают '
          'прикладной эффект исследуемой технологии на ваших данных.')
STAGES = {
    'incomplete': 'Данных для разбора недостаточно',
    'source_review': 'Разбор источников',
    'validation_designed': 'Проверка спроектирована',
    'externally_evaluated': 'Внешние результаты описаны',
    'locally_tested': 'Технология проверена локально',
}
_UNKNOWN = {'', 'unknown', 'not_reported', 'not reported', 'not known',
            'неизвестно', 'неизвестен', 'неизвестна', 'неизвестны', 'не указано',
            'не указан', 'не указана', 'не определено', 'нужно уточнить',
            'не определено в отчёте; нужно уточнить.'}
_CONTEXT = {
    'baseline_version': 'версия baseline', 'candidate_version': 'версия кандидата',
    'dataset': 'датасет и его версия', 'evaluation': 'методика оценки',
    'hardware': 'оборудование', 'load': 'нагрузка',
}
_REPRODUCIBILITY = {
    'bounded_execution': 'ограниченный журнал запуска исследуемой технологии',
    'raw_metric_artifacts': 'сырые результаты метрик обеих конфигураций',
    'dataset_version': 'проверочный набор и его версия',
    'baseline_artifact': 'воспроизводимая конфигурация baseline',
    'model_versions': 'версии обеих конфигураций',
    'matching_conditions': 'одинаковые методика, оборудование и нагрузка',
    'held_out_or_goal_check': 'отложенная проверка либо заранее заданный прикладной критерий',
}
_SIMULATED = {'simulation', 'simulated', 'synthetic', 'synthetic_simulation',
              'simulated_not_executed', 'simulation_only'}
_DIMENSIONS = {
    'latency': ('Задержка', {'latency', 'latency_ms', 'latency_p50', 'latency_p95',
                           'latency_p99', 'time_per_request', 'задержка',
                           'время ответа', 'время на запрос'}),
    'cost': ('Стоимость', {'cost', 'cost_usd', 'actual_cost_usd', 'cost_per_request',
                         'cost_per_token', 'стоимость', 'стоимость запроса'}),
    'quality': ('Качество', {'accuracy', 'exact_match', 'precision', 'recall', 'f1',
                           'f1_score', 'pass@1', 'pass_rate', 'success_rate',
                           'error_rate', 'качество', 'точность', 'доля ошибок'}),
}


def _dict(value):
    return value if isinstance(value, dict) else {}


def _rows(value):
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _known(value):
    return isinstance(value, str) and value.strip().casefold() not in _UNKNOWN


def _text(value):
    return value.strip() if _known(value) else None


def _number(value):
    return type(value) in {int, float} and math.isfinite(value) and 0 <= value <= 1e100


def _numbers(text):
    result = set()
    for token in re.findall(r'(?<![\w.,])[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?(?!\w|[.,]\d)', text):
        try:
            number = Decimal(token.replace(',', '.'))
            if number.is_finite():
                result.add(number)
        except InvalidOperation:
            pass
    return result


def _simulation(row):
    return any(str(row.get(key, '')).casefold() in _SIMULATED
               for key in ('origin', 'execution_mode', 'basis', 'validation_mode'))


def _gate(label, required, present, details, *, status=None):
    missing = [field for field in required if field not in present]
    return {'label': label,
            'status': status or ('recorded' if not missing else 'partial' if present else 'missing'),
            'required': list(required), 'missing': missing,
            'missing_labels': [required[field] for field in missing], 'details': details}


def _source_bindings(plan, presentation, evidence):
    """Recheck literal bindings; a saved ready flag alone does not cover a claim."""
    document_rows = _rows(_dict(plan.get('evidence_bundle')).get('documents'))
    document_ids = Counter(row.get('asset_id') for row in document_rows
                           if isinstance(row.get('asset_id'), str))
    documents = {row.get('asset_id'): row for row in document_rows
                 if isinstance(row.get('asset_id'), str) and document_ids[row['asset_id']] == 1}
    evidence_ids = Counter(row.get('id') for row in _rows(presentation.get('evidence'))
                           if isinstance(row.get('id'), str))
    bound, supported = {}, {}
    for check in _rows(_dict(presentation.get('source_validation')).get('checks')):
        ref = check.get('evidence_id')
        document_id = check.get('document_id')
        document = documents.get(document_id) if isinstance(document_id, str) else None
        if (not isinstance(ref, str) or evidence_ids[ref] != 1 or ref not in evidence or not document or
                document.get('status') not in ('captured', 'partial') or
                evidence[ref].get('source_url') != document.get('url')):
            continue
        quote = _text(check.get('quote'))
        matching_segments = [row for row in _rows(document.get('segments'))
                             if isinstance(row.get('id'), str) and row.get('id') == check.get('segment_id')]
        segment = matching_segments[0] if len(matching_segments) == 1 else {}
        if not quote or quote not in str(segment.get('text', '')):
            continue
        bound.setdefault(ref, []).append(check)
        if check.get('relation') == 'supports':
            supported.setdefault(ref, []).append(check)
    return bound, supported, sorted(key for key, count in document_ids.items() if count > 1)


def _value_supported(side, evidence, report, source_support=None):
    if (not _number(side.get('value')) or
            side.get('basis') not in ('author_claim', 'external_measurement') or
            _simulation(side)):
        return False
    refs = side.get('evidence_ids')
    if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) or ref not in evidence for ref in refs):
        return False
    number = Decimal(str(side['value']))
    if source_support is not None:
        return any(number in _numbers(str(check.get('quote', '')))
                   for ref in refs for check in source_support.get(ref, []))
    return any(_known(evidence[ref].get('source_url')) and
               _known(evidence[ref].get('excerpt')) and evidence[ref]['excerpt'] in report and
               number in _numbers(evidence[ref]['excerpt']) for ref in refs)


def _experiments(records, run_id):
    """Summarize only supported records, never promote API/imports to tech tests."""
    from .research_assets import identity
    from .research_experiments import validate_asset
    result = {'recorded_api_cases': 0, 'completed_api_cases': 0,
              'imported_observations': 0, 'simulation_records': 0,
              'unrecognized_experiment_records': 0}
    seen = set()
    for record in _rows(records):
        value = _dict(record.get('payload')) if 'payload' in record else record
        if value.get('run_id') not in (None, run_id):
            continue
        if _simulation(value):
            result['simulation_records'] += 1
            continue
        origin = value.get('origin')
        if origin not in ('executed_api', 'imported_not_executed_here', 'execution_summary'):
            result['unrecognized_experiment_records'] += 1
            continue
        try:
            validate_asset('experiment_observation', value)
            identifier = identity('experiment_observation', value)
            if record.get('id') is not None and record.get('id') != identifier:
                raise ValueError('Identity does not match the record.')
        except (ValueError, TypeError, KeyError, OverflowError):
            result['unrecognized_experiment_records'] += 1
            continue
        if identifier in seen:
            continue
        seen.add(identifier)
        if origin == 'executed_api':
            result['recorded_api_cases'] += 1
            result['completed_api_cases'] += value.get('status') == 'completed'
        elif origin == 'imported_not_executed_here':
            result['imported_observations'] += len(value['observations'])
    return result


def _comparison_dimensions(task, rows, evidence, report, supported):
    dimensions = {key: {'label': label, 'status': 'unknown', 'measurements': [], 'value': None}
                  for key, (label, _) in _DIMENSIONS.items()}
    for row in rows:
        metric = str(row.get('metric', '')).strip().casefold().replace(' ', '_')
        dimension = next((key for key, (_, names) in _DIMENSIONS.items()
                          if metric in names or metric.replace('_', ' ') in names), None)
        if dimension is None or _simulation(row):
            continue
        baseline, candidate = _dict(row.get('baseline')), _dict(row.get('candidate'))
        pair = all(_value_supported(side, evidence, report) for side in (baseline, candidate))
        source_pair = all(_value_supported(side, evidence, report, supported)
                          for side in (baseline, candidate))
        dimensions[dimension]['measurements'].append({
            'row_id': row.get('id'), 'metric': row.get('metric'),
            'definition': _text(row.get('definition')), 'unit': _text(row.get('unit')),
            'baseline': {'label': _text(baseline.get('label')), 'basis': _text(baseline.get('basis')),
                         'value': baseline.get('value') if _number(baseline.get('value')) else None},
            'candidate': {'label': _text(candidate.get('label')), 'basis': _text(candidate.get('basis')),
                          'value': candidate.get('value') if _number(candidate.get('value')) else None},
            'conditions': _text(row.get('conditions')),
            'measurement_context': {key: _text(_dict(row.get('measurement_context')).get(key))
                                    for key in _CONTEXT},
            'comparability': row.get('comparability', 'unknown'),
            'chart_eligible': pair and source_pair and row.get('comparability') == 'comparable' and
                              all(_known(_dict(row.get('measurement_context')).get(key)) for key in _CONTEXT),
            'source_bound_pair': source_pair, 'origin': 'stored_source_analysis',
            'verification': 'reported_not_independently_verified',
        })
        dimensions[dimension]['status'] = 'recorded'
    self_hosted = _dict(task.get('self_hosted'))
    fields = {key: _text(self_hosted.get(key)) for key in (
        'model', 'runtime', 'cpu', 'ram', 'gpu', 'vram', 'disk', 'context',
        'concurrency', 'dependencies', 'operations', 'license', 'cost')}
    dimensions['infrastructure'] = {
        'label': 'Инфраструктура', 'status': 'recorded' if any(fields.values()) else 'unknown',
        'value': None, 'fields': fields, 'origin': 'owner_task_context',
        'basis': self_hosted.get('evidence_level', 'unknown'),
        'source_url': _text(self_hosted.get('evidence_url')),
        'notice': 'Записанные требования задачи; оборудование и полная стоимость локально не проверены.',
    }
    return dimensions


def assess(run, presentation, measurements=None, experiment_observations=None):
    """Derive JSON-safe readiness from snapshots; never mutate, execute or fetch.

    Optional experiment records are caller-selected context. Current experiment
    plans have no study/run link, so these records never establish claim coverage.
    Legacy reports remain source reviews, without rewriting their approvals.
    """
    run, presentation = _dict(run), _dict(presentation)
    plan = _dict(run.get('plan'))
    task = _dict(_dict(plan.get('study_context')).get('task'))
    rows = _rows(_dict(presentation.get('applied_analysis')).get('rows'))
    evidence = {row['id']: row for row in _rows(presentation.get('evidence'))
                if isinstance(row.get('id'), str)}
    # Numbers occurring only inside an attached JSON block are not report prose.
    from .presentation import display_report
    report = display_report(run.get('output', '')) if isinstance(run.get('output'), str) else ''
    bound, supported, ambiguous_documents = _source_bindings(plan, presentation, evidence)
    evidence_counts = Counter(row.get('id') for row in _rows(presentation.get('evidence'))
                              if isinstance(row.get('id'), str))
    ambiguous_evidence = sorted(key for key, count in evidence_counts.items() if count > 1)
    report_backed = {ref for ref, row in evidence.items() if _known(row.get('excerpt')) and
                     row['excerpt'] in report and _known(row.get('source_url'))}
    task_required = {'applied_task_type': 'прикладной тип задачи', 'business_goal': 'рабочая цель',
                     'inputs': 'входные данные', 'expected_output': 'проверяемый результат'}
    present_task = {key for key in task_required if _known(task.get(key))}
    if _known(task.get('task_type')) and task['task_type'] != 'exploratory':
        present_task.add('applied_task_type')
    baseline = _dict(task.get('baseline'))
    baseline_required = {'name': 'решение для сравнения', 'version': 'версия решения для сравнения'}
    present_baseline = {key for key in baseline_required if _known(baseline.get(key))}
    metrics = _rows(task.get('metrics'))
    metric_required = {'definitions': 'метрики с определением, единицей и направлением',
                       'acceptance_criteria': 'заранее заданный критерий успеха'}
    present_metrics = set()
    if metrics and all(all(_known(row.get(key)) for key in ('name', 'definition', 'unit')) and
                       row.get('direction') in ('minimize', 'maximize', 'descriptive') for row in metrics):
        present_metrics.add('definitions')
    if _known(task.get('success_criteria')) or (metrics and all(_known(row.get('target')) for row in metrics)):
        present_metrics.add('acceptance_criteria')
    missing_context = set(_CONTEXT)
    if rows:
        missing_context = {key for key in _CONTEXT if any(
            not _known(_dict(row.get('measurement_context')).get(key)) for row in rows)}
    gates = {
        'task': _gate('Прикладная задача', task_required, present_task,
                      'Проверяется явная постановка задачи в сохранённом плане; общий обзор не означает прикладную проверку.'),
        'baseline': _gate('Baseline', baseline_required, present_baseline,
                          'Baseline и его версия должны быть заданы для рабочей задачи; название в чужом графике не заменяет этот выбор.'),
        'metrics': _gate('Метрики и критерий успеха', metric_required, present_metrics,
                         'Цели и ожидаемые значения описывают проверку, а не её результат.'),
        'conditions': _gate('Условия сравнения', _CONTEXT, set(_CONTEXT) - missing_context,
                            'Учитываются только структурированные условия каждой строки; совпадение условий и переносимость независимо не проверены.'),
        'evidence': _gate('Основания утверждений', {
            'explicit_claims': 'явные утверждения с источниками',
            'report_excerpts': 'дословные основания в сохранённом отчёте',
            'original_bindings': 'привязки к конкретным сегментам оригинала'},
            ({'explicit_claims'} if evidence and not ambiguous_evidence else set()) |
            ({'report_excerpts'} if evidence and len(report_backed) == len(evidence) else set()) |
            ({'original_bindings'} if evidence and len(bound) == len(evidence) else set()),
            'Привязка к цитате фиксирует происхождение. Оценка supports остаётся суждением модели, а не независимой проверкой истинности.' +
            (' Повторяются ID источников; неоднозначные привязки не засчитаны.' if ambiguous_documents else '') +
            (' Повторяются ID утверждений; неоднозначные привязки не засчитаны.' if ambiguous_evidence else '')),
        'execution': _gate('Выполнение прикладной проверки', {'technology_execution': 'журнал реального запуска исследуемой технологии'},
                           set(), 'У выбранного отчёта нет связанного журнала запуска исследуемой технологии. Отдельная CPU-проверка поиска не подтверждает выводы этого отчёта.',
                           status='not_executed'),
        'reproducibility': _gate('Воспроизводимость прикладного результата', _REPRODUCIBILITY,
                                 set(), 'Нужны связанные сырые артефакты обеих конфигураций и общие условия. Статус completed и текстовый рецепт их не создают.'),
    }
    pairs = [row for row in rows if not _simulation(row) and
             all(_value_supported(_dict(row.get(side)), evidence, report)
                 for side in ('baseline', 'candidate'))]
    source_pairs = [row for row in pairs if row.get('comparability') == 'comparable' and
                    all(_value_supported(_dict(row.get(side)), evidence, report, supported)
                        for side in ('baseline', 'candidate'))]
    contract = _dict(_dict(plan.get('research_protocol')).get('validation_contract'))
    design_fields = ('task', 'baseline', 'measurable_metrics', 'conditions',
                     'expected_artifact', 'minimal_falsifying_check', 'acceptance_criteria')
    design_missing = [key for key in design_fields if not contract.get(key) or
                      (isinstance(contract.get(key), str) and not _known(contract[key]))]
    design_missing.extend('missing_input.' + item for item in contract.get('missing_inputs', [])
                          if isinstance(item, str))
    designed = (contract.get('version') == 'applied-validation-v1' and not design_missing and
                all(gates[key]['status'] == 'recorded' for key in ('task', 'baseline', 'metrics', 'conditions')))
    stage = 'source_review' if report.strip() or evidence or rows else 'incomplete'
    if designed:
        stage = 'validation_designed'
    if source_pairs and all(gates[key]['status'] == 'recorded'
                            for key in ('task', 'baseline', 'metrics', 'conditions', 'evidence')):
        stage = 'externally_evaluated'
    registry = []
    for record in _rows(measurements):
        value = _dict(record.get('payload')) if 'payload' in record else record
        if value.get('run_id') == run.get('id'):
            registry.append(value)
    reported_values = [_dict(row.get(side)) for row in rows for side in ('baseline', 'candidate')]
    provenance = {
        'stored_source_analysis': sum(row.get('origin') == 'stored_source_analysis' for row in registry),
        'author_claim_values': sum(_number(row.get('value')) and row.get('basis') == 'author_claim' for row in reported_values),
        'external_reported_values': sum(_number(row.get('value')) and row.get('basis') == 'external_measurement' for row in reported_values),
        'simulated_comparison_rows': sum(_simulation(row) for row in rows),
        **_experiments(experiment_observations, run.get('id')),
        'executed_technology_tests': 0, 'independently_verified': False,
        'empirical_technology_validation': False, 'local_testing_supported': False,
        'experiment_linkage': 'caller_selected_context_not_claim_validation',
        'notice': 'author_claim и external_measurement — происхождение внешних чисел. Импорт, симуляция и API кейсы не являются локальным тестом технологии.',
    }
    next_actions = [{'gate': key, 'action': 'Зафиксировать: ' + '; '.join(gate['missing_labels']) + '.',
                     'missing': list(gate['missing'])} for key, gate in gates.items()
                    if gate['missing'] and key not in {'execution', 'reproducibility'}]
    next_actions.append({'gate': 'execution',
                         'action': 'Подготовить ограниченную проверку baseline и кандидата на общих данных с сырыми метриками, версиями, оборудованием и нагрузкой; затем отдельно выполнить её.',
                         'missing': list(_REPRODUCIBILITY)})
    return {
        'version': VERSION, 'run_id': run.get('id'), 'stage': stage, 'state': stage,
        'label': STAGES[stage], 'gates': gates,
        'gate_counts': {status: sum(gate['status'] == status for gate in gates.values())
                        for status in ('recorded', 'partial', 'missing', 'not_executed')},
        'claim_coverage': {'scope': 'explicit_evidence_claims_only', 'total': len(evidence),
                           'report_backed': len(report_backed), 'source_backed': len(bound),
                           'supported_by_source': len(supported),
                           'unbound': len(set(evidence) - set(bound)),
                           'unstructured_findings': len(presentation.get('findings', [])) if isinstance(presentation.get('findings'), list) else 0,
                           'missing_evidence_ids': sorted(set(evidence) - set(bound)),
                           'required_evidence_ids': sorted(evidence),
                           'ambiguous_evidence_ids': ambiguous_evidence,
                           'ambiguous_document_ids': ambiguous_documents,
                           'notice': 'Счётчик относится только к явному реестру evidence; все утверждения свободного текста не подсчитаны.'},
        'external_results': {'reported_pairs': len(pairs), 'source_bound_pairs': len(source_pairs),
                             'verification': 'reported_not_independently_verified'},
        'validation_design': {'version': contract.get('version'),
                              'status': 'described' if designed else 'incomplete',
                              'primary_route': contract.get('primary_route'),
                              'missing': design_missing,
                              'notice': 'Замороженное задание на проверку; маршрут и критерии не являются результатом выполнения.'},
        'provenance': provenance,
        'comparison_dimensions': _comparison_dimensions(task, rows, evidence, report, supported),
        'last_step': {'status': 'not_executed', 'label': 'Прикладная проверка ещё не выполнена',
                      'required': list(_REPRODUCIBILITY),
                    'notice': 'Отдельные API-кейсы или CPU-проверка поиска не подтверждают автоматически технологию из этого отчёта.'},
        'next_actions': next_actions, 'notice': NOTICE,
    }
