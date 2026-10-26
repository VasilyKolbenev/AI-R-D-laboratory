"""Real local approval routes with fake Telegram transport; no provider dispatch."""
from copy import deepcopy
from pathlib import Path
import unittest

from laboratory.core import LabError
from test_checkpoint_integration_v0150 import source_attempt
import test_research_http_v0140 as http_fixture
import test_telegram_workflow as tg


class CheckpointTelegramTests(unittest.TestCase):
    setUp = tg.TelegramWorkflowTests.setUp
    incoming = tg.TelegramWorkflowTests.incoming
    callback = tg.TelegramWorkflowTests.callback

    def prepare_checkpoint(self):
        _, parent, _ = source_attempt(self.temp.name, self.store)
        run = self.store.create_continuation(parent['id'])
        self.store.grant_pilot(run['id'], run['plan_hash'])
        self.workflow.present_plan(run['id'])
        key, session = self.workflow._latest()
        return parent, run, key, session

    def test_preview_saved_context_precedes_single_editor_approval_and_replay(self):
        parent, run, key, session = self.prepare_checkpoint()
        messages = [body for method, body in self.calls if method == 'sendMessage']
        self.assertTrue(all(not body.get('reply_markup') for body in messages[:-1]))
        combined = ''.join(body['text'] for body in messages)
        for text in ('только редактор', '151', '171', parent['id'], run['plan_hash'],
                     'ПАМЯТЬ И УРОКИ', 'СОХРАНЁННЫЕ ИСТОЧНИКИ', 'неизвестный'):
            self.assertIn(text, combined)
        buttons = [button for row in messages[-1]['reply_markup']['inline_keyboard']
                   for button in row]
        self.assertNotIn('Codex', [button['text'] for button in buttons])
        self.assertTrue(any('только редактора' in button['text'] for button in buttons))
        self.assertEqual(self.starts, [])
        self.assertEqual(self.store.agent_trace(run['id'])['phases'], [])
        query = self.callback(key, session)
        self.workflow.handle_callback(tg.TOKEN, query)
        self.workflow.handle_callback(tg.TOKEN, query)
        self.assertEqual(len(self.starts), 1)
        self.assertEqual(self.starts[0][0], run['id'])
        self.assertEqual(self.store.run(parent['id'])['status'], 'outcome_unknown')
        self.assertEqual(self.store.settings()['daily_run_limit'], 3)

    def test_refresh_command_and_forged_provider_never_create_full_rerun(self):
        parent, run, key, session = self.prepare_checkpoint()
        before = deepcopy(run['plan']['continuation'])
        self.workflow.handle_callback(tg.TOKEN, self.callback(key, session, 'claude'))
        self.assertEqual(self.store.run(run['id'])['plan']['provider'], 'codex')
        self.workflow.handle_callback(tg.TOKEN, self.callback(key, session, 'refresh'))
        self.assertEqual(self.workflow._latest()[1]['run_id'], run['id'])
        self.bridge._handle_update(tg.TOKEN, self.incoming('/continue ' + parent['id']))
        self.assertEqual(self.workflow._latest()[1]['run_id'], run['id'])
        self.assertEqual(self.store.run(run['id'])['plan']['continuation'], before)
        self.assertEqual(self.starts, [])
        with self.assertRaises(LabError):
            self.store.replan_context(run['id'], {'memory_options': {'enabled': False}})


class CheckpointHTTPTests(unittest.TestCase):
    setUp = http_fixture.ResearchHTTPTests.setUp
    tearDown = http_fixture.ResearchHTTPTests.tearDown
    request = http_fixture.ResearchHTTPTests.request

    def test_prepare_requires_csrf_is_idempotent_and_never_starts(self):
        _, parent, _ = source_attempt(Path(self.folder.name), self.app.store)
        path = '/api/runs/' + parent['id'] + '/continue'
        before = self.app.store.counts()['runs']
        self.assertEqual(self.request('POST', path, {}, False)[0], 403)
        self.assertEqual(self.app.store.counts()['runs'], before)
        status, run = self.request('POST', path, {})
        self.assertEqual(status, 200)
        self.assertEqual(run['plan']['research_protocol']['max_calls'], 1)
        self.assertEqual(run['status'], 'planned')
        self.assertIsNone(run['approved_at'])
        self.assertEqual(self.request('POST', path, {})[1]['id'], run['id'])
        self.assertEqual(self.app.store.counts()['runs'], before + 1)
        self.assertEqual(self.app.store.agent_trace(run['id'])['phases'], [])


if __name__ == '__main__':
    unittest.main()
