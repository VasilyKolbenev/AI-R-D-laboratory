"""Bounded, model-free rendering of a research result for people and Telegram.

New research can return one small presentation block in its existing invocation.
Old reports use labelled extractive rendering. Neither path measures performance.
"""
from __future__ import annotations

import hashlib
import html
import io
import ipaddress
import json
import math
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import textwrap
from urllib.parse import parse_qsl, urlsplit

from .visual_policy import VISUAL_FOCUS_VALUES, select_visual_profile


VERSION = 2
MAX_BLOCK_BYTES = 20_000
POST_LIMIT = 3500
SHORT_LIMIT = 900

def publication_rules():
    return {'version':'applied-channel-post-v1','language':'ru','maximum_utf16':POST_LIMIT,
            'reading_target':'до пяти минут вместе с визуалом',
            'sections':['Рабочая проблема','Кому полезно и сценарий','Как работает','Результаты авторов и условия',
                        'Ограничения','Настройка, инфраструктура и полная стоимость','Вывод для проекта','Следующий шаг','Источники'],
            'delivery':'Один готовый текст поста, инфографика и анимация; только в личный чат владельца.',
            'exclude':['служебное вступление','повторное резюме','пометка черновика','пояснения о работе лаборатории',
                       'ID и личная память','автоматическое вложение полного отчёта'],
            'evidence':'Сохранять авторство, условия сравнения и границы. Не обещать измеренный эффект для другой задачи.',
            'missing':'Не подставлять ноль вместо неизвестного; неполный или обрезанный формат не выдавать за готовый.'}
UNKNOWN = 'Не определено в отчёте; нужно уточнить.'
PROMPT_INSTRUCTIONS = '''
В этом же исследовательском ответе, без отдельного вызова, добавь ровно один блок <lab_presentation>{"title":"Название","problem":"Прикладная проблема","audience":"Кому полезно","use_case":"Рабочий сценарий","mechanism":["Шаг 1","Шаг 2","Шаг 3"],"findings":["Результат авторов и условия"],"limitations":["Граница или риск"],"resources":["Настройка, инфраструктура, расходы"],"public_takeaway":"Применимость к задачам читателя при названных условиях","next_step":"Дешёвый следующий шаг","evidence":[{"id":"e1","claim":"Проверяемое утверждение","source_url":"https://primary.example/paper","locator":"Таблица или раздел","excerpt":"Дословный фрагмент ТВОЕГО основного отчёта с этим утверждением и числами","limitations":"Условия и что не проверено"}],"comparisons":[{"label":"Название ОДНОГО показателя","unit":"Единица","baseline_label":"С чем сравнивали","baseline_value":10,"result_label":"Метод авторов","result_value":8,"conditions":"Задача, модель, нагрузка, условия; авторские данные, собственных замеров нет","evidence_ids":["e1"]}]}</lab_presentation>.
Сначала пиши основной отчёт: прикладная проблема → адресат/сценарий → механизм → baseline и результаты авторов с условиями → ограничения → настройка/инфраструктура/полная стоимость → практический вывод и следующий шаг. Повторно исследовать или отдельно переформатировать моделью не нужно. Блок не более 20000 UTF-8 байт, пиши кратко. Лимиты символов: title160, problem500, audience300, use_case400, public_takeaway500, next_step300; findings/limitations/resources до3 строк по400; mechanism ровно3 шага по160, описывающих конкретный механизм технологии.
evidence до4: id латиница до40, claim180, locator120, excerpt300, limitations160, source_url350. URL разрешены ТОЛЬКО в evidence.source_url; каждый URL также явно укажи в основном отчёте, только публичный первоисточник. excerpt должен дословно присутствовать в основном отчёте; это фиксация основания из отчёта, не независимая верификация источника. comparisons до3, только реальные сопоставимые числа, явно приведённые в связанных excerpt и основном отчёте; label120, unit40, baseline_label/result_label80, conditions300, evidence_ids до4. Каждое сравнение отдельного показателя в одной единице, не смешивай шкалы. Не подставляй 0 вместо неизвестного; нет обоснованных чисел — comparisons:[], объясни отсутствие в findings. Цифры примера10/8 не являются данными, не копируй их. Авторские замеры, расходы и собственные измерения разделяй. Публичный вывод касается задач/проектов читателя; не решения о перестройке лаборатории и не общего «внедрение отложить». Не включай персональные данные, HTML, команды, личные настройки, профиль владельца и секреты. Никаких дополнительных модельных прогонов для исправления блока.
'''
PROMPT_INSTRUCTIONS += '\nПравила готового поста (публичная структура; служебные сообщения в пост не включать): '+json.dumps(publication_rules(),ensure_ascii=False)+'\n'
PROMPT_INSTRUCTIONS += ('\nВ тот же блок lab_presentation можно добавить необязательное поле '
                        '"visual_focus":"auto". Допустимы только auto, comparison, mechanism, infrastructure, applicability. '
                        'Это выбор композиции визуала, а не изменение текста поста. comparison допустим только с '
                        'подтверждёнными сопоставимыми числами; при их отсутствии оставь comparisons:[] и выбери '
                        'mechanism либо applicability. Поле не требует дополнительного модельного вызова.\n')
PROMPT_INSTRUCTIONS += ('\nВ том же вызове разрешено необязательное поле "motion" (до 10000 UTF-8 байт): '
                        '{"version":"dataflow-v1","kind":"process","nodes":[],"edges":[],"baseline":'
                        '{"status":"unknown","label":"Baseline неизвестен","note":"В отчёте не установлен"},"notes":[]}. '
                        'kind: review|feedback|inference|process. До 12 nodes: {id,label,role,lane,evidence_ids}; '
                        'role: input|compute|decision|memory|output|data, lane: baseline|technology. '
                        'До 16 edges: {id,from,to,label,kind,evidence_ids}; kind: data|feedback|control. '
                        'ID латиницей до40, уникальны во всём графе; from/to указывают существующие узлы. '
                        'Подписи до64 символов, без чисел, кода и URL, дословно присутствуют в связанных evidence.excerpt; '
                        'evidence_ids содержат 1–4 ID из evidence этого же блока. '
                        'baseline.status: reported|conceptual|unknown; label64, note400. '
                        'reported требует дословного label и note в отчёте; conceptual явно назови концептуальным в note '
                        '(только для его узлов/рёбер разрешены пустые evidence_ids); unknown не имеет узлов baseline. '
                        'notes до5 строк по400, без URL/кода. Не придумывай baseline, оборудование, скорость или обратную связь. '
                        'Нет дословной опоры — опусти motion; схема будет собрана из сохранённого механизма. '
                        'Неверный motion отбрасывается локально и не требует повторного модельного вызова.\n')

