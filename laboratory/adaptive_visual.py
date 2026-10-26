"""Extractive visual compositions for the saved report's selected focus.

Only composition and reading emphasis change. All report text is kept complete
once selected, and no diagram claims a measured quantity or deployment status.
Imports of reader primitives are local so the reader can dispatch here safely.
"""
from __future__ import annotations

VERSION = 'adaptive-v1'
MODES = {'comparison', 'mechanism', 'infrastructure', 'applicability'}
MAX_ANIMATION_HEIGHT = 1920
MECHANISM_CAPTION = 'Схема метода; собственных замеров нет. Анимация показывает порядок, не скорость.'
INFRASTRUCTURE_CAPTION = 'Требования из отчёта; собственных замеров нет. Подсветка не означает готовность к внедрению.'
APPLICABILITY_CAPTION = 'Прикладной разбор; собственных замеров нет. Вывод относится к условиям и границам отчёта.'


def profile_mode(data):
    profile = data.get('visual_profile') or {}
    if isinstance(profile, dict) and profile.get('version') == VERSION and profile.get('mode') in MODES:
        return profile['mode']
    return None


def _items(data, key, fallback=None):
    """Take whole editorial items, never compact or rewrite their wording."""
    section = next((s for s in data.get('story', []) if s.get('id') == key), {})
    values = section.get('items') or data.get(key) or data.get(fallback or key) or []
    if isinstance(values, str):
        values = [values]
    return [value for value in values if isinstance(value, str) and value.strip()]


def _sources(data):
    from .presentation import _public_url
    urls = []
    for source in (data.get('publication_sources') or data.get('sources') or data.get('evidence') or []):
        if not isinstance(source, dict):
            continue
        url = _public_url(source.get('url') or source.get('source_url', ''))
        if url and url not in urls:
            urls.append(url)
    return urls


def _header(data, parts, mode):
    from .reader_infographic import _text, INK, GREEN, MUTED
    labels = {'mechanism': 'МЕХАНИЗМ', 'infrastructure': 'РЕСУРСЫ И РАЗВЁРТЫВАНИЕ', 'applicability': 'ПРИМЕНЕНИЕ И ГРАНИЦЫ'}
    parts.append(('text', 54, 30, 'VV FRONTIER · ' + labels[mode], 17, GREEN, True))
    y = _text(parts, data.get('title') or 'Прикладной разбор технологии', 54, 78, 972, 42, INK, True, gap=54) + 22
    if mode != 'applicability':
        problem = data.get('problem') or data.get('summary')
        if problem:
            y = _text(parts, problem, 54, y, 972, 23, MUTED, gap=31) + 24
    return y


def _footer(data, parts, y, caption):
    from .reader_infographic import _text, MUTED
    y = _text(parts, caption, 54, y + 6, 972, 20, MUTED, gap=27) + 10
    for url in _sources(data):
        y = _text(parts, 'Источник: ' + url, 54, y + 4, 972, 17, MUTED, gap=23)
    return y + 26


def _panel(parts, label, values, x, y, width, *, fill, active=False, size=23):
    from .reader_infographic import _text, INK, GREEN, WHITE, LINE
    at = y + 25
    start = len(parts)
    at = _text(parts, label, x + 28, at, width - 56, 17, GREEN, True, gap=23) + 18
    for value in values:
        at = _text(parts, value, x + 28, at, width - 56, size, INK, gap=round(size * 1.34)) + 14
    height = at - y + 12
    parts.insert(start, ('rect', x, y, width, height, fill, 22))
    if active:
        parts.insert(start + 1, ('outline_rect', x + 2, y + 2, width - 4, height - 4, GREEN, 3, 20))
    return y + height


def _mechanism(data, parts, y, active):
    from .reader_infographic import _mechanism_steps, _text, INK, MUTED, GREEN, WHITE, MINT, LINE, NO_COMPARISON
    steps = _mechanism_steps(data)
    if len(steps) != 3 or any(not step for step in steps):
        raise ValueError('Для пошаговой анимации нужны ровно три полных шага механизма.')
    y = _text(parts, 'Механизм по шагам', 54, y, 972, 29, INK, True, gap=38) + 10
    y = _text(parts, NO_COMPARISON, 54, y, 972, 20, MUTED, gap=27) + 24
    # A static connecting path encodes dependency, not duration or improvement.
    for index, step in enumerate(steps):
        start = len(parts)
        label = 'ШАГ ' + str(index + 1) + (' · СЕЙЧАС В СХЕМЕ' if index == active else '')
        at = _text(parts, label, 148, y + 22, 846, 17, GREEN if index == active else MUTED, True, gap=23) + 14
        end = _text(parts, step, 148, at, 846, 25, INK, gap=34) + 24
        height = end - y
        if index < 2:
            parts.insert(start, ('line', 80, y + 30, 80, end + 48, LINE, 4))
            start += 1
        parts.insert(start, ('rect', 120, y, 920, height, MINT if index == active else WHITE, 24))
        parts.insert(start + 1, ('circle', 80, y + 34, 16, GREEN if index == active else LINE))
        parts.insert(start + 2, ('circle', 80, y + 34, 6, WHITE))
        y = end + 18
    scenario = data.get('use_case') or data.get('audience')
    if scenario:
        y = _panel(parts, 'РАБОЧИЙ СЦЕНАРИЙ', [scenario], 40, y + 6, 1000, fill=WHITE) + 18
    return y, MECHANISM_CAPTION


