"""Deterministic composition hints for already validated publication data.

This module chooses presentation emphasis only. It does not infer measurements,
change the report, or repair an incomplete structured response.
"""
from __future__ import annotations

import math
import re
import unicodedata


VISUAL_FOCUS_VALUES = frozenset({'auto', 'comparison', 'mechanism', 'infrastructure', 'applicability'})
_LABELS = {'comparison': 'Сравнение по данным', 'mechanism': 'Механизм по шагам',
           'infrastructure': 'Инфраструктура и условия', 'applicability': 'Применимость и границы'}
_EMPHASIS = {'comparison': 'charts', 'mechanism': 'motion',
             'infrastructure': 'text', 'applicability': 'text'}
_INFRASTRUCTURE_HEADING = re.compile(
    r'\b(?:engine|runtime|serving)\b|\bрантайм\w*\b|'
    r'\bдвиж(?:ок|ка|ку|ком|ке|ки|ков|кам|ками|ках)\b', re.I)
_INFRASTRUCTURE = re.compile(
    r'\binference\s+(?:engine|runtime|serving|server)\b|'
    r'\b(?:serving|inference)\s+infrastructure\b|\bllm\s+serving\b|'
    r'движ\w*\s+(?:для\s+)?инференс|инференс\w*\s+движ|'
    r'(?:сервер|сервинг|разв[её]ртывани)\w*.{0,35}(?:инференс|llm|модел)|'
    r'(?:инференс|llm|модел)\w*.{0,35}(?:сервинг|разв[её]ртывани)', re.I)
_MECHANISM = re.compile(
    r'\bspeculative\s+decoding\b|'
    r'\b(?:algorithm|protocol|pipeline|process)\b|алгоритм|протокол|конвейер|обвязк|оркестрац|'
    r'спекулятивн\w*\s+декод|'
    r'провер\w*\s+(?:источник|документ)|'
    r'(?:источник|документ)\w*.{0,30}провер', re.I)


def _text(value):
    return unicodedata.normalize('NFKC', value).casefold() if isinstance(value, str) else ''


def _topic(data):
    # Resources can describe supporting hardware for any topic. They must never
    # make an otherwise unrelated document/assistant topic an infrastructure one.
    return ' '.join(_text(data.get(key, '')) for key in ('title', 'problem', 'use_case'))


def _has_mechanism(data):
    visual = data.get('visual')
    if not isinstance(visual, dict) or visual.get('basis') == 'review_process':
        return False
    steps = visual.get('steps')
    return (isinstance(steps, list) and len(steps) == 3
            and all(isinstance(step, dict) and isinstance(step.get('text'), str)
                    and step['text'].strip() for step in steps))


def _has_supported_comparison(data):
    """Recognize the validated comparison shape without deriving new numbers."""
    comparisons = data.get('comparisons')
    if not isinstance(comparisons, list):
        return False
    for row in comparisons:
        if not isinstance(row, dict):
            continue
        numbers = (row.get('baseline_value'), row.get('result_value'))
        if not all(type(number) in (int, float) and 0 <= number <= 1e100
                   and math.isfinite(number) for number in numbers):
            continue
        if not all(isinstance(row.get(key), str) and row[key].strip()
                   for key in ('label', 'unit', 'baseline_label', 'result_label', 'conditions')):
            continue
        references, evidence = row.get('evidence_ids'), row.get('evidence')
        if not isinstance(references, list) or not references or not isinstance(evidence, list):
            continue
        supported_ids = {item.get('id') for item in evidence
                         if isinstance(item, dict) and isinstance(item.get('id'), str)
                         and isinstance(item.get('source_url'), str) and item['source_url'].strip()}
        if all(isinstance(reference, str) and reference in supported_ids for reference in references):
            return True
    return False


def _profile(mode, reason, selection):
    return {'version': 'adaptive-v1', 'mode': mode, 'label': _LABELS[mode],
            'reason': reason, 'emphasis': _EMPHASIS[mode], 'selection': selection}


def select_visual_profile(data, requested='auto'):
    """Return metadata after editorial/evidence validation, without mutation.

    The caller retains the existing evidence and publication checks. A request
    for comparison cannot create a pair or overrule missing evidence.
    """
    requested = requested if isinstance(requested, str) and requested in VISUAL_FOCUS_VALUES else 'auto'
    if _has_supported_comparison(data):
        return _profile('comparison',
                        'Сопоставимая пара чисел, условия и связанные основания зафиксированы в отчёте; выбран график сравнения. Независимой проверки источника не было.',
                        'evidence')
    topic = _topic(data)
    mechanism = _has_mechanism(data)
    semantic_mechanism = mechanism and bool(_MECHANISM.search(topic))
    if requested == 'comparison':
        mode = 'mechanism' if semantic_mechanism else 'applicability'
        explanation = ('Показана последовательность механизма из отчёта.' if mode == 'mechanism'
                       else 'Показаны сценарий применения, требования и границы из отчёта.')
        return _profile(mode, 'Запрошено сравнение, но подтверждённой сопоставимой пары чисел нет. '
                        + explanation + ' Неизвестные значения не заменяются нулями.', 'requested')
    if requested == 'mechanism' and not mechanism:
        return _profile('applicability',
                        'Запрошена схема механизма, но полная последовательность шагов в отчёте отсутствует; показаны применимость и границы.',
                        'requested')
    if requested != 'auto':
        reasons = {'mechanism': 'В том же исследовательском ответе выбран механизм; показаны сохранённые шаги без имитации замеров.',
                   'infrastructure': 'В том же исследовательском ответе выбрана инфраструктура; показаны сохранённые требования, зависимости и неизвестные расходы.',
                   'applicability': 'В том же исследовательском ответе выбрана применимость; показаны рабочий сценарий, условия и границы.'}
        return _profile(requested, reasons[requested], 'requested')
    if _INFRASTRUCTURE_HEADING.search(_text(data.get('title', ''))) or _INFRASTRUCTURE.search(topic):
        return _profile('infrastructure',
                        'Тема и рабочий сценарий посвящены движку, обслуживанию или развёртыванию моделей; на первом плане требования и условия из отчёта.',
                        'heuristic')
    if semantic_mechanism:
        return _profile('mechanism',
                        'Тема описывает конкретный алгоритм или процесс, а в отчёте сохранены три шага; показана последовательность без обещания измеренного эффекта.',
                        'heuristic')
    return _profile('applicability',
                    'Подтверждённой сопоставимой пары чисел нет; тема не задаёт явного механизма или инфраструктурного фокуса. Показаны применимость и границы из отчёта.',
                    'heuristic')
