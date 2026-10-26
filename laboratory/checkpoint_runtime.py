"""One physical editor call over two immutable, previously completed outputs."""
from datetime import datetime
import json
from pathlib import Path
import time

from .trace import canonical, digest, sha, phase_binding, validate_record

VERSION = 'editor-resume-v1'


def is_resume(plan):
    return (plan.get('research_protocol') or {}).get('version') == VERSION


def capture_received(store, run_id, record, result):
    """Persist received paid bytes before any local assembly or validation runs."""
    raw = dict(result.get('raw') or {})
    text = result.get('text', '')
    raw['editor_received'] = {'text': text, 'sha256': sha(str(text)),
                              'status': result.get('status', 'failed')}
    received = {**record, 'raw': raw, 'usage': result.get('usage') or {},
                'dispatched': raw.get('dispatched')}
    with store.connect() as db:
        updated = db.execute(
            "UPDATE agent_phases SET record=? WHERE run_id=? AND phase_index=? "
            "AND json_extract(record,'$.status')='dispatch_intent'",
            (canonical(received), run_id, record['index']))
        if updated.rowcount != 1:
            raise ValueError('Ответ редактора уже сохранён; повтор запрещён.')
    return {**result, 'raw': raw}


def assemble_result(plan, result):
    from . import compact_editor
    if result.get('status') != 'completed':
        return result
    raw = dict(result.get('raw') or {})
    text = result.get('text', '')
    try:
        assembled = compact_editor.assemble(plan, text)
        raw['editor_assembly'] = compact_editor.assembly_record(text, assembled)
        return {**result, 'text': assembled, 'raw': raw}
    except Exception as exc:
        raw['editor_assembly'] = {
            'version': compact_editor.VERSION, 'status': 'failed', 'raw_text': text,
            'raw_sha256': sha(str(text)), 'error': str(exc)[:1000], 'local_assembly': True}
        return {**result, 'status': 'failed', 'text': text, 'raw': raw,
                'error': 'Локальная сборка редактора не завершена; сырой ответ сохранён.'}