_FIELDS = {'title': 160, 'verdict': 240, 'summary': 400, 'setup': 240, 'next_step': 300}
_ARRAYS = {'applicability', 'pros', 'cons', 'metrics', 'infrastructure'}
_STORY_TEXT = {'problem':500,'audience':300,'use_case':400,'public_takeaway':500}
_STORY_ARRAYS = {'findings','limitations','resources'}
_BLOCK = re.compile(r'<lab_presentation>\s*(.*?)\s*</lab_presentation>', re.S | re.I)
_PRIVATE_ID = re.compile(r'\b[0-9a-f]{32,64}\b', re.I)
_BOT_SECRET = re.compile(r'(?<![0-9])[0-9]{6,20}:[A-Za-z0-9_-]{20,200}(?![A-Za-z0-9_-])')
_URL = re.compile(r'https?://[^\s<>\"\']+', re.I)


def utf16_len(value):
    return len(str(value).encode('utf-16-le', errors='replace')) // 2


def _limit(value, limit):
    value = str(value)
    if utf16_len(value) <= limit:
        return value
    result, size = [], 0
    for character in value:
        units = 2 if ord(character) > 0xFFFF else 1
        if size + units > max(0, limit - 1):
            break
        result.append(character)
        size += units
    return ''.join(result).rstrip() + '…'


def _clean(value):
    if not isinstance(value, str):
        return ''
    value = value.encode('utf-8', errors='replace').decode('utf-8')
    value = re.sub(r'(?is)<(?:script|style)\b[^>]*>.*?</(?:script|style)>', '', value)
    value = html.unescape(re.sub(r'<[^>]*>', '', value))
    value = re.sub(r'\[([^\]]+)\]\(https?://[^)]+\)', r'\1', value)
    value = re.sub(r'\[(?:P|S)\d+(?:[–-](?:P|S)?\d+)?\]', '', value)
    value = _PRIVATE_ID.sub('[ID скрыт]', value)
    value = _BOT_SECRET.sub('[секрет скрыт]', value)
    value = _URL.sub(lambda match: _public_url(match.group()) or '[приватная ссылка скрыта]', value)
    value = re.sub(r'(?m)^\s*[-*#>]+\s*', '', value)
    value = value.replace('**', '').replace('`', '').replace('__', '')
    value = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', value)
    return re.sub(r'\s+', ' ', value).strip(' |\t\r\n')


def display_report(output):
    """Hide machine blocks, including malformed trailing blocks, from public text."""
    output = output if isinstance(output, str) else ''
    for tag in ('lab_memory_review', 'lab_presentation', 'lab_research', 'lab_critic', 'lab_public'):
        output = re.sub(r'(?is)<' + tag + r'>.*?</' + tag + r'>', '', output)
        output = re.sub(r'(?is)<' + tag + r'>.*\Z', '', output)
    return output.strip()


strip_service_blocks = display_report


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            # Preserve an invalidity marker so a duplicate inside optional
            # motion cannot invalidate otherwise valid publication prose.
            result['_lab_duplicate_json_key'] = True
        result[key] = value
    return result


def _duplicate_keys(value):
    if isinstance(value,dict):
        return '_lab_duplicate_json_key' in value or any(_duplicate_keys(item) for item in value.values())
    if isinstance(value,list):
        return any(_duplicate_keys(item) for item in value)
    return False


def _structured(output):
    blocks = _BLOCK.findall(output)
    if not blocks:
        return None, ['Структурированный блок отсутствует: использованы фрагменты готового отчёта.']
    if len(blocks) != 1 or len(blocks[0].encode('utf-8', errors='replace')) > MAX_BLOCK_BYTES + 10_000:
        return None, ['Структурированный блок неоднозначен или превышает лимит; использован готовый отчёт.']
    try:
        data = json.loads(blocks[0], object_pairs_hook=_pairs)
        block_size=len(blocks[0].encode('utf-8', errors='replace'))
        core={key:value for key,value in data.items() if key!='motion'} if isinstance(data,dict) else data
        if _duplicate_keys(core):
            raise ValueError('Duplicate key')
        if (block_size>MAX_BLOCK_BYTES and (not isinstance(data,dict) or 'motion' not in data)) or len(json.dumps(core,ensure_ascii=False).encode('utf-8',errors='replace'))>MAX_BLOCK_BYTES:
            raise ValueError('Oversized presentation core')
        if not isinstance(data, dict) or set(data) - (set(_FIELDS) | _ARRAYS | {'mechanism','evidence','comparisons','visual_focus','motion','applied_analysis','review_dispositions','evidence_checks'} | set(_STORY_TEXT) | _STORY_ARRAYS):
            raise ValueError('Unknown fields')
        visual_focus = data.get('visual_focus', 'auto')
        if not isinstance(visual_focus, str) or visual_focus not in VISUAL_FOCUS_VALUES:
            raise ValueError('Invalid visual focus')
        result = {}
        for key, maximum in _FIELDS.items():
            value = data.get(key, '')
            if not isinstance(value, str) or utf16_len(value) > maximum or '<' in value or '>' in value or _URL.search(value):
                raise ValueError('Invalid text')
            result[key] = _clean(value)
        for key, maximum in _STORY_TEXT.items():
            value=data.get(key,'')
            if not isinstance(value,str) or utf16_len(value)>maximum or '<' in value or '>' in value or _URL.search(value):
                raise ValueError('Invalid story text')
            result[key]=_clean(value)
        result['verdict']=result['verdict'] or result['public_takeaway']
        result['summary']=result['summary'] or result['problem']
        if not result['title'] or not result['verdict'] or not result['summary']:
            raise ValueError('Missing summary')
        for key in _ARRAYS:
            values = data.get(key, [])
            if not isinstance(values, list) or len(values) > 3:
                raise ValueError('Invalid list')
            if any(not isinstance(value, str) or utf16_len(value) > 240 or '<' in value or '>' in value or _URL.search(value) for value in values):
                raise ValueError('Invalid list item')
            result[key] = [_clean(value) for value in values if _clean(value)]
        for key in _STORY_ARRAYS:
            values=data.get(key,[])
            if not isinstance(values,list) or len(values)>3 or any(not isinstance(value,str) or utf16_len(value)>400 or '<' in value or '>' in value or _URL.search(value) for value in values):
                raise ValueError('Invalid story list')
            result[key]=[_clean(value) for value in values if _clean(value)]
        mechanism = data.get('mechanism', [])
        if mechanism and (not isinstance(mechanism, list) or len(mechanism) != 3 or any(
                not isinstance(value, str) or not value.strip() or utf16_len(value) > 160 or '<' in value or '>' in value or _URL.search(value) for value in mechanism)):
            raise ValueError('Invalid mechanism')
        result['mechanism'] = [_clean(value) for value in mechanism]
        result['_auto_evidence']=data.get('evidence',[])
        result['_auto_comparisons']=data.get('comparisons',[])
        result['_evidence_checks']=data.get('evidence_checks')
        result['_applied_analysis']=data.get('applied_analysis')
        result['_review_dispositions']=data.get('review_dispositions')
        result['_visual_focus']=visual_focus
        # The optional attachment is checked after report evidence is validated.
        # A malformed graph must not discard a valid publication block.
        result['_motion']=data.get('motion')
        return result, []
    except (ValueError, TypeError, RecursionError):
        return None, ['Структурированный блок не прошёл проверку; использованы фрагменты готового отчёта.']


