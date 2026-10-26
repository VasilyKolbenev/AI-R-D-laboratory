"""TEST_ONLY owner approval and delivery acceptance; no Telegram/model network."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from laboratory.core import Store
from laboratory.telegram import TelegramBridge, TelegramError
from laboratory.telegram_workflow import KEY, chunks


TOKEN = '123456789:' + 'A' * 35
TMP = Path(__file__).parent / '.tmp'
TMP.mkdir(exist_ok=True)


class FakePublisher:
    """Frozen package fixture with strict preview binding; never publishes."""
    def __init__(self, bridge):
        self.bridge = bridge
        self.expected_fingerprint = bridge._config['token_fingerprint']
        self.prepares, self.binds, self.approval_attempts, self.approved = [], [], [], []
        self.entry = {'id': 'TESTONLYentry1234', 'token': 'TESTONLYtoken1234', 'package_sha256': 'a' * 64,
                      'post_text': 'TEST_ONLY exact frozen publication package', 'state': 'prepared', 'can_enqueue': True,
                      'blockers': ['Канал не подключён', 'Расписание не задано', 'Выпуск выключен']}
        self.fail_bind = False

    def prepare(self, run_id):
        self.prepares.append(run_id)
        return copy.deepcopy(self.entry)

    def assets(self, entry_id):
        if entry_id != self.entry['id']: raise ValueError('TEST_ONLY wrong entry')
        return {'png': b'TEST_ONLY_FROZEN_PNG', 'mp4': b'TEST_ONLY_FROZEN_MP4'}

    def bind_preview(self, entry_id, message_id):
        if self.fail_bind: raise ValueError('TEST_ONLY bind failure')
        self.binds.append((entry_id, message_id))

    def approve(self, entry_id, token, message_id, owner, fingerprint):
        self.approval_attempts.append((entry_id, token, message_id, owner, fingerprint))
        if (entry_id != self.entry['id'] or token != self.entry['token'] or owner != 42
                or fingerprint != self.expected_fingerprint or not self.binds or message_id != self.binds[-1][1]):
            raise ValueError('TEST_ONLY stale or wrong publication approval')
        if not self.approved: self.approved.append(entry_id)
        return {**self.entry, 'state': 'queued'}

    def status(self):
        return {'enabled': False, 'timezone': 'Europe/Moscow', 'slots': [], 'channel_connected': False,
                'channel_title': None, 'items': [], 'counts': {'queued': len(self.approved)},
                'blockers': self.entry['blockers']}

    def tick(self):
        return None


class TelegramWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TMP)
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'data')
        self.calls, self.starts = [], []
        self.message_id = 100
        self.fail_method = None
        self.fail_text_number = None
        self.text_count = 0
        self.post = 'TEST_ONLY прикладной пост. Задача → механизм → результаты → границы → ресурсы → вывод.'
        for function, value in [('render_png', b'TEST_ONLY_PNG'), ('render_mp4', b'TEST_ONLY_MP4'), ('render_gif', b'TEST_ONLY_GIF')]:
            renderer = patch('laboratory.presentation.' + function, return_value=value, create=True)
            renderer.start()
            self.addCleanup(renderer.stop)

        def transport(token, method, payload):
            self.calls.append((method, copy.deepcopy(payload)))
            if method == 'sendMessage':
                self.text_count += 1
            if method == self.fail_method or (method == 'sendMessage' and self.text_count == self.fail_text_number):
                raise OSError('TEST_ONLY ambiguous network failure')
            self.message_id += 1
            if method == 'sendAnimation':
                return {'message_id': self.message_id,
                        'animation': {'width': 1920, 'height': 1080, 'file_name': 'research.mp4',
                                      'mime_type': 'video/mp4', 'file_size': 123456,
                                      'file_id': 'TEST_ONLY_private_file_id', 'file_unique_id': 'TEST_ONLY_private_unique'}}
            return {'message_id': self.message_id}

        self.bridge = TelegramBridge(self.store, Path(self.temp.name) / 'bridge', transport=transport)
        self.bridge._token = TOKEN
        self.bridge._config = {'owner_id': 42, 'token_fingerprint': self.bridge._fingerprint(TOKEN), 'username': 'TEST_ONLY_bot'}

        def start(run_id, body):
            self.starts.append((run_id, copy.deepcopy(body)))
            self.store.approve(run_id, body['plan_hash'], body['consent'], body['command_id'])
            return self.store.run(run_id)

        def cancel(run_id):
            self.store.cancel_planned(run_id)
            return self.store.run(run_id)

        self.workflow = self.bridge.bind_workflow(start, cancel,
            lambda run: {'short_text': 'TEST_ONLY: вывод; собственных измерений нет.',
                         'post_text': self.post, 'publication_checks': {'status': 'ready', 'issues': []}})

    def incoming(self, text='Speculative decoding inference TEST_ONLY https://example.org/paper', message_id=1, **extra):
        message = {'message_id': message_id, 'chat': {'id': 42, 'type': 'private'},
                   'from': {'id': 42, 'is_bot': False}, 'text': text, **extra}
        return {'update_id': message_id, 'message': message}

    def prepare(self):
        self.bridge._handle_update(TOKEN, self.incoming())
        key, session = self.workflow._latest()
        return key, session, self.store.run(session['run_id'])

    def callback(self, key, session, action='approve', **changes):
        value = {'id': 'TEST_ONLY_callback', 'from': {'id': 42, 'is_bot': False},
                 'message': {'message_id': session['approval_message_id'], 'chat': {'id': 42, 'type': 'private'}},
                 'data': 'lab:' + key + ':' + action}
        value.update(changes)
        return value

    def finish(self, run):
        self.store.trace.capture(self.store.run(run['id']))
        self.store.finish(run['id'], {'status': 'completed',
            'text': 'TEST_ONLY полный отчёт\n<lab_memory_review>{"comparisons":[]}</lab_memory_review>',
            'raw': {'test_only': True}})

    def test_validation_passport_is_visible_without_new_approval_or_dispatch(self):
        from laboratory.research_protocol import build_protocol
        _, _, original = self.prepare()
        run = copy.deepcopy(original)
        run['plan']['timeout_seconds'] = 240
        run['plan']['research_protocol'] = build_protocol(run['plan'])
        before_calls = copy.deepcopy(self.calls)
        text = '\n'.join(self.workflow._preview(run))
        self.assertIn('ПАСПОРТ ПРИКЛАДНОЙ ПРОВЕРКИ', text)
        self.assertIn('реальный эксперимент не запускался', text)
        self.assertIn('Baseline:', text)
        self.assertIn('Опровергающая проверка:', text)
        self.assertIn('Бюджет и число проходов выше не увеличиваются', text)
        self.assertEqual(self.starts, [])
        self.assertEqual(self.calls, before_calls)
        self.assertEqual(self.store.run(original['id']), original)
        legacy_text = '\n'.join(self.workflow._preview(original))
        self.assertNotIn('ПАСПОРТ ПРИКЛАДНОЙ ПРОВЕРКИ', legacy_text)

    def test_material_prepares_without_launch_and_all_context_before_button(self):
        key, session, run = self.prepare()
        self.assertEqual(self.starts, [])
        self.assertEqual(run['status'], 'planned')
        self.assertEqual(session['state'], 'ready')
        self.assertEqual(run['plan']['memory']['lessons'], [])
        self.assertTrue(run['plan']['web_search'])
        self.assertLessEqual(run['plan']['timeout_seconds'], 240)
        messages = [payload for method, payload in self.calls if method == 'sendMessage']
        self.assertTrue(all(not p.get('reply_markup') for p in messages[:-1]))
        self.assertIn('reply_markup', messages[-1])
        combined = ''.join(p['text'] for p in messages)
        self.assertIn(run['plan_hash'], combined)
        memory_text = next(p['text'] for p in messages if 'ПАМЯТЬ И УРОКИ' in p['text'])
        transmitted, _ = json.JSONDecoder().raw_decode(memory_text[memory_text.index('{'):])
        self.assertEqual(transmitted, {k: run['plan']['memory'].get(k) for k in
                                      ('enabled', 'profile', 'corrections', 'items', 'lessons', 'notices')})
        self.assertIn('baseline', combined)
        self.assertIn('self_hosted', combined)
        for row in messages[-1]['reply_markup']['inline_keyboard']:
            for button in row:
                self.assertLessEqual(len(button['callback_data'].encode()), 64)
        self.assertTrue(all(p['chat_id'] == 42 for p in messages))

    def test_only_owner_private_exact_message_can_approve_and_replay_is_free(self):
        key, session, run = self.prepare()
        bad = [self.callback(key, session, **{'from': {'id': 99}}),
               self.callback(key, session, message={'message_id': session['approval_message_id'], 'chat': {'id': 42, 'type': 'group'}}),
               self.callback(key, session, message={'message_id': 999999, 'chat': {'id': 42, 'type': 'private'}}),
               self.callback('X' * 16, session)]
        for callback in bad:
            self.workflow.handle_callback(TOKEN, callback)
        self.assertEqual(self.starts, [])
        callback = self.callback(key, session)
        self.workflow.handle_callback(TOKEN, callback)
        self.workflow.handle_callback(TOKEN, callback)
        self.assertEqual(len(self.starts), 1)
        self.assertEqual(self.starts[0][1]['plan_hash'], run['plan_hash'])
        self.assertEqual(self.store.run(run['id'])['status'], 'running')

    def test_stale_hash_and_changed_bot_cannot_approve(self):
        key, session, run = self.prepare()
        self.store.replan_context(run['id'], {'memory_options': {'enabled': True, 'lesson_ids': [], 'selected_ids': []}})
        self.workflow.handle_callback(TOKEN, self.callback(key, session))
        self.assertEqual(self.starts, [])
        key2, session2, _ = self.prepare_new_question()
        self.bridge._config['token_fingerprint'] = 'different_bot'
        self.workflow.handle_callback(TOKEN, self.callback(key2, session2))
        self.assertEqual(self.starts, [])

    def test_provider_selection_replaces_frozen_plan_without_launch_or_global_change(self):
        self.store.update_settings({'provider': 'codex', 'model': 'TEST_ONLY_codex_model'})
        settings = self.store.settings()
        key, session, run = self.prepare()
        original_plan = copy.deepcopy(run['plan'])
        markup = next(payload['reply_markup'] for method, payload in reversed(self.calls)
                      if method == 'sendMessage' and payload.get('reply_markup'))
        actions = [button['callback_data'].rsplit(':', 1)[-1] for row in markup['inline_keyboard'] for button in row]
        self.assertIn('codex', actions); self.assertIn('claude', actions)
        self.workflow.handle_callback(TOKEN, self.callback(key, session, 'claude'))
        new_key, new_session = self.workflow._latest()
        replacement = self.store.run(new_session['run_id'])
        self.assertNotEqual(replacement['id'], run['id'])
        self.assertEqual(replacement['plan']['provider'], 'claude')
        self.assertEqual(replacement['plan']['model'], '')
        self.assertEqual(replacement['plan']['question'], original_plan['question'])
        self.assertEqual(replacement['plan']['sources'], original_plan['sources'])
        self.assertEqual(self.store.run(run['id'])['plan'], original_plan)
        self.assertEqual(self.store.run(run['id'])['status'], 'cancelled')
        self.assertEqual(self.workflow._state()[key]['state'], 'superseded')
        self.assertEqual(self.store.settings(), settings)
        self.assertEqual(self.starts, [])
        self.workflow.handle_callback(TOKEN, self.callback(key, session))
        self.assertEqual(self.starts, [])
        count = len(self.store.runs())
        self.workflow.handle_callback(TOKEN, self.callback(new_key, new_session, 'claude'))
        self.assertEqual(len(self.store.runs()), count)
        self.workflow.handle_callback(TOKEN, self.callback(new_key, new_session, 'codex'))
        final_key, final_session = self.workflow._latest()
        self.assertEqual(self.store.run(final_session['run_id'])['plan']['provider'], 'codex')
        self.assertEqual(self.store.run(final_session['run_id'])['plan']['model'], '')
        self.workflow.handle_callback(TOKEN, self.callback(final_key, final_session))
        self.assertEqual(len(self.starts), 1)
        self.assertEqual(self.starts[0][0], final_session['run_id'])

    def test_provider_button_owner_message_and_partial_preview_guards(self):
        key, session, run = self.prepare()
        for query in (self.callback(key, session, 'claude', **{'from': {'id': 99}}),
                      self.callback(key, session, 'claude', message={'message_id': 999, 'chat': {'id': 42, 'type': 'private'}})):
            self.workflow.handle_callback(TOKEN, query)
        self.assertEqual(len(self.store.runs()), 1)
        self.fail_text_number = self.text_count + 1
        with self.assertRaises(TelegramError): self.workflow.handle_callback(TOKEN, self.callback(key, session, 'claude'))
        self.assertEqual(len(self.store.runs()), 2)
        self.assertEqual(self.workflow._state()[key]['state'], 'superseded')
        self.assertEqual(self.workflow._latest()[1]['state'], 'preview_uncertain')
        self.workflow.handle_callback(TOKEN, self.callback(key, session, 'claude'))
        self.assertEqual(len(self.store.runs()), 2)
        self.assertEqual(self.starts, [])

    def prepare_new_question(self):
        self.bridge._handle_update(TOKEN, self.incoming('/research TEST_ONLY новый вопрос о speculative decoding', message_id=2))
        key, session = self.workflow._latest()
        return key, session, self.store.run(session['run_id'])

    def test_partial_preview_has_no_actionable_button_and_retry_does_not_launch(self):
        self.fail_text_number = 2
        with self.assertRaises(TelegramError):
            self.bridge._handle_update(TOKEN, self.incoming())
        self.assertEqual(self.starts, [])
        self.assertFalse(any(p.get('reply_markup') for method, p in self.calls if method == 'sendMessage'))
        key, session = self.workflow._latest()
        self.assertEqual(session['state'], 'preview_uncertain')
        self.workflow.handle_callback(TOKEN, self.callback(key, session))
        self.assertEqual(self.starts, [])
        self.fail_text_number = None
        self.bridge._handle_update(TOKEN, self.incoming('/plan', message_id=2))
        _, new_session = self.workflow._latest()
        self.assertEqual(new_session['state'], 'ready')
        self.assertEqual(len(self.store.runs()), 1)

    def test_changed_profile_blocks_start_and_refresh_requires_new_button(self):
        key, session, run = self.prepare()
        profile = self.store.memory.profile()
        self.store.memory.save_profile({'expected_version': profile['version'], 'interests': 'TEST_ONLY newer profile',
                                        'goals': '', 'preferences': '', 'review_days': 30})
        self.workflow.handle_callback(TOKEN, self.callback(key, session))
        self.assertEqual(self.store.run(run['id'])['status'], 'planned')
        self.workflow.handle_callback(TOKEN, self.callback(key, session, 'refresh'))
        new_key, new_session = self.workflow._latest()
        self.assertNotEqual(new_key, key)
        self.assertNotEqual(new_session['plan_hash'], session['plan_hash'])
        self.workflow.handle_callback(TOKEN, self.callback(key, session))
        self.assertEqual(self.store.run(run['id'])['status'], 'planned')
        self.workflow.handle_callback(TOKEN, self.callback(new_key, new_session))
        self.assertEqual(self.store.run(run['id'])['status'], 'running')

    def test_completion_is_saved_once_delivered_and_survives_restart(self):
        key, session, run = self.prepare()
        self.workflow.handle_callback(TOKEN, self.callback(key, session))
        self.finish(run)
        self.calls.clear()
        with patch('laboratory.telegram_workflow.TelegramWorkflow._send', wraps=self.workflow._send):
            self.workflow.tick()
        self.assertEqual(len(self.store.knowledge()), 1)
        first_count = len(self.calls)
        self.bridge.bind_workflow(self.workflow.start_run, self.workflow.cancel_run, self.workflow.presentation_builder)
        self.bridge.tick_workflow()
        self.assertEqual(len(self.calls), first_count)
        self.assertEqual(len(self.starts), 1)
        _, current = self.bridge.workflow._latest()
        self.assertEqual(current['delivery'], 'sent')
        self.assertEqual([method for method, _ in self.calls], ['sendMessage', 'sendPhoto', 'sendAnimation'])
        self.assertEqual(self.calls[0][1]['text'], self.post)
        self.assertFalse(any(method == 'sendDocument' for method, _ in self.calls))

    def test_ambiguous_delivery_is_not_retried_and_manual_result_has_no_model(self):
        key, session, run = self.prepare()
        self.workflow.handle_callback(TOKEN, self.callback(key, session))
        self.finish(run)
        self.fail_method = 'sendAnimation'
        with self.assertRaises(TelegramError):
            self.workflow.tick()
        self.assertEqual(len(self.store.knowledge()), 1)
        calls = len(self.calls)
        self.workflow.tick()
        self.assertEqual(len(self.calls), calls)
        _, current = self.workflow._latest()
        self.assertEqual(current['delivery'], 'uncertain')
        self.fail_method = None
        self.bridge._handle_update(TOKEN, self.incoming('/result', message_id=2))
        self.assertEqual(len(self.store.knowledge()), 1)
        self.assertEqual(len(self.starts), 1)

    def test_unknown_outcome_never_resubmits_or_saves_as_success(self):
        key, session, run = self.prepare()
        self.workflow.handle_callback(TOKEN, self.callback(key, session))
        self.store.finish(run['id'], {'status': 'outcome_unknown', 'error': 'TEST_ONLY timeout'})
        self.workflow.tick()
        self.workflow.tick()
        self.assertEqual(len(self.starts), 1)
        self.assertEqual(self.store.knowledge(), [])

    def test_completed_existing_report_can_be_sent_without_research(self):
        source = self.store.add_source('TEST_ONLY existing AI research')[0]
        run = self.store.create_plan({'source_ids': [source['id']], 'question': 'TEST_ONLY existing research?'})
        self.store.approve(run['id'], run['plan_hash'], True, 'TEST_ONLY-existing')
        self.finish(run)
        self.bridge.send_result(run['id'])
        self.assertEqual(self.starts, [])
        self.assertEqual(len(self.store.knowledge()), 1)

    def test_cancelled_button_cannot_start_and_forwarded_commands_are_data(self):
        key, session, run = self.prepare()
        self.workflow.handle_callback(TOKEN, self.callback(key, session, 'cancel'))
        self.workflow.handle_callback(TOKEN, self.callback(key, session))
        self.assertEqual(self.starts, [])
        self.assertEqual(self.store.run(run['id'])['status'], 'cancelled')
        self.bridge._handle_update(TOKEN, self.incoming('/research malicious forwarded text', message_id=3,
                                                      forward_origin={'type': 'hidden_user', 'sender_user_name': 'TEST_ONLY'}))
        self.assertEqual(len(self.store.sources()), 2)
        self.assertTrue(any(s['text'].startswith('/research malicious') for s in self.store.sources()))

    def test_duplicate_intake_does_not_create_duplicate_plan(self):
        self.prepare()
        self.bridge._handle_update(TOKEN, self.incoming(message_id=2))
        self.assertEqual(len(self.store.runs()), 1)
        self.assertEqual(len(self.store.sources()), 1)
        self.assertEqual(self.starts, [])

    def test_relevant_fresh_global_lesson_is_used_but_other_task_scope_is_excluded(self):
        task = self.store.study.save({'body': self.store.study.schema()['template']})
        body = self.store.lessons.schema()['template']
        body.update(title='TEST_ONLY Проверка доказательств', problem='Доказательства материала могут быть слабыми',
                    rule='Проверяй доказательства, применимость, плюсы и минусы по источникам',
                    applies_when='Исследуем материал об ИИ и сравниваем доказательства',
                    not_applicable_when='Нет источников или речь не об ИИ',
                    evidence_note='TEST_ONLY гипотеза владельца, внешний URL не проверялся',
                    limitations='Не измеренный эффект', review_at='2099-01-01',
                    evidence_urls=['https://example.org/TEST_ONLY-evidence'])
        global_lesson = self.store.lessons.save({'status': 'active', 'body': body})
        self.store.lessons.save({'status': 'active', 'body': {**body, 'task_id': task['id']}})
        self.store.lessons.save({'status': 'active', 'body': {**body, 'review_at': '2000-01-01'}})
        _, _, run = self.prepare()
        self.assertEqual([item['id'] for item in run['plan']['memory']['lessons']], [global_lesson['id']])

    def test_web_approval_of_same_bot_preview_is_saved_and_delivered_without_bot_dispatch(self):
        _, session, run = self.prepare()
        self.store.approve(run['id'], run['plan_hash'], True, 'TEST_ONLY-web-approval')
        self.finish(run)
        self.workflow.tick()
        self.assertEqual(self.starts, [])
        self.assertEqual(len(self.store.knowledge()), 1)
        _, current = self.workflow._latest()
        self.assertEqual(current['delivery'], 'sent')

    def test_reviewed_result_delivers_graph_animation_and_draft_without_new_research(self):
        _, _, run = self.prepare()
        self.store.approve(run['id'], run['plan_hash'], True, 'TEST_ONLY-reviewed-delivery')
        self.finish(run)
        original = self.store.run(run['id'])['output']
        self.workflow.presentation_builder = lambda unused: {
            'provenance': {'mode': 'editor_reviewed'}, 'comparisons': [{'label': 'TEST_ONLY metric'}],
            'short_text': 'TEST_ONLY прикладной вывод', 'post_text': self.post,
            'publication_checks': {'status': 'ready', 'issues': []}}
        self.calls.clear()
        self.bridge.send_result(run['id'])
        methods = [method for method, _ in self.calls]
        self.assertEqual(methods, ['sendMessage', 'sendPhoto', 'sendAnimation'])
        texts = [payload['text'] for method, payload in self.calls if method == 'sendMessage']
        self.assertEqual(texts, [self.post])
        photo = next(payload for method, payload in self.calls if method == 'sendPhoto')
        self.assertEqual(photo.get('caption', ''), '')
        animation = next(payload for method, payload in self.calls if method == 'sendAnimation')
        self.assertEqual(animation.get('caption', ''), '')
        self.assertEqual(animation['_files']['animation'], ('research.mp4', b'TEST_ONLY_MP4', 'video/mp4'))
        self.assertTrue(all(payload['chat_id'] == 42 for _, payload in self.calls))
        _, current = self.workflow._latest()
        self.assertEqual(current['delivery_media'][-1], {
            'requested_file_name': 'research.mp4', 'requested_mime_type': 'video/mp4',
            'width': 1920, 'height': 1080, 'file_name': 'research.mp4', 'mime_type': 'video/mp4', 'file_size': 123456})
        self.assertNotIn('file_id', json.dumps(current['delivery_media']))
        self.assertEqual(self.starts, [])
        self.assertEqual(self.store.run(run['id'])['output'], original)

    def test_replayed_manual_result_update_does_not_retry_partial_delivery(self):
        _, _, run = self.prepare()
        self.store.approve(run['id'], run['plan_hash'], True, 'TEST_ONLY-web-manual-result')
        self.finish(run)
        request = self.incoming('/result', message_id=2)
        original_transport = self.bridge._transport

        def transport(token, method, payload):
            if method == 'getUpdates':
                return [request]
            return original_transport(token, method, payload)

        self.bridge._transport = transport
        self.fail_method = 'sendAnimation'
        with self.assertRaises(TelegramError):
            self.bridge._poll_once(TOKEN, self.bridge._config)
        before = sum(method == 'sendAnimation' for method, _ in self.calls)
        self.bridge._poll_once(TOKEN, self.bridge._config)
        self.assertEqual(sum(method == 'sendAnimation' for method, _ in self.calls), before)
        offset_key = 'telegram_offset_' + self.bridge._fingerprint(TOKEN)
        self.assertEqual(self.store.get_setting(offset_key), 3)
        request = self.incoming('/result', message_id=3)
        self.fail_method = None
        self.bridge._poll_once(TOKEN, self.bridge._config)
        self.assertEqual(sum(method == 'sendAnimation' for method, _ in self.calls), before + 1)
        self.assertEqual(self.starts, [])
        self.assertEqual(len(self.store.knowledge()), 1)

    def test_incomplete_format_sends_one_operational_notice_and_keeps_knowledge(self):
        key, session, run = self.prepare()
        self.workflow.handle_callback(TOKEN, self.callback(key, session))
        self.finish(run)
        self.workflow.presentation_builder = lambda unused: {
            'post_text': self.post, 'short_text': 'TEST_ONLY should not be sent',
            'publication_checks': {'status': 'incomplete', 'issues': ['TEST_ONLY missing source excerpt.']}}
        self.calls.clear()
        with patch('laboratory.presentation.render_mp4', create=True) as video, \
             patch('laboratory.presentation.render_png') as image:
            self.workflow.tick()
            video.assert_not_called(); image.assert_not_called()
        self.assertEqual([method for method, _ in self.calls], ['sendMessage'])
        text = self.calls[0][1]['text']
        self.assertIn('TEST_ONLY missing source excerpt.', text)
        self.assertIn('Отчёт сохранён в базе знаний', text)
        self.assertNotIn(self.post, text)
        self.assertNotIn('should not be sent', text)
        self.assertEqual(len(self.store.knowledge()), 1)
        count = len(self.calls); self.workflow.tick()
        self.assertEqual(len(self.calls), count)
        self.assertEqual(len(self.starts), 1)

    def test_exact_3500_utf16_post_is_one_message_and_oversize_is_not_fragmented(self):
        key, session, run = self.prepare()
        self.workflow.handle_callback(TOKEN, self.callback(key, session))
        self.finish(run)
        self.post = '🧠' * 1750
        self.calls.clear()
        self.workflow.tick()
        messages = [payload['text'] for method, payload in self.calls if method == 'sendMessage']
        self.assertEqual(messages, [self.post])
        self.assertEqual(len(messages[0].encode('utf-16-le')) // 2, 3500)
        self.post += 'x'
        self.calls.clear()
        self.bridge.send_result(run['id'])
        self.assertEqual([method for method, _ in self.calls], ['sendMessage'])
        self.assertIn('превышает 3500', self.calls[0][1]['text'])
        self.assertNotIn(self.post, self.calls[0][1]['text'])
        self.assertEqual(len(self.starts), 1)

    def test_mp4_absence_falls_back_to_gif_without_service_caption(self):
        key, session, run = self.prepare()
        self.workflow.handle_callback(TOKEN, self.callback(key, session))
        self.finish(run)
        self.calls.clear()
        with patch('laboratory.presentation.render_mp4', return_value=None, create=True), \
             patch('laboratory.presentation.render_gif', return_value=b'TEST_ONLY_FALLBACK') as gif:
            self.workflow.tick()
            gif.assert_called_once()
        animation = next(payload for method, payload in self.calls if method == 'sendAnimation')
        self.assertEqual(animation['_files']['animation'], ('research.gif', b'TEST_ONLY_FALLBACK', 'image/gif'))
        self.assertEqual(animation.get('caption', ''), '')
        self.assertEqual([method for method, _ in self.calls], ['sendMessage', 'sendPhoto', 'sendAnimation'])

    def test_missing_or_sensitive_response_media_fields_remain_unknown(self):
        key, session, run = self.prepare()
        self.workflow.handle_callback(TOKEN, self.callback(key, session))
        self.finish(run)
        original_transport = self.bridge._transport
        def transport(token, method, payload):
            response = original_transport(token, method, payload)
            if method == 'sendAnimation':
                response['animation'] = {'file_id': TOKEN, 'file_name': TOKEN,
                                         'mime_type': TOKEN, 'file_size': True, 'height': -1}
            return response
        self.bridge._transport = transport
        self.workflow.tick()
        _, current = self.workflow._latest()
        media = current['delivery_media'][-1]
        self.assertEqual({field: media[field] for field in ('width', 'height', 'file_size', 'file_name', 'mime_type')},
                         dict.fromkeys(('width', 'height', 'file_size', 'file_name', 'mime_type')))
        self.assertNotIn(TOKEN, json.dumps(media))
        self.assertNotIn('file_id', json.dumps(media))
        self.bridge._transport = lambda token, method, payload: {'message_id': 991}
        self.bridge.send_result(run['id'])
        _, current = self.workflow._latest()
        self.assertIsNone(current['delivery_media'][-1]['width'])

    def test_failed_and_cancelled_results_send_only_one_operational_notice(self):
        key, session, run = self.prepare()
        self.workflow.handle_callback(TOKEN, self.callback(key, session))
        self.store.finish(run['id'], {'status': 'failed', 'error': 'TEST_ONLY failure'})
        self.calls.clear()
        self.workflow.tick()
        self.assertEqual([method for method, _ in self.calls], ['sendMessage'])
        self.assertIn('failed', self.calls[0][1]['text'])
        self.assertEqual(self.store.knowledge(), [])
        count = len(self.calls); self.workflow.tick()
        self.assertEqual(len(self.calls), count)
        _, _, cancelled = self.prepare_new_question()
        self.store.cancel_planned(cancelled['id'])
        self.calls.clear()
        self.bridge.send_result(cancelled['id'])
        self.assertEqual([method for method, _ in self.calls], ['sendMessage'])
        self.assertIn('cancelled', self.calls[0][1]['text'])
        self.assertEqual(self.store.knowledge(), [])

    def test_uncertain_post_send_does_not_retry_or_send_media(self):
        key, session, run = self.prepare()
        self.workflow.handle_callback(TOKEN, self.callback(key, session))
        self.finish(run)
        self.calls.clear(); self.fail_method = 'sendMessage'
        with self.assertRaises(TelegramError): self.workflow.tick()
        self.assertEqual([method for method, _ in self.calls], ['sendMessage'])
        before = len(self.calls); self.workflow.tick()
        self.assertEqual(len(self.calls), before)
        self.assertEqual(len(self.starts), 1)
        self.assertEqual(len(self.store.knowledge()), 1)

    def test_utf16_chunking_preserves_all_text_and_bounds(self):
        value = '🧠 Модель и память\n' * 1400
        parts = chunks(value)
        self.assertEqual(''.join(parts), value)
        self.assertTrue(all(len(p.encode('utf-16-le')) // 2 <= 3300 for p in parts))

    def test_album_caption_and_unread_photo_create_one_plan_and_keep_caption_latest(self):
        caption = self.incoming('', message_id=10, media_group_id='TEST_ONLY_album',
                                caption='Dream-RSI TEST_ONLY исследование ИИ https://example.org/paper',
                                photo=[{'file_id': 'TEST_ONLY_photo_caption'}])
        caption['message'].pop('text')
        self.bridge._handle_update(TOKEN, caption)
        first_key, first_session = self.workflow._latest()
        first_run = self.store.run(first_session['run_id'])
        self.assertIn('Dream-RSI', first_run['plan']['sources'][0]['text'])
        self.assertIn('Содержимое файла не прочитано', first_run['plan']['sources'][0]['text'])
        photo = self.incoming('', message_id=11, media_group_id='TEST_ONLY_album',
                              photo=[{'file_id': 'TEST_ONLY_photo_only'}])
        photo['message'].pop('text')
        self.bridge._handle_update(TOKEN, photo)
        self.bridge._handle_update(TOKEN, photo)  # Update replay/duplicate intake.
        self.assertEqual(len(self.store.runs()), 1)
        self.assertEqual(len(self.store.sources()), 2)
        self.assertEqual(self.workflow._latest()[0], first_key)
        self.assertEqual(self.workflow._latest()[1]['run_id'], first_run['id'])
        self.assertEqual(self.starts, [])
        approval_messages = [payload for method, payload in self.calls if method == 'sendMessage' and payload.get('reply_markup')]
        self.assertEqual(len(approval_messages), 1)
        self.assertIn(first_run['plan']['sources'][0]['title'], approval_messages[0]['text'])
        unread = next(source for source in self.store.sources() if 'Dream-RSI' not in source['text'])
        self.assertEqual(unread['origins'][0]['raw']['media_group_id'], 'TEST_ONLY_album')
        self.assertTrue(unread['origins'][0]['attachment_unread'])

    def test_attachment_only_without_caption_is_saved_without_plan_or_button(self):
        photo = self.incoming('', message_id=12, photo=[{'file_id': 'TEST_ONLY_unread'}])
        photo['message'].pop('text')
        self.bridge._handle_update(TOKEN, photo)
        self.assertEqual(len(self.store.sources()), 1)
        self.assertEqual(self.store.runs(), [])
        self.assertIsNone(self.workflow._latest()[1])
        self.assertFalse(any(p.get('reply_markup') for method, p in self.calls if method == 'sendMessage'))
        self.assertEqual(self.starts, [])

    def test_generic_prepare_source_refuses_placeholder_even_when_forced_and_preserves_prior_plan(self):
        key, session, run = self.prepare()
        source = self.store.add_source('[Вложение Telegram: вложение. Содержимое файла не прочитано.]')[0]
        self.assertIsNone(self.workflow.prepare_source(source, force=True, question='TEST_ONLY inspect attachment'))
        self.assertEqual(len(self.store.runs()), 1)
        self.assertEqual(self.store.run(run['id'])['status'], 'planned')
        self.assertEqual(self.workflow._latest()[0], key)
        self.assertEqual(self.starts, [])

    def test_meaningful_text_or_url_next_to_notice_is_still_accepted(self):
        source = self.store.add_source('https://example.org/paper\n\n[Вложение Telegram: paper.png. Содержимое файла не прочитано.]',
                                       url='https://example.org/paper')[0]
        run = self.workflow.prepare_source(source)
        self.assertEqual(run['status'], 'planned')
        self.assertEqual(run['plan']['sources'][0]['text'], source['text'])
        self.assertEqual(self.starts, [])


    def test_publisher_preview_uses_frozen_package_and_button_follows_both_media(self):
        key, session, run = self.prepare()
        self.workflow.handle_callback(TOKEN, self.callback(key, session))
        self.finish(run)
        publisher = self.bridge.publisher = FakePublisher(self.bridge)
        self.calls.clear()
        with patch('laboratory.presentation.render_png') as png, patch('laboratory.presentation.render_mp4') as mp4:
            self.workflow.tick()
            png.assert_not_called(); mp4.assert_not_called()
        self.assertEqual([method for method, _ in self.calls], ['sendMessage', 'sendPhoto', 'sendAnimation', 'sendMessage'])
        self.assertEqual(self.calls[0][1]['text'], publisher.entry['post_text'])
        self.assertEqual(self.calls[1][1]['_files']['photo'][1], b'TEST_ONLY_FROZEN_PNG')
        self.assertEqual(self.calls[2][1]['_files']['animation'][1], b'TEST_ONLY_FROZEN_MP4')
        operation = self.calls[-1][1]
        button = operation['reply_markup']['inline_keyboard'][0][0]
        self.assertEqual(button['text'], 'В очередь')
        self.assertLessEqual(len(button['callback_data'].encode()), 64)
        self.assertIn(publisher.entry['package_sha256'], operation['text'])
        self.assertIn('Канал не подключён', operation['text'])
        self.assertIn('Расписание не задано', operation['text'])
        self.assertEqual(publisher.prepares, [run['id']])
        self.assertEqual(len(publisher.binds), 1)
        _, current = self.workflow._latest()
        self.assertEqual(current['publication_preview_message_id'], publisher.binds[-1][1])
        self.assertEqual(current['publication_package_sha256'], publisher.entry['package_sha256'])
        query = {'id': 'TEST_ONLY_pub', 'from': {'id': 42, 'is_bot': False},
                 'message': {'message_id': publisher.binds[-1][1], 'chat': {'id': 42, 'type': 'private'}},
                 'data': button['callback_data']}
        self.workflow.handle_callback(TOKEN, query)
        self.workflow.handle_callback(TOKEN, query)
        self.assertEqual(publisher.approved, [publisher.entry['id']])
        self.assertEqual(publisher.approval_attempts[-1], (publisher.entry['id'], publisher.entry['token'],
                         publisher.binds[-1][1], 42, self.bridge._config['token_fingerprint']))
        self.assertEqual(len(self.starts), 1)
        self.assertTrue(all(payload.get('chat_id') in (None, 42) for _, payload in self.calls))

    def test_publisher_callback_rejects_nonowner_wrong_message_and_changed_bot(self):
        key, session, run = self.prepare()
        self.workflow.handle_callback(TOKEN, self.callback(key, session)); self.finish(run)
        publisher = self.bridge.publisher = FakePublisher(self.bridge)
        self.workflow.tick()
        query = {'id': 'TEST_ONLY_pub', 'from': {'id': 42, 'is_bot': False},
                 'message': {'message_id': publisher.binds[-1][1], 'chat': {'id': 42, 'type': 'private'}},
                 'data': 'pub:' + publisher.entry['id'] + ':' + publisher.entry['token']}
        wrong = copy.deepcopy(query); wrong['from']['id'] = 99
        self.workflow.handle_callback(TOKEN, wrong)
        wrong = copy.deepcopy(query); wrong['message']['chat']['type'] = 'group'
        self.workflow.handle_callback(TOKEN, wrong)
        self.assertEqual(publisher.approval_attempts, [])
        wrong = copy.deepcopy(query); wrong['message']['message_id'] += 1
        self.workflow.handle_callback(TOKEN, wrong)
        self.assertEqual(publisher.approved, [])
        self.bridge._config['token_fingerprint'] = 'TEST_ONLY_CHANGED_BOT'
        self.workflow.handle_callback(TOKEN, query)
        self.assertEqual(publisher.approved, [])
        self.assertEqual(len(self.starts), 1)

    def test_publisher_media_failure_never_exposes_button_or_retries(self):
        key, session, run = self.prepare()
        self.workflow.handle_callback(TOKEN, self.callback(key, session)); self.finish(run)
        publisher = self.bridge.publisher = FakePublisher(self.bridge)
        self.calls.clear(); self.fail_method = 'sendAnimation'
        with self.assertRaises(TelegramError): self.workflow.tick()
        self.assertEqual(publisher.binds, [])
        self.assertFalse(any(payload.get('reply_markup') for method, payload in self.calls if method == 'sendMessage'))
        count = len(self.calls); self.workflow.tick()
        self.assertEqual(len(self.calls), count)
        self.assertEqual(self.workflow._latest()[1]['delivery'], 'uncertain')

    def test_expected_package_preparation_failure_is_notice_without_uncertain_or_retry(self):
        key, session, run = self.prepare()
        self.workflow.handle_callback(TOKEN, self.callback(key, session)); self.finish(run)
        publisher = self.bridge.publisher = FakePublisher(self.bridge)
        self.calls.clear()
        with patch.object(publisher, 'prepare', side_effect=ValueError('TEST_ONLY legacy report has no MP4')) as prepare, \
             patch.object(publisher, 'assets') as assets:
            self.workflow.tick()
            prepare.assert_called_once_with(run['id'])
            assets.assert_not_called()
            self.assertEqual([method for method, _ in self.calls], ['sendMessage'])
            self.assertIn('Отчёт сохранён в базе знаний', self.calls[0][1]['text'])
            self.assertIn('Пакет для очереди пока не готов', self.calls[0][1]['text'])
            self.assertNotIn('reply_markup', self.calls[0][1])
            self.assertEqual(publisher.binds, [])
            current = self.workflow._latest()[1]
            self.assertEqual(current['delivery'], 'sent')
            self.assertEqual(current['publication_package_status'], 'not_ready')
            count = len(self.calls); self.workflow.tick()
            self.assertEqual(len(self.calls), count)
            prepare.assert_called_once()
        self.assertEqual(len(self.store.knowledge()), 1)
        self.assertEqual(len(self.starts), 1)

    def test_publisher_button_failure_is_uncertain_and_unbound_without_retry(self):
        key, session, run = self.prepare()
        self.workflow.handle_callback(TOKEN, self.callback(key, session)); self.finish(run)
        publisher = self.bridge.publisher = FakePublisher(self.bridge)
        self.calls.clear(); self.fail_text_number = self.text_count + 2
        with self.assertRaises(TelegramError): self.workflow.tick()
        self.assertEqual([method for method, _ in self.calls], ['sendMessage', 'sendPhoto', 'sendAnimation', 'sendMessage'])
        self.assertEqual(publisher.binds, [])
        self.assertEqual(self.workflow._latest()[1]['delivery'], 'uncertain')
        count = len(self.calls); self.workflow.tick()
        self.assertEqual(len(self.calls), count)

    def test_published_or_uncertain_package_can_be_viewed_without_new_queue_button(self):
        key, session, run = self.prepare()
        self.workflow.handle_callback(TOKEN, self.callback(key, session)); self.finish(run)
        publisher = self.bridge.publisher = FakePublisher(self.bridge)
        publisher.entry.update(can_enqueue=False, state='publication_uncertain')
        self.calls.clear(); self.workflow.tick()
        self.assertEqual([method for method, _ in self.calls], ['sendMessage', 'sendPhoto', 'sendAnimation'])
        self.assertEqual(publisher.binds, [])
        self.assertEqual(self.workflow._latest()[1]['delivery'], 'sent')

    def test_adaptive_visual_reason_is_in_owner_control_without_changing_frozen_post_or_approving(self):
        _, _, run = self.prepare()
        self.store.approve(run['id'], run['plan_hash'], True, 'TEST_ONLY-adaptive-preview')
        self.finish(run)
        original = self.store.run(run['id'])['output']
        publisher = self.bridge.publisher = FakePublisher(self.bridge)
        self.workflow.presentation_builder = lambda unused: {
            'post_text': self.post, 'publication_checks': {'status': 'ready', 'issues': []},
            'visual_profile': {'mode': 'infrastructure', 'label': 'Инфраструктура и требования',
                               'reason': 'TEST_ONLY: основной вопрос — ресурсы и запуск.'},
            'motion_story': {'version': 'dataflow-v1', 'baseline': {'status': 'unknown',
                                'note': 'TEST_ONLY: сопоставимый движок в отчёте не указан.'}}}
        self.calls.clear()
        self.bridge.send_result(run['id'])
        messages = [payload for method, payload in self.calls if method == 'sendMessage']
        self.assertEqual(messages[0]['text'], publisher.entry['post_text'])
        self.assertNotIn('Визуал:', messages[0]['text'])
        self.assertIn('Визуал: Инфраструктура и требования', messages[-1]['text'])
        self.assertIn('TEST_ONLY: основной вопрос — ресурсы и запуск.', messages[-1]['text'])
        self.assertIn('Анимация: движение данных и работа компонентов.', messages[-1]['text'])
        self.assertIn('Baseline: не раскрыт.', messages[-1]['text'])
        self.assertIn('TEST_ONLY: сопоставимый движок в отчёте не указан.', messages[-1]['text'])
        self.assertIn('inline_keyboard', messages[-1]['reply_markup'])
        self.assertEqual(publisher.approved, [])
        self.assertEqual(self.store.run(run['id'])['output'], original)

    def test_queue_status_is_operational_and_does_not_enable_publication(self):
        self.calls.clear()
        self.bridge._handle_update(TOKEN, self.incoming('/queue'))
        self.assertEqual([method for method, _ in self.calls], ['sendMessage'])
        self.assertIn('не подключена', self.calls[-1][1]['text'])
        publisher = self.bridge.publisher = FakePublisher(self.bridge)
        publisher.approved.append(publisher.entry['id'])
        self.calls.clear()
        self.bridge._handle_update(TOKEN, self.incoming('/queue', message_id=2))
        self.assertEqual([method for method, _ in self.calls], ['sendMessage'])
        text = self.calls[0][1]['text']
        self.assertIn('Очередь публикаций: 1', text)
        self.assertIn('Канал: не подключён', text)
        self.assertIn('Расписание: не задано', text)
        self.assertIn('Автовыпуск: выключен', text)
        self.assertEqual(self.starts, [])
        self.assertEqual(publisher.prepares, [])


if __name__ == '__main__':
    unittest.main()