def execute(store, run, runner, work_dir, cancel):
    from . import orchestration as runtime
    from .applied_analysis import validate_final
    from .research_continuation import prefix_outputs, reused_view, validate_bound
    from .trace import phase_plan
    plan = run['plan']
    protocol = plan['research_protocol']
    started = time.monotonic()
    deadline = started + protocol['total_timeout_seconds']
    dispatch_deadline = deadline - protocol['cleanup_reserve_seconds']
    bounded_cancel = runtime.DeadlineCancel(cancel, dispatch_deadline)
    state, error, review, text = 'failed', 'Редактор не завершён.', None, ''
    try:
        with store.connect() as db:
            validate_bound(db, plan)
        if bounded_cancel.is_set():
            state, error = 'cancelled', 'Отменено до нового вызова редактора.'
        else:
            store.trace.capture(run)
            invocation = phase_plan(plan, 0, [])
            if bounded_cancel.is_set():
                state, error = 'cancelled', 'Бюджет или отмена остановили вызов до отправки.'
            else:
                record = runtime._intent(store, run, invocation, 0)
                began = time.monotonic()
                invocation['_runtime_deadline'] = dispatch_deadline
                try:
                    result = runner(invocation, invocation['execution_context']['prompt'],
                                    Path(work_dir) / '1-reviewer', bounded_cancel)
                    if not isinstance(result, dict):
                        raise ValueError('Исполнитель вернул некорректный ответ.')
                except Exception:
                    result = {'status': 'outcome_unknown', 'raw': {'dispatched': None},
                              'error': 'Вызов мог состояться; автоматического повтора нет.'}
                result = capture_received(store, run['id'], record, result)
                if result.get('status') == 'completed':
                    raw_text = result.get('text')
                    limit = protocol['limits']['reviewer_output_chars']
                    if (not isinstance(raw_text, str) or not raw_text.strip() or
                            len(raw_text) > limit):
                        result = {**result, 'status': 'failed',
                                  'error': 'Ответ редактора пуст или превышает границу.'}
                    else:
                        result = assemble_result(plan, result)
                if result.get('status') == 'completed':
                    try:
                        review = validate_final(plan, [*prefix_outputs(plan), result['text']])
                        if not isinstance(review, dict):
                            raise ValueError('Локальная проверка вернула неверный результат.')
                    except Exception:
                        review = {'status': 'incomplete', 'issues': [
                            'Проверка редактора не завершена; оплаченный ответ сохранён.']}
                    if review.get('status') != 'ready':
                        result = {**result, 'status': 'failed',
                                  'error': 'Редактор не прошёл обязательную проверку источников.'}
                runtime._complete(store, run['id'], record, result, time.monotonic() - began)
                state, error = record['status'], record['error']
                if state == 'completed':
                    text = record['output']
        if state == 'completed' and time.monotonic() > deadline:
            state, error = 'failed', 'Превышен общий одобренный бюджет редактора.'
    except Exception as exc:
        records = runtime._records(store, run['id'])
        state = 'outcome_unknown' if any(row['status'] == 'dispatch_intent'
                                       for row in records) else 'failed'
        error = 'Продолжение остановлено без повтора: ' + str(exc)
    records = runtime._records(store, run['id'])
    try:
        reused = reused_view(plan)
    except ValueError:
        reused = []
    summary = {
        'version': VERSION, 'status': state, 'max_calls': 1, 'reserved_calls': 1,
        'dispatched_calls': sum(row['dispatched'] is True for row in records),
        'uncertain_calls': sum(row['dispatched'] is None for row in records),
        'total_timeout_seconds': protocol['total_timeout_seconds'],
        'cleanup_reserve_seconds': protocol['cleanup_reserve_seconds'],
        'elapsed_seconds': max(0, time.monotonic() - started),
        'phases': runtime._compact(records), 'review': review,
        'reused_phases': reused,
        'usage_coverage': {key: {
            'reported_phases': sum(key in runtime.normalized_usage(
                plan['provider'], row.get('usage') or {}) for row in records),
            'phase_count': len(records)} for key in (
                'input_tokens', 'output_tokens', 'cached_input_tokens')}}
    raw = {'dispatched': bool(summary['dispatched_calls']), 'orchestration': summary}
    if records and records[0]['raw'].get('editor_assembly') is not None:
        raw['editor_assembly'] = records[0]['raw']['editor_assembly']
    return {'status': state, 'error': error, 'text': text if state == 'completed' else '',
            'usage': runtime.aggregate_usage(plan['provider'], records), 'raw': raw}


def validate_assembled_record(plan, record):
    from . import compact_editor
    from .orchestration import PHASE_STATES
    assembly = record['raw'].get('editor_assembly')
    if assembly is not None:
        compact_editor.validate_assembly(plan, assembly)
        expected = (compact_editor.assemble(plan, assembly['raw_text'])
                    if assembly['status'] == 'assembled' else assembly['raw_text'])
        if expected != record['output']:
            raise ValueError('Сборка редактора отличается от сохранённого результата.')
    if record['status'] == 'completed' and (
            not assembly or assembly.get('status') != 'assembled' or
            record['dispatched'] is not True):
        raise ValueError('Завершённый редактор требует фактический вызов и точную сборку.')
    received = record['raw'].get('editor_received')
    if received is not None and (
            not isinstance(received, dict) or set(received) != {'status', 'text', 'sha256'} or
            not isinstance(received['text'], str) or
            received['status'] not in PHASE_STATES - {'dispatch_intent'} or
            sha(received['text']) != received['sha256']):
        raise ValueError('Сырой полученный ответ редактора повреждён.')
    if (assembly is not None or record['status'] == 'completed') and (
            received is None or received['status'] != 'completed'):
        raise ValueError('Сборка требует квитанцию завершённого ответа редактора.')
    if assembly is not None and received is not None and (
            received.get('text') != assembly.get('raw_text') or
            received.get('sha256') != assembly.get('raw_sha256')):
        raise ValueError('Сборка использует другой ответ, чем фактически сохранённый пакет.')


