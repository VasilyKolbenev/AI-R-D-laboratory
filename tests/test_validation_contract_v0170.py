import copy
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from laboratory.core import Store
from laboratory.research_protocol import (
    VALIDATION_GUIDANCE, VALIDATION_ROLE_GUIDANCE, _protocol, build_protocol,
    canonical, comparison_context, phase_prompt, validate_protocol,
)


def sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


class ValidationContractTests(unittest.TestCase):
    def plan(self):
        plan = {'question': 'TEST_ONLY compare latency', 'timeout_seconds': 240,
                'web_search': False,
                'sources': [{'id': 'a' * 32, 'title': 'Paper', 'url': 'https://example.org/paper',
                             'text': 'TEST_ONLY source text', 'content_hash': 'b' * 64}],
                'study_context': {}, 'memory': {}}
        plan['comparison_context'] = comparison_context(plan)
        return plan

    def test_historical_recipe_and_prompt_bytes_remain_exact(self):
        plan = self.plan()
        plan['research_protocol'] = _protocol(240)
        frozen = canonical(plan)
        self.assertEqual(sha(canonical(plan['research_protocol'])),
                         'a2a465187254d25fd8de09df2b974d2aa1bc222b05edcec721702795f9dcbe35')
        hashes = ['83b97d16fb616f57a1d314c2dc5ab77aead6a29d24d4f89bf01b97576ca7ac73',
                  'dbeb00d139ab62abae21131e0b5c756bae00e2fde0a18b0311f7933ee32f7cda',
                  'd9e74305f176120deaee614591b55cbfe604d49b1bebeb924bfed3825cd22354']
        prior = ['TEST_ONLY research', 'TEST_ONLY critic']
        for index in range(3):
            validate_protocol(plan['research_protocol'])
            self.assertEqual(sha(phase_prompt(plan, index, prior[:index])), hashes[index])
        self.assertEqual(canonical(plan), frozen)

    def test_original_grounded_and_compact_template_bytes_are_preserved(self):
        cases = [(240, False, '9d564ae436716a7b1177ec8c1e49a3d550419e155b795819d6f3063c0e16ddda'),
                 (360, False, '343936e8f96eed6c856981fc5f09082fdb7f96771587d744234014f0dd3038d3'),
                 (360, True, '87355feff1912965d3018077bb8b6ff5117fdd3e8201e51cbd1d51052b3cc5c7')]
        for total, compact, expected in cases:
            with self.subTest(total=total, compact=compact):
                protocol = build_protocol({'evidence_bundle': {}, 'timeout_seconds': total,
                    **({'editor_format': 'compact-editor-v1'} if compact else {})})
                del protocol['validation_contract']
                for index, text in enumerate(protocol['templates']):
                    suffix = VALIDATION_GUIDANCE + VALIDATION_ROLE_GUIDANCE[index]
                    self.assertTrue(text.endswith(suffix))
                    protocol['templates'][index] = text[:-len(suffix)]
                frozen = canonical(protocol)
                validate_protocol(protocol)
                self.assertEqual(sha(frozen), expected)
                self.assertEqual(canonical(protocol), frozen)

    def test_future_contract_is_frozen_in_plan_and_each_phase(self):
        plan = self.plan()
        plan['research_protocol'] = build_protocol(plan)
        frozen = canonical(plan)
        contract = plan['research_protocol']['validation_contract']
        self.assertEqual(contract['version'], 'applied-validation-v1')
        self.assertEqual(contract['primary_route'], 'source_review_only')
        self.assertEqual(contract['empirical_status'], 'unverified')
        self.assertEqual(contract['dataset_version'], None)
        self.assertFalse(contract['external_execution_authorized'])
        self.assertEqual(contract['source_urls'], ['https://example.org/paper'])
        for index in range(3):
            prompt = phase_prompt(plan, index, ['TEST_ONLY research', 'TEST_ONLY critic'][:index])
            self.assertIn('"validation_contract":' + canonical(contract), prompt)
            self.assertIn('source_review_completed; empirically_unverified', prompt)
            self.assertIn('simulation_illustration никогда не доказывает производительность', prompt)
            self.assertIn('"web_search":false', prompt)
        self.assertEqual(canonical(plan), frozen)

    def test_direct_comparable_route_needs_explicit_task_inputs(self):
        plan = self.plan()
        task = {'business_goal': 'Reduce waiting time', 'baseline': {'name': 'Current', 'version': '1'},
                'metrics': [{'name': 'Latency', 'definition': 'Median wall time per request',
                             'unit': 'ms', 'direction': 'minimize', 'primary': True}],
                'dataset': 'TEST_ONLY fixed examples', 'evaluation': 'Same inputs and hardware',
                'success_criteria': 'Lower median with unchanged quality'}
        plan['study_context'] = {'task': task}
        protocol = build_protocol(plan)
        contract = protocol['validation_contract']
        self.assertEqual(contract['primary_route'], 'external_task_match')
        self.assertEqual(contract['missing_inputs'], [])
        self.assertEqual(contract['execution_mode'], 'source_review_only')
        self.assertEqual(contract['acceptance_criteria'], task['success_criteria'])
        task['baseline']['name'] = 'CHANGED_AFTER_FREEZE'
        self.assertEqual(contract['baseline']['name'], 'Current')
        for missing in ('baseline', 'metrics', 'dataset', 'evaluation'):
            incomplete = copy.deepcopy(plan)
            incomplete['study_context']['task'].pop(missing)
            self.assertEqual(build_protocol(incomplete)['validation_contract']['primary_route'],
                             'source_review_only')

    def test_contract_cannot_authorize_an_execution_or_extend_budgets(self):
        protocol = build_protocol(self.plan())
        for key, value in [('external_execution_authorized', True), ('execution_mode', 'benchmark'),
                           ('empirical_status', 'verified'), ('version', 'unknown'),
                           ('auto_execute', True), ('primary_route', 'controlled_experiment')]:
            changed = copy.deepcopy(protocol)
            changed['validation_contract'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_protocol(changed)
        self.assertEqual(protocol['max_calls'], 3)
        self.assertEqual(protocol['total_timeout_seconds'], 240)
        self.assertEqual(protocol['phase_timeouts'], [100, 60, 60])
        self.assertFalse(protocol['auto_retry'])
        self.assertEqual(protocol['web_search_budgets'], {
            'researcher': {'searches': 2, 'pages': 3},
            'critic': {'searches': 1, 'pages': 2},
            'reviewer': {'searches': 0, 'pages': 0}})

    def test_new_grounded_and_compact_plans_freeze_contract_without_dispatch(self):
        for compact in (False, True):
            with self.subTest(compact=compact), TemporaryDirectory() as folder:
                store = Store(Path(folder))
                store.update_settings({'research_mode': 'reviewed', 'timeout_seconds': 360,
                    'web_search': False, 'source_grounding': True,
                    'capture_originals': False, 'compact_editor': compact})
                source, _ = store.add_source('TEST_ONLY author reports a method.', 'TEST_ONLY',
                                               'https://example.org/paper')
                with patch('subprocess.Popen', side_effect=AssertionError('No dispatch')):
                    run = store.create_plan({'source_ids': [source['id']],
                                             'question': 'TEST_ONLY compare practical methods'})
                plan = run['plan']
                self.assertEqual(run['status'], 'planned')
                self.assertEqual(plan['research_protocol']['max_calls'], 3)
                self.assertEqual(plan['research_protocol']['total_timeout_seconds'], 360)
                self.assertEqual(plan['research_protocol']['validation_contract']['primary_route'],
                                 'source_review_only')
                self.assertIn('"validation_contract":', plan['execution_context']['prompt'])
                self.assertIn('"validation_contract":', phase_prompt(plan, 1, ['TEST_ONLY research']))
                if compact:
                    outputs = ['<lab_research>{"version":"research-packet-v1","claims":[]}</lab_research>',
                               '<lab_critic>{"version":"critic-review-v1","issues":[]}</lab_critic>']
                else:
                    outputs = ['TEST_ONLY research', 'TEST_ONLY critic']
                self.assertIn('"validation_contract":', phase_prompt(plan, 2, outputs))
                self.assertEqual(store.export()['tables']['agent_phases'], [])

    def test_single_offline_plan_keeps_original_execution_shape(self):
        with TemporaryDirectory() as folder:
            store = Store(Path(folder))
            store.update_settings({'research_mode': 'single', 'web_search': False})
            source, _ = store.add_source('TEST_ONLY source.', 'TEST_ONLY')
            with patch('subprocess.Popen', side_effect=AssertionError('No dispatch')):
                run = store.create_plan({'source_ids': [source['id']], 'question': 'TEST_ONLY review'})
            self.assertEqual(run['status'], 'planned')
            self.assertNotIn('research_protocol', run['plan'])
            self.assertNotIn('validation_contract', run['plan']['execution_context']['prompt'])
            self.assertFalse(run['plan']['web_search'])
            self.assertEqual(store.export()['tables']['agent_phases'], [])


if __name__ == '__main__':
    unittest.main()
