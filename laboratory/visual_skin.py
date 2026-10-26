"""Deterministic paint selection for the validated, compact mechanism graph.

Skins do not rewrite facts or request a model. Selection metadata becomes part
of the exact presentation already bound to the owner's publication approval.
"""
from __future__ import annotations

from .visual_policy import _has_supported_comparison

VERSION = 'skins-v1'
ROTATION_VERSION = 'alternate-v1'


def rotation_skin(position):
    """One immutable appearance for all assets of a numbered release."""
    if type(position) is not int or not 1 <= position <= 1_000_000_000:
        raise ValueError('Некорректный номер выпуска для чередования оформления.')
    key = 'dashboard' if position % 2 else 'blackboard'
    result = _skin(key, 'Чередование выпусков: дашборд → доска. Выпуск №'+str(position)+'.')
    result['rotation'] = {'version': ROTATION_VERSION, 'position': position}
    return result


def rotation_position(skin):
    """Recognize complete internally consistent release metadata."""
    if not isinstance(skin,dict) or skin.get('version') != VERSION:
        return None
    rotation=skin.get('rotation')
    if not isinstance(rotation,dict) or rotation.get('version') != ROTATION_VERSION:
        return None
    position=rotation.get('position')
    if type(position) is not int or not 1 <= position <= 1_000_000_000:
        return None
    if skin.get('id') != ('dashboard' if position % 2 else 'blackboard'):
        return None
    return position


def _skin(key, reason):
    return {'version': VERSION, 'id': key,
            'label': 'Схема на доске' if key == 'blackboard' else 'Технический дашборд',
            'reason': reason}


def select_visual_skin(data):
    """Legacy standalone appearance; App/Publisher pin numbered release skins.

    The publication pipeline overrides this content-based fallback before any
    owner preview, signature or asset render. It remains for standalone older
    consumers that have no publication queue context.
    """
    if not isinstance(data, dict):
        return _skin('dashboard', 'Нет проверенной схемы; сохранён основной стиль.')
    if _has_supported_comparison(data):
        return _skin('dashboard', 'Есть сопоставимые числа с условиями и основаниями; сохранён стиль графиков.')
    story = data.get('motion_story')
    if not isinstance(story, dict) or story.get('version') != 'dataflow-v1':
        return _skin('dashboard', 'Нет проверенной схемы; сохранён основной стиль.')
    if story.get('kind') == 'inference':
        return _skin('dashboard', 'Поток инференса и параллельные операции показаны в техническом дашборде.')
    if story.get('kind') in {'feedback', 'process', 'review'}:
        return _skin('blackboard', 'Механизм без подтверждённого числового сравнения показан как схема на доске.')
    return _skin('dashboard', 'Тип схемы не определён; сохранён основной стиль.')
