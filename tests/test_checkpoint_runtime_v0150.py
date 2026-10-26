"""One physical reviewer invocation; dependency contracts are isolated explicitly."""
from pathlib import Path
from types import SimpleNamespace
from copy import deepcopy
import json
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from laboratory import orchestration
from laboratory.core import Store
from laboratory.trace import canonical, sha

TMP = Path(__file__).parent / '.tmp'
TMP.mkdir(exist_ok=True)


class CheckpointRuntimeTests(unittest.TestCase):
    def test_validated_checkpoint_reserves_one_new_call(self):
        plan = {'research_protocol': {'version': 'editor-resume-v1', 'max_calls': 1,
                                     'roles': ['reviewer']}, 'continuation': {}}
        dependency = SimpleNamespace(validate_plan=lambda value: None)
        with patch('laboratory.research_protocol.validate_protocol', return_value=None), \
                patch.dict(sys.modules, {'laboratory.research_continuation': dependency}):
            self.assertEqual(orchestration.call_reservation(plan), 1)

    def fixture(self):
        from test_checkpoint_integration_v0150 import source_attempt
        temporary = tempfile.TemporaryDirectory(dir=TMP)
        self.addCleanup(temporary.cleanup)
        folder = Path(temporary.name)
        store, parent, outputs = source_attempt(folder)
        original = store.agent_trace(parent['id'])
        child = store.create_continuation(parent['id'])
        store.grant_pilot(child['id'], child['plan_hash'])
        store.approve(child['id'], child['plan_hash'], True, 'TEST_ONLY-checkpoint-runtime')
        raw = outputs[2][outputs[2].index('<lab_presentation>'):]
        return folder, store, parent, store.run(child['id']), raw, original

    def test_one_physical_editor_uses_new_usage_and_keeps_parent_immutable(self):
        from laboratory.research_continuation import prefix_outputs
        folder, store, parent, child, raw, original = self.fixture()
        calls, clock = [], [0]

        def editor(plan, prompt, directory, cancel):
            calls.append((plan, prompt))
            visible = store.agent_trace(child['id'])
            self.assertEqual(len(visible['phases']), 1)
            self.assertEqual(visible['phases'][0]['status'], 'dispatch_intent')
            self.assertEqual(visible['phases'][0]['index'], 0)
            self.assertEqual(visible['phases'][0]['role'], 'reviewer')
            self.assertEqual(plan['timeout_seconds'], 151)
            self.assertEqual(plan['_runtime_deadline'], 151)
            self.assertFalse(plan['web_search'])
            self.assertEqual(len(prefix_outputs(child['plan'])), 2)
            clock[0] = 150
            return {'status': 'completed', 'text': raw, 'usage': {'input_tokens': 7},
                    'raw': {'dispatched': True}}

        with patch('laboratory.checkpoint_runtime.time.monotonic', side_effect=lambda: clock[0]):
            result = orchestration.execute(store, child, editor, folder / 'resume',
                                           threading.Event())
        self.assertEqual(result['status'], 'completed', result['error'])
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['usage'], {'input_tokens': 7})
        self.assertEqual(len(result['raw']['orchestration']['phases']), 1)
        self.assertEqual(len(result['raw']['orchestration']['reused_phases']), 2)
        self.assertEqual(result['raw']['editor_assembly']['raw_text'], raw)
        self.assertNotEqual(result['text'], raw)
        store.finish(child['id'], result)
        self.assertEqual(store.agent_trace(parent['id']), original)
        self.assertEqual(store.run(parent['id'])['status'], 'outcome_unknown')
        self.assertEqual(store.run(child['id'])['agent_pipeline']['reserved_calls'], 1)
        restored = Store(folder / 'restored')
        restored.restore(store.export())
        self.assertEqual(restored.run(child['id'])['output'], result['text'])
        self.assertEqual(restored.run(child['id'])['usage'], {'input_tokens': 7})

    def test_timeout_and_direct_reentry_never_dispatch_twice(self):
        folder, store, parent, child, raw, original = self.fixture()
        calls, clock = [], [0]

        def editor(plan, prompt, directory, cancel):
            calls.append(1)
            clock[0] = 152
            self.assertTrue(cancel.is_set())
            return {'status': 'outcome_unknown', 'text': 'TEST_ONLY paid partial',
                    'usage': {}, 'raw': {'dispatched': True}, 'error': 'TEST_ONLY timeout'}

        with patch('laboratory.checkpoint_runtime.time.monotonic', side_effect=lambda: clock[0]):
            result = orchestration.execute(store, child, editor, folder, threading.Event())
        self.assertEqual(result['status'], 'outcome_unknown')
        self.assertEqual(result['text'], '')
        store.finish(child['id'], result)
        orchestration.execute(store, child, editor, folder, threading.Event())
        self.assertEqual(len(calls), 1)
        self.assertEqual(store.agent_trace(parent['id']), original)
        self.assertEqual(store.agent_trace(child['id'])['phases'][0]['output'],
                         'TEST_ONLY paid partial')

    def test_invalid_compact_packet_keeps_paid_bytes_and_usage_without_retry(self):
        folder, store, parent, child, raw, original = self.fixture()
        invalid = '<lab_presentation>{broken}</lab_presentation>'
        runner = unittest.mock.Mock(return_value={
            'status': 'completed', 'text': invalid, 'usage': {'output_tokens': 11},
            'raw': {'dispatched': True}})
        result = orchestration.execute(store, child, runner, folder, threading.Event())
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(runner.call_count, 1)
        self.assertEqual(result['usage'], {'output_tokens': 11})
        self.assertEqual(result['raw']['editor_assembly']['raw_text'], invalid)
        self.assertEqual(result['raw']['editor_assembly']['status'], 'failed')
        store.finish(child['id'], result)
        restored = Store(folder / 'failed-restored')
        restored.restore(store.export())
        self.assertEqual(restored.agent_trace(child['id'])['phases'][0]['output'], invalid)
        self.assertEqual(store.agent_trace(parent['id']), original)

    def test_received_packet_survives_crash_before_local_assembly(self):
        folder, store, parent, child, raw, original = self.fixture()
        runner = unittest.mock.Mock(return_value={
            'status': 'completed', 'text': raw, 'usage': {'input_tokens': 13},
            'raw': {'dispatched': True}})
        with patch('laboratory.checkpoint_runtime.assemble_result', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                orchestration.execute(store, child, runner, folder, threading.Event())
        store.recover_interrupted()
        journal = store.agent_trace(child['id'])['phases'][0]
        self.assertEqual(journal['status'], 'outcome_unknown')
        self.assertEqual(journal['raw']['editor_received']['text'], raw)
        self.assertEqual(journal['usage'], {'input_tokens': 13})
        self.assertEqual(store.run(child['id'])['usage'], {'input_tokens': 13})
        orchestration.execute(store, child, runner, folder, threading.Event())
        self.assertEqual(runner.call_count, 1)
        restored = Store(folder / 'crash-restored')
        restored.restore(store.export())
        self.assertEqual(restored.agent_trace(child['id'])['phases'][0]['usage'],
                         {'input_tokens': 13})

    def test_assembly_hash_corruption_in_backup_rolls_back(self):
        folder, store, parent, child, raw, original = self.fixture()
        result = orchestration.execute(store, child, lambda *args: {
            'status': 'completed', 'text': raw, 'usage': {'output_tokens': 3},
            'raw': {'dispatched': True}}, folder, threading.Event())
        self.assertEqual(result['status'], 'completed', result['error'])
        store.finish(child['id'], result)
        for variant in ('assembly_hash', 'received_packet', 'received_status',
                        'received_extra', 'received_nontext', 'received_enum'):
            with self.subTest(variant=variant):
                backup = deepcopy(store.export())
                row = next(row for row in backup['tables']['agent_phases']
                           if row['run_id'] == child['id'])
                record = json.loads(row['record'])
                if variant == 'assembly_hash':
                    record['raw']['editor_assembly']['assembled_sha256'] = '0' * 64
                elif variant == 'received_packet':
                    received = record['raw']['editor_received']
                    received['text'] += ' TEST_ONLY another packet'
                    received['sha256'] = sha(received['text'])
                elif variant == 'received_status':
                    record['raw']['editor_received']['status'] = 'outcome_unknown'
                elif variant == 'received_extra':
                    record['raw']['editor_received']['extra'] = True
                elif variant == 'received_nontext':
                    record['raw']['editor_received']['text'] = None
                    record['raw']['editor_received']['sha256'] = sha('None')
                else:
                    record['raw']['editor_received']['status'] = 'dispatch_intent'
                row['record'] = canonical(record)
                empty = Store(folder / ('corrupt-' + variant))
                with self.assertRaises(ValueError):
                    empty.restore(backup)
                self.assertEqual(empty.counts()['runs'], 0)

    def test_parent_corruption_prevents_dispatch(self):
        folder, store, parent, child, raw, original = self.fixture()
        with store.connect() as db:
            row = db.execute('SELECT record FROM agent_phases WHERE run_id=? AND phase_index=0',
                             (parent['id'],)).fetchone()
            record = json.loads(row[0])
            record['output'] += ' TEST_ONLY forged prefix'
            db.execute('UPDATE agent_phases SET record=? WHERE run_id=? AND phase_index=0',
                       (canonical(record), parent['id']))
        runner = unittest.mock.Mock()
        result = orchestration.execute(store, child, runner, folder, threading.Event())
        runner.assert_not_called()
        self.assertNotEqual(result['status'], 'completed')
        self.assertEqual(store.agent_trace(child['id'])['phases'], [])

    def full_fixture(self):
        from test_grounded_flow_v0140 import packets
        temporary = tempfile.TemporaryDirectory(dir=TMP)
        self.addCleanup(temporary.cleanup)
        folder = Path(temporary.name)
        store = Store(folder / 'data')
        store.update_settings({'research_mode': 'reviewed', 'timeout_seconds': 360,
                               'source_grounding': True, 'capture_originals': False,
                               'compact_editor': True})
        source = store.add_source('Latency is 10 ms for baseline and 8 ms for candidate.',
                                  'TEST_ONLY source', 'https://example.org/paper')[0]
        run = store.create_plan({'source_ids': [source['id']]})
        store.approve(run['id'], run['plan_hash'], True, 'TEST_ONLY-full-compact')
        outputs = packets(run)
        raw = outputs[2][outputs[2].index('<lab_presentation>'):]
        return folder, store, store.run(run['id']), outputs, raw

    def test_v4_assembles_only_third_with_shared_editor_remainder(self):
        folder, store, run, outputs, raw = self.full_fixture()
        self.assertEqual(run['plan']['research_protocol']['version'], 'three-pass-v4')
        self.assertEqual(run['plan']['research_protocol']['phase_timeouts'], [130, 100, 340])
        calls, clock = [], [0]

        def runner(plan, prompt, directory, cancel):
            index = len(calls)
            calls.append((plan, prompt))
            if index == 1:
                self.assertNotIn(outputs[0], prompt)
            if index == 2:
                self.assertEqual(plan['timeout_seconds'], 340)
                self.assertEqual(plan['_runtime_deadline'], 340)
                self.assertAlmostEqual(plan['_runtime_deadline'] - clock[0], 151.032)
            clock[0] += [106.515, 82.453, 150][index]
            return {'status': 'completed', 'text': outputs[index] if index < 2 else raw,
                    'usage': {'input_tokens': 10}, 'raw': {'dispatched': True}}

        from laboratory import compact_editor
        with patch('laboratory.orchestration.time.monotonic', side_effect=lambda: clock[0]), \
                patch('laboratory.compact_editor.assemble', wraps=compact_editor.assemble) as asm:
            result = orchestration.execute(store, run, runner, folder, threading.Event())
        self.assertEqual(result['status'], 'completed', result['error'])
        self.assertEqual(len(calls), 3)
        self.assertEqual(asm.call_count, 1)
        self.assertEqual(result['raw']['editor_assembly']['raw_text'], raw)
        journal = store.agent_trace(run['id'])['phases']
        self.assertEqual(journal[0]['output'], outputs[0])
        self.assertNotIn('editor_assembly', journal[0]['raw'])
        self.assertNotIn('editor_assembly', journal[1]['raw'])
        self.assertEqual(journal[2]['raw']['editor_received']['text'], raw)
        store.finish(run['id'], result)
        restored = Store(folder / 'full-restored')
        restored.restore(store.export())
        self.assertEqual(restored.run(run['id'])['output'], result['text'])

    def test_v4_crash_preserves_new_editor_packet_before_assembly(self):
        folder, store, run, outputs, raw = self.full_fixture()
        calls = []

        def runner(*args):
            index = len(calls)
            calls.append(1)
            return {'status': 'completed', 'text': outputs[index] if index < 2 else raw,
                    'usage': {'input_tokens': 10}, 'raw': {'dispatched': True}}

        with patch('laboratory.checkpoint_runtime.assemble_result', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                orchestration.execute(store, run, runner, folder, threading.Event())
        store.recover_interrupted()
        self.assertEqual(len(calls), 3)
        journal = store.agent_trace(run['id'])['phases']
        self.assertEqual(journal[2]['status'], 'outcome_unknown')
        self.assertEqual(journal[2]['raw']['editor_received']['text'], raw)
        self.assertEqual(store.run(run['id'])['usage'], {'input_tokens': 30})
        restored = Store(folder / 'v4-crash-restored')
        restored.restore(store.export())
        self.assertEqual(restored.agent_trace(run['id'])['phases'][2]['raw']
                         ['editor_received']['text'], raw)

    def test_resume_compact_format_cannot_authorize_unbound_numbers(self):
        folder, store, parent, child, raw, original = self.fixture()
        packet = json.loads(raw[len('<lab_presentation>'):-len('</lab_presentation>')])
        changed = 'Latency is 42 ms for baseline and 8 ms for candidate.'
        packet['findings'] = [changed]
        packet['evidence'][0]['excerpt'] = changed
        packet['applied_analysis']['rows'][0]['baseline']['value'] = 42
        forged = '<lab_presentation>' + json.dumps(packet) + '</lab_presentation>'
        runner = unittest.mock.Mock(return_value={
            'status': 'completed', 'text': forged, 'usage': {'output_tokens': 5},
            'raw': {'dispatched': True}})
        result = orchestration.execute(store, child, runner, folder, threading.Event())
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(runner.call_count, 1)
        self.assertEqual(result['raw']['editor_assembly']['status'], 'assembled')
        self.assertEqual(result['raw']['orchestration']['review']['status'], 'incomplete')
        self.assertEqual(store.agent_trace(parent['id']), original)

    def test_owner_cancel_before_editor_is_zero_new_dispatches(self):
        folder, store, parent, child, raw, original = self.fixture()
        cancel = threading.Event()
        cancel.set()
        runner = unittest.mock.Mock()
        result = orchestration.execute(store, child, runner, folder, cancel)
        runner.assert_not_called()
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(result['raw']['orchestration']['reserved_calls'], 1)
        self.assertEqual(result['raw']['orchestration']['dispatched_calls'], 0)
        self.assertEqual(store.agent_trace(child['id'])['phases'], [])
        self.assertEqual(store.agent_trace(parent['id']), original)

    def test_post_complete_crash_recovers_known_usage_and_rejects_missing_terminal_usage(self):
        folder, store, parent, child, raw, original = self.fixture()
        result = orchestration.execute(store, child, lambda *args: {
            'status': 'completed', 'text': raw, 'usage': {'input_tokens': 17},
            'raw': {'dispatched': True}}, folder, threading.Event())
        self.assertEqual(result['status'], 'completed', result['error'])
        active = store.export()
        store.recover_interrupted()
        self.assertEqual(store.run(child['id'])['status'], 'outcome_unknown')
        self.assertEqual(store.run(child['id'])['usage'], {'input_tokens': 17})
        self.assertEqual(store.agent_trace(child['id'])['phases'][0]['status'], 'completed')
        self.assertEqual(store.run(child['id'])['output'], '')
        restored = Store(folder / 'active-restored')
        restored.restore(active)
        self.assertEqual(restored.run(child['id'])['status'], 'outcome_unknown')
        self.assertEqual(restored.run(child['id'])['usage'], {'input_tokens': 17})
        corrupt = store.export()
        row = next(row for row in corrupt['tables']['runs'] if row['id'] == child['id'])
        row['usage'] = '{}'
        empty = Store(folder / 'missing-usage')
        with self.assertRaises(ValueError):
            empty.restore(corrupt)
        self.assertEqual(empty.counts()['runs'], 0)
        self.assertEqual(store.agent_trace(parent['id']), original)


if __name__ == '__main__':
    unittest.main()
