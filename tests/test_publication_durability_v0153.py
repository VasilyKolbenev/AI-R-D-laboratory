"""TEST_ONLY SQLite queue durability; no provider or Telegram transport calls."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from laboratory.core import Store
from laboratory.publication import CONFIG_KEY, QUEUE_KEY, Publisher, QueueConflict
import test_publication as fixtures


class PublicationDurabilityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=Path(__file__).parent / '.tmp')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name) / 'data'
        self.store = Store(self.directory)
        self.bridge = fixtures.FakeBridge()
        self.now = datetime(2026, 10, 19, 8, 0, tzinfo=timezone.utc)
        self.data = {'title': 'TEST_ONLY durable queue', 'post_text': 'TEST_ONLY saved post.',
                     'publication_checks': {'status': 'ready'},
                     'publication_rules': {'version': 'TEST_ONLY_durability'}}
        self.builder = lambda run: deepcopy(self.data)
        for name, value in [('render_png', b'TEST_ONLY_PNG'), ('render_mp4', b'TEST_ONLY_MP4')]:
            render = patch('laboratory.presentation.' + name, return_value=value)
            render.start()
            self.addCleanup(render.stop)
        self.publisher = Publisher(self.store, self.bridge, self.builder, clock=lambda: self.now)
        self.store.set_setting(CONFIG_KEY, {
            'enabled': True, 'timezone': 'Europe/Moscow',
            'slots': [{'weekday': 0, 'time': '12:00'}],
            'channel': {'id': -100123, 'title': 'TEST_ONLY channel', 'owner_id': 42,
                        'fingerprint': 'TEST_ONLY_fingerprint'}})
        self.run = fixtures.PublicationTests.complete(self)
        self.entry = self.publisher.prepare(self.run['id'])
        self.publisher.bind_preview(self.entry['id'], 91)

    def approve(self):
        return self.publisher.approve(self.entry['id'], self.entry['token'], 91,
                                      42, 'TEST_ONLY_fingerprint')

    def other_publisher(self):
        other = Publisher(Store(self.directory), self.bridge, self.builder, clock=lambda: self.now)
        other.lock = threading.RLock()
        return other

    def second_package(self):
        other = self.other_publisher()
        run = fixtures.PublicationTests.complete(self, 'two')
        entry = other.prepare(run['id'])
        other.bind_preview(entry['id'], 92)
        return other, entry

    def test_stale_other_publisher_cannot_erase_approved_queue(self):
        other_store = Store(self.directory)
        other = Publisher(other_store, self.bridge, self.builder, clock=lambda: self.now)
        # Distinct processes have independent in-memory locks, sharing SQLite only.
        other.lock = threading.RLock()
        self.assertIsNot(self.publisher.lock, other.lock)
        current, stale = self.publisher._entries(), other._entries()
        self.assertEqual(current, stale)
        approved = self.approve()
        saved = self.store.get_setting(QUEUE_KEY)
        self.assertEqual(approved['status'], 'queued')
        stale[self.entry['id']]['preview_message_id'] = 92
        with self.assertRaises(RuntimeError):
            other._save(stale)
        self.assertEqual(other_store.get_setting(QUEUE_KEY), saved)
        self.assertEqual(saved[self.entry['id']]['state'], 'queued')
        self.assertEqual(saved[self.entry['id']]['due_at'], approved['due_at'])
        self.assertEqual(self.bridge.calls, [])

    def test_approved_exact_slot_survives_new_sqlite_store_and_publisher(self):
        approved = self.approve()
        self.assertEqual(approved['due_at'], '2026-10-19T09:00:00+00:00')
        persisted = self.store.get_setting(QUEUE_KEY)
        reopened = Store(self.directory)
        restarted = Publisher(reopened, self.bridge, self.builder, clock=lambda: self.now)
        self.assertEqual(reopened.get_setting(QUEUE_KEY), persisted)
        visible = next(item for item in restarted.status()['items']
                       if item['id'] == self.entry['id'])
        for field in ('approved_at', 'due_at', 'package_sha256', 'post_text', 'status'):
            self.assertEqual(visible[field], approved[field])
        self.assertEqual(self.bridge.calls, [])

    def test_failed_or_noop_store_cannot_claim_successful_approval(self):
        before = self.store.get_setting(QUEUE_KEY)
        for cas_result in (False, True):
            with self.subTest(cas_result=cas_result):
                self.store.set_setting(QUEUE_KEY, deepcopy(before))
                with patch.object(self.store, 'compare_and_set_setting', create=True,
                                  return_value=cas_result) as write:
                    with self.assertRaises(RuntimeError):
                        self.approve()
                write.assert_called()
                self.assertEqual(self.store.get_setting(QUEUE_KEY), before)
                self.assertEqual(self.publisher.status()['items'][0]['status'], 'awaiting_owner')
        self.assertEqual(self.bridge.calls, [])

    def test_repeated_valid_approval_keeps_exact_slot_and_all_persisted_fields(self):
        first = self.approve()
        before = self.store.get_setting(QUEUE_KEY)
        self.now += timedelta(days=8)
        second = self.approve()
        self.assertEqual(second, first)
        self.assertEqual(self.store.get_setting(QUEUE_KEY), before)
        self.assertEqual(self.bridge.calls, [])

    def test_valid_repreview_click_preserves_original_approval_and_slot(self):
        first = self.approve()
        original = self.store.get_setting(QUEUE_KEY)[self.entry['id']]
        self.now += timedelta(minutes=5)
        self.publisher.bind_preview(self.entry['id'], 93)
        before = self.store.get_setting(QUEUE_KEY)
        result = self.publisher.approve(self.entry['id'], self.entry['token'], 93,
                                        42, 'TEST_ONLY_fingerprint')
        saved = self.store.get_setting(QUEUE_KEY)
        self.assertEqual(result['status'], 'queued')
        self.assertEqual(saved, before)
        entry = saved[self.entry['id']]
        self.assertEqual(entry['preview_message_id'], 93)
        self.assertEqual(entry['approved_message_id'], original['approved_message_id'])
        self.assertEqual(entry['approved_message_id'], 91)
        self.assertEqual(result['approved_at'], first['approved_at'])
        self.assertEqual(result['due_at'], first['due_at'])
        self.assertEqual(self.bridge.calls, [])

    def test_invalid_callbacks_leave_approved_queue_unchanged(self):
        self.approve()
        before = self.store.get_setting(QUEUE_KEY)
        callbacks = [
            (self.entry['id'], 'TEST_ONLY_wrong_token', 91, 42, 'TEST_ONLY_fingerprint'),
            (self.entry['id'], self.entry['token'], 92, 42, 'TEST_ONLY_fingerprint'),
            (self.entry['id'], self.entry['token'], 91, 43, 'TEST_ONLY_fingerprint'),
            (self.entry['id'], self.entry['token'], 91, 42, 'TEST_ONLY_other_fingerprint'),
            ('TEST_ONLY_missing', self.entry['token'], 91, 42, 'TEST_ONLY_fingerprint')]
        for callback in callbacks:
            with self.subTest(callback=callback), self.assertRaises(ValueError):
                self.publisher.approve(*callback)
            self.assertEqual(self.store.get_setting(QUEUE_KEY), before)
        self.assertEqual(self.bridge.calls, [])

    def test_channel_race_preserves_concurrent_approval_and_original_target(self):
        other = self.other_publisher()
        original_queue = self.store.get_setting(QUEUE_KEY)
        original_config = self.store.get_setting(CONFIG_KEY)
        read_entries, api = self.publisher._entries, self.bridge._api
        for variant, target in [('title', -100123), ('target', -100999)]:
            with self.subTest(variant=variant):
                self.store.set_setting(QUEUE_KEY, deepcopy(original_queue))
                saved = []

                def approve_after_snapshot():
                    stale = read_entries()
                    other.approve(self.entry['id'], self.entry['token'], 91,
                                  42, 'TEST_ONLY_fingerprint')
                    saved.append(self.store.get_setting(QUEUE_KEY))
                    return stale

                def channel_api(token, method, payload):
                    response = api(token, method, payload)
                    if method == 'getChat':
                        response['title'] = 'TEST_ONLY changed title'
                    return response

                with patch.object(self.publisher, '_entries', side_effect=approve_after_snapshot), \
                        patch.object(self.bridge, '_api', side_effect=channel_api):
                    with self.assertRaises(QueueConflict):
                        self.publisher.connect_channel(target)
                self.assertEqual(len(saved), 1)
                self.assertEqual(self.store.get_setting(QUEUE_KEY), saved[0])
                self.assertEqual(saved[0][self.entry['id']]['state'], 'queued')
                self.assertEqual(self.store.get_setting(CONFIG_KEY), original_config)
        self.assertEqual([method for method, _ in self.bridge.calls],
                         ['getChat', 'getChatMember', 'getChat', 'getChatMember'])

    def test_send_conflict_keeps_other_approval_and_receipt_without_retry(self):
        other, second = self.second_package()
        self.approve()
        self.now += timedelta(hours=1)
        api, concurrent = self.bridge._api, []

        def approve_during_send(token, method, payload):
            response = api(token, method, payload)
            if method == 'sendMessage':
                other.approve(second['id'], second['token'], 92, 42, 'TEST_ONLY_fingerprint')
                concurrent.append(deepcopy(self.store.get_setting(QUEUE_KEY)[second['id']]))
            return response

        with patch.object(self.bridge, '_api', side_effect=approve_during_send):
            self.publisher.tick()
        saved = self.store.get_setting(QUEUE_KEY)
        first = saved[self.entry['id']]
        self.assertEqual(first['state'], 'publication_uncertain')
        self.assertEqual(len(concurrent), 1)
        self.assertEqual(saved[second['id']], concurrent[0])
        self.assertEqual(saved[second['id']]['state'], 'queued')
        self.assertTrue(saved[second['id']]['approved_at'])
        self.assertTrue(saved[second['id']]['due_at'])
        self.assertEqual([method for method, _ in self.bridge.calls], ['sendMessage'])
        self.assertEqual(len(first['receipts']), 1)
        self.assertEqual(first['receipts'][0]['method'], 'sendMessage')
        self.assertEqual(first['receipts'][0]['message_id'], 1001)
        restarted = self.other_publisher()
        self.publisher.tick()
        restarted.tick()
        self.assertEqual(self.store.get_setting(QUEUE_KEY), saved)
        self.assertEqual([method for method, _ in self.bridge.calls], ['sendMessage'])

    def test_local_cas_retry_reads_new_queue_and_preserves_other_approval(self):
        other, second = self.second_package()
        cas, concurrent, attempts = self.store.compare_and_set_setting, [], []

        def race_once(key, expected, value):
            attempts.append(deepcopy(expected))
            if len(attempts) == 1:
                other.approve(second['id'], second['token'], 92, 42, 'TEST_ONLY_fingerprint')
                concurrent.append(deepcopy(self.store.get_setting(QUEUE_KEY)[second['id']]))
            return cas(key, expected, value)

        with patch.object(self.store, 'compare_and_set_setting', side_effect=race_once):
            result = self.approve()
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0][second['id']]['state'], 'awaiting_owner')
        self.assertEqual(attempts[1][second['id']], concurrent[0])
        saved = self.store.get_setting(QUEUE_KEY)
        self.assertEqual(saved[second['id']], concurrent[0])
        self.assertEqual(result['status'], 'queued')
        self.assertNotEqual(saved[self.entry['id']]['due_at'], saved[second['id']]['due_at'])
        self.assertEqual(self.bridge.calls, [])


if __name__ == '__main__':
    unittest.main()
