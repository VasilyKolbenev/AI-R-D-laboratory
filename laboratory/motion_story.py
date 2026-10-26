"""Compile bounded dataflow explanations from a saved report, without providers.

Archetypes describe source-supported operations, never a product-name lookup.
An optional graph from the existing research response is accepted only when its
labels are quoted by its referenced, already validated report evidence.
"""
from __future__ import annotations

import copy
import json
import re


VERSION = 'dataflow-v1'
KINDS = {'review', 'feedback', 'inference', 'process'}
ROLES = {'input', 'compute', 'decision', 'memory', 'output', 'data'}
LANES = {'baseline', 'technology'}
EDGE_KINDS = {'data', 'feedback', 'control'}
_ID = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,39}\Z')
_URL = re.compile(r'https?://[^\s<>"\']+', re.I)
_UNSAFE = re.compile(r'https?://|[<>`{}]|(?:javascript|data):|[\x00-\x1f\x7f]', re.I)
_CODE = re.compile(r'\b(?:import|from|def|class)\s+[A-Za-z_]|\b(?:print|exec|eval|open)\s*\(|\b(?:curl|wget|powershell|cmd\.exe)\b|=>|\$\(|[A-Za-z_]\w*\s*=[^=]', re.I)


def _plain(value):
    value = re.sub(r'\[([^\]]+)\]\(https?://[^)]+\)', r'\1', str(value))
    return ' '.join(value.replace('**', '').replace('`', '').split()).strip(' #>*-')


def _text(value, maximum=64):
    return isinstance(value, str) and 0 < len(value) <= maximum and not _UNSAFE.search(value) and not _CODE.search(value)


def _has(text, pattern):
    return bool(re.search(pattern, text, re.I))


def _steps(data):
    for row in data.get('story', []) if isinstance(data.get('story'), list) else []:
        if isinstance(row, dict) and row.get('id') == 'mechanism':
            values = row.get('items', [])
            if isinstance(values, list) and len(values) == 3 and all(isinstance(x, str) and x.strip() for x in values):
                return values
    visual = data.get('visual') or {}
    if visual.get('basis') == 'review_process':
        return []
    values = visual.get('steps', [])
    if isinstance(values, list) and len(values) == 3:
        values = [row.get('text', '') if isinstance(row, dict) else row for row in values]
        if all(isinstance(x, str) and x.strip() for x in values):
            return values
    return []


def _sources(data):
    result = []
    for row in [*data.get('publication_sources', []), *data.get('sources', [])]:
        if isinstance(row, dict) and isinstance(row.get('url'), str) and row['url'].startswith(('https://', 'http://')):
            if row['url'] not in [item['url'] for item in result]:
                result.append({'url': row['url']})
    return result[:8]


class _Facts:
    def __init__(self, report, sources):
        self.report, self.sources, self.rows = report, sources, []

    def find(self, pattern):
        """Keep a bounded literal report fragment, with its existing source link."""
        for line in self.report.splitlines():
            if _has(line, pattern):
                raw = line.strip()
                if len(raw) > 1000:
                    match = re.search(pattern, raw, re.I)
                    start = max(0, match.start() - 180)
                    raw = raw[start:start + 900]
                return self.add(raw)
        return []

    def add(self, excerpt):
        excerpt = excerpt.strip()
        if not excerpt or excerpt not in self.report:
            return []
        for row in self.rows:
            if row['excerpt'] == excerpt:
                return [row['id']]
        url = next((row['url'] for row in self.sources if row['url'] in excerpt), '')
        if not url:
            refs = re.findall(r'\[(\d+)\]', excerpt)
            for ref in refs:
                match = re.search(r'(?m)^\s*(?:\[' + ref + r'\]|' + ref + r'\.)[^\n]*?(https?://[^\s]+)', self.report)
                if match and match.group(1).rstrip('.,;)') in [row['url'] for row in self.sources]:
                    url = match.group(1).rstrip('.,;)')
                    break
        if not url and self.sources:
            url = self.sources[0]['url']
        identifier = 'motion_e' + str(len(self.rows) + 1)
        self.rows.append({'id': identifier, 'excerpt': excerpt, 'source_url': url,
                          'basis': 'saved_report', 'verification': 'report_fragment_not_independent_verification'})
        return [identifier]