def _public_url(value):
    if not isinstance(value, str) or len(value) > 1800 or _BOT_SECRET.search(value):
        return ''
    value = value.strip().rstrip('.,;:!?)]}')
    try:
        parts = urlsplit(value)
        host = parts.hostname
        if (parts.scheme not in {'http', 'https'} or not host or parts.username or parts.password
                or parts.port not in {None, 80, 443} or any(character.isspace() for character in value)):
            return ''
        if host.casefold() in {'localhost', 'localhost.localdomain'} or host.casefold().endswith(('.localhost', '.local', '.internal')):
            return ''
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if '.' not in host or host.endswith('.'):
                return ''
        else:
            if not address.is_global:
                return ''
        if any(re.search(r'token|secret|password|signature|credential|api.?key|auth|session', key, re.I)
               for key, _ in parse_qsl(parts.query)):
            return ''
        return value
    except ValueError:
        return ''


def _literal_numbers(text):
    """A bounded literal check, not a check of metric semantics or science."""
    values=set()
    for token in re.findall(r'(?<![\w.,])[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?(?!\w|[.,]\d)',text[:80_000]):
        try:
            number=Decimal(token.replace(',','.'))
            if number.is_finite():values.add(number)
        except InvalidOperation:pass
    return values


def _auto_support(evidence_rows, comparison_rows, report, allowed_urls):
    """Drop unsupported attachments locally, preserving the original report."""
    evidence,comparisons,issues=[],[],[]
    normalized_report=_clean(report)
    if not isinstance(evidence_rows,list) or len(evidence_rows)>4:
        issues.append('Автоматические доказательства: допустимо до 4 записей; неверный список отброшен.')
        evidence_rows=[]
    limits={'id':40,'claim':180,'source_url':350,'locator':120,'excerpt':300,'limitations':160}
    identifiers=set()
    for index,row in enumerate(evidence_rows):
        valid=isinstance(row,dict) and not (set(row)-set(limits))
        if valid:
            valid=all(isinstance(row.get(key),str) and row[key].strip() and utf16_len(row[key])<=maximum
                      and '<' not in row[key] and '>' not in row[key]
                      and (key=='source_url' or not _URL.search(row[key])) for key,maximum in limits.items())
        if valid:
            url=_public_url(row['source_url']);identifier=row['id']
            valid=bool(re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,39}',identifier) and identifier not in identifiers
                       and all(_clean(row[key]) for key in limits)
                       and url and url in allowed_urls and _clean(row['excerpt']) in normalized_report)
        if not valid:
            issues.append(f'Доказательство {index+1} отброшено: проверьте поля, публичный источник и дословный фрагмент отчёта.')
            continue
        identifiers.add(identifier)
        evidence.append({**{key:_clean(row[key]) for key in limits},'id':identifier,'source_url':url,'basis':'saved_report'})
    if not isinstance(comparison_rows,list) or len(comparison_rows)>3:
        issues.append('Автоматические сравнения: допустимо до 3 записей; неверный список отброшен.')
        comparison_rows=[]
    by_id={row['id']:row for row in evidence}
    text_limits={'label':120,'unit':40,'baseline_label':80,'result_label':80,'conditions':300}
    for index,row in enumerate(comparison_rows):
        valid=isinstance(row,dict) and not (set(row)-(set(text_limits)|{'baseline_value','result_value','evidence_ids'}))
        if valid:
            valid=all(isinstance(row.get(key),str) and row[key].strip() and utf16_len(row[key])<=maximum
                      and '<' not in row[key] and '>' not in row[key] and not _URL.search(row[key])
                      for key,maximum in text_limits.items())
        if valid:
            refs=row.get('evidence_ids');numbers=[row.get('baseline_value'),row.get('result_value')]
            valid=(isinstance(refs,list) and 1<=len(refs)<=4 and all(isinstance(ref,str) and ref in by_id for ref in refs)
                   and len(set(refs))==len(refs)
                   and all(type(number) in (int,float) and 0<=number<=1e100 and math.isfinite(number) for number in numbers))
        if valid:
            literals=_literal_numbers(' '.join(by_id[ref]['excerpt'] for ref in refs))
            valid=all(Decimal(str(number)) in literals for number in numbers)
        if not valid:
            issues.append(f'Сравнение {index+1} отброшено: нет полных условий, связанного доказательства или обоих чисел в его фрагменте отчёта.')
            continue
        comparisons.append({**{key:_clean(row[key]) for key in text_limits},
                            'baseline_value':numbers[0],'result_value':numbers[1],'evidence_ids':list(refs)})
    return evidence,comparisons,issues