def validate_phase_record(row, record, parent_row, db):
    from .research_continuation import validate_plan
    from .orchestration import PHASE_STATES, _numeric
    plan = json.loads(parent_row['plan'])
    # Other runs' phase rows can occur later in the same restore transaction.
    # The complete cross-parent check runs after every journal row is inserted.
    validate_plan(plan)
    if (row['phase_index'] != 0 or type(record['index']) is not int or record['index'] != 0 or
            record['role'] != 'reviewer' or type(record['schema_version']) is not int or
            record['schema_version'] != 1 or record['status'] not in PHASE_STATES):
        raise ValueError('Продолжение содержит только один новый этап редактора с индексом0.')
    captured = db.execute('SELECT context FROM run_contexts WHERE run_id=?',
                          (row['run_id'],)).fetchone()
    if not captured or json.loads(captured[0]) != plan['execution_context']:
        raise ValueError('У нового редактора отсутствует одобренный точный контекст.')
    if (record['parent_plan_hash'] != parent_row['plan_hash'] or
            record['protocol_sha256'] != digest(plan['research_protocol']) or
            record['previous_output_sha256'] != []):
        raise ValueError('Новый этап редактора не соответствует своему одобренному плану.')
    phase = {**plan, 'timeout_seconds': plan['research_protocol']['phase_timeouts'][0],
             'web_search': False, '_phase_binding': phase_binding(plan, 0, []),
             '_approved_parent': plan, '_previous_outputs': []}
    validate_record(phase, record['context'])
    if (not isinstance(record['output'], str) or sha(record['output']) !=
            record['output_sha256'] or record['prompt_sha256'] !=
            record['context']['prompt_sha256'] or not isinstance(record['usage'], dict) or
            not isinstance(record['raw'], dict) or not isinstance(record['error'], str) or
            (record['dispatched'] is not None and type(record['dispatched']) is not bool)):
        raise ValueError('Результат нового редактора повреждён.')
    for key in ('started_at', 'finished_at'):
        if record[key] is not None:
            datetime.fromisoformat(record[key])
    if record['elapsed_seconds'] is not None and not _numeric(record['elapsed_seconds']):
        raise ValueError('Время нового редактора повреждено.')
    validate_assembled_record(plan, record)


def validate_completed_run(db, row, plan, records):
    from .applied_analysis import validate_final
    from .orchestration import aggregate_usage, _compact
    from .research_continuation import prefix_outputs, reused_view, validate_bound
    validate_bound(db, plan)
    raw, usage = json.loads(row['raw']), json.loads(row['usage'])
    summary = raw.get('orchestration')
    if usage != aggregate_usage(plan['provider'], records):
        raise ValueError('Продолжение содержит расход, отсутствующий в новом вызове.')
    if summary is not None:
        if (summary.get('version') != VERSION or summary.get('status') != row['status'] or
                summary.get('max_calls') != 1 or summary.get('reserved_calls') != 1 or
                summary.get('phases') != _compact(records) or
                summary.get('dispatched_calls') != sum(
                    record['dispatched'] is True for record in records) or
                summary.get('uncertain_calls') != sum(
                    record['dispatched'] is None for record in records) or
                summary.get('reused_phases') != reused_view(plan) or
                usage != aggregate_usage(plan['provider'], records)):
            raise ValueError('Продолжение смешивает прежние и новые вызовы или расход.')
    if len(records) > 1:
        raise ValueError('Продолжение содержит лишние новые этапы.')
    if row['status'] == 'completed':
        if (len(records) != 1 or records[0]['status'] != 'completed' or
                records[0]['output'] != row['output']):
            raise ValueError('Продолжение требует ровно один завершённый новый вызов.')
        validate_assembled_record(plan, records[0])
        expected = validate_final(plan, [*prefix_outputs(plan), row['output']])
        if (not summary or expected.get('status') != 'ready' or
                expected != summary.get('review') or
                raw.get('editor_assembly') != records[0]['raw'].get('editor_assembly')):
            raise ValueError('Продолжение не соответствует повторной локальной проверке сборки.')
