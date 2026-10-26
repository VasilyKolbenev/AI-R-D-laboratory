"""Immutable local public dossiers; never deployment or provider dispatch.

The projection is deliberately independent from private run/audit objects.
Literal source binding and machine judgments do not prove scientific truth.
"""
from copy import deepcopy
import hashlib
import html
import json
import math
import re

VERSION = 'public-dossier-v1'
FOCUSES = {'comparison', 'mechanism', 'applicability', 'disagreement'}
BASES = {'unknown', 'hypothesis', 'author_claim', 'external_measurement', 'estimate',
         'own_measurement'}
PUBLIC_INSTRUCTIONS = '''
В этом же финальном вызове можно добавить один необязательный <lab_public> JSON:
{"version":"public-addendum-v1","english_abstract":{"language":"en","text":
"An actual substantive English abstract of this source analysis and its limitations."},
"evidence_story":{"focus":"applicability","summary":"Главный доказательный вывод",
"limitations":["Что не установлено"],"source_refs":["точный публичный URL источника"]}}.
focus comparison|mechanism|applicability|disagreement; summary до700, limitations до4 строк
по300, source_refs до6 URL уже присутствующих в публичных источниках отчёта.
English abstract необязателен: только настоящий английский текст 80..1800 символов.
Не называй русский текст английским; не заявляй о ручном переводе или независимой проверке.
Не включай память, private IDs, локальные пути, prompt, ключи, внутренний аудит.
Различай результат авторов, оценку и собственный замер. Нет измерения — не выдумывай число.
Все числа английского резюме и evidence_story должны уже быть в обычном финальном отчёте.
Необязательный блок до12000 UTF-8 байт. Никаких дополнительных вызовов для оформления.
'''


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False)


def _text(value, maximum=2000):
    if not isinstance(value, str):
        return ''
    from .presentation import _public_url, _PRIVATE_ID, _BOT_SECRET
    value = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', value)
    value = _PRIVATE_ID.sub('[ID omitted]', value)
    value = _BOT_SECRET.sub('[secret omitted]', value)
    value = re.sub(r'https?://[^\s<>"\]]+',
                   lambda match: _public_url(match[0]) or '[private URL omitted]', value)
    value = re.sub(r'\bsk-[A-Za-z0-9_-]{16,}\b', '[secret omitted]', value)
    return value.strip()[:maximum]


def _texts(values, maximum=500, count=8):
    if not isinstance(values, list):
        return []
    return [text for value in values[:count] if (text := _text(value, maximum))]


def _items(value, count):
    return value[:count] if isinstance(value, list) else []


def _english(value):
    if not isinstance(value, dict) or value.get('language') != 'en':
        return None
    text = _text(value.get('text'), 1800)
    words = re.findall(r'\b[A-Za-z]+\b', text.lower())
    letters = [character for character in text if character.isalpha()]
    latin = sum(character.isascii() for character in letters)
    common = {'the', 'and', 'of', 'this', 'is', 'in', 'with', 'a', 'an', 'to', 'for'}
    if (len(text) < 80 or len(words) < 12 or not letters
            or latin / len(letters) < .9 or len(common.intersection(words)) < 2):
        return None
    return {'language': 'en', 'text': text}


def _story(value, allowed_urls=None):
    if (not isinstance(value, dict) or not isinstance(value.get('focus'), str)
            or value.get('focus') not in FOCUSES):
        return None
    from .presentation import _public_url
    summary = _text(value.get('summary'), 700)
    if not summary:
        return None
    urls = []
    for item in _items(value.get('source_refs'), 6):
        url = _public_url(item)
        if url and (allowed_urls is None or url in allowed_urls) and url not in urls:
            urls.append(url)
    return {'focus': value['focus'], 'summary': summary,
            'limitations': _texts(value.get('limitations'), 300, 4), 'source_refs': urls}


