"""Local owner-facing routes; the existing handler enforces host/origin/CSRF."""
import json
import hashlib
import re
import threading


def start_experiment(app, body):
    from .research_experiments import Experiments
    plan_id = body.get('plan_id')
    plan = app.store.assets.get(plan_id)
    if plan['kind'] != 'experiment_plan':
        raise ValueError('Укажите план эксперимента.')
    from .research_assets import canonical
    expected = hashlib.sha256(canonical(plan['payload']).encode('utf-8')).hexdigest()
    if body.get('consent') is not True or body.get('plan_hash') != expected:
        raise ValueError('Подтвердите точный показанный план эксперимента.')
    if not Experiments(app.store).config()['configured']:
        raise ValueError('Сначала настройте API-ключ локально; ключ в чат не отправляйте.')
    with app.lock:
        if app.jobs or app.experiment_jobs:
            raise ValueError('Дождитесь текущего исследования или эксперимента.')
        cancel = threading.Event()

        def execute():
            try:
                Experiments(app.store).start(
                    plan_id, body.get('plan_hash'), body.get('consent'),
                    body.get('command_id'), cancel)
            except Exception:
                app.experiment_errors[plan_id] = (
                    'Эксперимент остановлен. Проверьте журнал; автоматического повтора нет.')
            finally:
                with app.lock:
                    app.experiment_jobs.pop(plan_id, None)

        worker = threading.Thread(target=execute, daemon=True)
        app.experiment_jobs[plan_id] = (cancel, worker)
        try:
            worker.start()
        except Exception:
            app.experiment_jobs.pop(plan_id, None)
            raise ValueError('Рабочий процесс эксперимента не создан; вызов не отправлен.')
    return {'status': 'running', 'plan_id': plan_id, 'notice': 'Без автоматических повторов.'}


def handle_get(handler, path):
    from .lexical_api import handle_get as lexical_get
    if lexical_get(handler, path):
        return True
    store = handler.app.store
    if path == '/api/research':
        from .research_views import workspace
        result = workspace(store)
        result['runtime'] = {'running_experiments': list(handler.app.experiment_jobs),
                             'errors': list(handler.app.experiment_errors.values())}
        handler.send(result)
    elif re.fullmatch('/api/runs/[0-9a-f]{32}/research', path):
        from .research_views import run_view
        run = store.run(path.split('/')[3])
        presentation = handler.app.reviewed_presentation(run) if run['output'] else None
        handler.send(run_view(store, run, presentation))
    elif re.fullmatch(r'/api/research/dossiers/[0-9a-f]{64}\.(html|json)', path):
        from .research_public import render_html
        name = path.split('/')[-1]
        asset = store.assets.get(name.split('.')[0])
        if asset['kind'] != 'public_dossier':
            raise ValueError('Укажите одобренную публичную версию.')
        payload = asset['payload']
        if name.endswith('.html'):
            handler.send(render_html(payload).encode('utf-8'),
                         content_type='text/html; charset=utf-8', download='VV-Frontier.html')
        else:
            handler.send(json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8'),
                         download='VV-Frontier.json')
    else:
        return False
    return True


def handle_post(handler, path, body):
    from .lexical_api import handle_post as lexical_post
    if lexical_post(handler, path, body):
        return True
    store = handler.app.store
    if path == '/api/research/capture':
        from .evidence_archive import Archive
        source = store.source(body.get('source_id'))
        asset = Archive(store).capture(source, fetch=True, refresh=body.get('refresh') is True)
        payload = asset['payload']
        handler.send({'id': asset['id'], 'status': payload['status'],
                      'limitations': payload['limitations'],
                      'notice': 'Нужен новый план, чтобы включить новый захват в исследование.'})
    elif path == '/api/research/cost':
        from .research_workbench import cost_scenarios
        handler.send(cost_scenarios(body))
    elif path == '/api/research/evaluation':
        from .research_evaluation import Evaluation
        handler.send(Evaluation(store).annotate(body))
    elif path == '/api/research/experiments/config':
        from .research_experiments import Experiments
        handler.send(Experiments(store).configure(body.get('api_key'), body.get('model')))
    elif path == '/api/research/experiments/plan':
        from .research_experiments import Experiments
        handler.send(Experiments(store).plan(body))
    elif path == '/api/research/experiments/start':
        handler.send(start_experiment(handler.app, body))
    elif path == '/api/research/experiments/import':
        from .research_experiments import Experiments
        handler.send(Experiments(store).imports(body))
    elif re.fullmatch('/api/runs/[0-9a-f]{32}/dossier', path):
        from .research_public import approve
        run = store.run(path.split('/')[3])
        if run['status'] != 'completed':
            raise ValueError('Публичная версия доступна после завершения исследования.')
        handler.send(approve(store, handler.app.reviewed_presentation(run),
                             body.get('projection_hash'), body.get('consent')))
    else:
        return False
    return True
