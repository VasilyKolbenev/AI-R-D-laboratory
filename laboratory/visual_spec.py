"""Deterministic visual choices over saved evidence; no execution or fetching.

Preferred engines describe suitable representations, not installed integrations.
Readiness remains the authoritative gate for numeric comparisons.
"""
from copy import deepcopy
import hashlib
import json
import math
import re


VERSION = 'visual-spec-v1'
READ_ORDER = ['task', 'main_figure', 'comparison', 'applicability', 'evidence']
_ID = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,39}\Z')
_HEX = re.compile(r'[0-9a-f]{64}\Z')
_MEASURED = {'author_claim', 'external_measurement'}


def _dict(value):
    return value if isinstance(value, dict) else {}


def _rows(value, limit=1000):
    return [row for row in value[:limit] if isinstance(row, dict)] if isinstance(value, list) else []


def _number(value):
    return type(value) in (int, float) and 0 <= value <= 1e100 and math.isfinite(value)


def _safe(value):
    """Copy JSON inputs, keeping missing/invalid numbers distinct from zero."""
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return None


def _sha(value):
    # Nonfinite values are tagged for identity, even though displays use null.
    def canonical(item):
        if isinstance(item, dict):
            return {str(key): canonical(val) for key, val in item.items()}
        if isinstance(item, (list, tuple)):
            return [canonical(val) for val in item]
        if isinstance(item, float) and not math.isfinite(item):
            return {'invalid_number': str(item)}
        return item
    return hashlib.sha256(json.dumps(canonical(value), ensure_ascii=False,
        sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _block(identifier, slot, kind, title, available, reason_code, reason,
           capability, engine='Visual Explainer', data=None, refs=None, sources=None,
           provenance=None, assumptions=None):
    return {'id': identifier, 'slot': slot, 'kind': kind, 'title': title,
            'available': bool(available), 'selected': bool(available),
            'reason_code': reason_code, 'reason': reason,
            'required_capability': capability, 'preferred_engine': engine,
            'supported_renderer': 'native_dom_svg', 'data_refs': refs or [],
            'source_refs': sources or [], 'provenance': provenance or {},
            'assumptions': assumptions or [], 'data': _safe(data or {})}


def _choice(kind, engine, code, reason, capability, status='deferred'):
    return {'kind': kind, 'preferred_engine': engine, 'supported_renderer': None,
            'available': False, 'selected': False, 'status': status,
            'reason_code': code, 'reason': reason, 'required_capability': capability}


def _finish(subject, binding, blocks, primary, choices):
    ordered = sorted(blocks, key=lambda row: READ_ORDER.index(row['slot']))
    for block in ordered:
        choices.append({key: deepcopy(block[key]) for key in (
            'kind', 'preferred_engine', 'supported_renderer', 'available',
            'selected', 'reason_code', 'reason', 'required_capability')})
        choices[-1]['status'] = 'selected' if block['selected'] else 'rejected'
    return {'version': VERSION,
            'selector': {'method': 'deterministic_rules', 'version': 'visual-selector-v1',
                         'new_model_calls': 0},
            'subject': subject, 'input_binding': binding,
            'input_digest': _sha({'subject': subject, 'binding': binding}),
            'primary_block_id': primary, 'read_order': list(READ_ORDER),
            'blocks': ordered, 'choices': choices}


def _motion_valid_inner(story, report):
    """Accept an existing bounded dataflow, never synthesize plan/workflow edges."""
    if (not isinstance(story, dict) or story.get('version') != 'dataflow-v1'
            or story.get('kind') not in {'review', 'feedback', 'inference', 'process'}
            or _dict(story.get('selection')).get('method') not in
               {'same_call_validated', 'report_concepts'}):
        return False
    nodes, edges = story.get('nodes'), story.get('edges')
    if (not isinstance(nodes, list) or not 2 <= len(nodes) <= 12
            or not isinstance(edges, list) or not 1 <= len(edges) <= 16):
        return False
    baseline = _dict(story.get('baseline')).get('status')
    if baseline not in {'unknown', 'conceptual', 'reported'}:
        return False
    evidence = _rows(story.get('evidence'), 64)
    evidence_ids = [row.get('id') for row in evidence]
    if (not evidence or any(not isinstance(ref, str) for ref in evidence_ids)
            or len(set(evidence_ids)) != len(evidence_ids)
            or any(not isinstance(row.get('excerpt'), str) or not row['excerpt']
                   or row['excerpt'] not in report for row in evidence)):
        return False
    ids, by_id = set(), {}
    for node in nodes:
        if not isinstance(node, dict):
            return False
        ref, refs = node.get('id'), node.get('evidence_ids')
        if (not isinstance(ref, str) or not _ID.fullmatch(ref) or ref in ids
                or node.get('role') not in {'input', 'compute', 'decision', 'memory', 'output', 'data'}
                or node.get('lane') not in {'baseline', 'technology'}
                or not isinstance(node.get('label'), str) or not node['label'].strip()
                or not isinstance(refs, list) or len(refs) > 4
                or any(not isinstance(item, str) or item not in evidence_ids for item in refs)
                or (node['lane'] == 'baseline' and baseline == 'unknown')
                or (not refs and not (node['lane'] == 'baseline' and baseline == 'conceptual'))):
            return False
        ids.add(ref)
        by_id[ref] = node
    adjacency = {ref: [] for ref in by_id}
    for edge in edges:
        if not isinstance(edge, dict):
            return False
        ref, refs = edge.get('id'), edge.get('evidence_ids')
        if (not isinstance(ref, str) or not _ID.fullmatch(ref) or ref in ids
                or edge.get('from') not in by_id or edge.get('to') not in by_id
                or edge['from'] == edge['to'] or edge.get('kind') not in {'data', 'feedback', 'control'}
                or not isinstance(edge.get('label'), str) or not edge['label'].strip()
                or not isinstance(refs, list) or len(refs) > 4
                or any(not isinstance(item, str) or item not in evidence_ids for item in refs)):
            return False
        ids.add(ref)
        if edge['kind'] != 'feedback':
            adjacency[edge['from']].append(edge['to'])
    visiting, finished = set(), set()
    def visit(ref):
        if ref in visiting:
            return False
        if ref in finished:
            return True
        visiting.add(ref)
        if not all(visit(other) for other in adjacency[ref]):
            return False
        visiting.remove(ref)
        finished.add(ref)
        return True
    return all(visit(ref) for ref in by_id)


def _motion_valid(story, report):
    try:
        return _motion_valid_inner(story, report)
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError):
        return False


def build_run_spec(run, presentation, readiness, sources=None):
    """Select from saved run artifacts and the caller's authoritative readiness."""
    run, presentation, readiness = _dict(run), _dict(presentation), _dict(readiness)
    plan = _dict(run.get('plan'))
    report = run.get('output') if isinstance(run.get('output'), str) else ''
    raw_sources, sources = sources if isinstance(sources, list) else [], _rows(sources)
    complete = (run.get('status') == 'completed' and bool(report.strip())
                and isinstance(run.get('id'), str) and bool(run['id'])
                and readiness.get('stage') in ('source_review', 'validation_designed', 'externally_evaluated', 'locally_tested')
                and readiness.get('run_id') == run.get('id'))
    binding = {'run_id': run.get('id'), 'report_sha256': hashlib.sha256(report.encode()).hexdigest(),
               'plan_sha256': _sha(plan), 'presentation_sha256': _sha(presentation),
               'readiness_sha256': _sha(readiness), 'sources_sha256': _sha(raw_sources)}
    provenance = {'origin': 'saved_report', 'independently_verified': False,
                  'empirical_technology_validation': False,
                  'readiness_stage': readiness.get('stage')}
    task = _dict(_dict(plan.get('study_context')).get('task'))
    blocks = [_block('task', 'task', 'task_context', 'Задача и сохранённый разбор', True,
        'saved_task_context', 'Постановка задачи и статус взяты из сохранённого запуска.',
        'text_and_structured_context', data={
            'title': presentation.get('title') or plan.get('topic') or plan.get('title'),
            'problem': presentation.get('problem') if complete else None,
            'task': task, 'readiness_stage': readiness.get('stage')},
        refs=['/run/plan/study_context/task', '/readiness/stage'], provenance=provenance)]
    all_rows, accepted, row_refs = [], [], []
    dimensions = _dict(readiness.get('comparison_dimensions'))
    for dimension in ('latency', 'cost', 'quality'):
        info = _dict(dimensions.get(dimension))
        for index, row in enumerate(_rows(info.get('measurements'), 100)):
            value = {**row, 'dimension': dimension, 'label': info.get('label')}
            all_rows.append(value)
            if (complete and row.get('chart_eligible') is True and row.get('source_bound_pair') is True
                    and row.get('comparability') == 'comparable'
                    and all(isinstance(row.get(key), str) and row[key].strip()
                            for key in ('metric', 'unit', 'conditions'))
                    and all(isinstance(_dict(row.get(side)).get('basis'), str)
                            and _dict(row.get(side)).get('basis') in _MEASURED
                            and isinstance(_dict(row.get(side)).get('label'), str)
                            and _dict(row.get(side))['label'].strip()
                            and _number(_dict(row.get(side)).get('value'))
                            for side in ('baseline', 'candidate'))):
                accepted.append(value)
                row_refs.append('/readiness/comparison_dimensions/' + dimension + '/measurements/' + str(index))
    numeric_provenance = {**provenance, 'origin': 'stored_source_analysis',
                          'verification': 'reported_not_independently_verified'}
    blocks.append(_block('comparison_bars', 'main_figure', 'comparison_bars', 'Внешние числовые сравнения', bool(accepted),
        'source_bound_comparable_values' if accepted else 'no_eligible_numeric_pairs',
        'Сопоставимые пары связаны с источниками; это внешние числа, не локальный тест.' if accepted else
        'Нет двух допустимых сопоставимых чисел с привязкой к источнику; неизвестное не заменяется нулём.',
        'source_bound_comparable_nonnegative_pairs', 'G2', {'rows': accepted},
        row_refs + ['/presentation/source_validation/checks'],
        sources=[row['source_url'] for row in _rows(presentation.get('evidence')) if isinstance(row.get('source_url'), str)],
        provenance=numeric_provenance,
        assumptions=['Каждый показатель имеет отдельную шкалу с нулём; интервалы неопределённости не выведены.']))
    story = presentation.get('motion_story')
    motion = complete and _motion_valid(story, report)
    blocks.append(_block('process_flow', 'main_figure', 'process_flow', 'Механизм по сохранённому отчёту', motion,
        'saved_illustrative_dataflow' if motion else 'no_valid_saved_dataflow',
        'Сохранённая схема объясняет механизм; движение и геометрия иллюстративны.' if motion else
        'Нет допустимой сохранённой схемы с явными узлами, рёбрами и основаниями отчёта.',
        'saved_validated_dataflow', 'AntV Infographic',
        {'graph': story if motion else None, 'illustrative': True}, ['/presentation/motion_story'],
        sources=[row['source_url'] for row in _rows(_dict(story).get('evidence')) if isinstance(row.get('source_url'), str)],
        provenance={**provenance, 'illustrative': True, 'selection_method': _dict(story).get('selection', {}).get('method')
                    if isinstance(_dict(story).get('selection'), dict) else None},
        assumptions=['Схема из отчёта не является исполняемой моделью, физической симуляцией или измерением эффекта.']))
    blocks.append(_block('comparison_table', 'comparison', 'comparison_table', 'Показатели и неизвестные условия',
        complete and bool(all_rows), 'recorded_dimensions' if complete and all_rows else 'no_recorded_dimensions',
        'Таблица сохраняет неизвестные значения, оценки и происхождение каждого показателя.' if complete and all_rows else
        'Структурированные показатели ещё не сохранены.', 'structured_measurements',
        data={'rows': all_rows if complete else []}, refs=['/readiness/comparison_dimensions'], provenance=numeric_provenance))
    blocks.append(_block('applicability', 'applicability', 'applicability', 'Применимость и границы', complete,
        'saved_applicability' if complete else 'run_not_ready',
        'Границы применения и следующий шаг взяты из сохранённого разбора.' if complete else
        'Незавершённый запуск не имеет готовых выводов о применимости.', 'saved_scope_and_limits',
        data={'summary': presentation.get('public_takeaway') if complete else None,
              'limitations': presentation.get('limitations', []) if complete else [],
              'resources': presentation.get('resources', []) if complete else [],
              'last_step': readiness.get('last_step'), 'next_actions': readiness.get('next_actions', [])},
        refs=['/presentation/public_takeaway', '/presentation/limitations', '/readiness/last_step'], provenance=provenance))
    evidence = _rows(presentation.get('evidence'), 200)
    blocks.append(_block('evidence', 'evidence', 'evidence_ledger', 'Основания и происхождение', complete and bool(evidence or sources),
        'saved_evidence' if complete and (evidence or sources) else 'no_saved_evidence',
        'Привязка к источнику фиксирует происхождение и не означает независимую проверку истинности.',
        'saved_source_references', data={'evidence': evidence if complete else [], 'sources': sources if complete else [],
        'claim_coverage': readiness.get('claim_coverage')}, refs=['/presentation/evidence', '/sources', '/readiness/claim_coverage'],
        sources=[row.get('source_url') for row in evidence if isinstance(row.get('source_url'), str)], provenance=provenance))
    choices = [
        _choice('knowledge_graph', 'G6', 'missing_typed_source_bound_edges',
            'Нет отдельного контракта типизированных связей; контекст памяти не означает supports или refutes.', 'typed_source_bound_edges'),
        _choice('custom_simulation', 'Polo Club', 'missing_formal_model',
            'В текущем протоколе нет формальной модели состояний и вычислений для интерактивной симуляции.', 'validated_formal_model'),
        _choice('video', 'Manim', 'missing_formal_model_and_renderer',
            'Нет проверенной модели переходов и подключённого Manim renderer; шаги текста не создают модель.', 'validated_state_transitions_and_video_renderer')]
    primary = 'comparison_bars' if accepted else 'process_flow' if motion else 'task'
    return _finish({'type': 'run', 'id': run.get('id'), 'status': run.get('status'),
                    'readiness_stage': readiness.get('stage')}, binding, blocks, primary, choices)


def _corpus_series(overview):
    corpus = _dict(overview.get('corpus'))
    reproduction = _dict(corpus.get('reproduction'))
    years, topics = corpus.get('years'), overview.get('topics')
    if (overview.get('available') is not True or overview.get('status') != 'ready'
            or not _HEX.fullmatch(str(corpus.get('snapshot_id', '')))
            or reproduction.get('matched') is not True
            or not isinstance(years, list) or not 2 <= len(years) <= 100
            or any(type(year) is not int for year in years) or years != sorted(set(years))
            or not isinstance(topics, list) or not 1 <= len(topics) <= 1001):
        return None
    denominators = reproduction.get('denominators')
    if (not isinstance(denominators, list) or len(denominators) != len(years)
            or any(not isinstance(point, dict) or point.get('year') != year
                   or type(point.get('papers')) is not int or point['papers'] <= 0
                   for point, year in zip(denominators, years))):
        return None
    result, ids = [], set()
    for topic in topics:
        if not isinstance(topic, dict) or type(topic.get('id')) is not int or topic['id'] in ids:
            return None
        points = topic.get('trajectory')
        if not isinstance(points, list) or len(points) != len(years):
            return None
        for point, year, denominator in zip(points, years, denominators):
            if (not isinstance(point, dict) or point.get('year') != year
                    or type(point.get('numerator')) is not int
                    or type(point.get('denominator')) is not int
                    or point['denominator'] != denominator['papers']
                    or not 0 <= point['numerator'] <= point['denominator']
                    or not _number(point.get('share')) or point['share'] > 100
                    or not math.isclose(point['share'], point['numerator'] * 100 / point['denominator'], abs_tol=0.00005001)):
                return None
        ids.add(topic['id'])
        result.append({'id': topic['id'], 'name': topic.get('name'),
                       'is_noise': topic.get('is_noise') is True, 'points': points})
    return result


def build_corpus_spec(overview):
    """Select trends only for validated, matched snapshot counts, never effects."""
    overview = _dict(overview)
    corpus = _dict(overview.get('corpus'))
    stable = deepcopy(overview)
    stable.pop('visual_spec', None)
    _dict(stable.get('corpus')).pop('imported_at', None)
    binding = {'snapshot_id': corpus.get('snapshot_id'), 'overview_sha256': _sha(stable)}
    series = _corpus_series(overview)
    ready = series is not None
    provenance = {**_dict(corpus.get('provenance')), 'origin': 'external_extraction',
                  'snapshot_id': corpus.get('snapshot_id'), 'independently_verified': False,
                  'validation_state': 'imported_unverified', 'new_model_calls': 0}
    blocks = [
        _block('corpus', 'task', 'corpus_overview', corpus.get('title') or 'Сохранённый корпус',
            True, 'saved_corpus_context', 'Контекст фиксированного внешнего снимка.', 'corpus_snapshot',
            data={key: corpus.get(key) for key in ('counts', 'years', 'provenance', 'reproduction')},
            refs=['/overview/corpus'], provenance=provenance),
        _block('trends', 'main_figure', 'trend_lines', 'Доля статей с темой по годам', ready,
            'matched_distinct_paper_shares' if ready else 'invalid_or_missing_corpus_trends',
            'Линии показывают пересчитанные доли уникальных статей, а не качество или эффект технологии.' if ready else
            'Нужен доступный снимок с совпавшим пересчётом, возрастающими годами и корректными числителями и знаменателями.',
            'matched_distinct_paper_year_shares', 'G2',
            {'series': series or [], 'unit': 'percent', 'quantity': 'distinct_paper_share', 'overlapping_topics': True},
            ['/overview/topics/*/trajectory', '/overview/corpus/reproduction'], provenance=provenance,
            assumptions=['Статьи могут относиться к нескольким темам; доли не образуют разбиение 100%.',
                         'Числитель и знаменатель — уникальные статьи аналитической выборки, не число claims.']),
        _block('topics', 'comparison', 'topic_table', 'Темы и состав корпуса', ready,
            'saved_topic_counts' if ready else 'invalid_or_missing_corpus_trends',
            'Количество статей и claims показано отдельно от долей темы.', 'topic_count_table',
            data={'rows': [{key: row.get(key) for key in ('id', 'name', 'papers', 'claims', 'is_noise')}
                           for row in _rows(overview.get('topics'))] if ready else []},
            refs=['/overview/topics'], provenance=provenance),
        _block('corpus_scope', 'applicability', 'applicability', 'Область действия снимка', ready,
            'fixed_snapshot_scope' if ready else 'corpus_not_ready',
            'Выводы ограничены сохранённой аналитической выборкой; внешнее извлечение не проверено независимо.',
            'snapshot_scope', data={'summary': None, 'limitations': corpus.get('notices', [])},
            refs=['/overview/corpus/notices'], provenance=provenance),
        _block('corpus_evidence', 'evidence', 'evidence_ledger', 'Происхождение корпуса', ready,
            'external_snapshot_provenance' if ready else 'corpus_not_ready',
            'Источники и совпавший пересчёт фиксируют происхождение; истинность каждого claim не проверена.',
            'external_snapshot_provenance', data={'evidence': [], 'sources': _dict(corpus.get('provenance')),
                                                'reproduction': corpus.get('reproduction')},
            refs=['/overview/corpus/provenance', '/overview/corpus/reproduction'], provenance=provenance)]
    choices = [_choice(kind, 'G2', 'overlapping_topics_not_partition',
        'Темы пересекаются; их доли нельзя складывать в круговую диаграмму или 100% stacked chart.',
        'mutually_exclusive_partition', status='rejected') for kind in ('pie', 'stacked_share')]
    choices.append(_choice('knowledge_graph', 'G6', 'missing_typed_source_bound_edges',
        'Совместная тема не задаёт supports/refutes между утверждениями; типизированных оснований нет.', 'typed_source_bound_edges'))
    return _finish({'type': 'corpus', 'id': corpus.get('snapshot_id'),
                    'status': overview.get('status'), 'readiness_stage': 'snapshot_reproduced' if ready else 'incomplete'},
                   binding, blocks, 'trends' if ready else 'corpus', choices)