def _publication_checks(data, automatic_issues, model_story):
    if data.get('provenance',{}).get('mode')=='editor_reviewed':
        sections={section['id']:section for section in data.get('story',[])}
        missing=[]
        for key,label in [('title','название'),('problem','проблема'),('audience','адресат'),('use_case','прикладной сценарий'),
                          ('public_takeaway','практический вывод'),('next_step','следующий шаг')]:
            if not data.get(key) or data[key]==UNKNOWN:missing.append('Не заполнено поле: '+label+'.')
        for key,label in [('mechanism','три шага механизма'),('findings','результаты'),('limitations','ограничения'),('resources','ресурсы')]:
            items=sections.get(key,{}).get('items',[])
            if not items or (key=='mechanism' and len(items)!=3):missing.append('Не заполнено: '+label+'.')
        return {'status':'incomplete' if missing else 'ready','issues':missing,'automatic':False,
                'numeric_data':'supported' if data.get('comparisons') else 'not_provided',
                'notice':'Проверена полнота редакторской версии; это ручная подготовка по сохранённому отчёту, не независимая научная проверка.'}
    issues=list(automatic_issues)
    if not model_story:
        issues.append('Нет полного автоматического блока: показано извлечение из сохранённого отчёта.')
    else:
        for key,label in [('title','название'),('problem','проблема'),('audience','адресат'),('use_case','прикладной сценарий'),
                          ('public_takeaway','практический вывод'),('next_step','следующий шаг')]:
            if not model_story.get(key):issues.append('Не заполнено поле: '+label+'.')
        for key,label in [('mechanism','три шага механизма'),('findings','результаты'),('limitations','ограничения'),('resources','ресурсы')]:
            if not model_story.get(key) or (key=='mechanism' and len(model_story[key])!=3):issues.append('Не заполнено: '+label+'.')
        if not data.get('evidence'):issues.append('Нет подтверждённой связки: источник → дословный фрагмент основного отчёта.')
    rejected=any('Сравнение' in issue or 'сравнения' in issue for issue in issues)
    numeric='supported' if data.get('comparisons') else ('rejected' if rejected else 'not_provided')
    return {'status':'incomplete' if issues else 'ready','issues':issues,'automatic':True,'numeric_data':numeric,
            'notice':'Проверены структура, источники и наличие чисел в сохранённом отчёте; научная достоверность и переносимость не подтверждены.'}


def _sections(text):
    sections, title = {}, 'intro'
    for line in text.splitlines():
        heading = re.match(r'^\s*#{1,6}\s+(.+)', line)
        if heading:
            title = _clean(re.sub(r'^\d+[.)]?\s*', '', heading.group(1))).casefold()
            sections.setdefault(title, [])
        else:
            sections.setdefault(title, []).append(line)
    return {key: '\n'.join(value).strip() for key, value in sections.items()}


def _section(sections, *needles):
    return '\n\n'.join(value for key, value in sections.items() if any(needle.casefold() in key for needle in needles))


def _paragraphs(text):
    values = []
    for paragraph in re.split(r'\n\s*\n|\n(?=\s*[-*]\s)', text):
        if paragraph.lstrip().startswith('|'):
            continue
        value = _clean(paragraph)
        if value and not re.match(r'^https?://', value):
            # Keep a complete first sentence so a truncation does not hide a caveat.
            sentence = re.split(r'(?<=[.!?])\s+(?=[А-ЯA-Z«])', value, maxsplit=1)[0]
            values.append(sentence)
    return values


def _first(text, default=UNKNOWN, limit=300):
    values = _paragraphs(text)
    return _limit(values[0], limit) if values else default


def _table_cells(text):
    cells = []
    for line in text.splitlines():
        if line.strip().startswith('|') and not re.match(r'^\s*\|[\s:|-]+\|\s*$', line):
            row = [_clean(value) for value in line.strip().strip('|').split('|')]
            cells.extend(value for value in row if value)
    return cells


def _table_facts(text):
    result = []
    for line in text.splitlines():
        if not line.strip().startswith('|') or re.match(r'^\s*\|[\s:|-]+\|\s*$', line):
            continue
        row = [_clean(value) for value in line.strip().strip('|').split('|')]
        if len(row) < 2 or row[0].casefold() in {'подход', 'источник', 'метрика'}:
            continue
        for value in row[1:]:
            if value:
                result.append((row[0], value))
    return result


def _legacy(run, report):
    plan = run.get('plan') if isinstance(run.get('plan'), dict) else {}
    study = plan.get('study_context') if isinstance(plan.get('study_context'), dict) else {}
    task = study.get('task') if isinstance(study.get('task'), dict) else {}
    sources = plan.get('sources') if isinstance(plan.get('sources'), list) else []
    title = task.get('title') or (sources[0].get('title') if sources and isinstance(sources[0], dict) else '') or 'Разбор исследования ИИ'
    sections = _sections(report)
    conclusion = _section(sections, 'краткий вывод', 'заключение') or sections.get('intro', '')
    decision = _section(sections, 'решение', 'следующ')
    applicability = _section(sections, 'применим', 'бизнес')
    infra = _section(sections, 'self-host', 'инфраструктур')
    limitation = _section(sections, 'ограничен', 'риск')
    benefit = _section(sections, 'преимущ', 'плюсы')
    facts = _table_facts(report)
    pros = _paragraphs(benefit)[:2]
    application_sentences = re.split(r'(?<=[.!?])\s+(?=[А-ЯA-Z«])', _clean(applicability))
    if not pros:
        pros = ['Оценка из отчёта: ' + value for value in application_sentences
                if re.search(r'бизнес-польза|преимуществ', value, re.I)][:2]
    if not pros:
        candidates = [(name, value) for name, value in facts if re.search(r'без обучения|не нужна|сохраняет распределение|снижение задерж|полезн', value, re.I)]
        candidates.sort(key=lambda item: not bool(re.search(r'не нужна|сохраняет распределение', item[1], re.I)))
        pros = [name + ': ' + value for name, value in candidates[:2]]
    cons = ['Оценка из отчёта: ' + value for value in application_sentences
            if re.search(r'невыгодн|не окуп|ухудш|риск|не подход', value, re.I)][:2]
    if not cons:
        cons = [name + ': ' + value for name, value in facts if re.search(r'дополнительные веса|не гарантирует|нужен совместимый|ограничен|стоимость|не прочитан', value, re.I)
                and name + ': ' + value not in pros][:2]
    if not cons:
        cons = _paragraphs(limitation)[:2]
    metric_section = _section(sections, 'метрики', 'baseline')
    metrics = []
    for line in metric_section.splitlines():
        if line.lstrip().startswith('|'):
            row = [_clean(value) for value in line.strip().strip('|').split('|')]
            if len(row) >= 2 and row[0] and not re.search(r'^[-:]|метрика|источник', row[0], re.I):
                metrics.append(_limit(row[0] + ': ' + row[1], 240))
    if not metrics:
        metrics = [_limit(value, 240) for value in _paragraphs(metric_section)[:2]]
    return {
        'title': _limit(_clean(title), 160),
        'verdict': _first(conclusion or decision or report, 'Решение пока не выделено в отчёте.', 240),
        'summary': _first(conclusion or report, 'Краткое резюме пока не выделено.', 400),
        'applicability': [_first(applicability, limit=240)],
        'pros': [_limit(value, 240) for value in pros] or ['Преимущества нужно сверить в полном отчёте.'],
        'cons': [_limit(value, 240) for value in cons] or ['Ограничения нужно сверить в полном отчёте.'],
        'metrics': metrics[:3] or [UNKNOWN],
        'infrastructure': [_limit(value, 240) for value in _paragraphs(infra)
                           if not re.search(r'^Это будущий сценарий', value, re.I)][:3] or [UNKNOWN],
        'setup': _first(_section(sections, 'сложность', 'настройк', 'затраты'),
                        'Сложность настройки не оценена отдельно; нужны модель, движок и профиль нагрузки.', 240),
        'next_step': _first(decision, 'Определить задачу, baseline и условия следующей проверки.', 300),
        'mechanism': []}


