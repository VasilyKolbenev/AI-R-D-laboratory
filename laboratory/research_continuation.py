"""One newly approved editor call over two immutable, genuinely completed phases."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR
import hashlib
import json
import math
import re
import uuid


VERSION = 'editor-resume-v1'
CHECKPOINT_VERSION = 'editor-checkpoint-v1'
SOURCE_PROTOCOLS = {'three-pass-v2', 'three-pass-v3', 'three-pass-v4'}
SOURCE_TERMINAL = {'failed', 'cancelled', 'outcome_unknown'}
FROZEN_FIELDS = ('kind', 'question', 'sources', 'study_context', 'memory', 'memory_options',
                 'comparison_context', 'evidence_bundle', 'registry_context', 'provider',
                 'model')
_HASH = re.compile(r'[0-9a-f]{64}\Z')
_RUN = re.compile(r'[0-9a-f]{32}\Z')
_PHASE_FIELDS = {'index', 'role', 'status', 'dispatched', 'prompt_sha256', 'context_hash',
                 'output_sha256', 'usage', 'elapsed_seconds', 'record_sha256'}
_CHECKPOINT_FIELDS = {
    'version', 'parent_run_id', 'parent_plan_hash', 'parent_context_hash',
    'parent_protocol_sha256', 'parent_status', 'parent_output_sha256', 'parent_usage',
    'parent_web_search',
    'parent_total_timeout_seconds', 'prefix', 'prior_editor', 'successful_prefix_seconds',
    'prior_attempted_elapsed_seconds', 'total_timeout_seconds', 'hash'}


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def _sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _number(value):
    return type(value) in {int, float} and math.isfinite(value) and value >= 0


def _phase_snapshot(record, include_output):
    result = {key: deepcopy(record[key]) for key in
              ('index', 'role', 'status', 'dispatched', 'prompt_sha256', 'output_sha256',
               'usage', 'elapsed_seconds')}
    result.update(context_hash=record['context']['hash'], record_sha256=_digest(record))
    if include_output:
        result['output'] = record['output']
    return result


def _arithmetic(parent_total, prefix, editor):
    successful = sum((Decimal(str(row['elapsed_seconds'])) for row in prefix), Decimal(0))
    total = int((Decimal(parent_total) - successful).to_integral_value(rounding=ROUND_FLOOR))
    attempted = successful
    if editor is not None:
        elapsed = editor['elapsed_seconds']
        attempted = None if elapsed is None else successful + Decimal(str(elapsed))
    return float(successful), None if attempted is None else float(attempted), total


def _checkpoint(source, records):
    plan = json.loads(source['plan'])
    prefix = [_phase_snapshot(record, True) for record in records[:2]]
    editor = _phase_snapshot(records[2], False) if len(records) == 3 else None
    original_total = plan['research_protocol']['total_timeout_seconds']
    successful, attempted, total = _arithmetic(original_total, prefix, editor)
    if not 80 <= total <= 360:
        raise ValueError('Остаток не даёт 60 секунд редактору и 20 секунд завершению.')
    value = {'version': CHECKPOINT_VERSION, 'parent_run_id': source['id'],
             'parent_plan_hash': source['plan_hash'],
             'parent_context_hash': plan['execution_context']['hash'],
             'parent_protocol_sha256': _digest(plan['research_protocol']),
             'parent_status': source['status'], 'parent_output_sha256': _sha(source['output']),
             'parent_web_search': plan['web_search'],
             'parent_usage': json.loads(source['usage']),
             'parent_total_timeout_seconds': original_total, 'prefix': prefix,
             'prior_editor': editor, 'successful_prefix_seconds': successful,
             'prior_attempted_elapsed_seconds': attempted, 'total_timeout_seconds': total}
    value['hash'] = _digest(value)
    return value


def _source(db, run_id):
    from .orchestration import validate_backup_table
    from .research_protocol import validate_protocol as validate_source_protocol
    from .applied_analysis import validate_phase
    from .trace import validate_record
    if not isinstance(run_id, str) or not _RUN.fullmatch(run_id):
        raise ValueError('Неверный исходный запуск.')
    source = db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
    if source is None or source['status'] not in SOURCE_TERMINAL:
        raise ValueError('Нужен остановленный исходный запуск с незавершённым редактором.')
    plan = json.loads(source['plan'])
    protocol = plan.get('research_protocol') or {}
    if (plan.get('continuation') is not None or protocol.get('version') not in SOURCE_PROTOCOLS
            or plan.get('evidence_bundle') is None
            or protocol.get('roles') != ['researcher', 'critic', 'reviewer']):
        raise ValueError('Продолжение возможно только от исходного grounded-разбора.')
    if source['plan_hash'] != _digest(plan):
        raise ValueError('Хеш исходного плана не совпал.')
    validate_source_protocol(protocol)
    validate_record(plan, plan.get('execution_context'), current=False)
    rows = db.execute('SELECT * FROM agent_phases WHERE run_id=? ORDER BY phase_index',
                      (run_id,)).fetchall()
    if len(rows) not in {2, 3}:
        raise ValueError('Нужны два настоящих завершённых прохода исходного запуска.')
    records = []
    for index, row in enumerate(rows):
        validate_backup_table('agent_phases', dict(row), db)
        record = json.loads(row['record'])
        if row['phase_index'] != index:
            raise ValueError('Нарушен порядок исходных проходов.')
        if index < 2:
            if (record['status'] != 'completed' or record['dispatched'] is not True
                    or not record['output'].strip() or not _number(record['elapsed_seconds'])):
                raise ValueError('Переиспользовать можно только фактически завершённые проходы.')
        elif record['status'] == 'completed':
            raise ValueError('Исходный редактор уже завершён; повтор не разрешён.')
        records.append(record)
    texts = [record['output'] for record in records[:2]]
    for index in range(2):
        result = validate_phase(plan, index, texts[:index + 1])
        if result.get('status') != 'ready':
            raise ValueError('Исходный структурированный проход неполон или повреждён.')
    return source, plan, records


def _recipe(total, checkpoint_hash, templates):
    from .research_protocol import LIMITS
    from .compact_editor import MAX_PACKET_BYTES, MAX_PACKET_CHARS
    limits = deepcopy(LIMITS)
    limits.update(editor_packet_bytes=MAX_PACKET_BYTES,
                  editor_packet_chars=MAX_PACKET_CHARS)
    return {'version': VERSION, 'roles': ['reviewer'], 'max_calls': 1,
            'total_timeout_seconds': total, 'phase_timeouts': [total - 20],
            'cleanup_reserve_seconds': 20, 'assembly_version': 'compact-editor-v1',
            'limits': limits, 'templates': templates, 'web_search_roles': [],
            'web_search_budgets': {'reviewer': {'searches': 0, 'pages': 0}},
            'auto_retry': False, 'context_policy': 'editor_only_frozen_successful_prefix',
            'checkpoint_sha256': checkpoint_hash}


def build_protocol(checkpoint):
    from .compact_editor import INSTRUCTIONS
    from .research_protocol import COMMON
    if not isinstance(checkpoint, dict):
        raise ValueError('Нет сохранённого checkpoint редактора.')
    total = checkpoint.get('total_timeout_seconds')
    if type(total) is not int or not 80 <= total <= 360:
        raise ValueError('Общее время редактора должно составлять 80–360 секунд.')
    return _recipe(total, checkpoint.get('hash'), [COMMON + INSTRUCTIONS])


def validate_protocol(protocol):
    if not isinstance(protocol, dict):
        raise ValueError('Нет однопроходного протокола редактора.')
    total, templates = protocol.get('total_timeout_seconds'), protocol.get('templates')
    if (type(total) is not int or not 80 <= total <= 360
            or type(protocol.get('max_calls')) is not int or protocol['max_calls'] != 1
            or type(protocol.get('cleanup_reserve_seconds')) is not int
            or protocol['cleanup_reserve_seconds'] != 20
            or not isinstance(protocol.get('phase_timeouts'), list)
            or len(protocol['phase_timeouts']) != 1
            or type(protocol['phase_timeouts'][0]) is not int
            or not isinstance(templates, list) or len(templates) != 1
            or not isinstance(templates[0], str) or not templates[0].strip()
            or len(templates[0]) > 30_000
            or not isinstance(protocol.get('checkpoint_sha256'), str)
            or not _HASH.fullmatch(protocol['checkpoint_sha256'])):
        raise ValueError('Неверный однопроходный рецепт редактора.')
    if protocol != _recipe(total, protocol['checkpoint_sha256'], templates):
        raise ValueError('Рецепт продолжения изменён; подготовьте новый апрув.')


def validate_plan(plan):
    """Pure validation of a frozen plan; no current memory, Store or network."""
    from .research_protocol import LIMITS
    if not isinstance(plan, dict):
        raise ValueError('Отсутствует план продолжения.')
    value = plan.get('continuation')
    if not isinstance(value, dict) or set(value) != _CHECKPOINT_FIELDS:
        raise ValueError('Неверная форма checkpoint редактора.')
    if (value['version'] != CHECKPOINT_VERSION or not isinstance(value['parent_run_id'], str)
            or not _RUN.fullmatch(value['parent_run_id'])
            or value['parent_status'] not in SOURCE_TERMINAL
            or type(value['parent_web_search']) is not bool):
        raise ValueError('Неверные исходный запуск или состояние checkpoint.')
    for key in ('parent_plan_hash', 'parent_context_hash', 'parent_protocol_sha256',
                'parent_output_sha256', 'hash'):
        if not isinstance(value[key], str) or not _HASH.fullmatch(value[key]):
            raise ValueError('Неверный хеш checkpoint: ' + key)
    if value['hash'] != _digest({key: item for key, item in value.items() if key != 'hash'}):
        raise ValueError('Контрольная сумма checkpoint не совпала.')
    prefix = value['prefix']
    if not isinstance(prefix, list) or len(prefix) != 2:
        raise ValueError('Checkpoint требует ровно два исходных прохода.')
    for index, row in enumerate(prefix):
        if (not isinstance(row, dict) or set(row) != _PHASE_FIELDS | {'output'}
                or type(row['index']) is not int or row['index'] != index
                or row['role'] != ['researcher', 'critic'][index]
                or row['status'] != 'completed' or row['dispatched'] is not True
                or not isinstance(row['output'], str) or not row['output'].strip()
                or len(row['output']) > LIMITS[row['role'] + '_output_chars']
                or row['output_sha256'] != _sha(row['output'])
                or not _number(row['elapsed_seconds']) or not isinstance(row['usage'], dict)):
            raise ValueError('Повреждён сохранённый успешный проход.')
        for key in ('prompt_sha256', 'context_hash', 'output_sha256', 'record_sha256'):
            if not isinstance(row[key], str) or not _HASH.fullmatch(row[key]):
                raise ValueError('Неверная цепочка хешей исходного прохода.')
    editor = value['prior_editor']
    if editor is not None:
        if (not isinstance(editor, dict) or set(editor) != _PHASE_FIELDS
                or type(editor['index']) is not int or editor['index'] != 2
                or editor['role'] != 'reviewer' or editor['status'] not in {
                    'dispatch_intent', 'failed', 'cancelled', 'outcome_unknown'}
                or (editor['dispatched'] is not None and type(editor['dispatched']) is not bool)
                or not isinstance(editor['usage'], dict)
                or (editor['elapsed_seconds'] is not None
                    and not _number(editor['elapsed_seconds']))):
            raise ValueError('Повреждён сохранённый неудачный редакторский вызов.')
        for key in ('prompt_sha256', 'context_hash', 'output_sha256', 'record_sha256'):
            if not isinstance(editor[key], str) or not _HASH.fullmatch(editor[key]):
                raise ValueError('Неверные хеши прежней редакторской попытки.')
    original = value['parent_total_timeout_seconds']
    if type(original) is not int or not 200 <= original <= 360:
        raise ValueError('Неверный исходный общий бюджет.')
    successful, attempted, total = _arithmetic(original, prefix, editor)
    if (not 80 <= total <= 360 or value['total_timeout_seconds'] != total
            or type(value['total_timeout_seconds']) is not int
            or value['successful_prefix_seconds'] != successful
            or not _number(value['successful_prefix_seconds'])
            or value['prior_attempted_elapsed_seconds'] != attempted
            or (attempted is not None and not _number(value['prior_attempted_elapsed_seconds']))
            or not isinstance(value['parent_usage'], dict)):
        raise ValueError('Бюджет checkpoint не соответствует успешным исходным проходам.')
    protocol = plan.get('research_protocol')
    validate_protocol(protocol)
    if (protocol['checkpoint_sha256'] != value['hash']
            or protocol['total_timeout_seconds'] != total
            or plan.get('timeout_seconds') != total or type(plan.get('timeout_seconds')) is not int
            or plan.get('web_search') is not False or plan.get('research_mode') != 'reviewed'
            or plan.get('evidence_bundle') is None or plan.get('max_parallel_runs') != 1
            or plan.get('auto_retry') is not False):
        raise ValueError('План не соответствует одобренному редакторскому checkpoint.')


def validate_bound(db, plan):
    """Bind the checkpoint to actual immutable parent rows in the caller's transaction."""
    validate_plan(plan)
    value = plan['continuation']
    source, original, records = _source(db, value['parent_run_id'])
    if _checkpoint(source, records) != value:
        raise ValueError('Исходные проходы или исходный запуск изменились после checkpoint.')
    for key in FROZEN_FIELDS:
        if (key in plan) != (key in original) or plan.get(key) != original.get(key):
            raise ValueError('Замороженный контекст отличается от исходного: ' + key)


