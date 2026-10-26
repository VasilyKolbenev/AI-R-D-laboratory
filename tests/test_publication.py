"""TEST_ONLY packages and Telegram transport; no models or external network."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from laboratory.core import Store
from laboratory.publication import Publisher, QUEUE_KEY, _next_slot


class FakeBridge:
    def __init__(self):
        self._lock = threading.RLock()
        self._token = 'TEST_ONLY_TOKEN'
        self._config = {'owner_id': 42, 'token_fingerprint': 'TEST_ONLY_fingerprint', 'bot_id': 777}
        self.calls = []
        self.fail = None
        self.channel_type = 'channel'
        self.may_post = True

    def _api(self, token, method, payload):
        self.calls.append((method, copy.deepcopy(payload)))
        if method == self.fail:
            raise OSError('TEST_ONLY ambiguous transport')
        if method == 'getChat':
            return {'id': payload['chat_id'], 'type': self.channel_type, 'title': 'TEST_ONLY channel'}
        if method == 'getChatMember':
            return {'status': 'administrator', 'can_post_messages': self.may_post, 'user': {'id': self._config['bot_id']}}
        return {'message_id': 1000 + len(self.calls)}


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'data')
        self.bridge = FakeBridge()
        self.now = datetime(2026, 10, 19, 8, 0, tzinfo=timezone.utc)
        self.data = {'title': 'TEST_ONLY applied result', 'post_text': 'TEST_ONLY точный пост — 10 мс → 8 мс.',
                     'publication_checks': {'status': 'ready', 'numeric_data': 'supported'},
                     'publication_rules': {'version': 'TEST_ONLY_rules_v1'}, 'provenance': {'mode': 'model_structured'}}
        self.builder = lambda run: copy.deepcopy(self.data)
        for name, value in [('render_png', b'TEST_ONLY_PNG'), ('render_mp4', b'TEST_ONLY_MP4')]:
            mock = patch('laboratory.presentation.' + name, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)
        self.publisher = Publisher(self.store, self.bridge, self.builder, clock=lambda: self.now)
        self.run = self.complete()

    def complete(self, suffix='one'):
        source = self.store.add_source('TEST_ONLY AI material ' + suffix)[0]
        run = self.store.create_plan({'source_ids': [source['id']], 'question': 'TEST_ONLY применимость ИИ?'})
        self.store.approve(run['id'], run['plan_hash'], True, 'TEST_ONLY_command_' + suffix)
        self.store.trace.capture(self.store.run(run['id']))
        self.store.finish(run['id'], {'status': 'completed', 'text': 'TEST_ONLY saved source analysis ' + suffix,
                                     'raw': {'test_only': True}})
        return self.store.run(run['id'])

    def prepare(self, run=None):
        entry = self.publisher.prepare((run or self.run)['id'])
        self.publisher.bind_preview(entry['id'], 91)
        return entry

    def approve(self, entry):
        return self.publisher.approve(entry['id'], entry['token'], 91, 42, 'TEST_ONLY_fingerprint')

    def connect(self):
        self.publisher.connect_channel(-100123)
        self.publisher.configure({'enabled': True, 'slots': [{'weekday': 0, 'time': '12:00'}]})
        self.bridge.calls.clear()

    def test_defaults_and_settings_work_without_a_connected_bot(self):
        publisher = Publisher(self.store, object(), self.builder)
        status = publisher.status()
        self.assertFalse(status['enabled'])
        self.assertEqual(status['slots'], [])
        self.assertFalse(status['channel_configured'])
        publisher.configure({'slots': [{'weekday': 4, 'time': '12:00'}]})
        publisher.tick()
        self.assertEqual(self.bridge.calls, [])
        with self.assertRaises(ValueError):
            publisher.prepare(self.run['id'])

    def test_prepare_freezes_exact_assets_without_network_or_changing_research(self):
        before = self.store.run(self.run['id'], include_raw=True)
        entry = self.prepare()
        self.assertEqual(entry['post_text'], self.data['post_text'])
        self.assertEqual(self.publisher.assets(entry['id']), {'png': b'TEST_ONLY_PNG', 'mp4': b'TEST_ONLY_MP4'})
        self.assertEqual(self.publisher.prepare(self.run['id'])['id'], entry['id'])
        self.assertLessEqual(len('pub:' + entry['id'] + ':' + entry['token']), 64)
        self.assertEqual(self.bridge.calls, [])
        self.assertEqual(self.store.run(self.run['id'], include_raw=True), before)
        self.assertNotIn('token', self.publisher.status()['items'][0])

    def test_only_exact_owner_token_and_preview_message_can_approve(self):
        entry = self.prepare()
        bad = [('bad', 91, 42, 'TEST_ONLY_fingerprint'),
               (entry['token'], 90, 42, 'TEST_ONLY_fingerprint'),
               (entry['token'], 91, 43, 'TEST_ONLY_fingerprint'),
               (entry['token'], 91, 42, 'other_fingerprint')]
        for token, message, owner, fingerprint in bad:
            with self.subTest(owner=owner, message=message, token=token), self.assertRaises(ValueError):
                self.publisher.approve(entry['id'], token, message, owner, fingerprint)
        self.assertEqual(self.publisher.status()['items'][0]['status'], 'awaiting_owner')
        first = self.approve(entry)
        self.assertEqual(first['status'], 'queued')
        self.assertEqual(self.approve(entry)['approved_at'], first['approved_at'])
        self.publisher.tick(self.now + timedelta(days=30))
        self.assertEqual(self.bridge.calls, [])

    def test_channel_setup_cannot_silently_authorize_an_old_unbound_package(self):
        entry = self.prepare()
        self.approve(entry)
        self.connect()
        self.publisher.tick(self.now + timedelta(hours=1))
        self.assertEqual(self.bridge.calls, [])
        self.assertEqual(self.publisher.status()['items'][0]['status'], 'blocked')
        with self.assertRaises(ValueError):
            self.approve(entry)
        replacement = self.prepare()
        self.assertNotEqual(entry['package_sha256'], replacement['package_sha256'])
        self.assertEqual(self.approve(replacement)['status'], 'queued')

    def test_channel_verification_rejects_group_and_missing_posting_rights(self):
        for field, value in [('channel_type', 'supergroup'), ('may_post', False)]:
            setattr(self.bridge, field, value)
            with self.assertRaises(ValueError):
                self.publisher.connect_channel(-100123)
            self.bridge.channel_type, self.bridge.may_post = 'channel', True
        self.assertFalse(self.publisher.status()['channel_configured'])

    def test_schedule_sends_only_approved_exact_package_at_due_slot_once(self):
        self.connect()
        entry = self.prepare()
        self.publisher.tick(self.now + timedelta(hours=1))
        self.assertEqual(self.bridge.calls, [])
        approved = self.approve(entry)
        self.assertEqual(approved['due_at'], '2026-10-19T09:00:00+00:00')
        self.publisher.tick(self.now + timedelta(minutes=59))
        self.assertEqual(self.bridge.calls, [])
        self.now += timedelta(hours=1)
        self.publisher.tick()
        self.assertEqual([method for method, _ in self.bridge.calls], ['sendMessage', 'sendPhoto', 'sendAnimation'])
        self.assertEqual(self.bridge.calls[0][1]['text'], entry['post_text'])
        self.assertTrue(all(payload['chat_id'] == -100123 for _, payload in self.bridge.calls))
        self.assertEqual(self.bridge.calls[2][1]['_files']['animation'][1], b'TEST_ONLY_MP4')
        item = self.publisher.status()['items'][0]
        self.assertEqual(item['status'], 'published')
        self.assertEqual(len(item['receipts']), 3)
        self.publisher.tick()
        recovered = Publisher(self.store, self.bridge, self.builder, clock=lambda: self.now)
        recovered.tick()
        self.assertEqual(len(self.bridge.calls), 3)
        self.assertFalse(recovered.prepare(self.run['id'])['can_enqueue'])

    def test_unconfirmed_partial_send_stays_uncertain_after_restart_without_retry(self):
        self.connect()
        entry = self.prepare()
        self.approve(entry)
        self.bridge.fail = 'sendPhoto'
        self.now += timedelta(hours=1)
        self.publisher.tick()
        item = self.publisher.status()['items'][0]
        self.assertEqual(item['status'], 'publication_uncertain')
        self.assertEqual([receipt['method'] for receipt in item['receipts']], ['sendMessage'])
        recovered = Publisher(self.store, self.bridge, self.builder, clock=lambda: self.now)
        self.bridge.fail = None
        recovered.tick()
        self.assertEqual(len(self.bridge.calls), 2)
        self.assertFalse(recovered.prepare(self.run['id'])['can_enqueue'])

    def test_interrupted_intent_is_not_assumed_unsent(self):
        self.connect()
        entry = self.prepare()
        self.approve(entry)
        saved = self.store.get_setting(QUEUE_KEY)
        saved[entry['id']]['state'] = 'publishing'
        self.store.set_setting(QUEUE_KEY, saved)
        recovered = Publisher(self.store, self.bridge, self.builder, clock=lambda: self.now)
        self.now += timedelta(hours=1)
        recovered.tick()
        self.assertEqual(recovered.status()['items'][0]['status'], 'publication_uncertain')
        self.assertEqual(self.bridge.calls, [])

    def test_changed_post_rules_or_report_require_new_approval(self):
        for change in ('post', 'rules', 'report'):
            with self.subTest(change=change):
                # A fresh package for each change, with old blocked entries kept.
                self.connect()
                entry = self.prepare()
                self.approve(entry)
                if change == 'post':
                    self.data['post_text'] += ' TEST_ONLY changed'
                elif change == 'rules':
                    self.data['publication_rules']['version'] += '_changed'
                else:
                    with self.store.connect() as db:
                        db.execute('UPDATE runs SET output=output||? WHERE id=?', (' TEST_ONLY changed', self.run['id']))
                self.publisher.tick(self.now + timedelta(hours=1))
                self.assertEqual(self.bridge.calls, [])
                item = next(item for item in self.publisher.status()['items'] if item['id'] == entry['id'])
                self.assertEqual(item['status'], 'blocked')

    def test_cancel_revokes_approval_before_any_send(self):
        self.connect()
        entry = self.prepare()
        self.approve(entry)
        cancelled = self.publisher.cancel(entry['id'])
        self.assertEqual(cancelled['status'], 'cancelled')
        self.assertIsNone(cancelled['due_at'])
        self.publisher.tick(self.now + timedelta(hours=1))
        self.assertEqual(self.bridge.calls, [])
        with self.assertRaises(ValueError):self.approve(entry)

    def test_cancel_cannot_hide_an_uncertain_send(self):
        self.connect()
        entry = self.prepare()
        self.approve(entry)
        self.bridge.fail = 'sendPhoto'
        self.publisher.tick(self.now + timedelta(hours=1))
        with self.assertRaises(ValueError):self.publisher.cancel(entry['id'])
        self.assertEqual(self.publisher.status()['items'][0]['status'], 'publication_uncertain')

    def test_oversized_manifest_is_rejected_before_parsing_or_network(self):
        entry = self.prepare()
        (self.store.data_dir / 'publications' / entry['id'] / 'manifest.json').write_bytes(b'x' * 65537)
        with self.assertRaises(ValueError):self.publisher.assets(entry['id'])
        self.assertEqual(self.bridge.calls, [])

    def test_tampered_file_is_blocked_before_any_network_request(self):
        self.connect()
        entry = self.prepare()
        self.approve(entry)
        (self.store.data_dir / 'publications' / entry['id'] / 'animation.mp4').write_bytes(b'TEST_ONLY_TAMPERED')
        self.publisher.tick(self.now + timedelta(hours=1))
        self.assertEqual(self.publisher.status()['items'][0]['status'], 'blocked')
        self.assertEqual(self.bridge.calls, [])

    def test_disconnected_owner_or_replaced_bot_cannot_publish(self):
        self.connect()
        entry = self.prepare()
        self.approve(entry)
        self.bridge._config['token_fingerprint'] = 'TEST_ONLY_replaced'
        self.publisher.tick(self.now + timedelta(hours=1))
        self.assertEqual(self.publisher.status()['items'][0]['status'], 'blocked')
        self.assertEqual(self.bridge.calls, [])

    def test_offline_missed_slot_moves_to_future_instead_of_burst(self):
        self.connect()
        entry = self.prepare()
        self.approve(entry)
        self.now += timedelta(hours=2)
        self.publisher.tick()
        self.assertEqual(self.bridge.calls, [])
        self.assertEqual(self.publisher.status()['items'][0]['due_at'], '2026-10-26T09:00:00+00:00')

    def test_distinct_queue_items_reserve_distinct_slots(self):
        self.connect()
        first = self.approve(self.prepare())
        second = self.approve(self.prepare(self.complete('two')))
        self.assertNotEqual(first['due_at'], second['due_at'])
        self.assertEqual(second['due_at'], '2026-10-26T09:00:00+00:00')

    def test_two_concurrent_ticks_dispatch_one_package_only(self):
        self.connect()
        self.approve(self.prepare())
        other = Publisher(self.store, self.bridge, self.builder, clock=lambda: self.now)
        self.now += timedelta(hours=1)
        barrier = threading.Barrier(2)
        def tick(publisher):
            barrier.wait()
            publisher.tick()
        threads = [threading.Thread(target=tick, args=(publisher,)) for publisher in (self.publisher, other)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(timeout=5)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(len(self.bridge.calls), 3)

    def test_invalid_schedule_and_channel_injection_are_rejected(self):
        bad = [{'channel': {'id': -100123}}, {'enabled': 1}, {'timezone': 'UTC'},
               {'slots': [{'weekday': True, 'time': '12:00'}]}, {'slots': [{'weekday': 7, 'time': '12:00'}]},
               {'slots': [{'weekday': 0, 'time': '24:00'}]}, {'slots': [{'weekday': 0, 'time': '12:0'}]}]
        for body in bad:
            with self.subTest(body=body), self.assertRaises(ValueError):
                self.publisher.configure(body)

    def test_moscow_calendar_and_year_boundary_keep_utc_plus_three(self):
        slots = [{'weekday': 4, 'time': '00:15'}]
        # Friday midnight Moscow is still Thursday in UTC, in winter and summer.
        for after, expected in [(datetime(2026, 12, 31, 20, tzinfo=timezone.utc), '2026-12-31T21:15:00+00:00'),
                                (datetime(2026, 7, 2, 20, tzinfo=timezone.utc), '2026-07-02T21:15:00+00:00')]:
            self.assertEqual(_next_slot(after, slots), expected)

    def test_incomplete_compacted_or_missing_media_never_creates_approval(self):
        for change in ('incomplete', 'compacted', 'oversize', 'missing'):
            original = copy.deepcopy(self.data)
            with self.subTest(change=change):
                if change == 'incomplete':self.data['publication_checks']['status'] = 'incomplete'
                elif change == 'compacted':self.data['post_compacted'] = True
                elif change == 'oversize':self.data['post_text'] = 'x' * 3501
                else:
                    with patch('laboratory.presentation.render_mp4', return_value=None), self.assertRaises(ValueError):
                        self.publisher.prepare(self.run['id'])
                    continue
                with self.assertRaises(ValueError):self.publisher.prepare(self.run['id'])
            self.data = original
        self.assertEqual(self.publisher.status()['items'], [])
        self.assertEqual(self.bridge.calls, [])


if __name__ == '__main__':
    unittest.main()
