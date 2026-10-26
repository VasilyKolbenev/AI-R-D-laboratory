"""Depth is derived from saved artifacts, never from an agent's completion flag."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from laboratory.research_assets import canonical, identity
from laboratory.research_readiness import assess


def fixture():
    quote = 'TEST_ONLY baseline latency is 10 ms and candidate latency is 8 ms.'
    task = {
        'task_type': 'classification', 'business_goal': 'TEST_ONLY route support requests',
        'inputs': 'TEST_ONLY request text', 'expected_output': 'TEST_ONLY one routing label',
        'baseline': {'name': 'Rules', 'version': 'rules-v1'},
        'metrics': [{'name': 'Latency', 'definition': 'Time per request', 'unit': 'ms',
                     'direction': 'minimize', 'target': 'TEST_ONLY p95 below a fixed threshold',
                     'primary': True}],
        'success_criteria': 'TEST_ONLY latency target with unchanged held-out accuracy',
        'dataset': 'TEST_ONLY held-out-routing-v1', 'evaluation': 'TEST_ONLY replay-v1',
    }
    context = {'baseline_version': 'rules-v1', 'candidate_version': 'candidate-v1',
               'dataset': 'TEST_ONLY external-dataset-v1', 'evaluation': 'TEST_ONLY external-protocol-v1',
               'hardware': 'TEST_ONLY GPU-A', 'load': 'TEST_ONLY one concurrent request'}
    row = {'id': 'latency', 'metric': 'Latency', 'definition': 'Time per request',
           'unit': 'ms', 'direction': 'minimize', 'conditions': 'TEST_ONLY external conditions',
           'comparability': 'comparable', 'measurement_context': context,
           'baseline': {'label': 'Rules', 'value': 10, 'basis': 'author_claim', 'evidence_ids': ['e1']},
           'candidate': {'label': 'Candidate', 'value': 8, 'basis': 'external_measurement', 'evidence_ids': ['e1']}}
    document = {'asset_id': 'a' * 64, 'url': 'https://example.org/TEST_ONLY',
                'origin': 'fetched', 'status': 'captured',
                'segments': [{'id': 's1', 'text': quote, 'locator': 'TEST_ONLY table 1'}]}
    run = {'id': '1' * 32, 'status': 'completed', 'output': quote,
           'plan': {'study_context': {'task': task}, 'evidence_bundle': {'documents': [document]}}}
    presentation = {
        'evidence': [{'id': 'e1', 'claim': 'TEST_ONLY external latency comparison',
                      'source_url': document['url'], 'excerpt': quote}],
        'source_validation': {'status': 'ready', 'checks': [
            {'evidence_id': 'e1', 'document_id': document['asset_id'], 'segment_id': 's1',
             'quote': quote, 'relation': 'supports'}]},
        'applied_analysis': {'rows': [row]}, 'findings': ['TEST_ONLY authors report a comparison'],
    }
    return run, presentation


def api_observation(arm='baseline'):
    output = 'TEST_ONLY API output'
    payload = {'version': 'experiment-observation-v1', 'origin': 'executed_api',
               'plan_id': 'a' * 64, 'intent_id': 'b' * 64,
               'index': 0 if arm == 'baseline' else 1, 'case_id': 'TEST_ONLY_case',
               'arm': arm, 'repetition': 0, 'status': 'completed', 'output': output,
               'output_sha256': hashlib.sha256(output.encode()).hexdigest(),
               'raw_sha256': 'c' * 64, 'latency_ms': 12, 'usage': {'output_tokens': 5},
               'actual_cost_usd': None, 'metrics': {'latency_ms': 12, 'exact_match': True},
               'error': '', 'finished_at': '2026-10-26T00:00:00+00:00'}
    return {'id': identity('experiment_observation', payload), 'payload': payload}


class ReadinessTests(unittest.TestCase):
    def test_completed_cli_and_source_numbers_never_claim_a_local_technology_test(self):
        run, presentation = fixture()
        before = deepcopy((run, presentation))
        result = assess(run, presentation, measurements=[{
            'run_id': run['id'], 'origin': 'stored_source_analysis',
            'basis': 'external_measurement', 'value': 8, 'status': 'completed'}])
        self.assertEqual(result['stage'], 'externally_evaluated')
        self.assertEqual(result['external_results']['source_bound_pairs'], 1)
        self.assertEqual(result['provenance']['stored_source_analysis'], 1)
        self.assertEqual(result['provenance']['executed_technology_tests'], 0)
        self.assertFalse(result['provenance']['empirical_technology_validation'])
        self.assertFalse(result['provenance']['independently_verified'])
        self.assertEqual(result['gates']['execution']['status'], 'not_executed')
        self.assertEqual(result['last_step']['status'], 'not_executed')
        self.assertEqual((run, presentation), before)
        self.assertNotIn('confidence', result)
        self.assertNotIn('score', result)

    def test_report_only_and_legacy_completion_keep_their_actual_depth(self):
        run, presentation = fixture()
        presentation.pop('source_validation')
        result = assess(run, presentation)
        self.assertEqual(result['stage'], 'source_review')
        self.assertEqual(result['external_results']['reported_pairs'], 1)
        self.assertEqual(result['external_results']['source_bound_pairs'], 0)
        self.assertEqual(result['claim_coverage']['report_backed'], 1)
        self.assertEqual(result['claim_coverage']['source_backed'], 0)
        self.assertIn('original_bindings', result['gates']['evidence']['missing'])
        self.assertFalse(result['comparison_dimensions']['latency']['measurements'][0]['chart_eligible'])
        legacy = assess({'status': 'completed', 'output': 'TEST_ONLY old report'}, {})
        self.assertEqual(legacy['label'], 'Разбор источников')
        self.assertEqual(legacy['last_step']['status'], 'not_executed')

    def test_unread_source_or_forged_ready_flags_do_not_cover_claims(self):
        run, presentation = fixture()
        run['plan']['evidence_bundle']['documents'][0]['status'] = 'blocked'
        presentation['source_validation']['checks'][0].update(literal_quote=True, source_bound=True)
        result = assess(run, presentation)
        self.assertEqual(result['claim_coverage']['source_backed'], 0)
        self.assertEqual(result['external_results']['source_bound_pairs'], 0)
        self.assertEqual(result['stage'], 'source_review')
        run['plan']['evidence_bundle']['documents'][0]['status'] = 'captured'
        presentation['source_validation']['checks'][0]['quote'] = 'TEST_ONLY fabricated quote 8'
        self.assertEqual(assess(run, presentation)['claim_coverage']['source_backed'], 0)

    def test_duplicate_document_and_segment_ids_are_ambiguous_not_source_coverage(self):
        run, presentation = fixture()
        documents = run['plan']['evidence_bundle']['documents']
        documents.append(deepcopy(documents[0]))
        result = assess(run, presentation)
        self.assertEqual(result['claim_coverage']['ambiguous_document_ids'], ['a' * 64])
        self.assertEqual(result['claim_coverage']['source_backed'], 0)
        self.assertEqual(result['external_results']['source_bound_pairs'], 0)
        self.assertIn('Повторяются ID источников', result['gates']['evidence']['details'])
        documents.pop()
        documents[0]['segments'].append(deepcopy(documents[0]['segments'][0]))
        self.assertEqual(assess(run, presentation)['claim_coverage']['source_backed'], 0)
        documents[0]['segments'].pop()
        presentation['evidence'].append(deepcopy(presentation['evidence'][0]))
        duplicate_claim = assess(run, presentation)
        self.assertEqual(duplicate_claim['claim_coverage']['ambiguous_evidence_ids'], ['e1'])
        self.assertEqual(duplicate_claim['claim_coverage']['source_backed'], 0)

    def test_missing_task_baseline_cannot_be_filled_by_a_source_chart(self):
        run, presentation = fixture()
        run['plan']['study_context']['task']['baseline'] = {}
        result = assess(run, presentation)
        self.assertEqual(result['stage'], 'source_review')
        self.assertEqual(result['gates']['baseline']['missing'], ['name', 'version'])
        action = next(row for row in result['next_actions'] if row['gate'] == 'baseline')
        self.assertIn('версия решения для сравнения', action['action'])

    def test_unknown_structured_conditions_are_not_recovered_from_free_prose(self):
        run, presentation = fixture()
        presentation['applied_analysis']['rows'][0]['measurement_context']['hardware'] = None
        presentation['applied_analysis']['rows'][0]['conditions'] = 'TEST_ONLY GPU-A and all versions match'
        result = assess(run, presentation)
        self.assertIn('hardware', result['gates']['conditions']['missing'])
        self.assertEqual(result['stage'], 'source_review')
        self.assertFalse(result['comparison_dimensions']['latency']['measurements'][0]['chart_eligible'])

    def test_synthetic_results_and_simulations_never_become_empirical_validation(self):
        run, presentation = fixture()
        presentation['applied_analysis']['rows'][0]['origin'] = 'simulation'
        result = assess(run, presentation, experiment_observations=[{
            'origin': 'synthetic', 'status': 'completed', 'accuracy': 1.0}])
        self.assertEqual(result['stage'], 'source_review')
        self.assertEqual(result['external_results']['reported_pairs'], 0)
        self.assertEqual(result['provenance']['simulation_records'], 1)
        self.assertEqual(result['provenance']['simulated_comparison_rows'], 1)
        self.assertFalse(result['provenance']['empirical_technology_validation'])
        self.assertEqual(result['comparison_dimensions']['latency']['status'], 'unknown')

    def test_valid_bounded_responses_records_remain_api_cases_not_a_technology_benchmark(self):
        run, presentation = fixture()
        result = assess(run, presentation, experiment_observations=[
            api_observation(), api_observation('candidate'), api_observation()])
        self.assertEqual(result['provenance']['recorded_api_cases'], 2)
        self.assertEqual(result['provenance']['completed_api_cases'], 2)
        self.assertEqual(result['provenance']['executed_technology_tests'], 0)
        self.assertFalse(result['provenance']['local_testing_supported'])
        self.assertIn('raw_metric_artifacts', result['gates']['reproducibility']['missing'])
        self.assertNotEqual(result['stage'], 'locally_tested')
        fake = api_observation()
        fake['payload']['output'] = 'TEST_ONLY changed after execution'
        invalid = assess(run, presentation, experiment_observations=[fake])
        self.assertEqual(invalid['provenance']['recorded_api_cases'], 0)
        self.assertEqual(invalid['provenance']['unrecognized_experiment_records'], 1)

    def test_imported_metrics_remain_imported_and_are_not_independently_verified(self):
        run, presentation = fixture()
        observations = [{'case_id': 'TEST_ONLY', 'arm': 'baseline', 'repetition': 0,
                         'output': 'TEST_ONLY', 'latency_ms': 0, 'metrics': {}}]
        record = {'version': 'experiment-import-v1', 'origin': 'imported_not_executed_here',
                  'plan_id': None, 'observations': observations,
                  'raw_sha256': hashlib.sha256(canonical(observations).encode()).hexdigest(),
                  'note': 'TEST_ONLY', 'notice': 'TEST_ONLY imported'}
        result = assess(run, presentation, experiment_observations=[record])
        self.assertEqual(result['provenance']['imported_observations'], 1)
        self.assertEqual(result['provenance']['recorded_api_cases'], 0)
        self.assertFalse(result['provenance']['independently_verified'])

    def test_frozen_guidance_alone_does_not_promote_readiness(self):
        from laboratory.research_protocol import freeze_validation_contract
        run, presentation = fixture()
        protocol = freeze_validation_contract({'templates': ['', '', '']}, run['plan'])
        run['plan']['research_protocol'] = protocol
        presentation['source_validation'] = {}
        designed = assess(run, presentation)
        self.assertEqual(designed['stage'], 'validation_designed')
        self.assertEqual(designed['validation_design']['status'], 'described')
        run['plan']['study_context']['task']['metrics'] = []
        limited = assess(run, presentation)
        self.assertEqual(limited['stage'], 'source_review')
        self.assertEqual(limited['validation_design']['status'], 'incomplete')
        self.assertEqual(limited['gates']['metrics']['status'], 'partial')

    def test_comparison_dimensions_preserve_zero_and_unknown_without_prose_inference(self):
        run, presentation = fixture()
        row = presentation['applied_analysis']['rows'][0]
        row['baseline']['value'] = 0
        row['candidate']['value'] = None
        presentation['resources'] = ['TEST_ONLY GPU-99 costs 100 USD and quality is 99%']
        result = assess(run, presentation)
        latency = result['comparison_dimensions']['latency']['measurements'][0]
        self.assertEqual(latency['baseline']['value'], 0)
        self.assertIsNone(latency['candidate']['value'])
        self.assertFalse(latency['chart_eligible'])
        self.assertEqual(result['comparison_dimensions']['cost']['status'], 'unknown')
        self.assertEqual(result['comparison_dimensions']['quality']['measurements'], [])
        self.assertIsNone(result['comparison_dimensions']['infrastructure']['fields']['gpu'])
        self.assertEqual(result['comparison_dimensions']['infrastructure']['status'], 'unknown')

    def test_machine_json_numbers_are_not_counted_as_report_support(self):
        run, presentation = fixture()
        run['output'] = 'TEST_ONLY no numeric result\n<lab_presentation>' + json.dumps(presentation) + '</lab_presentation>'
        result = assess(run, presentation)
        self.assertEqual(result['claim_coverage']['report_backed'], 0)
        self.assertEqual(result['external_results']['reported_pairs'], 0)
        self.assertNotEqual(result['stage'], 'externally_evaluated')

    def test_read_only_run_view_integration_uses_registry_copy_and_never_dispatches(self):
        from laboratory.core import Store
        from laboratory.research_views import run_view
        temporary_root = Path(__file__).parent / '.tmp'
        temporary_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as directory:
            store = Store(Path(directory) / 'data')
            source, _ = store.add_source('TEST_ONLY source')
            run = store.create_plan({'source_ids': [source['id']]})
            before = store.export()
            with patch('laboratory.research_experiments._transport', side_effect=AssertionError('No API')):
                result = run_view(store, run, None)
            self.assertEqual(result['readiness']['version'], 'readiness-v1')
            self.assertEqual(result['readiness']['stage'], 'incomplete')
            self.assertEqual(result['measurement_assets'], result['measurements'])
            self.assertIsNot(result['measurement_assets'], result['measurements'])
            self.assertEqual(store.export(), before)


if __name__ == '__main__':
    unittest.main()