def _visual(data, report):
    if data.get('mechanism'):
        steps = [{'label': 'Шаг ' + str(index + 1), 'text': value} for index, value in enumerate(data['mechanism'])]
        kind = 'research_path'
    elif 'speculativ' in report.casefold() and re.search(r'(?:target|целевая).*проверяет', report, re.I):
        steps = [{'label': 'Черновик', 'text': 'Малая модель предлагает продолжение.'},
                 {'label': 'Проверка', 'text': 'Целевая модель проверяет предложенные токены.'},
                 {'label': 'Продолжение', 'text': 'Принятый префикс остаётся; после отклонения продолжение строится заново.'}]
        kind = 'speculative_decoding'
    else:
        steps = [{'label': 'Материал', 'text': 'Что заявлено и какими источниками подкреплено.'},
                 {'label': 'Сравнение', 'text': 'Задача, baseline, метрики и условия применения.'},
                 {'label': 'Решение', 'text': _limit(data['next_step'], 120)}]
        kind = 'research_path'
    return {'kind': kind, 'caption': 'Схема объясняет идею; это не замер скорости.', 'steps': steps,
            'basis':'report_mechanism' if data.get('mechanism') or kind=='speculative_decoding' else 'review_process'}


def _list_line(label, values, maximum=310):
    return label + '\n' + _limit(' • '.join(values) if values else UNKNOWN, maximum)


def _post(data):
    mechanism = [item['text'] for item in (data.get('visual') or {}).get('steps', [])]
    if (data.get('visual') or {}).get('basis') == 'review_process':
        mechanism = ['Механизм нужно уточнить по полному отчёту.']
    takeaway = data['verdict']
    if re.search(r'внедрени.{0,50}отлож|отлож.{0,50}внедр|преждевремен',takeaway,re.I):
        takeaway = 'Рекомендация исходного отчёта не задаёт ясный сценарий применения. Нужна редакторская привязка к задаче читателя.'
    parts = ['🧪 ' + data['title'], 'ЗАДАЧА И ИДЕЯ\n' + data['summary'],
             _list_line('КОМУ ПОЛЕЗНО', data['applicability']),
             _list_line('КАК РАБОТАЕТ', mechanism,440),
             _list_line('Плюсы и основания', data['pros']),
             _list_line('ПОКАЗАТЕЛИ И УСЛОВИЯ', data['metrics']),
             _list_line('ОГРАНИЧЕНИЯ', data['cons']),
             _list_line('РЕСУРСЫ И НАСТРОЙКА', data['infrastructure']+[data['setup']]),
             'ПРАКТИЧЕСКИЙ ВЫВОД\n'+takeaway,
             'Анализ источников; собственных замеров нет. Черновик поста — проверьте перед публикацией.']
    source_lines = []
    for source in data['sources'][:3]:
        line = source['url']
        if utf16_len('\n'.join(source_lines + [line])) <= 500:
            source_lines.append(line)
    if source_lines:
        parts.append('Источники\n' + '\n'.join(source_lines))
    return _limit('\n\n'.join(parts), POST_LIMIT)


def _review_body(review):
    if not isinstance(review, dict):
        return {}, None
    current = review.get('current')
    if isinstance(current, dict):
        return current.get('body') or {}, current.get('version')
    return review.get('body', review), review.get('version')


def _editorial(data, review):
    body, revision = _review_body(review)
    value = body.get('editorial') if isinstance(body, dict) else None
    if not isinstance(value, dict) or not value.get('problem') or not value.get('public_takeaway'):
        return data
    limits = {'title':160, 'problem':800, 'audience':500, 'use_case':700,
              'public_takeaway':700, 'next_step':700}
    clean = {key:_limit(_clean(value.get(key, '')), maximum) for key,maximum in limits.items()}
    lists = {key:[_limit(_clean(item), 700) for item in value.get(key, []) if isinstance(item,str) and _clean(item)][:5]
             for key in ('mechanism','findings','limitations','resources')}
    if clean['title']:
        data['title'] = clean['title']
    data.update(problem=clean['problem'], audience=clean['audience'], use_case=clean['use_case'],
                public_takeaway=clean['public_takeaway'], verdict=clean['public_takeaway'],
                summary=clean['problem'], next_step=clean['next_step'] or data['next_step'],
                applicability=[clean['audience'],clean['use_case']],
                cons=lists['limitations'], infrastructure=lists['resources'])
    data['story'] = [
        {'id':'problem','title':'1 · Какая проблема','text':clean['problem']},
        {'id':'audience','title':'2 · Кому и для какой задачи','text':clean['audience'], 'items':[clean['use_case']]},
        {'id':'mechanism','title':'3 · Как работает','text':'', 'items':lists['mechanism']},
        {'id':'findings','title':'4 · Что показали авторы','text':'Результаты из сохранённого отчёта; независимое воспроизведение не выполнялось.'+(' '+data['numeric_note'] if data.get('numeric_note') else ''), 'items':lists['findings']},
        {'id':'limitations','title':'5 · Где границы','text':'', 'items':lists['limitations']},
        {'id':'resources','title':'6 · Что потребуется','text':'', 'items':lists['resources']},
        {'id':'takeaway','title':'7 · Практический вывод','text':clean['public_takeaway']}]
    if value.get('visual_kind') == 'replay_tree':
        from .replay_visual import replay_visual
        data['visual'] = replay_visual()
    elif len(lists['mechanism'])==3:
        from .process_visual import process_visual
        data['visual'] = process_visual(lists['mechanism'],data['title'])
    data['provenance'].update(mode='editor_reviewed', editorial_version=revision,
                              notice='Редакторская версия по сохранённому отчёту. Новых модельных прогонов и экспериментов не было.')
    allowed_urls={item['url'] for item in data['sources']}
    preferred=[]
    for evidence in body.get('evidence', []):
        if isinstance(evidence,dict):
            url=_public_url(evidence.get('source_url',''))
            if url in allowed_urls and url not in preferred:preferred.append(url)
    data['sources'].sort(key=lambda item:preferred.index(item['url']) if item['url'] in preferred else len(preferred))
    data['publication_sources']=[item for item in data['sources'] if item['url'] in preferred] if preferred else data['sources'][:4]
    comparisons=[]
    evidence_by_id={item.get('id'):item for item in body.get('evidence',[]) if isinstance(item,dict)}
    for item in value.get('comparisons',[])[:3] if isinstance(value.get('comparisons',[]),list) else []:
        if not isinstance(item,dict):continue
        numbers=[item.get('baseline_value'),item.get('result_value')]
        if any(type(number) not in (int,float) or not 0<=number<=1e100 or not math.isfinite(number) for number in numbers):continue
        references=item.get('evidence_ids',[])
        if not isinstance(references,list) or not references or any(not isinstance(reference,str) or reference not in evidence_by_id for reference in references):continue
        comparison={key:_limit(_clean(item.get(key,'')),1600 if key=='conditions' else 200)
                    for key in ('label','unit','baseline_label','result_label','conditions')}
        comparison.update(baseline_value=item['baseline_value'],result_value=item['result_value'],
                          evidence_ids=list(references),
                          evidence=[{**{key:evidence_by_id[reference].get(key) for key in ('id','basis','locator','limitations')},
                                     'source_url':_public_url(evidence_by_id[reference].get('source_url',''))}
                                    for reference in references])
        comparisons.append(comparison)
    data['comparisons']=comparisons
    data['post_text'] = _story_post(data)
    data['short_text'] = _limit('🧪 '+data['title']+'\n\n'+clean['problem']+'\n\n'+clean['public_takeaway']+
                                '\n\nПолный разбор и доказательства сохранены в лаборатории.', SHORT_LIMIT)
    return data