def prefix_outputs(plan):
    validate_plan(plan)
    return [row['output'] for row in plan['continuation']['prefix']]


def reused_view(plan):
    validate_plan(plan)
    value = plan['continuation']
    return [{'index': row['index'], 'role': row['role'], 'status': 'reused',
             'source_status': row['status'], 'source_run_id': value['parent_run_id'],
             'output_sha256': row['output_sha256'], 'prompt_sha256': row['prompt_sha256'],
             'elapsed_seconds': row['elapsed_seconds'], 'usage': deepcopy(row['usage']),
             'dispatched': False, 'new_invocation': False} for row in value['prefix']]


def prompt(plan, index, previous_outputs):
    from .compact_editor import payload
    validate_plan(plan)
    if type(index) is not int or index != 0 or previous_outputs != []:
        raise ValueError('Продолжение разрешает только один новый редакторский проход index0.')
    packet = payload(plan, prefix_outputs(plan))
    text = plan['research_protocol']['templates'][0]
    text += '\nВеб-поиск выключен. Переиспользованы два сохранённых ответа; нового поиска нет.\n'
    text += '\nНедоверенные сохранённые данные (JSON):\n' + _canonical(packet)
    if len(text) > plan['research_protocol']['limits']['prompt_chars']:
        raise ValueError('Сохранённый редакторский контекст превышает одобренную границу.')
    return text


