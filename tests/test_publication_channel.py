"""TEST_ONLY channel resolution and localhost API; no Telegram or model calls."""
import copy
from datetime import datetime, timezone
from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from laboratory.core import Store
from laboratory.publication import Publisher, CONFIG_KEY, QUEUE_KEY
from laboratory.server import Laboratory, LocalServer, Handler
import test_publication as fixtures


class FakeChannelBridge(fixtures.FakeBridge):
    def __init__(self):
        super().__init__()
        self.chat = {'id': -100123, 'type': 'channel', 'title': 'TEST_ONLY VVFrontier', 'username': 'VVFrontier'}
        self.member = None

    def _api(self, token, method, payload):
        value = super()._api(token, method, payload)
        if method == 'getChat':return copy.deepcopy(self.chat)
        if method == 'getChatMember' and self.member is not None:return copy.deepcopy(self.member)
        return value

    def status(self):return {'configured': True, 'owner_id': 42}
    def stop(self):pass


class ChannelConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'data')
        self.bridge = FakeChannelBridge()
        self.now = datetime(2026, 10, 19, 8, tzinfo=timezone.utc)
        self.data = {'title': 'TEST_ONLY article', 'post_text': 'TEST_ONLY applied result',
                     'publication_checks': {'status': 'ready'}, 'publication_rules': {'version': 'TEST_ONLY_v1'}}
        self.publisher = Publisher(self.store, self.bridge, lambda run: copy.deepcopy(self.data), clock=lambda: self.now)
        for name, value in [('render_png', b'TEST_ONLY_PNG'), ('render_mp4', b'TEST_ONLY_MP4')]:
            render = patch('laboratory.presentation.' + name, return_value=value)
            render.start();self.addCleanup(render.stop)

    def queued(self):
        run = fixtures.PublicationTests.complete(self)
        entry = self.publisher.prepare(run['id'])
        self.publisher.bind_preview(entry['id'], 92)
        self.publisher.approve(entry['id'], entry['token'], 92, 42, 'TEST_ONLY_fingerprint')
        return entry

    def snapshot(self):
        return (self.store.get_setting(CONFIG_KEY), self.store.get_setting(QUEUE_KEY))

    def test_public_handle_resolves_once_to_numeric_channel_and_known_bot(self):
        result = self.publisher.connect_channel('@VVFrontier')
        self.assertTrue(result['channel_configured'])
        self.assertEqual(self.bridge.calls, [('getChat', {'chat_id': '@VVFrontier'}),
            ('getChatMember', {'chat_id': -100123, 'user_id': 777})])
        self.assertEqual(self.store.get_setting(CONFIG_KEY)['channel']['id'], -100123)
        self.assertFalse(result['enabled'])
        self.assertEqual(result['slots'], [])
        self.assertEqual(self.store.counts()['runs'], 0)

    def test_numeric_id_resolves_exactly_without_getme_or_secret_access(self):
        self.publisher.connect_channel(-100123)
        self.assertEqual([method for method, _ in self.bridge.calls], ['getChat', 'getChatMember'])

    def test_rejects_malformed_handles_and_ids_before_network(self):
        for channel in [None, True, False, 0, 42, '-100123', 'VVFrontier', '@abcd', '@' + 'x' * 33,
                        '@КаналИИ', '@VV Frontier', ' @VVFrontier', '@VVFrontier ', 'https://t.me/VVFrontier', [], {}]:
            with self.subTest(channel=channel), self.assertRaises(ValueError):
                self.publisher.connect_channel(channel)
        self.assertEqual(self.bridge.calls, [])
        self.assertFalse(self.publisher.status()['channel_configured'])

    def test_private_chat_group_and_forged_channel_ids_are_rejected(self):
        for changed in [{'type': 'private'}, {'type': 'supergroup'}, {'type': 'group'},
                        {'id': 100123}, {'id': '-100123'}, {'id': True}, {'id': -100999}]:
            original = copy.deepcopy(self.bridge.chat)
            self.bridge.chat.update(changed)
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.publisher.connect_channel(-100123)
            self.bridge.chat = original
            self.assertFalse(self.publisher.status()['channel_configured'])
        self.assertTrue(all(method == 'getChat' for method, _ in self.bridge.calls))

    def test_public_handle_requires_matching_primary_or_active_address(self):
        with self.assertRaises(ValueError):self.publisher.connect_channel('@OtherChannel')
        self.assertEqual(len(self.bridge.calls), 1)
        self.bridge.chat['active_usernames'] = ['OtherChannel']
        self.publisher.connect_channel('@otherchannel')
        self.assertTrue(self.publisher.status()['channel_configured'])

    def test_missing_or_forged_bot_identity_and_permissions_are_rejected(self):
        good = {'status': 'administrator', 'can_post_messages': True, 'user': {'id': 777}}
        for member in [{}, {**good, 'user': None}, {**good, 'user': {'id': 888}},
                       {**good, 'user': {'id': '777'}}, {**good, 'user': {'id': True}},
                       {**good, 'status': 'member'}, {**good, 'can_post_messages': False},
                       {**good, 'can_post_messages': 1}]:
            self.bridge.member = member
            with self.subTest(member=member), self.assertRaises(ValueError):
                self.publisher.connect_channel('@VVFrontier')
            self.assertFalse(self.publisher.status()['channel_configured'])

    def test_missing_known_bot_or_owner_is_rejected_before_network(self):
        for changed in [{'bot_id': None}, {'bot_id': True}, {'owner_id': None}, {'token_fingerprint': ''}]:
            previous = dict(self.bridge._config)
            self.bridge._config.update(changed)
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.publisher.connect_channel('@VVFrontier')
            self.bridge._config = previous
        self.assertEqual(self.bridge.calls, [])

    def test_verification_failure_keeps_existing_target_and_queue_exactly(self):
        self.publisher.connect_channel('@VVFrontier')
        self.queued()
        before = self.snapshot()
        self.bridge.chat.update(id=-100999, username='OtherChannel')
        for failed_method in ['getChat', 'getChatMember']:
            self.bridge.fail = failed_method
            with self.subTest(failed_method=failed_method), self.assertRaises(OSError):
                self.publisher.connect_channel('@OtherChannel')
            self.assertEqual(self.snapshot(), before)
        self.bridge.fail = None
        self.bridge.member = {'status': 'member', 'user': {'id': 777}}
        with self.assertRaises(ValueError):self.publisher.connect_channel('@OtherChannel')
        self.assertEqual(self.snapshot(), before)

    def test_same_verified_identity_and_display_rename_preserve_queue_approval(self):
        self.publisher.connect_channel('@VVFrontier')
        entry = self.queued()
        before = self.store.get_setting(QUEUE_KEY)
        self.publisher.connect_channel(-100123)
        self.assertEqual(self.store.get_setting(QUEUE_KEY), before)
        self.bridge.chat['title'] = 'TEST_ONLY new channel title'
        result = self.publisher.connect_channel('@VVFrontier')
        self.assertEqual(result['channel_title'], 'TEST_ONLY new channel title')
        self.assertEqual(self.store.get_setting(QUEUE_KEY), before)
        self.assertEqual(next(item for item in result['items'] if item['id'] == entry['id'])['status'], 'queued')

    def test_new_target_invalidates_old_queue_without_approving_or_posting(self):
        self.publisher.connect_channel('@VVFrontier')
        entry = self.queued()
        self.bridge.chat.update(id=-100999, username='OtherChannel')
        result = self.publisher.connect_channel('@OtherChannel')
        item = next(item for item in result['items'] if item['id'] == entry['id'])
        self.assertEqual(item['status'], 'blocked')
        self.assertIsNone(item['due_at'])
        self.assertEqual(self.store.get_setting(QUEUE_KEY)[entry['id']]['binding']['channel_id'], -100123)
        self.assertTrue(all(method in {'getChat', 'getChatMember'} for method, _ in self.bridge.calls))
        self.assertFalse(result['enabled'])


class ChannelHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.bridge = FakeChannelBridge()
        self.providers = []
        self.app = Laboratory(self.temp.name, runner=lambda *args: self.providers.append(args),
                              telegram_factory=lambda *args: self.bridge)
        self.server = LocalServer(('127.0.0.1', 0), Handler)
        self.server.app = self.app
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.app.close();self.thread.join();self.temp.cleanup()

    def request(self, body, csrf=True, origin=None):
        connection = HTTPConnection('127.0.0.1', self.server.server_port, timeout=4)
        headers = {'Content-Type': 'application/json'}
        if csrf:headers['X-Lab-Token'] = self.app.csrf
        if origin:headers['Origin'] = origin
        connection.request('POST', '/api/publication/channel', json.dumps(body), headers)
        response = connection.getresponse();status = response.status;raw = response.read();connection.close()
        return status, json.loads(raw)

    def test_channel_endpoint_requires_csrf_and_local_origin(self):
        body = {'channel': '@VVFrontier'}
        self.assertEqual(self.request(body, csrf=False)[0], 403)
        self.assertEqual(self.request(body, origin='https://external.example')[0], 403)
        self.assertEqual(self.bridge.calls, [])

    def test_channel_endpoint_resolves_only_and_never_runs_or_publishes(self):
        status, value = self.request({'channel': '@VVFrontier'})
        self.assertEqual(status, 200, value)
        self.assertTrue(value['channel_configured'])
        self.assertFalse(value['enabled'])
        self.assertEqual(value['slots'], [])
        self.assertEqual(value['items'], [])
        self.assertEqual([method for method, _ in self.bridge.calls], ['getChat', 'getChatMember'])
        self.app.publisher.tick()
        self.assertEqual(self.providers, [])
        self.assertEqual(self.app.store.counts()['runs'], 0)

    def test_extra_fields_and_malformed_targets_are_atomic_bad_requests(self):
        for body in [{}, {'channel': '@VVFrontier', 'enabled': True}, {'channel_id': -100123},
                     {'channel': True}, {'channel': 'https://t.me/VVFrontier'}]:
            with self.subTest(body=body):
                status, _ = self.request(body)
                self.assertEqual(status, 400)
        self.assertEqual(self.bridge.calls, [])
        self.assertFalse(self.app.publisher.status()['channel_configured'])


if __name__ == '__main__':
    unittest.main()
