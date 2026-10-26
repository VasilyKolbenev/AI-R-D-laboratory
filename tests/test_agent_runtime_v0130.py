"""No real CLI, model, network or Telegram: paid-call boundaries are mocked."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from laboratory.core import Store, LabError, canonical, digest
from laboratory import orchestration, trace, providers
from laboratory.server import Laboratory
from test_core import NoTelegram


TMP = Path(__file__).parent / '.tmp'
TMP.mkdir(exist_ok=True)


class AgentRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TMP)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'data')
        self.source = self.store.add_source('TEST_ONLY ИИ: источник с доказательствами.')[0]
        self.final = patch('laboratory.applied_analysis.validate_final', side_effect=self.ready)
        self.final.start()
        self.addCleanup(self.final.stop)

    @staticmethod
    def ready(plan, texts):
        return {'status': 'ready', 'issues': [], 'critic': {}, 'dispositions': [],
                'applied_analysis': {}, 'final_output_sha256': trace.sha(texts[-1]),
                'protocol_sha256': trace.digest(plan['research_protocol'])}

    def plan(self, **values):
        return self.store.create_plan({'source_ids': [self.source['id']], 'research_mode': 'reviewed', 'timeout_seconds': 240, **values})

    def approve(self, run):
        self.store.approve(run['id'], run['plan_hash'], True, 'TEST_ONLY-' + run['id'])
        return self.store.run(run['id'])

    def runner(self, calls, status='completed', stop_at=None):
        def run(plan, prompt, directory, cancel):
            index = len(calls)
            calls.append((plan, prompt, directory, cancel))
            self.assertEqual(self.store.agent_trace(active['id'])['phases'][index]['status'], 'dispatch_intent')
            self.assertEqual(prompt, plan['execution_context']['prompt'])
            trace.validate_record(plan, plan['execution_context'], current=True)
            return {'status': status if stop_at == index else 'completed', 'text': ['research', 'critic', 'editor'][index],
                    'usage': {'input_tokens': 100, 'cached_input_tokens': 40, 'output_tokens': 5}, 'raw': {'dispatched': True}}
        active = self.active
        return run

    def run_reviewed(self, runner, cancel=None):
        run = self.approve(self.plan())
        self.active = run
        with patch('laboratory.applied_analysis.validate_phase', return_value={'status': 'ready', 'issues': []}, create=True):
            result = orchestration.execute(self.store, run, runner, self.root / 'jobs', cancel or threading.Event())
        self.store.finish(run['id'], result)
        return self.store.run(run['id'], include_raw=True)

    def test_three_calls_are_ordered_durable_fresh_and_usage_not_double_counted(self):
        calls = []
        run = self.approve(self.plan())
        self.active = run
        with patch('laboratory.applied_analysis.validate_phase', return_value={'status': 'ready', 'issues': []}, create=True):
            result = orchestration.execute(self.store, run, self.runner(calls), self.root / 'jobs', threading.Event())
        self.store.finish(run['id'], result)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(calls), 3)
        self.assertEqual([call[0]['timeout_seconds'] for call in calls], [100, 60, 60])
        self.assertEqual([call[0]['web_search'] for call in calls], [False, False, False])
        self.assertEqual(len({str(call[2]) for call in calls}), 3)
        self.assertIn('research', calls[1][1])
        self.assertIn('critic', calls[2][1])
        self.assertEqual(result['usage'], {'input_tokens': 300, 'cached_input_tokens': 120, 'output_tokens': 15})
        saved = self.store.run(run['id'])
        self.assertEqual(saved['agent_pipeline']['dispatched_calls'], 3)
        self.assertNotIn('output', saved['agent_pipeline']['phases'][0])
        self.assertEqual(saved['agent_review']['status'], 'ready')
        self.assertEqual(self.store.review.get(run['id'])['costs']['primary']['cli_invocations'], 3)
        self.assertEqual(self.store.agent_trace(run['id'])['phases'][2]['output'], 'editor')
        self.assertFalse(self.store.approve(run['id'], run['plan_hash'], True, 'TEST_ONLY-replay'))

    def test_failed_or_unknown_phase_never_starts_successor_or_ingests_draft(self):
        for status in ('failed', 'outcome_unknown', 'cancelled'):
            with self.subTest(status=status):
                folder = self.root / status
                store = Store(folder)
                source = store.add_source('TEST_ONLY ИИ материал')[0]
                run = store.create_plan({'source_ids': [source['id']], 'research_mode': 'reviewed', 'timeout_seconds': 240})
                store.approve(run['id'], run['plan_hash'], True, 'TEST_ONLY-failed-' + status)
                calls = []
                def runner(*args):
                    calls.append(1)
                    return {'status': status, 'text': 'partial paid draft', 'raw': {'dispatched': True}}
                result = orchestration.execute(store, store.run(run['id']), runner, folder / 'jobs', threading.Event())
                store.finish(run['id'], result)
                self.assertEqual(len(calls), 1)
                self.assertEqual(result['status'], status)
                self.assertEqual(store.run(run['id'])['output'], '')
                self.assertEqual(store.agent_trace(run['id'])['phases'][0]['output'], 'partial paid draft')
                self.assertEqual(store.knowledge(), [])

    def test_cancel_before_first_call_is_zero_dispatches(self):
        run = self.approve(self.plan())
        event = threading.Event()
        event.set()
        runner = unittest.mock.Mock()
        result = orchestration.execute(self.store, run, runner, self.root / 'jobs', event)
        runner.assert_not_called()
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(result['raw']['orchestration']['reserved_calls'], 3)
        self.assertEqual(result['raw']['orchestration']['dispatched_calls'], 0)

    def test_paid_response_survives_unexpected_local_validation_error(self):
        run = self.approve(self.plan())
        runner = unittest.mock.Mock(return_value={'status': 'completed', 'text': 'paid answer with malformed packet',
                                                   'usage': {'input_tokens': 17}, 'raw': {'dispatched': True, 'stdout': 'paid diagnostic'}})
        with patch('laboratory.applied_analysis.validate_phase', side_effect=RuntimeError('TEST_ONLY parser crash')):
            result = orchestration.execute(self.store, run, runner, self.root / 'jobs', threading.Event())
        self.store.finish(run['id'], result)
        self.assertEqual(runner.call_count, 1)
        phase = self.store.agent_trace(run['id'])['phases'][0]
        self.assertEqual(phase['status'], 'failed')
        self.assertEqual(phase['output'], 'paid answer with malformed packet')
        self.assertEqual(phase['raw']['stdout'], 'paid diagnostic')
        self.assertEqual(result['usage']['input_tokens'], 17)
        self.assertEqual(self.store.run(run['id'])['agent_review']['status'], 'incomplete')

    def test_critic_parse_failure_preserves_paid_result_and_prevents_editor(self):
        run = self.approve(self.plan())
        self.active = run
        calls = []
        with patch('laboratory.applied_analysis.validate_phase', side_effect=[{'status': 'ready'}, {'status': 'incomplete', 'issues': ['invalid critic packet']}]):
            result = orchestration.execute(self.store, run, self.runner(calls), self.root / 'jobs', threading.Event())
        self.assertEqual(len(calls), 2)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['text'], '')
        self.assertEqual(self.store.agent_trace(run['id'])['phases'][1]['output'], 'critic')

    def test_global_deadline_prevents_later_calls_and_reserves_cleanup(self):
        run = self.approve(self.plan())
        clock = [0]
        calls = []
        def runner(*args):
            calls.append(1)
            clock[0] = 221
            return {'status': 'completed', 'text': 'research', 'raw': {'dispatched': True}}
        with patch.object(orchestration, 'time', SimpleNamespace(monotonic=lambda: clock[0])), patch('laboratory.applied_analysis.validate_phase', return_value={'status': 'ready', 'issues': []}, create=True):
            result = orchestration.execute(self.store, run, runner, self.root / 'jobs', threading.Event())
        self.assertEqual(len(calls), 1)
        self.assertNotEqual(result['status'], 'completed')
        self.assertEqual(result['raw']['orchestration']['cleanup_reserve_seconds'], 20)

    def test_exception_after_intent_is_unknown_without_retry(self):
        run = self.approve(self.plan())
        runner = unittest.mock.Mock(side_effect=OSError('TEST_ONLY ambiguous spawn'))
        result = orchestration.execute(self.store, run, runner, self.root / 'jobs', threading.Event())
        self.assertEqual(runner.call_count, 1)
        self.assertEqual(result['status'], 'outcome_unknown')
        self.assertEqual(result['raw']['orchestration']['uncertain_calls'], 1)

    def test_budget_three_is_one_reviewed_study_and_pilot_never_bypasses_it(self):
        run = self.approve(self.plan())
        self.store.finish(run['id'], {'status': 'failed'})
        other = self.plan()
        with self.assertRaises(LabError):
            self.approve(other)
        self.assertEqual(self.store.settings()['daily_run_limit'], 3)
        with self.assertRaises(LabError):
            self.store.grant_pilot(other['id'], other['plan_hash'])

    def test_one_existing_single_call_leaves_insufficient_three_call_budget(self):
        single = self.store.create_plan({'source_ids': [self.source['id']]})
        self.approve(single)
        self.store.finish(single['id'], {'status': 'failed'})
        with self.assertRaises(LabError):
            self.approve(self.plan())

    def test_mode_and_explicit_shorter_budget_are_not_silently_changed(self):
        self.assertEqual(self.store.settings()['research_mode'], 'single')
        with self.assertRaises(LabError):
            self.plan(timeout_seconds=180)
        run = self.plan()
        replanned = self.store.replan_context(run['id'], {'memory_options': {'enabled': False}})
        self.assertNotEqual(run['plan_hash'], replanned['plan_hash'])
        self.assertEqual(replanned['plan']['research_protocol']['max_calls'], 3)

    def test_frozen_parent_and_actual_phase_prompts_are_bound(self):
        run = self.plan()
        phase = trace.phase_plan(run['plan'], 1, ['research'])
        self.assertFalse(phase['web_search'])
        changed = copy.deepcopy(phase)
        changed['_previous_outputs'] = ['different earlier output']
        with self.assertRaises(ValueError):
            trace.validate_record(changed, changed['execution_context'])
        record = copy.deepcopy(run['plan']['execution_context'])
        altered = copy.deepcopy(run['plan'])
        altered['research_protocol']['templates'][1] += '\nChanged recipe.'
        with self.assertRaises(ValueError):
            trace.validate_record(altered, record)

    def test_claude_cache_and_model_usage_are_one_usage_view(self):
        records = [{'usage': {'input_tokens': 10, 'cache_creation_input_tokens': 20,
                              'cache_read_input_tokens': 30, 'output_tokens': 5,
                              'model_usage': {'model': {'inputTokens': 9999}}}}] * 3
        value = orchestration.aggregate_usage('claude', records)
        self.assertEqual(value['input_tokens'], 180)
        self.assertEqual(value['cached_input_tokens'], 90)
        self.assertEqual(value['output_tokens'], 15)

    def test_version_six_roundtrip_and_corrupt_phase_rolls_back(self):
        run = self.approve(self.plan())
        self.active = run
        with patch('laboratory.applied_analysis.validate_phase', return_value={'status': 'ready', 'issues': []}, create=True):
            result = orchestration.execute(self.store, run, self.runner([]), self.root / 'jobs', threading.Event())
        self.store.finish(run['id'], result)
        backup = self.store.export()
        self.assertEqual(backup['schema_version'], 7)
        restored = Store(self.root / 'restored')
        restored.restore(backup)
        self.assertEqual(restored.agent_trace(run['id'])['phases'][2]['output_sha256'], trace.sha('editor'))
        corrupt = copy.deepcopy(backup)
        body = json.loads(corrupt['tables']['agent_phases'][1]['record'])
        body['previous_output_sha256'] = [trace.sha('invented predecessor')]
        corrupt['tables']['agent_phases'][1]['record'] = canonical(body)
        empty = Store(self.root / 'corrupt')
        with self.assertRaises(ValueError):
            empty.restore(corrupt)
        self.assertEqual(empty.counts()['runs'], 0)

    def test_legacy_backup_without_phase_table_and_interrupted_intent(self):
        legacy = self.store.create_plan({'source_ids': [self.source['id']]})
        old = self.store.export()
        old['schema_version'] = 5
        old['tables'].pop('agent_phases')
        old['tables'].pop('research_assets')
        old['tables'].pop('research_asset_claims')
        restored = Store(self.root / 'legacy')
        restored.restore(old)
        self.assertNotIn('research_protocol', restored.run(legacy['id'])['plan'])
        run = self.approve(self.plan())
        self.store.trace.capture(run)
        phase = trace.phase_plan(run['plan'], 0, [])
        orchestration._intent(self.store, run, phase, 0)
        snapshot = self.store.export()
        restored = Store(self.root / 'interrupted')
        restored.restore(snapshot)
        self.assertEqual(restored.run(run['id'])['status'], 'outcome_unknown')
        self.assertEqual(restored.agent_trace(run['id'])['phases'][0]['status'], 'outcome_unknown')

    def test_providers_keep_existing_restrictions_for_a_derived_phase(self):
        run = self.plan(web_search=True)
        phases = [trace.phase_plan(run['plan'], i, ['research', 'critic'][:i]) for i in range(3)]
        commands = [providers._command(phase, 'codex.exe') for phase in phases]
        self.assertIn('features.multi_agent=false', commands[0])
        self.assertIn('features.multi_agent=false', commands[2])
        self.assertEqual([phase['web_search'] for phase in phases], [True, True, False])
        self.assertIn('web_search="live"', commands[0])
        self.assertIn('web_search="live"', commands[1])
        self.assertIn('web_search="disabled"', commands[2])

    def test_provider_deadline_before_spawn_is_zero_real_calls(self):
        executable = self.root / 'approved-native.exe'
        executable.write_bytes(b'TEST_ONLY binary identity, never executed')
        with patch.object(providers, '_executable', return_value=str(executable)):
            run = self.plan()
            phase = trace.phase_plan(run['plan'], 0, [])
            phase['_runtime_deadline'] = 0
            with patch.object(providers.subprocess, 'Popen') as spawn:
                result = providers.run(phase, phase['execution_context']['prompt'], self.root / 'expired-job', threading.Event())
        spawn.assert_not_called()
        self.assertEqual(result['status'], 'cancelled')
        self.assertFalse(result['raw']['dispatched'])

    def test_server_dispatches_three_roles_once_and_agents_route_is_read_only(self):
        from laboratory.server import Handler
        calls = []
        def runner(*args):
            calls.append(1)
            return {'status': 'completed', 'text': ['research', 'critic', 'editor'][len(calls)-1], 'raw': {'dispatched': True}}
        app = Laboratory(self.root / 'app', runner=runner, telegram_factory=NoTelegram)
        try:
            source = app.store.add_source('TEST_ONLY ИИ сервер')[0]
            run = app.store.create_plan({'source_ids': [source['id']], 'research_mode': 'reviewed', 'timeout_seconds': 240})
            body = {'plan_hash': run['plan_hash'], 'consent': True, 'command_id': 'TEST_ONLY-server-three'}
            with patch('laboratory.applied_analysis.validate_phase', return_value={'status': 'ready'}):
                app.start_run(run['id'], body)
                until = time.monotonic() + 5
                while app.jobs and time.monotonic() < until:
                    time.sleep(.01)
            self.assertEqual(len(calls), 3)
            self.assertEqual(app.store.run(run['id'])['status'], 'completed')
            app.start_run(run['id'], body)
            self.assertEqual(len(calls), 3)
            handler = SimpleNamespace(path='/api/runs/' + run['id'] + '/agents', app=app,
                                      check_host=lambda: None, send=lambda value, *args, **kwargs: value)
            detail = Handler.do_GET(handler)
            self.assertEqual(detail['dispatched_calls'], 3)
            self.assertEqual(detail['phases'][2]['output'], 'editor')
            self.assertEqual(len(calls), 3)
        finally:
            app.close()


if __name__ == '__main__':
    unittest.main()
