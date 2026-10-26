"""Registry and assumption calculations through local public seams."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from laboratory.core import Store
from laboratory.research_workbench import Workbench, compatibility, cost_scenarios

TMP = Path(__file__).parent / '.tmp'
TMP.mkdir(exist_ok=True)


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TMP)
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        source = self.store.add_source('TEST_ONLY AI latency 8 ms', url='https://example.org/a')[0]
        run = self.store.create_plan({'source_ids': [source['id']]})
        self.store.approve(run['id'], run['plan_hash'], True, 'TEST_ONLY-registry-approval')
        self.store.finish(run['id'], {'status': 'completed', 'text': 'TEST_ONLY AI latency 8 ms'})
        self.run = self.store.run(run['id'])
        side = {'label': 'Method', 'value': 8, 'basis': 'author_claim', 'evidence_ids': ['e1']}
        self.presentation = {
            'publication_checks': {'status': 'ready'}, 'agent_review': {'status': 'ready'},
            'evidence': [{'id': 'e1', 'source_url': 'https://example.org/a'}],
            'applied_analysis': {'rows': [{
                'id': 'latency', 'metric': 'Latency', 'definition': 'Time per request',
                'unit': 'ms', 'direction': 'minimize', 'conditions': 'Model v1, workload unknown',
                'comparability': 'unknown', 'baseline': {**side, 'value': None},
                'candidate': side}], 'unknowns': ['Hardware and workload unknown']}}
        self.workbench = Workbench(self.store)

    def test_registry_is_idempotent_and_only_selected_runs_enter_context(self):
        first = self.workbench.ingest(self.run, self.presentation)
        self.assertEqual(len(first), 2)
        self.assertEqual(first, self.workbench.ingest(self.run, self.presentation))
        self.assertEqual(len(self.workbench.measurements()), 2)
        self.assertEqual(self.workbench.selected([])['measurements'], [])
        selected = self.workbench.selected([self.run['id']])
        self.assertEqual(len(selected['measurements']), 2)
        self.assertEqual(selected['run_ids'], [self.run['id']])
        self.assertEqual(first[1]['payload']['basis'], 'author_claim')
        self.assertIsNone(first[0]['payload']['value'])
        self.assertNotIn('rank', selected)

    def test_incomplete_result_is_not_registered_as_measured_fact(self):
        self.presentation['agent_review']['status'] = 'incomplete'
        self.assertEqual(self.workbench.ingest(self.run, self.presentation), [])

    def test_costs_keep_unknown_rates_and_explicit_assumption_arithmetic(self):
        unknown = cost_scenarios({'requests': 2, 'input_tokens': 100, 'output_tokens': 20})
        self.assertIsNone(unknown['estimated_cost_usd'])
        value = cost_scenarios({
            'requests': 2, 'input_tokens': 100, 'output_tokens': 20,
            'input_usd_per_million': 1, 'output_usd_per_million': 5, 'fixed_cost_usd': 0})
        self.assertAlmostEqual(value['estimated_cost_usd'], .0004)
        self.assertEqual(value['status'], 'assumption_based')
        self.assertEqual(len(value['sensitivity']), 3)
        with self.assertRaises(ValueError):
            cost_scenarios({'requests': True})

    def test_unknown_fixed_overhead_keeps_total_and_total_sensitivity_unknown(self):
        value = cost_scenarios({
            'requests': 2, 'input_tokens': 100, 'output_tokens': 20,
            'input_usd_per_million': 1, 'output_usd_per_million': 5})
        self.assertIsNone(value['estimated_cost_usd'])
        self.assertAlmostEqual(value['variable_cost_usd'], .0004)
        self.assertIsNone(value['assumptions']['fixed_cost_usd'])
        self.assertTrue(all(row['estimated_cost_usd'] is None for row in value['sensitivity']))

    def test_recipe_contains_case_acceptance_and_unknowns_without_fake_results(self):
        recipe = self.workbench.recipe(self.run, self.presentation)
        self.assertIn('acceptance_criteria', recipe)
        self.assertIn('Hardware and workload unknown', recipe['unknowns'])
        self.assertEqual(recipe['execution'], 'not_executed')

    def test_extracted_conditions_preserved_and_unknown_prevents_ranking(self):
        row = self.presentation['applied_analysis']['rows'][0]
        row['measurement_context'] = {
            'baseline_version': 'B-v1', 'candidate_version': 'C-v2', 'dataset': 'Set-A',
            'evaluation': 'Protocol-1', 'hardware': 'GPU-A', 'load': '1 request'}
        values = self.workbench.ingest(self.run, self.presentation)
        baseline, candidate = [value['payload'] for value in values]
        self.assertEqual(candidate['model_version'], 'C-v2')
        self.assertEqual(candidate['hardware'], 'GPU-A')
        self.assertEqual(candidate['evaluation'], 'Protocol-1')
        self.assertEqual(compatibility(baseline, candidate)['status'], 'incompatible')
        unknown = {**candidate, 'hardware': None}
        self.assertEqual(compatibility(candidate, unknown)['status'], 'unknown')
        self.assertEqual(compatibility(candidate, candidate)['status'], 'compatible')

    def test_only_successful_fetched_original_changes_raise_impacts(self):
        from laboratory.evidence_archive import Archive
        archive = Archive(self.store)
        source = self.store.sources()[0]
        with patch('laboratory.evidence_archive.pinned_fetch', return_value={
                'raw': b'<p>TEST_ONLY old 8 ms</p>', 'content_type': 'text/html'}):
            captured = archive.capture(source, fetch=True)
        self.run['plan']['evidence_bundle'] = {'documents': [{
            'asset_id': captured['id'], 'url': source['url'],
            'sha256': captured['payload']['sha256']}]}
        self.workbench.ingest(self.run, self.presentation)
        archive.capture(source)
        with patch('laboratory.evidence_archive.pinned_fetch', side_effect=TimeoutError):
            archive.capture(source, fetch=True, refresh=True)
        self.assertEqual(self.workbench.impacts(), [])
        with patch('laboratory.evidence_archive.pinned_fetch', return_value={
                'raw': b'<p>TEST_ONLY changed 7 ms</p>', 'content_type': 'text/html'}):
            archive.capture(source, fetch=True, refresh=True)
        self.assertEqual(len(self.workbench.impacts()), 2)

    def test_registry_backup_roundtrip_preserves_exact_run_binding(self):
        self.workbench.ingest(self.run, self.presentation)
        destination = Store(Path(self.temp.name) / 'restored')
        destination.restore(self.store.export())
        self.assertEqual(len(Workbench(destination).measurements()), 2)


if __name__ == '__main__':
    unittest.main()