def _infrastructure(data, parts, y, active):
    from .reader_infographic import _text, INK, MUTED, WHITE, MINT, LINE, GREEN
    y = _text(parts, 'Стек требований из отчёта', 54, y, 972, 29, INK, True, gap=38) + 12
    y = _text(parts, 'Слои показывают зависимости развёртывания; доступность и стоимость не подразумеваются.', 54, y, 972, 20, MUTED, gap=27) + 22
    resources = _items(data, 'resources', 'infrastructure') or ['Ресурсы и полная стоимость в отчёте не определены; нужно уточнить.']
    # Staggered layer widths distinguish a dependency stack from process cards.
    for index, resource in enumerate(resources):
        inset = min(index, 2) * 22
        y = _panel(parts, 'ТРЕБОВАНИЯ / РЕСУРСЫ', [resource], 40 + inset, y, 1000 - inset,
                   fill=MINT if index == active else WHITE) + 14
        if index + 1 < len(resources):
            parts.append(('line', 72 + inset, y - 9, 72 + inset, y + 1, LINE, 3))
    limits = _items(data, 'limitations', 'cons')
    selected_limits = limits[:1] or ['Границы развёртывания в отчёте не определены; нужно уточнить.']
    y = _panel(parts, 'ГОТОВНОСТЬ И ОГРАНИЧЕНИЯ', selected_limits, 40, y + 6, 1000,
               fill='#fae8bc', active=active is not None and active >= len(resources)) + 16
    if data.get('next_step'):
        y = _panel(parts, 'ПЕРЕД ПИЛОТОМ', [data['next_step']], 40, y, 1000, fill=WHITE) + 18
    return y, INFRASTRUCTURE_CAPTION


def _applicability(data, parts, y, active):
    from .reader_infographic import _text, INK, MUTED, WHITE, MINT, GREEN
    problem = data.get('problem') or data.get('summary') or 'Рабочая проблема в отчёте не определена.'
    y = _text(parts, 'РАБОЧАЯ ПРОБЛЕМА', 54, y, 972, 17, GREEN, True, gap=23) + 14
    y = _text(parts, problem, 54, y, 972, 29, INK, True, gap=39) + 28
    # A narrow audience column and wide scenario column create a text briefing.
    audience = data.get('audience') or 'Адресат в отчёте не определён.'
    scenario = data.get('use_case') or 'Рабочий сценарий в отчёте не определён.'
    left = _panel(parts, 'КОМУ ПОЛЕЗНО', [audience], 40, y, 332, fill=MINT, active=active == 0, size=22)
    right = _panel(parts, 'РАБОЧИЙ СЦЕНАРИЙ', [scenario], 392, y, 648, fill=WHITE, active=active == 0)
    y = max(left, right) + 20
    takeaway = data.get('public_takeaway') or data.get('verdict')
    if not takeaway:
        section = next((s for s in data.get('story', []) if s.get('id') == 'takeaway'), {})
        takeaway = section.get('text') or 'Практический вывод в отчёте не определён.'
    y = _panel(parts, 'ЦЕННОСТЬ ДЛЯ РАБОЧЕЙ ЗАДАЧИ', [takeaway], 40, y, 1000, fill=WHITE, active=active == 1, size=25) + 20
    limits = _items(data, 'limitations', 'cons')
    y = _panel(parts, 'ГРАНИЦЫ ПРИМЕНЕНИЯ', limits[:1] or ['Границы применимости в отчёте не определены.'],
               40, y, 1000, fill='#fae8bc', active=active == 2) + 16
    if data.get('next_step'):
        y = _panel(parts, 'С ЧЕГО НАЧАТЬ', [data['next_step']], 40, y, 1000, fill=WHITE) + 18
    return y, APPLICABILITY_CAPTION


def layout(data, active=None, *, animation=False, mode=None):
    """Return complete native-size primitives; oversized animation is rejected."""
    from .reader_infographic import W, PAPER
    mode = mode or profile_mode(data)
    if mode not in {'mechanism', 'infrastructure', 'applicability'}:
        raise ValueError('Для адаптивной композиции нужен поддерживаемый профиль.')
    if active is not None and (type(active) is not int or active < 0):
        raise ValueError('Недопустимый фокус анимации.')
    parts = []
    y = _header(data, parts, mode)
    builders = {'mechanism': _mechanism, 'infrastructure': _infrastructure, 'applicability': _applicability}
    y, caption = builders[mode](data, parts, y, active)
    y = _footer(data, parts, y, caption)
    height = int(y) + int(y) % 2
    if animation and height > MAX_ANIMATION_HEIGHT:
        raise ValueError('Полные выбранные формулировки и источники не помещаются в читаемый анимационный кадр.')
    if height > 9000:
        raise ValueError('Инфографика слишком длинная; сократите редакционные поля.')
    parts.insert(0, ('rect', 0, 0, W, height, PAPER, 0))
    return height, parts


def phases(data):
    """Reading order only: no timing scale, animated metric or speed claim."""
    if profile_mode(data) == 'infrastructure':
        return range(len(_items(data, 'resources', 'infrastructure') or [None]) + 1)
    return range(3)


def frame(data, active):
    from .reader_infographic import _raster_parts
    height, parts = layout(data, active, animation=True)
    return _raster_parts(height, parts)