def _node(identifier, label, role, refs, lane='technology'):
    return {'id': identifier, 'label': label, 'role': role, 'lane': lane, 'evidence_ids': list(refs)}


def _edge(identifier, start, end, label, refs, kind='data'):
    return {'id': 'e_' + identifier, 'from': start, 'to': end, 'label': label, 'kind': kind, 'evidence_ids': list(refs)}


def _review(facts):
    read = facts.find(r'(?:агент.{0,35}(?:читают|читает|diff)|agents?.{0,35}(?:read|diff))')
    check = facts.find(r'(?:отсеивает|неподтвержд|verify|verification).{0,100}(?:наход|find|ранж|rank)')
    publish = facts.find(r'(?:замечания публикуются|findings.{0,30}(?:publish|pull request))')
    human = facts.find(r'(?:CI и решение|человеческие одобрения|решением человека|human.{0,25}(?:decision|approval))')
    baseline = facts.find(r'(?:ручное ревью плюс CI|manual review.{0,20}CI)')
    if not all((read, check, publish, human)):
        return None
    nodes = [_node('baseline_input', 'Изменения кода', 'input', baseline, 'baseline'),
             _node('baseline_review', 'Ручное ревью', 'compute', baseline, 'baseline'),
             _node('baseline_ci', 'CI', 'compute', baseline, 'baseline'),
             _node('baseline_decision', 'Решение человека', 'decision', baseline, 'baseline'),
             _node('input', 'Diff + окружающий код', 'input', read),
             _node('inspect', 'Поиск ошибок агентами', 'compute', read),
             _node('inspect_peer', 'Другой агент поиска', 'compute', read),
             _node('verify', 'Перепроверка находок', 'decision', check),
             _node('rank', 'Объединение и ранжирование', 'compute', check),
             _node('findings', 'Замечания в PR', 'output', publish),
             _node('human', 'Решение человека + CI', 'decision', human)]
    edges = [_edge('base_review', 'baseline_input', 'baseline_review', 'Код', baseline),
             _edge('base_ci', 'baseline_review', 'baseline_ci', 'Проверки', baseline, 'control'),
             _edge('base_decide', 'baseline_ci', 'baseline_decision', 'Результаты CI', baseline, 'control'),
             _edge('read', 'input', 'inspect', 'Код', read),
             _edge('read_peer', 'input', 'inspect_peer', 'Тот же код', read),
             _edge('check', 'inspect', 'verify', 'Кандидаты ошибок', check),
             _edge('check_peer', 'inspect_peer', 'verify', 'Кандидаты ошибок', check),
             _edge('rank', 'verify', 'rank', 'Подтверждённые находки', check),
             _edge('publish', 'rank', 'findings', 'Ранжированные замечания', publish),
             _edge('human_decision', 'findings', 'human', 'Основания для ревью', human, 'control')]
    baseline_meta = {'status': 'conceptual', 'label': 'Ручное ревью + CI',
                     'note': 'Концептуальный baseline из отчёта; конкретный процесс проекта не задан.'}
    if not baseline:
        nodes = [node for node in nodes if node['lane'] != 'baseline']
        edges = [edge for edge in edges if not edge['id'].startswith('e_base_')]
        baseline_meta = {'status': 'unknown', 'label': 'Baseline не установлен',
                         'note': 'В сохранённом отчёте нет описания прежнего процесса.'}
    return nodes, edges, baseline_meta, [
        'Публичный сервис выдаёт замечания; он сам не одобряет PR и не запускает код.',
        'Доля PR с комментариями — покрытие замечаниями, не качество и не доказанный причинный эффект.',
        'Ветви обозначают нескольких агентов; точное число и независимость их ошибок не установлены.']