def _story_post(data, *, compact=False):
    sources=[]
    source_candidates=data.get('publication_sources',[]) if data.get('provenance',{}).get('editorial_version') is not None else [*data.get('publication_sources',[]),*data['sources']]
    for item in source_candidates:
        if item['url'] not in sources and utf16_len('\n'.join(sources+[item['url']]))<=650:
            sources.append(item['url'])
        if len(sources)==4:break
    parts = ['🧪 '+data['title']]
    budgets = {'problem':330,'audience':330,'mechanism':530,'findings':700,'limitations':430,'resources':330,'takeaway':380}
    labels = {'problem':'ПРОБЛЕМА','audience':'КОМУ ПОЛЕЗНО','mechanism':'КАК РАБОТАЕТ',
              'findings':'ЧТО ПОКАЗАЛИ АВТОРЫ','limitations':'ГРАНИЦЫ','resources':'НАСТРОЙКА И РЕСУРСЫ','takeaway':'ПРАКТИЧЕСКИЙ ВЫВОД'}
    numeric_note=data.get('numeric_note','')
    if compact:
        labels.update(problem='ЗАДАЧА',audience='КОМУ',mechanism='МЕХАНИЗМ',
                      findings='У АВТОРОВ',resources='РЕСУРСЫ',takeaway='ВЫВОД')
        if numeric_note=='Нет сопоставимой пары подтверждённых чисел; известные данные и пробелы показаны в таблице.':
            numeric_note='Пара чисел не подтверждена.'
    texts={section['id']:'\n'.join(([numeric_note] if section['id']=='findings' and numeric_note else [section['text']] if section.get('text') and section['id']!='findings' else [])+
                                [('• ' if not compact and len(section.get('items',[]))>1 else '')+item for item in section.get('items',[])])
           for section in data['story']}
    attribution='' if 'собственных замеров' in '\n'.join(texts.values()).lower() else ('Своих замеров нет.\n\n' if compact else 'Результаты авторов; собственных замеров нет.\n\n')
    footer=attribution+'Источники\n'+'\n'.join(sources)
    next_label='ШАГ' if compact else 'С ЧЕГО НАЧАТЬ'
    next_step=next_label+'\n'+data['next_step'] if data.get('next_step') else ''
    full_parts=[*parts,*[labels[section['id']]+'\n'+texts[section['id']] for section in data['story']]]
    if next_step:full_parts.append(next_step)
    full='\n\n'.join(full_parts)+'\n\n'+footer
    data['post_compacted']=utf16_len(full)>POST_LIMIT
    if utf16_len(full)<=POST_LIMIT:return full
    # Budget each complete section, reserving the sources instead of clipping
    # the finished post and accidentally removing its attribution.
    if next_step:next_step=next_label+'\n'+_limit(data['next_step'],350)
    remaining = POST_LIMIT - utf16_len('\n\n'.join(parts)+ '\n\n'+footer+'\n\n'+next_step) - 40
    overhead=sum(utf16_len(labels[section['id']])+3 for section in data['story'])
    available=max(100,remaining-overhead)
    weight=sum(budgets[section['id']] for section in data['story'])
    for section in data['story']:
        text = texts[section['id']]
        maximum=max(30,int(available*budgets[section['id']]/max(1,weight)))
        block = labels[section['id']]+'\n'+_limit(text,maximum)
        parts.append(block)
    if next_step:parts.append(next_step)
    return _limit('\n\n'.join(parts)+'\n\n'+footer, POST_LIMIT)


