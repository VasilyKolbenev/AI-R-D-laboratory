"""Local-only regression for the failed web pilot and its frozen replacement budget."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from laboratory.core import LabError, Store
from laboratory.orchestration import execute
from laboratory.trace import inputs
from test_grounded_flow_v0140 import packets
import test_telegram_workflow as tg


class WebBudgetIntegrationTests(unittest.TestCase):
    def create_plan(self, store):
        failure = None
        try:
            store.update_settings({'research_mode': 'reviewed', 'timeout_seconds': 360,
                                   'source_grounding': True, 'capture_originals': False})
        except LabError as exc:
            failure = str(exc)
        self.assertIsNone(failure, 'Approved six-minute grounded budget must be accepted')
        source, _ = store.add_source(
            'Latency is 10 ms for baseline and 8 ms for candidate.',
            'TEST_ONLY bounded original', 'https://example.org/paper')
        return store.create_plan({'source_ids': [source['id']], 'web_search': True})

    def test_six_minute_three_phase_flow_keeps_gates_quota_and_backup(self):
        with TemporaryDirectory(dir=tg.TMP) as folder:
            store = Store(folder)
            run = self.create_plan(store)
            self.assertEqual(run['plan']['research_protocol']['version'], 'three-pass-v3')
            self.assertEqual(store.settings()['daily_run_limit'], 3)
            self.assertEqual(inputs(run['plan'])['evidence_bundle'],
                             run['plan']['evidence_bundle'])
            self.assertTrue(store.approve(run['id'], run['plan_hash'], True, 'TEST_ONLY-first'))
            outputs = packets(run)
            calls, clock = [], [0.0]

            def runner(plan, prompt, directory, cancel):
                index = len(calls)
                duration = [98, 80, 90][index]
                calls.append((plan['timeout_seconds'], plan['web_search'], prompt))
                self.assertLess(duration, plan['timeout_seconds'])
                self.assertFalse(cancel.is_set())
                clock[0] += duration
                return {'status': 'completed', 'text': outputs[index],
                        'usage': {'input_tokens': 10, 'output_tokens': 5},
                        'raw': {'dispatched': True}}

            with patch('laboratory.orchestration.time.monotonic', side_effect=lambda: clock[0]):
                result = execute(store, store.run(run['id']), runner,
                                 Path(folder) / 'jobs', threading.Event())
            self.assertEqual(result['status'], 'completed', result['error'])
            self.assertEqual([(limit, web) for limit, web, _ in calls],
                             [(130, True), (100, True), (110, False)])
            self.assertNotIn(outputs[0], calls[1][2])
            store.finish(run['id'], result)
            second = self.create_plan(store)
            with self.assertRaisesRegex(LabError, 'нужно 3.*доступно 0'):
                store.approve(second['id'], second['plan_hash'], True, 'TEST_ONLY-second')
            from laboratory.presentation import build_presentation
            data = build_presentation(store.run(run['id']), store.review.get(run['id']))
            self.assertEqual(data['source_validation']['status'], 'ready')
            backup = store.export()
            restored = Store(Path(folder) / 'restored')
            restored.restore(backup)
            self.assertEqual(restored.run(run['id'])['output'], outputs[2])
            self.assertEqual(restored.run(run['id'])['agent_pipeline']['dispatched_calls'], 3)

    def test_v3_never_bypasses_original_quote_gate(self):
        from test_evidence_validation_v0140 import EvidenceValidationTests
        from laboratory.evidence_validation import validate_checks
        plan, parsed, evidence = EvidenceValidationTests().fixture()
        plan['research_protocol']['version'] = 'three-pass-v3'
        parsed['evidence_checks'][0]['quote'] = 'TEST_ONLY forged quote with 10 and 8'
        self.assertEqual(validate_checks(plan, parsed, 'report', evidence)['status'],
                         'incomplete')


class WebBudgetTelegramTests(unittest.TestCase):
    setUp = tg.TelegramWorkflowTests.setUp
    incoming = tg.TelegramWorkflowTests.incoming
    prepare = tg.TelegramWorkflowTests.prepare
    callback = tg.TelegramWorkflowTests.callback

    def test_grounded_provider_change_does_not_silently_become_single(self):
        self.store.update_settings({'research_mode': 'reviewed', 'timeout_seconds': 240,
                                    'source_grounding': True, 'capture_originals': False})
        key, session, run = self.prepare()
        self.assertEqual(run['plan']['research_protocol']['version'], 'three-pass-v2')
        self.workflow.handle_callback(tg.TOKEN, self.callback(key, session, 'claude'))
        new = self.store.run(self.workflow._latest()[1]['run_id'])
        self.assertEqual((new['plan'].get('research_protocol') or {}).get('max_calls'), 3)
        self.assertEqual(self.starts, [])

    def test_six_minute_preview_refresh_and_choice_preserve_exact_budget(self):
        failure = None
        try:
            self.store.update_settings({'research_mode': 'reviewed', 'timeout_seconds': 360,
                                        'source_grounding': True, 'capture_originals': False})
        except LabError as exc:
            failure = str(exc)
        self.assertIsNone(failure, 'Telegram must preserve the configured six-minute budget')
        key, session, run = self.prepare()
        self.assertEqual(run['plan']['timeout_seconds'], 360)
        combined = '\n'.join(body['text'] for method, body in self.calls
                             if method == 'sendMessage')
        for text in ('360', '130', '100', '110', '3 вызова CLI'):
            self.assertIn(text, combined)
        self.workflow.handle_callback(tg.TOKEN, self.callback(key, session, 'claude'))
        replacement = self.store.run(self.workflow._latest()[1]['run_id'])
        self.assertEqual(replacement['plan']['timeout_seconds'], 360)
        self.assertEqual(replacement['plan']['research_protocol']['version'], 'three-pass-v3')
        self.assertEqual(self.starts, [])

    def test_timeout_notice_names_phase_and_never_calls_missing_usage_zero(self):
        self.store.update_settings({'research_mode': 'reviewed', 'timeout_seconds': 240,
                                    'source_grounding': True, 'capture_originals': False})
        _, _, run = self.prepare()
        self.store.approve(run['id'], run['plan_hash'], True, 'TEST_ONLY-failure')
        outputs, calls, clock = packets(run), [], [0.0]

        def runner(plan, prompt, directory, cancel):
            index = len(calls)
            calls.append(index)
            clock[0] += [98.062, 60.25][index]
            if index:
                return {'status': 'outcome_unknown', 'text': '', 'usage': {},
                        'error': 'Истёк лимит времени.', 'raw': {'dispatched': True}}
            return {'status': 'completed', 'text': outputs[0],
                    'usage': {'input_tokens': 49828, 'cached_input_tokens': 21248,
                              'output_tokens': 3392}, 'raw': {'dispatched': True}}

        with patch('laboratory.orchestration.time.monotonic', side_effect=lambda: clock[0]):
            result = execute(self.store, self.store.run(run['id']), runner,
                             Path(self.temp.name) / 'jobs', threading.Event())
        self.assertEqual(result['status'], 'outcome_unknown')
        self.assertEqual(calls, [0, 1])
        self.store.finish(run['id'], result)
        self.calls.clear()
        self.workflow.send_result(run['id'])
        text = '\n'.join(body['text'] for method, body in self.calls if method == 'sendMessage')
        for expected in ('Критик', '60.25', '49828', '3392', '1 из 2',
                         'Расход остальных проходов неизвестен'):
            self.assertIn(expected, text)
        self.assertIn('Автоматического повторного запуска нет', text)
        self.assertNotIn('Расход: 0', text)
        self.assertEqual(self.starts, [])


if __name__ == '__main__':
    unittest.main()