def _feedback(facts):
    method = facts.find(r'(?:Propose.{0,15}Probe.{0,15}Compose|предлагает изменения.{0,80}проверяет варианты)')
    transfer = facts.find(r'(?:переносит опыт.{0,35}следующ|experience.{0,35}(?:next|transfer))')
    fixed = facts.find(r'(?:фиксированн.{0,15}вес|fixed.{0,15}weights)')
    if not all((method, transfer, fixed)):
        return None
    nodes = [_node('baseline_input', 'Текущая задача', 'input', [], 'baseline'),
             _node('baseline_harness', 'Неизменная обвязка', 'compute', [], 'baseline'),
             _node('baseline_output', 'Результат задачи', 'output', [], 'baseline'),
             _node('input', 'Текущая задача', 'input', method),
             _node('propose', 'Propose · варианты обвязки', 'compute', method),
             _node('probe', 'Probe · проверка вариантов', 'decision', method),
             _node('compose', 'Compose · новая обвязка', 'compute', method),
             _node('output', 'Результат текущей задачи', 'output', method),
             _node('experience', 'Опыт для следующих задач', 'memory', transfer)]
    edges = [_edge('base_input', 'baseline_input', 'baseline_harness', 'Задача', []),
             _edge('base_result', 'baseline_harness', 'baseline_output', 'Один процесс', []),
             _edge('propose', 'input', 'propose', 'Задача + текущая обвязка', method),
             _edge('probe', 'propose', 'probe', 'Предложенные варианты', method),
             _edge('compose', 'probe', 'compose', 'Результаты проверки', method),
             _edge('result', 'compose', 'output', 'Собранная обвязка', method),
             _edge('remember', 'compose', 'experience', 'Опыт изменений', transfer),
             _edge('reuse', 'experience', 'propose', 'На следующей задаче', transfer, 'feedback')]
    return nodes, edges, {'status': 'conceptual', 'label': 'Неизменная обвязка',
                         'note': 'Концептуальное сравнение: обычный процесс с фиксированной обвязкой; измерения baseline не восстановлены.'}, [
        'Веса модели фиксированы; изменяется обвязка вокруг модели.',
        'Петля переносит опыт между задачами. Её движение не показывает измеренный выигрыш.',
        'Дополнительные попытки расходуют бюджет; переносимость требует отдельной проверки.']


def _inference(facts):
    stages = facts.find(r'prefill.{0,140}decode')
    draft = facts.find(r'(?:предлагает черновые токены.{0,100}провер|draft.{0,50}tokens?.{0,100}verif)')
    parallel = facts.find(r'(?:параллелизм.{0,120}(?:вниман|эксперт)|parallel.{0,120}(?:attention|expert))')
    requests = facts.find(r'(?:запрос|requests?)')
    if not all((stages, draft, parallel, requests)):
        return None
    draft_label = 'Черновые токены'
    excerpt = next(row['excerpt'] for row in facts.rows if row['id'] == draft[0])
    name = re.search(r'\b([A-Za-z][A-Za-z0-9_-]{1,20})\s+предлагает черновые токены', excerpt)
    if name:
        draft_label = name.group(1) + ' · черновые токены'
    nodes = [_node('input', 'Запросы / входной контекст', 'input', requests),
             _node('prefill', 'Prefill · входной контекст', 'compute', stages),
             _node('decode', 'Decode · генерация', 'compute', stages),
             _node('draft', draft_label, 'data', draft),
             _node('verify', 'Проверка токенов моделью', 'decision', draft),
             _node('output', 'Выходные токены', 'output', draft)]
    edges = [_edge('context', 'input', 'prefill', 'Контекст', requests),
             _edge('generation', 'prefill', 'decode', 'К генерации', stages, 'control'),
             _edge('draft', 'decode', 'draft', 'Предложить токены', draft),
             _edge('verify', 'draft', 'verify', 'Черновые токены', draft),
             _edge('output', 'verify', 'output', 'Проверенное продолжение', draft)]
    return nodes, edges, {'status': 'unknown', 'label': 'Baseline не установлен',
                         'note': 'В отчёте предложено сравнение при одинаковой модели и нагрузке; проверенного baseline нет.'}, [
        'Параллелизм внимания и экспертов; планировщик совмещает подготовку пакетов с вычислениями.',
        'Prefill → decode — схема стадий; аппаратная топология и минимальные ресурсы не установлены.',
        'Движение токенов иллюстративно; проверенных чисел ускорения и экономии нет.']


def _process(facts, steps):
    if len(steps) != 3:
        return None
    nodes = []
    for index, step in enumerate(steps, 1):
        # A long paragraph cannot honestly become a small operation by clipping
        # it. Keep the established adaptive renderer for that case.
        plain = _plain(step)
        label = plain
        if not _text(label) or re.search(r'\d', label):
            return None
        refs = facts.add(step) if step in facts.report else []
        nodes.append(_node('step' + str(index), label, 'compute', refs))
    return nodes, [_edge('step1_to_step2', 'step1', 'step2', 'Следующий шаг', []),
                   _edge('step2_to_step3', 'step2', 'step3', 'Следующий шаг', [])], {
                       'status': 'unknown', 'label': 'Baseline не установлен',
                       'note': 'По сохранённым шагам нельзя восстановить сопоставимый baseline.'}, [
        'Схема следует трём шагам механизма из текущей редакторской подачи; подробности — в отчёте.',
        'Стрелки означают порядок описанных операций; размер эффекта и дополнительные компоненты не выведены.']


