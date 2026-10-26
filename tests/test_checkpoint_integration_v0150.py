"""Owner approval integration: reuse paid prefix and dispatch only one new editor."""
import json
from copy import deepcopy
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from laboratory.core import LabError, Store
from laboratory.orchestration import execute
from test_grounded_flow_v0140 import packets
import test_telegram_workflow as tg


def source_attempt(folder, store=None):
    store = store or Store(Path(folder) / 'data')
    store.update_settings({'research_mode': 'reviewed', 'timeout_seconds': 360,
                           'source_grounding': True, 'capture_originals': False})
    source, _ = store.add_source('Latency is 10 ms for baseline and 8 ms for candidate.',
                                  'TEST_ONLY primary', 'https://example.org/paper')
    parent = store.create_plan({'source_ids': [source['id']]})
    store.approve(parent['id'], parent['plan_hash'], True, 'TEST_ONLY-original')
    outputs, calls, clock = packets(parent), [], [0.0]

    def runner(plan, prompt, directory, cancel):
        index = len(calls)
        calls.append(index)
        clock[0] += [106.515, 82.453, 110.235][index]
        if index == 2:
            return {'status': 'outcome_unknown', 'text': '', 'usage': {},
                    'error': 'TEST_ONLY timeout', 'raw': {'dispatched': True}}
        return {'status': 'completed', 'text': outputs[index],
                'usage': {'input_tokens': 100, 'output_tokens': 10},
                'raw': {'dispatched': True}}

    with patch('laboratory.orchestration.time.monotonic', side_effect=lambda: clock[0]):
        result = execute(store, store.run(parent['id']), runner,
                         Path(folder) / 'first', threading.Event())
    store.finish(parent['id'], result)
    assert store.run(parent['id'])['status'] == 'outcome_unknown'
    return store, store.run(parent['id']), outputs


class CheckpointApprovalTests(unittest.TestCase):
    def test_public_store_checkpoint_entry_exists(self):
        self.assertTrue(callable(getattr(Store, 'create_continuation', None)),
                        'A separate checkpoint factory is required before owner approval')

    def test_saved_web_evidence_remains_valid_but_new_editor_stays_offline(self):
        from tempfile import TemporaryDirectory
        import test_checkpoint_v0150 as checkpoint_fixture
        from laboratory.research_continuation import prefix_outputs
        from laboratory.applied_analysis import validate_phase
        with TemporaryDirectory(dir=tg.TMP) as folder:
            store = Store(Path(folder) / 'data')
            parent = checkpoint_fixture.CheckpointTests().parent(store, web=True)
            child = store.create_continuation(parent['id'])
            self.assertEqual(validate_phase(child['plan'], 1,
                                           prefix_outputs(child['plan']))['status'], 'ready')
            self.assertTrue(store.approve(child['id'], child['plan_hash'], True,
                                          'TEST_ONLY-web-prefix'))
            final = packets(parent)[2]
            raw = final[final.index('<lab_presentation>'):]
            calls = []

            def editor(plan, *args):
                calls.append(1)
                self.assertFalse(plan['web_search'])
                return {'status': 'completed', 'text': raw, 'usage': {},
                        'raw': {'dispatched': True}}

            result = execute(store, store.run(child['id']), editor,
                             Path(folder) / 'editor', threading.Event())
            self.assertEqual(result['status'], 'completed', result.get('error'))
            self.assertEqual(len(calls), 1)
            checked = result['raw']['orchestration']['review']['critic']['checked_sources']
            self.assertEqual(checked[0]['source_url'], 'https://example.org/independent')

    def test_one_new_approved_editor_keeps_prefix_and_daily_cap(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory(dir=tg.TMP) as folder:
            store, parent, old_outputs = source_attempt(folder)
            old_trace = store.agent_trace(parent['id'])
            new = store.create_continuation(parent['id'])
            self.assertEqual(new['plan']['timeout_seconds'], 171)
            self.assertEqual(new['plan']['research_protocol']['phase_timeouts'], [151])
            self.assertEqual(new['plan']['research_protocol']['max_calls'], 1)
            self.assertEqual(store.create_continuation(parent['id'])['id'], new['id'])
            self.assertEqual(store.agent_trace(new['id'])['phases'], [])
            with self.assertRaises(LabError):
                store.approve(new['id'], new['plan_hash'], False, 'TEST_ONLY-no-consent')
            with self.assertRaisesRegex(LabError, 'бюджет'):
                store.approve(new['id'], new['plan_hash'], True, 'TEST_ONLY-no-budget')
            allowance = store.grant_pilot(new['id'], new['plan_hash'])
            self.assertEqual(allowance['state'], 'pending')
            self.assertEqual(store.settings()['daily_run_limit'], 3)
            self.assertTrue(store.approve(new['id'], new['plan_hash'], True, 'TEST_ONLY-new'))
            self.assertFalse(store.approve(new['id'], new['plan_hash'], True, 'TEST_ONLY-new'))
            raw_packet = old_outputs[2][old_outputs[2].index('<lab_presentation>'):]
            calls = []

            def editor(plan, prompt, directory, cancel):
                calls.append((plan, prompt))
                self.assertEqual(plan['timeout_seconds'], 151)
                self.assertFalse(plan['web_search'])
                return {'status': 'completed', 'text': raw_packet,
                        'usage': {'input_tokens': 12, 'output_tokens': 8},
                        'raw': {'dispatched': True}}

            result = execute(store, store.run(new['id']), editor,
                             Path(folder) / 'resume', threading.Event())
            self.assertEqual(result['status'], 'completed', result.get('error'))
            store.finish(new['id'], result)
            self.assertEqual(len(calls), 1)
            self.assertEqual(result['usage'], {'input_tokens': 12, 'output_tokens': 8})
            self.assertEqual(store.agent_trace(parent['id']), old_trace)
            self.assertEqual(store.run(parent['id'])['status'], 'outcome_unknown')
            trace = store.agent_trace(new['id'])
            self.assertEqual([row['role'] for row in trace['phases']], ['reviewer'])
            self.assertEqual(trace['dispatched_calls'], 1)
            self.assertEqual(trace['reserved_calls'], 1)
            from laboratory.presentation import build_presentation
            data = build_presentation(store.run(new['id']), store.review.get(new['id']))
            self.assertEqual(data['source_validation']['status'], 'ready')
            self.assertEqual(data['publication_checks']['status'], 'ready')
            tampered = deepcopy(store.run(new['id']))
            tampered['agent_pipeline']['reused_phases'][0]['output_sha256'] = '0' * 64
            self.assertEqual(build_presentation(tampered)['publication_checks']['status'],
                             'incomplete')
            tampered = deepcopy(store.run(new['id']))
            tampered['agent_pipeline']['phases'][0]['dispatched'] = False
            self.assertEqual(build_presentation(tampered)['publication_checks']['status'],
                             'incomplete')
            self.assertEqual(store.run(new['id'])['research_ingestion']['status'], 'ready')
            restored = Store(Path(folder) / 'restored')
            restored.restore(store.export())
            self.assertEqual(restored.run(new['id'])['output'], store.run(new['id'])['output'])
            self.assertEqual(restored.agent_trace(parent['id']), old_trace)


if __name__ == '__main__':
    unittest.main()