def build_presentation(run, review=None):
    """Return a JSON-compatible publication draft without accessing any provider."""
    if not isinstance(run, dict):
        raise ValueError('Нужен сохранённый результат исследования.')
    output = run.get('output') if isinstance(run.get('output'), str) else ''
    report = display_report(output)
    data, warnings = _structured(output)
    mode = 'model_structured' if data else 'legacy_extractive'
    data = data or _legacy(run, report)
    evidence_rows=data.pop('_auto_evidence',[])
    comparison_rows=data.pop('_auto_comparisons',[])
    applied_packet={key:data.pop(key,None) for key in ('_applied_analysis','_review_dispositions','_evidence_checks')}
    visual_focus=data.pop('_visual_focus','auto')
    optional_motion=data.pop('_motion',None)
    model_story = {key:data[key] for key in (set(_STORY_TEXT)|_STORY_ARRAYS|{'title','mechanism','next_step'}) if key in data} if data.get('problem') and data.get('public_takeaway') else None
    if model_story:
        data['applicability']=[data['audience'],data['use_case']]
        data['cons']=data.get('limitations',[])
        data['infrastructure']=data.get('resources',[])
    for key in _FIELDS:
        data[key] = data.get(key) or UNKNOWN
    for key in _ARRAYS:
        data[key] = data.get(key) or [UNKNOWN]
    public_sources = []
    candidates = list(_URL.findall(report))
    links = run.get('links') if isinstance(run.get('links'), list) else []
    candidates.extend(link if isinstance(link, str) else link.get('url', '') if isinstance(link, dict) else '' for link in links)
    automatic_allowed_urls={url for candidate in candidates if (url:=_public_url(candidate))}
    plan = run.get('plan') if isinstance(run.get('plan'), dict) else {}
    for source in plan.get('sources', []) if isinstance(plan.get('sources'), list) else []:
        if isinstance(source, dict):
            candidates.append(source.get('url', ''))
    for value in candidates:
        url = _public_url(value)
        if url and url not in public_sources:
            public_sources.append(url)
        if len(public_sources) == 8:
            break
    data['version'] = VERSION
    data['sources'] = [{'label': 'Источник ' + str(index + 1), 'url': url,
                        'verification': 'link_in_report_not_independent_verification'} for index, url in enumerate(public_sources)]
    data['visual'] = _visual(data, report)
    data.pop('mechanism', None)
    data['provenance'] = {'mode': mode, 'notice': 'Черновик по готовому отчёту. Оформление не запускает новое исследование.',
                          'evidence': 'source_analysis_not_reproduced_experiment',
                          'presentation_block_valid': mode == 'model_structured',
                          'report_sha256': hashlib.sha256(report.encode('utf-8')).hexdigest(), 'warnings': warnings}
    automatic_issues=[]
    agent_gate=None
    if mode=='model_structured':
        evidence,comparisons,automatic_issues=_auto_support(evidence_rows,comparison_rows,report,automatic_allowed_urls)
        data['evidence']=evidence
        if model_story:
            model_story['comparisons']=comparisons
            data['numeric_note']='' if comparisons else 'Нет подтверждённых численных сравнений; показана схема механизма, а не график эффективности.'
        data['provenance']['warnings'].extend(automatic_issues)
        for item in evidence:
            if item['source_url'] not in {source['url'] for source in data['sources']}:
                data['sources'].append({'label':'Источник','url':item['source_url'],'verification':'link_in_report_not_independent_verification'})
    if plan.get('research_protocol'):
        from .applied_analysis import presentation_gate
        agent_gate=presentation_gate(run,applied_packet,report,data.get('evidence',[]))
        data['agent_review']=agent_gate
        if agent_gate.get('source_validation') is not None:
            data['source_validation']=agent_gate['source_validation']
        data['applied_analysis']=agent_gate['applied_analysis']
        if model_story:
            model_story['comparisons']=agent_gate.get('comparisons',[]) if agent_gate['status']=='ready' else []
        data['numeric_note']='' if agent_gate.get('comparisons') and agent_gate['status']=='ready' else 'Нет сопоставимой пары подтверждённых чисел; известные данные и пробелы показаны в таблице.'
    data['post_text'] = _post(data)
    data['short_text'] = _limit('🧪 ' + data['title'] + '\n\n' + data['verdict'] + '\n\n→ ' + data['next_step']
                                + '\n\nАнализ источников; собственных замеров нет. Полный отчёт доступен в лаборатории.', SHORT_LIMIT)
    if model_story:
        data=_editorial(data,{'editorial':model_story,'evidence':data.get('evidence',[])})
        data['provenance'].update(mode='model_structured',editorial_version=None,
                                  notice='Публичный разбор из того же исследовательского ответа. Редакторская оценка ещё не выполнялась.')
    vetted_comparisons=data.get('comparisons',[])
    data=_editorial(data, review)
    if (model_story and data.get('post_compacted') and
            (plan.get('research_protocol') or {}).get('assembly_version') == 'compact-editor-v1'):
        from .channel_layout import fit
        layout = fit(data, _story_post, POST_LIMIT)
        if layout is None:
            layout = fit(data, lambda value: _story_post(value, compact=True), POST_LIMIT)
            if layout is not None:
                layout['metadata']['surface_version']='compact-static-v1'
        if layout is not None:
            data.update(post_text=layout['text'], post_layout=layout['metadata'], post_compacted=False)
    if agent_gate is not None:
        # A manual prose revision cannot create a new numeric path or waive a
        # missing machine pass. The owner still approves the publication itself.
        data['comparisons']=vetted_comparisons
    if data['visual'].get('kind') != 'replay_tree' and (model_story or (data.get('story') and data['visual'].get('kind') == 'process_flow')):
        data['visual_theme']='reader_infographic'
    if data.get('visual_theme') == 'reader_infographic':
        data['visual_profile']=select_visual_profile(data,visual_focus)
        from .motion_story import build_motion_story
        motion_story=build_motion_story(data,report,optional_motion,data.get('evidence',[]))
        if motion_story:
            data['motion_story']=motion_story
            from .motion_dashboard import LAYOUT_VERSION
            data['visual']['layout_version'] = LAYOUT_VERSION
            from .visual_skin import select_visual_skin
            data['visual_skin']=select_visual_skin(data)
    data['publication_checks']=_publication_checks(data,automatic_issues,model_story)
    if agent_gate is not None:
        data['publication_checks']['agent_review_status']=agent_gate['status']
        data['publication_checks']['notice']+=' '+agent_gate['notice']
        if agent_gate['status']!='ready':
            data['publication_checks']['status']='incomplete'
            data['publication_checks']['issues'].extend(agent_gate['issues'] or ['Обязательная проверка трёх проходов не завершена.'])
    data['publication_rules']=publication_rules()
    if data.get('post_compacted'):
        data['publication_checks']['status']='incomplete'
        data['publication_checks']['issues'].append('Пост не помещается в лимит целиком; сокращённая версия не считается готовой к публикации.')
    return data


def _lines(value, width, maximum):
    lines = textwrap.wrap(_clean(value), width=width, break_long_words=True, break_on_hyphens=False)
    if len(lines) > maximum:
        lines = lines[:maximum]
        lines[-1] = lines[-1].rstrip(' .,;:') + '…'
    return lines


