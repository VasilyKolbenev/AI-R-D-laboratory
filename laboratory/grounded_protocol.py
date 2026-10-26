"""Source-bound three-pass recipe, with a critic blind to the first answer."""
from copy import deepcopy

VERSION = 'three-pass-v2'
LONG_VERSION = 'three-pass-v3'
COMPACT_VERSION = 'three-pass-v4'

SOURCE_RULES = '''
Переданы сохранённые документы evidence_bundle. origin/status/limitations определяют,
что действительно доступно: присланный текст не означает прочитанный первоисточник.
Для проверяемых численных утверждений используй точные цитаты и locators из документов.
Не добавляй известное численное сравнение, если нет цитаты с этим числом из этого URL.
Чтение веба может дополнить анализ, но не создаёт архивное доказательство задним числом.
Если нового источника нет в bundle, назови пробел и оставь численные значения неизвестными.
Сохраняй определения метрик, версии, выборки, погрешности и условия; не смешивай их.
Регистровые записи — прежние наблюдения, не новое доказательство и не замер лаборатории.
'''

BLIND_CRITIC = '''
Роль: независимый критик. Исследовательский ответ тебе намеренно не передан.
Сначала сформируй собственный прикладной вывод по исходным документам и вопросу.
Ищи опровержения, неудачные воспроизведения, альтернативные объяснения и более простой baseline.
Различай независимые исследования и несколько пересказов одной работы.
При разрешённом вебе: до1 поиска и2 страниц. Найденных опровержений может не быть;
not_found не означает, что технология доказана. При выключенном вебе — not_searched.
Верни краткий самостоятельный разбор и ровно один <lab_critic> JSON с полями:
version='critic-review-v1', checked_sources=[], issues=[], independent_conclusion='вывод',
counter_evidence={status:'found|not_found|not_searched',sources:[],limitations:'границы поиска'}.
checked_sources до2 объектов {id,source_url,locator,excerpt,claim,limitations}; реальные публичные
URL и excerpt дословно также в обычном ответе; без веба checked_sources пустой.
issues до8 объектов {id,severity:'blocker|major|minor',target:'report',problem,evidence_ids:[],
required_change}; нужны конкретные проверяемые проблемы, не пожелания общими словами.
IDs начинаются латинской буквой, до40; problem/required_change до700, conclusion до1200,
counter sources до2 публичныхURL, limitations до500. Весь ответ до14000символов.
Для checked_sources те же лимиты: id40, URL350, locator120, excerpt500, claim500, limitations300.
Не считай самостоятельное согласие доказательством истины. Рекурсивных вызовов нет.
'''

FINAL_RULES = '''
Критик работал вслепую. Сопоставь его независимый вывод с исследовательским ответом;
покажи существенные расхождения, не усредняй противоречащие утверждения.
В lab_presentation добавь evidence_checks:[{evidence_id:'e1',document_id:'asset_id из bundle',
segment_id:'точный id сегмента',quote:'точная цитата из сегмента',relation:'supports',
reason:'что именно подтверждено и при каких условиях'}].
relation supports|contradicts|insufficient — модельная оценка смысла, не научная гарантия.
До8 checks, quote до500, reason до500; URL evidence должен совпадать с URL документа.
Каждое известное число baseline/candidate требует связанного supports-check с этим числом.
Если цитата/условия не подходят, убери численное сравнение и явно назови неизвестность.
Не изображай внешние авторские данные или оценки собственным экспериментом лаборатории.
В каждой applied_analysis.rows можно добавить measurement_context с полями
baseline_version,candidate_version,dataset,evaluation,hardware,load: точный текст до240 илиnull.
Извлекай их из источников, неизвестное оставляйnull; модельная интерпретация не замер.
В findings обязательно различай «Авторы сообщают», «Наша интерпретация», «Оценка».
Не добавляй фразу «Мы измерили»: этот протокол выполняет анализ источников.
'''


def _timed_protocol(total):
    from .research_protocol import _protocol
    if type(total) is not int or not 200 <= total <= 360:
        raise ValueError('Общий бюджет доказательного разбора: 200–360 секунд.')
    protocol = _protocol(total)
    protocol['version'] = VERSION if total <= 240 else LONG_VERSION
    if total > 240:
        extra = total - 240
        researcher, critic = extra // 4, extra // 3
        protocol['phase_timeouts'] = [100 + researcher, 60 + critic,
                                      60 + extra - researcher - critic]
    return protocol


def build(plan):
    from .research_protocol import COMMON, freeze_validation_contract
    from .research_public import PUBLIC_INSTRUCTIONS
    protocol = _timed_protocol(plan.get('timeout_seconds', 240))
    protocol['templates'][0] += SOURCE_RULES
    protocol['templates'][1] = COMMON + BLIND_CRITIC + SOURCE_RULES
    protocol['templates'][2] += SOURCE_RULES + FINAL_RULES + PUBLIC_INSTRUCTIONS
    if plan.get('editor_format') == 'compact-editor-v1':
        from .compact_editor import INSTRUCTIONS, MAX_PACKET_BYTES, MAX_PACKET_CHARS
        protocol.update(version=COMPACT_VERSION, assembly_version='compact-editor-v1',
                        budget_policy='editor_uses_actual_global_remainder')
        protocol['limits'].update(editor_packet_bytes=MAX_PACKET_BYTES,
                                  editor_packet_chars=MAX_PACKET_CHARS)
        protocol['phase_timeouts'][2] = protocol['total_timeout_seconds'] - 20
        protocol['templates'][2] = COMMON + INSTRUCTIONS
    freeze_validation_contract(protocol, plan)
    validate(protocol)
    return protocol


