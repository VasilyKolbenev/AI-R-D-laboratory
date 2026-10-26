"""Owner-local read models. Never fetch, dispatch, annotate or leak raw captures."""
from copy import deepcopy


def source_view(asset):
    value = asset.get('payload', asset)
    result = {key: deepcopy(value.get(key)) for key in (
        'source_id', 'url', 'kind', 'status', 'sha256', 'retrieved_at',
        'retrieved_time', 'parser_version', 'origin', 'limitations',
        'previous_asset_id', 'source_changed') if key in value}
    result['asset_id'] = asset.get('id') or value.get('asset_id')
    result['document_id'] = result['asset_id']
    result['segments'] = [
        {key: segment.get(key, '') for key in ('id', 'locator', 'text')}
        for segment in value.get('segments', [])[:80] if isinstance(segment, dict)
    ]
    return result


def workspace(store):
    from .research_assets import Assets
    from .research_workbench import Workbench
    from .research_evaluation import Evaluation
    from .research_experiments import Experiments
    from .lexical_benchmark import LexicalBenchmark
    workbench, experiments = Workbench(store), Experiments(store)
    return {
        'sources': [source_view(item) for item in Assets(store).list('source_capture')],
        'measurements': workbench.measurements(),
        'impacts': workbench.impacts(),
        'evaluation': Evaluation(store).summary(),
        'experiments': experiments.status(),
        'lexical_benchmarks': LexicalBenchmark(store).list(),
        'experiment_config': experiments.config(),
    }


def run_view(store, run, presentation):
    from .research_workbench import Workbench
    from .research_evaluation import Evaluation
    from .research_public import preview
    from .research_readiness import assess
    presentation = presentation if isinstance(presentation, dict) else {}
    bundle = run.get('plan', {}).get('evidence_bundle') or {}
    documents = bundle.get('documents') or []
    workbench = Workbench(store)
    selected = workbench.selected([run['id']])
    measurements = (selected.get('measurements', [])
                    if isinstance(selected, dict) else selected)
    return {
        'sources': [source_view(item) for item in documents],
        'evidence': deepcopy(presentation.get('source_validation') or {
            'status': 'pending' if run.get('status') == 'planned' else 'legacy',
            'checks': [], 'issues': [],
            'notice': 'Привязка выводов к сохранённому оригиналу пока не зафиксирована.'}),
        'measurements': measurements,
        'measurement_assets': deepcopy(measurements),
        'readiness': assess(run, presentation, measurements=measurements),
        'recipe': workbench.recipe(run, presentation),
        'evaluation': Evaluation(store).summary(run['id']),
        'public_preview': preview(presentation) if presentation.get('title') else None,
    }
