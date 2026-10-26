"""One fixed CPU benchmark behind existing owner-local Host/Origin/CSRF checks."""
import json
from pathlib import Path
import re
import threading

from .lexical_benchmark import LexicalBenchmark, DATASET_PARTS

BASE = '/api/benchmarks/lexical'
ITEM = re.compile(BASE + r'/([0-9a-f]{64})(?:/(export))?\Z')


def view(app, plan_id):
    service = LexicalBenchmark(app.store)
    result = service.status(plan_id)
    result['plan'] = service.assets.get(plan_id)['payload']
    if plan_id in app.experiment_jobs and result['status'] in {'planned', 'outcome_unknown'}:
        result['status'] = 'running'
        result['notice'] = 'Рабочий поток проверяет зафиксированные входы и журнал CPU-проверки.'
    if plan_id in app.experiment_errors:
        result['error'] = app.experiment_errors[plan_id]
    return result


def handle_get(handler, path):
    if path == BASE:
        return handler.send({'items': LexicalBenchmark(handler.app.store).list()}) or True
    match = ITEM.fullmatch(path)
    if not match:
        return False
    data = view(handler.app, match[1])
    if match[2]:
        return handler.send(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2).encode('utf-8'),
                            content_type='application/json; charset=utf-8',
                            download='VV-Frontier-lexical-benchmark.json') or True
    handler.send(data)
    return True


def handle_post(handler, path, body):
    if path not in {BASE + '/prepare', BASE + '/start'}:
        return False
    app = handler.app
    service = LexicalBenchmark(app.store)
    if not isinstance(body, dict):
        raise ValueError('Нужен объект локального плана.')
    if path.endswith('/prepare'):
        if body:
            raise ValueError('Этот кейс использует только зафиксированный локальный датасет.')
        source = Path(app.store.data_dir).joinpath(*DATASET_PARTS, 'manifest.json')
        if source.is_symlink() or not source.is_file() or source.stat().st_size > 256 * 1024:
            raise ValueError('Данные SciFact ещё не подготовлены в лаборатории.')
        plan = service.prepare(json.loads(source.read_text(encoding='utf-8')))
        handler.send(view(app, plan['plan_id']))
        return True
    if set(body) != {'plan_id', 'plan_hash', 'consent', 'command_id'}:
        raise ValueError('Подтвердите только точный показанный CPU-план.')
    plan_id, plan_hash, command_id = body['plan_id'], body['plan_hash'], body['command_id']
    if (not isinstance(plan_id, str) or not re.fullmatch('[a-f0-9]{64}', plan_id)
            or not isinstance(plan_hash, str) or not re.fullmatch('[a-f0-9]{64}', plan_hash)
            or body['consent'] is not True or not isinstance(command_id, str)
            or not 8 <= len(command_id) <= 100):
        raise ValueError('Нужен явный апрув показанного хеша и ID команды.')
    previous = service.status(plan_id)
    if previous['plan_hash'] != plan_hash:
        raise ValueError('Показанный план изменился; нужен новый апрув.')
    if previous['status'] != 'planned':
        handler.send(view(app, plan_id))
        return True
    with app.lock:
        if app.jobs or app.experiment_jobs:
            raise ValueError('Дождитесь текущего исследования или эксперимента.')
        cancelled = threading.Event()

        def execute():
            try:
                service.start(plan_id, plan_hash, True, command_id, cancelled)
            except Exception:
                app.experiment_errors[plan_id] = (
                    'CPU-проверка не завершилась. Проверьте план, данные и журнал; автоматического повтора нет.')
            finally:
                with app.lock:
                    app.experiment_jobs.pop(plan_id, None)

        worker = threading.Thread(target=execute, daemon=True)
        app.experiment_errors.pop(plan_id, None)
        app.experiment_jobs[plan_id] = (cancelled, worker)
        try:
            worker.start()
        except Exception:
            app.experiment_jobs.pop(plan_id, None)
            raise ValueError('Рабочий поток не создан; CPU-проверка не отправлена.')
    handler.send({**previous, 'status': 'running', 'notice': 'Принят один CPU-прогон. Без моделей и повторов.'})
    return True