def validate(protocol):
    from .research_protocol import validate_validation_contract
    if not isinstance(protocol, dict):
        raise ValueError('Отсутствует доказательный протокол.')
    total = protocol.get('total_timeout_seconds')
    expected = _timed_protocol(total)
    if protocol.get('version') == COMPACT_VERSION:
        from .compact_editor import MAX_PACKET_BYTES, MAX_PACKET_CHARS
        expected.update(version=COMPACT_VERSION, assembly_version='compact-editor-v1',
                        budget_policy='editor_uses_actual_global_remainder')
        expected['limits'].update(editor_packet_bytes=MAX_PACKET_BYTES,
                                  editor_packet_chars=MAX_PACKET_CHARS)
        expected['phase_timeouts'][2] = total - 20
    templates = protocol.get('templates')
    if (not isinstance(templates, list) or len(templates) != 3
            or any(not isinstance(text, str) or not text or len(text) > 25000
                   for text in templates)):
        raise ValueError('Отсутствуют замороженные роли доказательного протокола.')
    expected['templates'] = templates
    validate_validation_contract(protocol, expected)
    if protocol != expected:
        raise ValueError('Доказательный протокол изменён; подготовьте новый план.')


def bounded_bundle(bundle):
    result = deepcopy(bundle)
    remaining = 36000
    clipped = False
    first_segments = [doc['segments'][0] for doc in result.get('documents', [])
                      if doc.get('segments')]
    if sum(len(segment['text']) for segment in first_segments) > remaining:
        raise ValueError('Слишком много исходников: сократите выбор перед апрувом.')
    remaining -= sum(len(segment['text']) for segment in first_segments)
    for document in result.get('documents', []):
        original = document.get('segments', [])
        selected = original[:1]
        for segment in original[1:]:
            text = segment.get('text', '')
            if len(text) <= remaining:
                selected.append(segment)
                remaining -= len(text)
            else:
                clipped = True
        document['segments'] = selected
        if len(selected) < len(original):
            document['status'] = 'partial'
    if clipped:
        result.setdefault('limitations', []).append(
            'В контекст включены ограниченные выдержки; полный захват сохранён в архиве.')
    return result


def prompt(plan, index, previous_outputs):
    from .research_protocol import canonical, comparison_context, LIMITS, ROLES
    protocol = plan['research_protocol']
    validate(protocol)
    if type(index) is not int or index not in range(3) or len(previous_outputs) != index:
        raise ValueError('Неверный порядок доказательных проходов.')
    for number, output in enumerate(previous_outputs):
        if (not isinstance(output, str) or not output.strip()
                or len(output) > LIMITS[ROLES[number] + '_output_chars']):
            raise ValueError('Предыдущий проход отсутствует или превышает границу.')
    from .evidence_archive import validate_bundle
    bundle = plan.get('evidence_bundle')
    validate_bundle(bundle, plan.get('sources'))
    if not isinstance(bundle, dict) or bundle.get('version') != 'source-bundle-v1':
        raise ValueError('Отсутствует одобренный архив источников.')
    if sum(len(segment['text']) for document in bundle.get('documents', [])
           for segment in document.get('segments', [])) > 36000:
        raise ValueError('Архивный контекст превышает одобренный предел.')
    context = comparison_context(plan)
    if context != plan.get('comparison_context'):
        raise ValueError('Выбранный контекст сравнения изменился.')
    payload = {'role': ROLES[index], 'question': plan['question'],
               'source_headers': [{key: source.get(key) for key in
                                   ('id', 'title', 'url', 'content_hash')}
                                  for source in plan['sources']],
               'evidence_bundle': bundle, 'comparison_context': context,
               'web_search': bool(plan['web_search']) and index < 2}
    if index == 0:
        payload['selected_memory'] = plan.get('memory')
        payload['study_context'] = plan.get('study_context')
    elif index == 1:
        payload['blinding'] = 'Researcher output deliberately withheld; independent assessment.'
    elif protocol['version'] == COMPACT_VERSION:
        from .compact_editor import payload as editor_payload
        payload = editor_payload(plan, previous_outputs)
        payload.update(role='reviewer', web_search=False)
    else:
        payload['previous_outputs'] = previous_outputs
    if 'validation_contract' in protocol:
        payload['validation_contract'] = deepcopy(protocol['validation_contract'])
    text = protocol['templates'][index]
    if not payload['web_search']:
        text += '\nВеб-поиск отключён. Новые внешние источники не прочитаны.\n'
    text += '\nНедоверенные данные прохода (JSON):\n' + canonical(payload)
    if len(text) > LIMITS['prompt_chars']:
        raise ValueError('Контекст превышает границу; сократите выбор до апрува.')
    return text