def validate_motion_graph(value, report, evidence):
    """Validate the optional same-call graph; failures never invalidate the post.

    This is literal report grounding, not independent scientific verification.
    Numeric claims belong exclusively in the existing validated comparisons.
    """
    try:
        if not isinstance(value, dict) or set(value) - {'version', 'kind', 'nodes', 'edges', 'baseline', 'notes'}:
            raise ValueError('поля графа')
        if len(json.dumps(value, ensure_ascii=False).encode('utf-8', errors='replace')) > 10000:
            raise ValueError('размер графа')
        if value.get('version') != VERSION or value.get('kind') not in KINDS:
            raise ValueError('версия или тип')
        by_evidence = {row['id']: row for row in evidence if isinstance(row, dict) and isinstance(row.get('id'), str)
                       and isinstance(row.get('excerpt'), str) and row['excerpt'] and _plain(row['excerpt']) in _plain(report)}
        nodes, edges = value.get('nodes'), value.get('edges')
        if not isinstance(nodes, list) or not 1 <= len(nodes) <= 12 or not isinstance(edges, list) or len(edges) > 16:
            raise ValueError('границы графа')
        baseline = value.get('baseline')
        if not isinstance(baseline, dict) or set(baseline) != {'status', 'label', 'note'}:
            raise ValueError('baseline')
        if baseline['status'] not in {'reported', 'conceptual', 'unknown'} or not _text(baseline['label']) or not _text(baseline['note'], 400):
            raise ValueError('статус baseline')
        if re.search(r'\d', baseline['label'] + baseline['note']):
            raise ValueError('числа вне сравнений')
        if baseline['status'] == 'conceptual' and not _has(baseline['note'], r'концепту|conceptual'):
            raise ValueError('не обозначен концептуальный baseline')
        if baseline['status'] == 'reported' and (_plain(baseline['label']).casefold() not in _plain(report).casefold()
                                                or _plain(baseline['note']).casefold() not in _plain(report).casefold()
                                                or _has(baseline['label'] + ' ' + baseline['note'], r'неизвест|не (?:задан|определ|установ)|unknown|not (?:established|defined|reported)')):
            raise ValueError('baseline не процитирован в отчёте')

        def grounded(row, allowed, optional=False):
            if not isinstance(row, dict) or set(row) != allowed or not isinstance(row.get('id'), str) or not _ID.fullmatch(row['id']):
                raise ValueError('поля или ID')
            if not _text(row.get('label')) or re.search(r'\d', row['label']):
                raise ValueError('подпись или численное утверждение')
            refs = row.get('evidence_ids')
            if (not isinstance(refs, list) or len(refs) > 4 or any(not isinstance(ref, str) or ref not in by_evidence for ref in refs)
                    or len(refs) != len(set(refs)) or (not refs and not optional)):
                raise ValueError('ссылки на доказательства')
            if refs and not any(_plain(row['label']).casefold() in _plain(by_evidence[ref]['excerpt']).casefold() for ref in refs):
                raise ValueError('подпись отсутствует в процитированном основании')
            if not refs and _plain(row['label']).casefold() not in _plain(report).casefold():
                raise ValueError('концептуальная подпись отсутствует в отчёте')

        identifiers = set()
        node_by_id = {}
        for node in nodes:
            conceptual = isinstance(node, dict) and node.get('lane') == 'baseline' and baseline['status'] == 'conceptual'
            grounded(node, {'id', 'label', 'role', 'lane', 'evidence_ids'}, conceptual)
            if node['id'] in identifiers or node['role'] not in ROLES or node['lane'] not in LANES:
                raise ValueError('повтор ID, роль или полоса')
            if node['lane'] == 'baseline' and baseline['status'] == 'unknown':
                raise ValueError('выдуманная полоса baseline')
            if node['role'] == 'memory' and not any(_has(by_evidence[ref]['excerpt'], r'памят|опыт|истори|кэш|cache|memory|experience|history') for ref in node['evidence_ids']):
                raise ValueError('память не поддержана отчётом')
            identifiers.add(node['id'])
            node_by_id[node['id']] = node
        for edge in edges:
            if not isinstance(edge, dict):
                raise ValueError('ребро')
            if edge.get('from') not in node_by_id or edge.get('to') not in node_by_id or edge['from'] == edge['to']:
                raise ValueError('концы ребра')
            conceptual = baseline['status'] == 'conceptual' and all(node_by_id[edge[key]]['lane'] == 'baseline' for key in ('from', 'to'))
            grounded(edge, {'id', 'from', 'to', 'label', 'kind', 'evidence_ids'}, conceptual)
            if edge['id'] in identifiers or edge['kind'] not in EDGE_KINDS:
                raise ValueError('повтор ID или тип ребра')
            if edge['kind'] == 'feedback' and not any(_has(by_evidence[ref]['excerpt'], r'опыт|следующ|повтор|обратн|feedback|experience|reuse|next') for ref in edge['evidence_ids']):
                raise ValueError('обратная связь не поддержана')
            identifiers.add(edge['id'])
        nexts = {identifier: [] for identifier in node_by_id}
        for edge in edges:
            if edge['kind'] != 'feedback':
                nexts[edge['from']].append(edge['to'])
        visiting, finished = set(), set()

        def visit(identifier):
            if identifier in visiting:
                raise ValueError('цикл не обозначен обратной связью')
            if identifier not in finished:
                visiting.add(identifier)
                for next_id in nexts[identifier]:
                    visit(next_id)
                visiting.remove(identifier)
                finished.add(identifier)
        for identifier in nexts:
            visit(identifier)
        notes = value.get('notes', [])
        if not isinstance(notes, list) or len(notes) > 5 or any(not _text(note, 400) or re.search(r'\d', note)
                                                              or _plain(note).casefold() not in _plain(report).casefold() for note in notes):
            raise ValueError('примечания')
        return copy.deepcopy(value), []
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        return None, ['Необязательный motion отброшен (' + str(error) + '); схема собрана по сохранённому механизму.']