def parse_public(output):
    """Parse an optional addendum locally; malformed/mislabeled output is absent."""
    if not isinstance(output, str):
        return {}
    matches = re.findall(r'<lab_public>\s*(.*?)\s*</lab_public>', output, re.S)
    if len(matches) != 1 or len(matches[0].encode('utf-8')) > 12000:
        return {}
    try:
        value = json.loads(matches[0])
    except (ValueError, TypeError):
        return {}
    if not isinstance(value, dict) or value.get('version') != 'public-addendum-v1':
        return {}
    result = {}
    english, story = _english(value.get('english_abstract')), _story(value.get('evidence_story'))
    if english:
        result['english_abstract'] = english
    if story:
        result['evidence_story'] = story
    return result


def _sources(presentation):
    from .presentation import _public_url
    values = presentation.get('publication_sources') or presentation.get('sources') or []
    if not isinstance(values, list):
        return []
    result = []
    for item in values[:12]:
        if not isinstance(item, dict):
            continue
        url = _public_url(item.get('url') or item.get('source_url'))
        if url and not any(source['url'] == url for source in result):
            result.append({'title': _text(item.get('title'), 200), 'url': url})
    return result


def attach_public(presentation, output):
    result = deepcopy(presentation)
    result.pop('english_abstract', None)
    result.pop('evidence_story', None)
    addendum = parse_public(output)
    from .presentation import display_report, _literal_numbers
    ordinary = re.sub(r'<lab_public>.*?</lab_public>', '', output or '', flags=re.S | re.I)
    available_numbers = _literal_numbers(display_report(ordinary))
    if ('english_abstract' in addendum and
            not _numbers_supported(addendum['english_abstract']['text'], available_numbers)):
        del addendum['english_abstract']
    if 'evidence_story' in addendum:
        story = addendum['evidence_story']
        statement = ' '.join([story['summary'], *story['limitations']])
        if not _numbers_supported(statement, available_numbers):
            del addendum['evidence_story']
    urls = {source['url'] for source in _sources(presentation)}
    if 'evidence_story' in addendum:
        addendum['evidence_story'] = _story(addendum['evidence_story'], urls)
    result.update(addendum)
    return result


def _numbers_supported(statement, available):
    from .presentation import _literal_numbers
    return _literal_numbers(statement).issubset(available)


def _side(value):
    value = value if isinstance(value, dict) else {}
    number = value.get('value')
    if type(number) not in (int, float) or not math.isfinite(number) or number < 0:
        number = None
    basis = value.get('basis') if isinstance(value.get('basis'), str) else 'unknown'
    return {'label': _text(value.get('label'), 120), 'value': number,
            'basis': basis if basis in BASES else 'unknown'}


def _project(presentation):
    if not isinstance(presentation, dict):
        raise ValueError('Нужен сохранённый публичный разбор.')
    payload = {'version': VERSION, 'title': _text(presentation.get('title'), 240),
               'summary': _text(presentation.get('summary') or presentation.get('verdict'), 2400),
               'post_text': _text(presentation.get('post_text'), 7000),
               'sources': _sources(presentation), 'story': []}
    for item in _items(presentation.get('story'), 9):
        if isinstance(item, dict):
            payload['story'].append({'title': _text(item.get('title'), 180),
                                     'text': _text(item.get('text'), 2400),
                                     'items': _texts(item.get('items'), 500)})
    analysis = presentation.get('applied_analysis')
    if isinstance(analysis, dict):
        rows = []
        for row in _items(analysis.get('rows'), 8):
            if not isinstance(row, dict):
                continue
            fields = ('metric', 'definition', 'unit', 'direction', 'conditions',
                      'comparability', 'comparability_reason')
            safe = {key: _text(row.get(key), 700) for key in fields}
            safe.update(baseline=_side(row.get('baseline')), candidate=_side(row.get('candidate')))
            rows.append(safe)
        payload['applied_analysis'] = {'rows': rows,
                                     'unknowns': _texts(analysis.get('unknowns'), 500)}
    english = _english(presentation.get('english_abstract'))
    story = _story(presentation.get('evidence_story'), {s['url'] for s in payload['sources']})
    if english:
        payload['english_abstract'] = english
    if story:
        payload['evidence_story'] = story
    return payload


