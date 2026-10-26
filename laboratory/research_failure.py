"""Owner-facing failure facts from the persisted journal, without executing anything."""
import math


ROLES = {'researcher': 'Исследователь', 'critic': 'Критик', 'reviewer': 'Редактор'}


def _number(value):
    return type(value) in {int, float} and math.isfinite(value) and value >= 0


def failure_notice(run):
    status = run.get('status')
    status = status if status in {'failed', 'cancelled', 'outcome_unknown'} else 'unknown'
    lines = ['Исследование остановлено. Статус: «' + status + '».']
    pipeline = run.get('agent_pipeline') or {}
    phases = pipeline.get('phases') or []
    if phases:
        stopped = phases[-1]
        role = ROLES.get(stopped.get('role'), 'Проход')
        seconds = stopped.get('elapsed_seconds')
        duration = f' — {seconds:.2f} сек.' if _number(seconds) else ''
        lines.append('Этап: ' + role + duration)
        error = str(stopped.get('error') or run.get('error') or '').casefold()
        if 'лимит времени' in error or 'бюджет времени' in error:
            lines.append('Причина: достигнут лимит времени.')
        if stopped.get('status') == 'outcome_unknown':
            lines.append('Исход внешнего запроса неизвестен.')
        completed = sum(phase.get('status') == 'completed' for phase in phases)
        protocol = run.get('plan', {}).get('research_protocol') or {}
        resume = protocol.get('version') == 'editor-resume-v1'
        lines.append(f'Завершено новых проходов: {completed} из 1.' if resume else
                     f'Завершено проходов: {completed} из 3.')
        if resume:
            lines.append('Исследователь и критик сохранены в исходном запуске; '
                         'повторно не запускались. Прошлый неизвестный расход учтён отдельно.')
        lines.append('Частичные ответы и точные запросы сохранены в журнале лаборатории.')
    dispatched = pipeline.get('dispatched_calls')
    reserved = pipeline.get('reserved_calls')
    if _number(dispatched) and _number(reserved):
        lines.append(f'Отправлено вызовов CLI: {dispatched}; зарезервировано: {reserved}.')
    usage = run.get('usage') or {}
    values = []
    for key, label in (('input_tokens', 'вход'), ('output_tokens', 'выход')):
        value = usage.get(key)
        if _number(value):
            values.append(label + ' ' + str(value))
    if values:
        lines.append('Известные токены: ' + ', '.join(values) + '.')
        cached = usage.get('cached_input_tokens')
        if _number(cached):
            lines.append(f'Из входных токенов кешировано: {cached}; повторно не суммируется.')
        reported = sum(bool(_number((phase.get('usage') or {}).get('input_tokens'))
                            and _number((phase.get('usage') or {}).get('output_tokens')))
                       for phase in phases)
        if phases:
            lines.append(f'Полные сведения о токенах: {reported} из {len(phases)} проходов.')
        if reported < len(phases) or not phases:
            lines.append('Расход остальных проходов неизвестен; это не нулевой расход.')
    else:
        lines.append('Расход неизвестен; CLI не сообщил полные сведения о токенах.')
    lines.append('Готовность поста не подтверждена. Автоматического повторного запуска нет.')
    return '\n'.join(lines)