def _layout(data, active=None):
    """One layout powers SVG, PNG and schematic GIF; no generated executable code."""
    elements = [('rect', 0, 0, 1200, 1240, '#09131f', 0),
                ('text', 64, 54, 'AI R&D LABORATORY  /  RESEARCH BRIEF', 20, '#6edbc8', False)]
    for index, line in enumerate(_lines(data.get('title', ''), 43, 3)):
        elements.append(('text', 64, 112 + index * 47, line, 40, '#f1f5fb', True))
    elements.append(('rect', 64, 245, 1072, 150, '#14343a', 18))
    elements.append(('text', 88, 278, 'РЕШЕНИЕ', 17, '#7de1ca', True))
    for index, line in enumerate(_lines(data.get('verdict', ''), 75, 3)):
        elements.append(('text', 88, 313 + index * 28, line, 24, '#f4fffb', True))
    steps = (data.get('visual') or {}).get('steps', [])
    for index, step in enumerate(steps[:3]):
        x = 64 + index * 366
        fill = '#23524d' if active == index else '#142334'
        elements.extend([('rect', x, 430, 340, 150, fill, 16),
                         ('text', x + 20, 462, f'0{index + 1}  ' + _limit(step.get('label', ''), 24), 21, '#7de1ca', True)])
        for line_index, line in enumerate(_lines(step.get('text', ''), 30, 3)):
            elements.append(('text', x + 20, 501 + line_index * 25, line, 20, '#e3ebf5', False))
        if index < 2:
            elements.append(('text', x + 344, 514, '›', 28, '#6edbc8', True))
    elements.append(('text', 64, 609, 'СХЕМА ИДЕИ • НЕ БЕНЧМАРК • НЕТ СОБСТВЕННЫХ ЗАМЕРОВ', 16, '#8ca0b6', False))
    metric_names = [value.split(':', 1)[0] for value in (data.get('metrics') or [UNKNOWN])]
    infrastructure = list(data.get('infrastructure') or [UNKNOWN])
    infrastructure.sort(key=lambda value: 'неизвест' not in value.casefold())
    boxes = [('ГДЕ ПОЛЕЗНО', (data.get('applicability') or [UNKNOWN])[0]),
             ('ЧТО ДАЁТ', (data.get('pros') or [UNKNOWN])[0]),
             ('ОГРАНИЧЕНИЯ', (data.get('cons') or [UNKNOWN])[0]),
             ('ЧТО ИЗМЕРЯТЬ', ' • '.join(metric_names) + '. Значения и условия — в отчёте.'),
             ('ИНФРАСТРУКТУРА', ' '.join(infrastructure[:2])),
             ('СЛЕДУЮЩИЙ ШАГ', data.get('next_step', UNKNOWN))]
    for index, (label, value) in enumerate(boxes):
        x, y = 64 + (index % 2) * 548, 642 + (index // 2) * 174
        elements.extend([('rect', x, y, 524, 156, '#111f30', 14),
                         ('text', x + 20, y + 29, label, 16, '#8ca0b6', True)])
        for line_index, line in enumerate(_lines(value, 46, 4)):
            elements.append(('text', x + 20, y + 61 + line_index * 22, line, 19, '#e0e9f3', False))
    elements.append(('text', 64, 1211, 'ЧЕРНОВИК ПО ОТЧЁТУ  ·  ПРОВЕРЬТЕ УСЛОВИЯ И ПЕРВОИСТОЧНИКИ', 17, '#8ca0b6', False))
    return elements


def render_svg(data):
    if data.get('visual_theme') == 'reader_infographic':
        from .reader_infographic import render_infographic_svg
        return render_infographic_svg(data)
    if data.get('comparisons'):
        from .comparison_visual import render_comparison_svg
        return render_comparison_svg(data)
    if (data.get('visual') or {}).get('kind') == 'process_flow':
        from .process_visual import render_process_svg
        return render_process_svg(data)
    if (data.get('visual') or {}).get('kind') == 'replay_tree':
        from .replay_visual import render_replay_svg
        return render_replay_svg(data)
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="1240" viewBox="0 0 1200 1240" role="img">',
             '<title>' + html.escape(str(data.get('title', 'Разбор исследования'))) + '</title>',
             '<desc>Карточка по отчёту. Схема объясняет идею и не является измерением скорости.</desc>']
    for element in _layout(data):
        if element[0] == 'rect':
            _, x, y, width, height, color, radius = element
            parts.append(f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{radius}" fill="{color}"/>')
        else:
            _, x, y, text, size, color, bold = element
            parts.append(f'<text x="{x}" y="{y}" font-family="Segoe UI,Arial,sans-serif" font-size="{size}" font-weight="{700 if bold else 400}" fill="{color}">{html.escape(text)}</text>')
    return ''.join(parts) + '</svg>'


def _font(size, bold=False):
    from PIL import ImageFont
    candidates = [Path('C:/Windows/Fonts') / ('segoeuib.ttf' if bold else 'segoeui.ttf'),
                  Path('/usr/share/fonts/truetype/dejavu') / ('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf')]
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size=size)


def _raster(data, active=None):
    from PIL import Image, ImageDraw
    picture = Image.new('RGB', (1200, 1240), '#09131f')
    draw = ImageDraw.Draw(picture)
    fonts = {}
    for element in _layout(data, active):
        if element[0] == 'rect':
            _, x, y, width, height, color, radius = element
            draw.rounded_rectangle((x, y, x + width, y + height), radius=radius, fill=color)
        else:
            _, x, y, text, size, color, bold = element
            key = size, bold
            if key not in fonts:
                fonts[key] = _font(size, bold)
            draw.text((x, y), text, font=fonts[key], fill=color, anchor='ls')
    return picture


def render_png(data):
    if data.get('visual_theme') == 'reader_infographic':
        from .reader_infographic import render_infographic_png
        return render_infographic_png(data)
    if data.get('comparisons'):
        from .comparison_visual import render_comparison_png
        return render_comparison_png(data)
    if (data.get('visual') or {}).get('kind') == 'process_flow':
        from .process_visual import render_process_png
        return render_process_png(data)
    if (data.get('visual') or {}).get('kind') == 'replay_tree':
        from .replay_visual import render_replay_png
        return render_replay_png(data)
    try:
        picture = _raster(data)
    except ImportError:
        return None
    stream = io.BytesIO()
    picture.save(stream, format='PNG', optimize=True)
    return stream.getvalue()


def render_gif(data):
    """Highlight explanatory steps, deliberately not an animation of measured speed."""
    if data.get('visual_theme') == 'reader_infographic' and data.get('comparisons'):
        from .reader_infographic import render_infographic_gif
        return render_infographic_gif(data)
    if (data.get('visual') or {}).get('kind') == 'process_flow':
        from .process_visual import render_process_gif
        return render_process_gif(data)
    if (data.get('visual') or {}).get('kind') == 'replay_tree':
        from .replay_visual import render_replay_gif
        return render_replay_gif(data)
    try:
        from PIL import Image
        frames = [_raster(data, active=index).resize((720, 744), Image.Resampling.LANCZOS).convert('P', palette=Image.Palette.ADAPTIVE, colors=128)
                  for index in range(3)]
    except ImportError:
        return None
    stream = io.BytesIO()
    frames[0].save(stream, format='GIF', save_all=True, append_images=frames[1:], duration=[1100, 1100, 1500], loop=0, optimize=True)
    return stream.getvalue()


def render_mp4(data):
    from .media_encoder import render_mp4 as encode
    return encode(data)
