"""Fake Responses endpoint only; no actual API, credential test or paid call."""
from pathlib import Path
from datetime import datetime, timezone
import tempfile
import threading
import unittest
from unittest.mock import patch

from laboratory.core import Store
from laboratory.research_experiments import Experiments

TMP = Path(__file__).parent / '.tmp'
TMP.mkdir(exist_ok=True)
SECRET = 'sk-TEST_ONLY-key-never-sent-0123456789'


def fake_dpapi(value, decrypt=False):
    return value[8:] if decrypt else b'WRAPPED:' + value


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TMP)
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.calls = []

        def transport(endpoint, headers, body, timeout):
            self.calls.append((endpoint, headers, body, timeout))
            return {'status': 'completed', 'output': [{
                'type': 'message', 'content': [{'type': 'output_text', 'text': 'expected'}]}],
                'usage': {'input_tokens': 10, 'output_tokens': 5}}
        self.transport = transport
        self.dpapi = patch('laboratory.research_experiments._dpapi', side_effect=fake_dpapi)
        self.dpapi.start()
        self.addCleanup(self.dpapi.stop)
        self.runner = Experiments(self.store, transport=transport)
        self.runner.configure(SECRET, 'TEST_ONLY-explicit-model')

    def plan(self, **values):
        return self.runner.plan({
            'cases': [{'id': 'case_1', 'input': 'TEST_ONLY query', 'expected': 'expected'}],
            'baseline': {'label': 'Baseline', 'instructions': 'Answer'},
            'candidate': {'label': 'Candidate', 'instructions': 'Answer carefully'},
            'repetitions': 1, 'max_requests': 2, 'timeout_seconds': 60,
            'max_output_tokens': 64, 'max_input_chars': 1000,
            'metrics': ['latency_ms', 'exact_match'],
            'stop_criteria': ['Stop on first failed or uncertain request'], **values})

    def test_exact_approval_durable_intent_two_arms_and_no_duplicate_dispatch(self):
        plan = self.plan()
        self.assertEqual(self.calls, [])
        with self.assertRaises(ValueError):
            self.runner.start(plan['id'], plan['plan_hash'], False, 'TEST_ONLY-no-consent')
        result = self.runner.start(plan['id'], plan['plan_hash'], True, 'TEST_ONLY-approval')
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['dispatched_requests'], 2)
        self.assertEqual(len(self.calls), 2)
        visible = self.runner.status(plan['id'])['observations']
        self.assertEqual(len(visible), 2)
        self.assertEqual(visible[0]['payload']['output'], 'expected')
        self.assertTrue(visible[0]['payload']['metrics']['exact_match'])
        self.assertGreaterEqual(visible[0]['payload']['metrics']['latency_ms'], 0)
        self.assertEqual(self.calls[0][0], 'https://api.openai.com/v1/responses')
        self.assertEqual(self.calls[0][2]['tools'], [])
        self.assertFalse(self.calls[0][2]['store'])
        self.assertEqual(self.calls[0][2]['max_output_tokens'], 64)
        self.runner.start(plan['id'], plan['plan_hash'], True, 'TEST_ONLY-replay')
        self.assertEqual(len(self.calls), 2)
        self.assertNotIn(SECRET, str(self.store.export()))
        self.assertNotIn(SECRET, str(result))
        self.assertEqual(self.store.settings()['daily_run_limit'], 3)

    def test_uncertain_dispatch_never_retries_and_stops_second_arm(self):
        def uncertain(*args):
            self.calls.append(args)
            raise TimeoutError('TEST_ONLY includes ' + SECRET)
        runner = Experiments(self.store, transport=uncertain)
        plan = self.plan()
        result = runner.start(plan['id'], plan['plan_hash'], True, 'TEST_ONLY-uncertain')
        self.assertEqual(result['status'], 'outcome_unknown')
        self.assertEqual(len(self.calls), 1)
        runner.start(plan['id'], plan['plan_hash'], True, 'TEST_ONLY-uncertain-again')
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn(SECRET, str(result))
        self.assertNotIn(SECRET, str(self.store.export()))

    def test_full_schedule_cap_cancel_and_no_custom_endpoint(self):
        with self.assertRaises(ValueError):
            self.plan(repetitions=2)
        with self.assertRaises(ValueError):
            self.plan(endpoint='http://127.0.0.1/private')
        plan = self.plan()
        cancel = threading.Event()
        cancel.set()
        result = self.runner.start(
            plan['id'], plan['plan_hash'], True, 'TEST_ONLY-cancel', cancel)
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(self.calls, [])

    def test_import_is_hashed_and_never_claims_local_execution(self):
        result = self.runner.imports({'observations': [{
            'case_id': 'case_1', 'arm': 'baseline', 'repetition': 0,
            'output': 'TEST_ONLY imported', 'latency_ms': 12, 'metrics': {}}],
            'note': 'Owner imported a measurement file.'})
        self.assertEqual(result['payload']['origin'], 'imported_not_executed_here')
        self.assertEqual(len(result['payload']['raw_sha256']), 64)
        self.assertEqual(self.calls, [])

    def test_intent_exists_before_transport_and_paid_results_survive_restore(self):
        def observed(endpoint, headers, body, timeout):
            intents = self.store.assets.list('experiment_intent')
            self.assertEqual(len(intents), len(self.calls) + 1)
            self.assertEqual(runner.status(plan['id'])['status'], 'running')
            return self.transport(endpoint, headers, body, timeout)
        runner = Experiments(self.store, transport=observed)
        plan = self.plan()
        runner.start(plan['id'], plan['plan_hash'], True, 'TEST_ONLY-before-transport')
        destination = Store(Path(self.temp.name) / 'restored')
        destination.restore(self.store.export())
        restored = Experiments(destination, transport=unittest.mock.Mock())
        self.assertEqual(restored.status(plan['id'])['status'], 'completed')
        self.assertEqual(restored.status(plan['id'])['dispatched_requests'], 2)
        self.assertFalse(restored.config()['configured'])

    def test_crash_after_intent_is_unknown_and_does_not_reenter_transport(self):
        def crashed(*args):
            self.calls.append(1)
            raise KeyboardInterrupt('TEST_ONLY abrupt process loss after durable intent')
        runner = Experiments(self.store, transport=crashed)
        plan = self.plan()
        with self.assertRaises(KeyboardInterrupt):
            runner.start(plan['id'], plan['plan_hash'], True, 'TEST_ONLY-crash-intent')
        self.assertEqual(runner.status(plan['id'])['status'], 'outcome_unknown')
        self.assertEqual(runner.status(plan['id'])['dispatched_requests'], 1)
        runner.start(plan['id'], plan['plan_hash'], True, 'TEST_ONLY-no-crash-retry')
        self.assertEqual(len(self.calls), 1)
        destination = Store(Path(self.temp.name) / 'interrupted-restored')
        destination.restore(self.store.export())
        self.assertEqual(Experiments(destination).status(plan['id'])['status'], 'outcome_unknown')

    def test_twenty_daily_requests_are_reserved_atomically_separate_from_cli(self):
        plan = self.plan(cases=[{'id': 'c' + str(index), 'input': 'TEST_ONLY case'}
                               for index in range(10)], max_requests=20)
        self.runner.start(plan['id'], plan['plan_hash'], True, 'TEST_ONLY-twenty-requests')
        self.assertEqual(len(self.calls), 20)
        other = self.plan()
        with self.assertRaises(ValueError):
            self.runner.start(other['id'], other['plan_hash'], True, 'TEST_ONLY-cap-blocked')
        with self.assertRaises(ValueError):
            self.store.assets.claim('experiment_approval', {
                'version': 'experiment-approval-v1', 'plan_id': other['id'],
                'plan_hash': other['plan_hash'], 'consent': True,
                'command_id': 'TEST_ONLY-direct-atomic-claim',
                'approved_at': datetime.now(timezone.utc).isoformat(),
                'reserved_requests': 2}, 'TEST_ONLY-independent-writer')
        self.assertEqual(self.store.settings()['daily_run_limit'], 3)
        self.assertEqual(len(self.calls), 20)

    def test_changed_hash_key_or_unsupported_stop_rule_never_dispatches(self):
        plan = self.plan()
        with self.assertRaises(ValueError):
            self.runner.start(plan['id'], 'f' * 64, True, 'TEST_ONLY-wrong-hash')
        self.runner.configure('sk-TEST_ONLY-different-key-0123456789', 'TEST_ONLY-model')
        with self.assertRaises(ValueError):
            self.runner.start(plan['id'], plan['plan_hash'], True, 'TEST_ONLY-changed-key')
        with self.assertRaises(ValueError):
            self.plan(stop_criteria=['Execute arbitrary stop code'])
        self.assertEqual(self.calls, [])

    def test_config_and_untrusted_response_cannot_persist_api_key(self):
        with self.assertRaises(ValueError):
            self.runner.configure(SECRET, SECRET)
        def echo(*args):
            return {'status': 'completed', 'output': [{
                'type': 'message', 'content': [{'type': 'output_text', 'text': SECRET}]}],
                'usage': {SECRET: 100, 'input_tokens': 2}}
        plan = self.plan()
        Experiments(self.store, transport=echo).start(
            plan['id'], plan['plan_hash'], True, 'TEST_ONLY-secret-echo')
        self.assertNotIn(SECRET, str(self.store.export()))


if __name__ == '__main__':
    unittest.main()
