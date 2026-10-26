"""Offline publication callbacks report only their persisted queue assignment."""
import copy
import sqlite3
import unittest
from unittest.mock import Mock, patch

import laboratory.telegram_workflow as workflow_module

import test_telegram_workflow as fixtures


class QueueSlotResponseTests(unittest.TestCase):
    setUp = fixtures.TelegramWorkflowTests.setUp

    def test_slot_uses_ascii_strftime_independent_of_windows_locale(self):
        local = Mock()
        local.weekday.return_value = 0

        def ascii_date(pattern):
            pattern.encode('ascii')  # CPython 3.11 Windows C-locale boundary.
            return ', 26.10.2026, 00:30'

        local.strftime.side_effect = ascii_date
        with patch.object(workflow_module, 'datetime') as clock:
            clock.fromisoformat.return_value.astimezone.return_value = local
            self.assertEqual(workflow_module._moscow_slot('2026-10-25T21:30:00Z'),
                             'пн, 26.10.2026, 00:30 МСК')

    def publisher(self, **changes):
        entry = {'id': 'TESTONLYentry1234', 'state': 'queued', 'status': 'queued',
                 'due_at': '2026-10-25T21:30:00+00:00', 'blockers': []}
        entry.update(changes)
        publisher = Mock()
        publisher.approve.return_value = entry
        self.bridge.publisher = publisher
        return publisher

    @staticmethod
    def query():
        return {'id': 'TEST_ONLY_queue_callback', 'from': {'id': 42, 'is_bot': False},
                'message': {'message_id': 101, 'chat': {'id': 42, 'type': 'private'}},
                'data': 'pub:TESTONLYentry1234:TESTONLYtoken1234'}

    def answers(self):
        return [body for method, body in self.calls if method == 'answerCallbackQuery']

    def test_actual_saved_slot_is_localized_and_repeat_returns_same_slot(self):
        publisher = self.publisher()
        result = copy.deepcopy(publisher.approve.return_value)

        def approved(*args):
            self.assertEqual(self.calls, [] if publisher.approve.call_count == 1
                             else [('answerCallbackQuery', self.answers()[0])])
            return copy.deepcopy(result)

        publisher.approve.side_effect = approved
        self.workflow.handle_callback(fixtures.TOKEN, self.query())
        self.workflow.handle_callback(fixtures.TOKEN, self.query())
        answers = self.answers()
        self.assertEqual(len(answers), 2)
        self.assertEqual(answers[0], answers[1])
        self.assertIn('пн, 26.10.2026, 00:30 МСК', answers[0]['text'])
        self.assertIn('Сохранено в очереди', answers[0]['text'])
        self.assertTrue(answers[0]['show_alert'])
        self.assertLessEqual(len(answers[0]['text']), 200)
        publisher.status.assert_not_called()
        self.assertEqual(self.starts, [])
        self.assertTrue(all(method == 'answerCallbackQuery' for method, _ in self.calls))

    def test_save_failure_has_no_success_no_slot_and_no_automatic_retry(self):
        for error in (RuntimeError('TEST_ONLY unconfirmed save'),
                      sqlite3.OperationalError('TEST_ONLY locked')):
            with self.subTest(error=type(error).__name__):
                self.calls.clear()
                publisher = self.publisher()
                publisher.approve.side_effect = error
                self.workflow.handle_callback(fixtures.TOKEN, self.query())
                publisher.approve.assert_called_once()
                text = self.answers()[0]['text']
                self.assertIn('Сохранение в очередь не подтверждено', text)
                self.assertNotIn('Сохранено в очереди', text)
                self.assertNotIn('МСК', text)
                self.assertNotIn('TEST_ONLY', text)
                self.assertEqual(self.starts, [])
                self.assertEqual([method for method, _ in self.calls],
                                 ['answerCallbackQuery'])

    def test_waiting_without_saved_slot_does_not_use_global_or_alias_slot(self):
        publisher = self.publisher(due_at=None, scheduled_for='2026-10-26T07:00:00Z',
                                   blockers=['Расписание не задано.',
                                             'Публикация по расписанию выключена.'])
        publisher.status.return_value = {'next_slot': '2026-10-26T07:00:00Z'}
        self.workflow.handle_callback(fixtures.TOKEN, self.query())
        text = self.answers()[0]['text']
        self.assertIn('Сохранено в очереди', text)
        self.assertIn('Слот пока не назначен', text)
        self.assertIn('Ожидает настройки', text)
        self.assertNotIn('МСК', text)
        publisher.status.assert_not_called()

    def test_invalid_or_naive_due_at_never_becomes_an_invented_local_slot(self):
        for timestamp in ('2026-10-26T10:00:00', 'broken', None):
            with self.subTest(timestamp=timestamp):
                self.calls.clear()
                self.publisher(due_at=timestamp)
                self.workflow.handle_callback(fixtures.TOKEN, self.query())
                text = self.answers()[0]['text']
                self.assertIn('Слот пока не назначен', text)
                self.assertNotIn('МСК', text)

    def test_blocked_or_unconfirmed_return_never_claims_queued(self):
        for entry in ({'state': 'blocked', 'due_at': '2026-10-26T10:00:00Z'}, None):
            with self.subTest(entry=entry):
                self.calls.clear()
                publisher = self.publisher()
                publisher.approve.return_value = entry
                self.workflow.handle_callback(fixtures.TOKEN, self.query())
                text = self.answers()[0]['text']
                self.assertNotIn('Сохранено в очереди', text)
                self.assertNotIn('МСК', text)
                self.assertIn('заблокирован' if entry else 'не подтверждено', text)

    def test_stale_preview_remains_rejected_and_answer_failure_never_reapproves(self):
        publisher = self.publisher()
        publisher.approve.side_effect = ValueError('TEST_ONLY stale')
        self.workflow.handle_callback(fixtures.TOKEN, self.query())
        self.assertIn('Пакет или подключение изменились', self.answers()[0]['text'])
        self.calls.clear()
        publisher = self.publisher()
        self.fail_method = 'answerCallbackQuery'
        self.workflow.handle_callback(fixtures.TOKEN, self.query())
        publisher.approve.assert_called_once()
        self.assertEqual([method for method, _ in self.calls], ['answerCallbackQuery'])
        self.assertEqual(self.starts, [])

    def test_queue_command_lists_readable_schedule_and_actual_item_slots(self):
        publisher = self.publisher()
        publisher.status.return_value = {
            'enabled': False, 'channel_connected': True, 'channel_title': 'TEST_ONLY channel',
            'slots': [{'weekday': 0, 'time': '10:00'}, {'weekday': 3, 'time': '17:30'}],
            'counts': {'queued': 2}, 'blockers': ['Публикация по расписанию выключена.'],
            'next_slot': '2099-01-01T00:00:00Z',
            'items': [{'state': 'queued', 'title': 'TEST_ONLY assigned',
                       'due_at': '2026-10-26T07:00:00Z'},
                      {'state': 'queued', 'title': 'TEST_ONLY waiting', 'due_at': None}]}
        message = fixtures.TelegramWorkflowTests.incoming(self, '/queue')
        self.bridge._handle_update(fixtures.TOKEN, message)
        text = '\n'.join(body['text'] for method, body in self.calls if method == 'sendMessage')
        self.assertIn('Очередь публикаций: 2', text)
        self.assertIn('пн 10:00 МСК', text)
        self.assertIn('чт 17:30 МСК', text)
        self.assertIn('пн, 26.10.2026, 10:00 МСК', text)
        self.assertIn('TEST_ONLY waiting', text)
        self.assertIn('слот пока не назначен', text)
        self.assertIn('Публикация по расписанию выключена', text)
        self.assertNotIn("'weekday'", text)
        self.assertNotIn('2099', text)
        publisher.approve.assert_not_called()
        self.assertEqual(self.starts, [])


if __name__ == '__main__':
    unittest.main()