def build_motion_story(data, report, optional=None, evidence=None):
    """Return compiled metadata only; do not change text, review, or run state."""
    if not isinstance(data, dict) or not isinstance(report, str) or (data.get('visual') or {}).get('kind') == 'replay_tree':
        return None
    sources = _sources(data)
    issues = []
    if optional is not None:
        graph, issues = validate_motion_graph(optional, report, evidence or [])
        if graph:
            graph.update(sources=sources, evidence=copy.deepcopy(evidence or []),
                         selection={'method': 'same_call_validated', 'reason': 'Подписи графа дословно поддержаны связанными фрагментами сохранённого отчёта.'})
            graph.setdefault('notes', []).append('Проверено совпадение с отчётом; независимая проверка источников и измерение скорости не выполнялись.')
            return graph
    facts = _Facts(report, sources)
    choices = [
        ('review', _has(report, r'\bPR\b|\bdiff\b|pull request') and _has(report, r'несколько агент|multiple agents'), _review),
        ('feedback', _has(report, r'propose') and _has(report, r'probe') and _has(report, r'compose'), _feedback),
        ('inference', _has(report, r'prefill') and _has(report, r'decode') and _has(report, r'чернов.{0,15}токен|draft.{0,15}token'), _inference)]
    selected, kind = None, 'process'
    for candidate, supported, builder in choices:
        if supported:
            selected = builder(facts)
            if selected:
                kind = candidate
                break
    if selected is None:
        selected = _process(facts, _steps(data))
    if selected is None:
        return None
    nodes, edges, baseline, notes = selected
    reason = {'review': 'В отчёте описаны код, поиск ошибок, перепроверка находок и решение человека.',
              'feedback': 'В отчёте описаны предложение, проверка и сборка обвязки с переносом опыта при фиксированных весах.',
              'inference': 'В отчёте названы prefill/decode, черновые токены и проверка моделью.',
              'process': 'Более подробный тип не подтверждён; показаны только три сохранённых шага механизма.'}[kind]
    return {'version': VERSION, 'kind': kind, 'nodes': nodes, 'edges': edges, 'baseline': baseline,
            'notes': notes + issues, 'sources': sources, 'evidence': facts.rows,
            'selection': {'method': 'report_concepts', 'reason': reason}}
