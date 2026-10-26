"""TEST_ONLY owner UI and mock Telegram, with no provider/network dispatch."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

import test_telegram_workflow as telegram_fixtures


class ReviewedTelegramSurfaceTests(unittest.TestCase):
    setUp = telegram_fixtures.TelegramWorkflowTests.setUp
    incoming = telegram_fixtures.TelegramWorkflowTests.incoming
    prepare = telegram_fixtures.TelegramWorkflowTests.prepare
    callback = telegram_fixtures.TelegramWorkflowTests.callback

    def test_reviewed_preview_has_roles_budget_exact_selected_comparison_before_button(self):
        self.store.update_settings({'research_mode': 'reviewed', 'timeout_seconds': 240})
        _, _, run = self.prepare()
        self.assertEqual(self.starts, [])
        self.assertEqual(run['plan']['research_protocol']['version'], 'three-pass-v1')
        messages = [payload for method, payload in self.calls if method == 'sendMessage']
        combined = ''.join(payload['text'] for payload in messages)
        for text in ('исследователь и прикладной аналитик', 'критик', 'рецензент', '3 вызова CLI', '240',
                     'Веб-поиск разрешён ролям:', 'СРАВНЕНИЕ: ТОЧНЫЙ СНИМОК'):
            self.assertIn(text, combined)
        self.assertNotIn('Один запуск codex', combined)
        comparison = next(payload['text'] for payload in messages if 'СРАВНЕНИЕ: ТОЧНЫЙ СНИМОК' in payload['text'])
        transmitted, _ = json.JSONDecoder().raw_decode(comparison[comparison.index('{'):])
        self.assertEqual(transmitted, run['plan']['comparison_context'])
        self.assertTrue(all(not payload.get('reply_markup') for payload in messages[:-1]))
        self.assertIn('резервирует 3 вызова CLI за 24 часа', messages[-1]['text'])
        self.assertTrue(all(payload['chat_id'] == 42 for payload in messages))

    def test_provider_choice_keeps_reviewed_mode_and_budget(self):
        self.store.update_settings({'research_mode': 'reviewed', 'timeout_seconds': 240})
        key, session, _ = self.prepare()
        self.workflow.handle_callback('123456789:' + 'A' * 35, self.callback(key, session, 'claude'))
        replacement = self.store.run(self.workflow._latest()[1]['run_id'])
        self.assertEqual(replacement['plan']['provider'], 'claude')
        self.assertEqual(replacement['plan']['research_protocol']['max_calls'], 3)
        self.assertEqual(replacement['plan']['timeout_seconds'], 240)
        self.assertEqual(self.starts, [])

    def test_legacy_provider_choice_remains_single_after_new_global_defaults(self):
        key, session, run = self.prepare()
        self.assertNotIn('research_protocol', run['plan'])
        self.store.update_settings({'research_mode': 'reviewed', 'timeout_seconds': 240})
        self.workflow.handle_callback('123456789:' + 'A' * 35, self.callback(key, session, 'claude'))
        replacement = self.store.run(self.workflow._latest()[1]['run_id'])
        self.assertNotIn('research_protocol', replacement['plan'])
        self.assertEqual(replacement['plan']['timeout_seconds'], run['plan']['timeout_seconds'])
        self.assertEqual(self.starts, [])


class ReviewedWebSurfaceTests(unittest.TestCase):
    def test_owner_dom_contract_without_browser_or_network(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node is unavailable')
        fixture = Path(__file__).with_name('reviewed_surface_dom.cjs')
        result = subprocess.run([node, str(fixture)], capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('lazy journal passed', result.stdout)


if __name__ == '__main__':
    unittest.main()