def preview(presentation):
    payload = _project(presentation)
    return {'projection_hash': hashlib.sha256(_canonical(payload).encode('utf-8')).hexdigest(),
            'payload': payload,
            'notice': 'Локальный preview. Отдельный апрув сохранит эту публичную версию; '
                      'размещения в интернете и отправки в Telegram нет.'}


def validate_asset(kind, payload):
    if kind != 'public_dossier' or not isinstance(payload, dict):
        raise ValueError('Некорректный публичный объект.')
    # Re-projecting a public payload must preserve every byte/field. This rejects
    # unknown nested keys during restore as well as direct export attempts.
    if payload.get('version') != VERSION or _project(payload) != payload:
        raise ValueError('Публичная версия содержит непубличные или некорректные поля.')
    if not payload.get('title') or len(_canonical(payload).encode('utf-8')) > 80000:
        raise ValueError('Публичная версия пуста или превышает лимит.')
    return True


def approve(store, presentation, projection_hash, consent):
    result = preview(presentation)
    if consent is not True or projection_hash != result['projection_hash']:
        raise ValueError('Нужен отдельный апрув точной публичной версии.')
    validate_asset('public_dossier', result['payload'])
    from .research_assets import Assets
    return Assets(store).put('public_dossier', result['payload'])


def render_html(payload):
    validate_asset('public_dossier', payload)
    escape = lambda value: html.escape(str(value), quote=True)
    title = escape(payload['title'])
    parts = ['<!doctype html><html lang="ru"><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width,initial-scale=1">',
             '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
             'style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">',
             '<title>' + title + '</title><style>',
             'body{max-width:860px;margin:32px auto;padding:0 20px;color:#192d39;'
             'font:17px/1.7 system-ui;background:#fafcfb}h1{line-height:1.2}'
             'article,section{margin:28px 0}p,li{overflow-wrap:anywhere}'
             '.note{color:#50616e;font-size:14px}.metric{border:1px solid #aabac0;'
             'padding:16px;border-radius:8px}a{color:#145c75}',
             '</style><main><h1>' + title + '</h1>',
             '<p class="note">Анализ источников. Совпадение цитаты и модельная оценка '
             'не являются независимым воспроизведением или доказательством истины.</p>']
    if payload['summary']:
        parts.append('<p>' + escape(payload['summary']) + '</p>')
    if payload.get('english_abstract'):
        parts.append('<section lang="en"><h2>English abstract</h2><p>' +
                     escape(payload['english_abstract']['text']) + '</p></section>')
    for item in payload['story']:
        parts.append('<section><h2>' + escape(item['title']) + '</h2><p>' +
                     escape(item['text']) + '</p><ul>')
        parts.extend('<li>' + escape(text) + '</li>' for text in item['items'])
        parts.append('</ul></section>')
    if payload.get('evidence_story'):
        story = payload['evidence_story']
        parts.append('<section><h2>Основания и ограничения</h2><p>' +
                     escape(story['summary']) + '</p><ul>')
        parts.extend('<li>' + escape(text) + '</li>' for text in story['limitations'])
        parts.append('</ul></section>')
    bases = {'unknown': 'неизвестно', 'hypothesis': 'гипотеза', 'author_claim': 'результат авторов',
             'external_measurement': 'внешний замер', 'estimate': 'оценка',
             'own_measurement': 'собственный замер'}
    for row in payload.get('applied_analysis', {}).get('rows', []):
        parts.append('<article class="metric"><h3>' + escape(row['metric']) + '</h3>')
        for side in ('baseline', 'candidate'):
            value = row[side]
            number = 'неизвестно' if value['value'] is None else str(value['value'])
            parts.append('<p>' + escape(value['label'] + ': ' + number + ' ' + row['unit']) +
                         ' · ' + escape(bases[value['basis']]) + '</p>')
        parts.append('<p>' + escape(row['conditions']) + '</p><p>' +
                     escape(row['comparability_reason']) + '</p></article>')
    parts.append('<section><h2>Источники</h2><ul>')
    for source in payload['sources']:
        parts.append('<li><a rel="noopener noreferrer" href="' + escape(source['url']) + '">' +
                     escape(source['title'] or source['url']) + '</a></li>')
    parts.append('</ul></section></main></html>')
    return ''.join(parts)