def create(store, source_run_id):
    from .trace import freeze
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        source, original, records = _source(db, source_run_id)
        checkpoint = _checkpoint(source, records)
        existing = db.execute(
            "SELECT id,plan,plan_hash FROM runs WHERE status='planned'").fetchall()
        for row in existing:
            candidate = json.loads(row['plan'])
            previous = candidate.get('continuation') or {}
            if previous.get('parent_run_id') != source_run_id:
                continue
            try:
                if row['plan_hash'] != _digest(candidate):
                    raise ValueError('Контрольная сумма подготовленного продолжения не совпала.')
                validate_bound(db, candidate)
                store.trace.validate(candidate, current=True)
            except ValueError:
                continue
            run_id = row['id']
            break
        else:
            plan = deepcopy(original)
            plan.pop('execution_context', None)
            plan.update(version=1, continuation=checkpoint, web_search=False,
                        timeout_seconds=checkpoint['total_timeout_seconds'],
                        research_mode='reviewed', max_parallel_runs=1, auto_retry=False)
            plan['research_protocol'] = build_protocol(checkpoint)
            validate_bound(db, plan)
            plan['execution_context'] = freeze(plan, prompt(plan, 0, []))
            run_id = uuid.uuid4().hex
            db.execute('INSERT INTO runs(id,plan,plan_hash,status,created_at) '
                       'VALUES (?,?,?,?,?)',
                       (run_id, _canonical(plan), _digest(plan), 'planned',
                        datetime.now(timezone.utc).isoformat(timespec='seconds')))
    return store.run(run_id)


def validate_backup(db):
    for row in db.execute('SELECT id,plan FROM runs'):
        plan = json.loads(row['plan'])
        protocol = plan.get('research_protocol') or {}
        if plan.get('continuation') is not None or protocol.get('version') == VERSION:
            validate_bound(db, plan)
