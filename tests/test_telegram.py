import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from laboratory.core import Store
from laboratory.telegram import TelegramBridge, TelegramError, _dpapi, import_telegram


TOKEN = "123456789:" + "A" * 35


class MemoryStore:
    def __init__(self):
        self.settings, self.sources, self.events = {}, [], []
        self.fail_source = False

    def get_setting(self, key, default=None):
        return self.settings.get(key, default)

    def set_setting(self, key, value):
        self.events.append(("setting", key))
        self.settings[key] = value

    def add_source(self, **source):
        if self.fail_source:
            raise RuntimeError("storage unavailable")
        self.events.append(("source", source["text"]))
        old = next((row for row in self.sources if row["text"] == source["text"]), None)
        if old:
            return old, False
        self.sources.append(source)
        return source, True


class ImportTests(unittest.TestCase):
    def test_mixed_text_links_provenance_dedup_and_skip(self):
        store = MemoryStore()
        message = {"id": 12, "type": "message", "date": "2026-10-20T16:00:00", "forwarded_from": "AI paper",
                   "text": ["RAG: ", {"type": "bold", "text": "evidence"}, " ", {"type": "text_link", "text": "paper", "href": "https://example.org/paper"}]}
        export = {"id": 99, "type": "saved_messages", "messages": [message, {"id": 13, "type": "service"}]}
        self.assertEqual(import_telegram(export, store), {"imported": 1, "duplicates": 0, "skipped": 1})
        row = store.sources[0]
        self.assertIn("RAG: evidence paper (https://example.org/paper)", row["text"])
        self.assertEqual(row["url"], "https://example.org/paper")
        self.assertEqual(row["origin"]["raw"], message)
        self.assertEqual(row["origin"]["chat_id"], 99)
        self.assertEqual(len(row["origin"]["raw_sha256"]), 64)
        self.assertEqual(import_telegram(export, store)["duplicates"], 1)

    def test_full_export_imports_only_saved_messages(self):
        store = MemoryStore()
        export = {"chats": {"list": [{"type": "personal_chat", "name": "Private", "messages": [{"text": "secret"}]},
                                      {"type": "saved_messages", "messages": [{"text": "AI study"}]}]}}
        self.assertEqual(import_telegram(export, store)["imported"], 1)
        self.assertEqual([row["text"] for row in store.sources], ["AI study"])
        with self.assertRaises(TelegramError):
            import_telegram({"type": "personal_chat", "messages": [{"text": "private"}]}, store)

    def test_unread_attachment_and_bot_text_link(self):
        store = MemoryStore()
        export = {"messages": [{"id": 1, "caption": "Read this", "document": {"file_name": "paper.pdf"},
                                "caption_entities": [{"type": "text_link", "url": "https://example.org"}]}]}
        import_telegram(export, store)
        self.assertIn("Содержимое файла не прочитано", store.sources[0]["text"])
        self.assertTrue(store.sources[0]["origin"]["attachment_unread"])
        self.assertEqual(store.sources[0]["url"], "https://example.org")

    def test_limits_do_not_silently_truncate_or_partially_import_large_batch(self):
        store = MemoryStore()
        self.assertEqual(import_telegram({"messages": [{"text": "x" * 50001}]}, store)["skipped"], 1)
        with self.assertRaises(TelegramError):
            import_telegram({"messages": [{"text": "AI"}] * 10001}, store)
        self.assertEqual(store.sources, [])


class BridgeTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parent / ".tmp"
        temp_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_root)
        self.addCleanup(self.temp.cleanup)
        self.store = MemoryStore()
        self.calls, self.updates = [], []
        self.webhook = ""

        def transport(token, method, payload):
            self.calls.append((method, payload))
            if method == "getMe":
                return {"id": 77, "is_bot": True, "username": "test_lab_bot"}
            if method == "getWebhookInfo":
                return {"url": self.webhook}
            if method == "getUpdates":
                return self.updates
            return {}

        self.bridge = TelegramBridge(self.store, self.temp.name, transport=transport)
        self.addCleanup(self.bridge.stop)

    def configure(self):
        with patch("laboratory.telegram._dpapi", side_effect=lambda data, decrypt=False: b"encrypted-test-data"):
            return self.bridge.configure(TOKEN)

    @staticmethod
    def message(sender, text, update_id=1, private=True):
        return {"update_id": update_id, "message": {"message_id": update_id, "date": 100,
                "chat": {"id": sender, "type": "private" if private else "group"},
                "from": {"id": sender, "is_bot": False}, "text": text}}

    def pair(self):
        status = self.configure()
        self.bridge._handle_update(TOKEN, self.message(42, "/start " + status["pairing_code"]))

    def test_pairing_is_explicit_private_and_owner_only(self):
        status = self.configure()
        self.assertNotIn(TOKEN, json.dumps(status))
        self.assertIsNone(self.bridge._handle_update(TOKEN, self.message(8, "/start wrong")))
        self.assertIsNone(self.bridge._handle_update(TOKEN, self.message(8, "Привет, лаборатория")))
        self.assertIsNone(self.bridge._handle_update(TOKEN, self.message(8, "/start " + status["pairing_code"], private=False)))
        self.assertIsNone(self.bridge.status()["owner_id"])
        reply = self.bridge._handle_update(TOKEN, self.message(42, "/start " + status["pairing_code"]))
        self.assertEqual(reply[0], 42)
        self.assertEqual(self.bridge.status()["owner_id"], 42)
        self.assertEqual(self.bridge.status()["pairing_code"], "")
        self.assertIsNone(self.bridge._handle_update(TOKEN, self.message(8, "Research secret")))
        self.bridge._handle_update(TOKEN, self.message(42, "Research AI agents", 2))
        self.assertEqual(len(self.store.sources), 1)
        self.assertEqual(self.store.sources[0]["origin"]["kind"], "telegram_bot")
        self.assertFalse(any(method not in {"getMe", "getWebhookInfo"} for method, _ in self.calls))

    def test_source_is_committed_before_offset_and_reply(self):
        self.pair()
        self.store.events.clear()
        self.updates = [self.message(42, "AI claim", 15)]
        self.bridge._poll_once(TOKEN, self.bridge._config)
        self.assertEqual(self.store.events[0][0], "source")
        self.assertEqual(self.store.events[1][0], "setting")
        self.assertEqual(self.store.get_setting("telegram_offset_" + self.bridge._fingerprint(TOKEN)), 16)
        self.assertEqual(self.calls[-1][0], "sendMessage")
        self.bridge._poll_once(TOKEN, self.bridge._config)
        self.assertEqual(len(self.store.sources), 1)

    def test_failed_storage_does_not_acknowledge_update(self):
        self.pair()
        self.store.fail_source = True
        self.updates = [self.message(42, "AI claim", 20)]
        with self.assertRaises(RuntimeError):
            self.bridge._poll_once(TOKEN, self.bridge._config)
        self.assertEqual(self.store.get_setting("telegram_offset_" + self.bridge._fingerprint(TOKEN), 0), 0)

    def test_webhook_is_not_removed_and_errors_do_not_expose_token(self):
        self.webhook = "https://example.org/existing"
        with self.assertRaisesRegex(TelegramError, "webhook"):
            self.configure()
        self.assertFalse(self.bridge.status()["configured"])
        self.assertNotIn("deleteWebhook", [method for method, _ in self.calls])

        def fail(*args):
            raise RuntimeError("https://api.telegram.org/bot" + TOKEN + "/getMe")

        self.bridge._transport = fail
        with self.assertRaises(TelegramError) as caught:
            self.bridge.configure(TOKEN)
        self.assertNotIn(TOKEN, str(caught.exception))

    def test_disconnect_clears_token_and_owner(self):
        self.pair()
        status = self.bridge.disconnect()
        self.assertFalse(status["configured"])
        self.assertIsNone(status["owner_id"])
        self.assertFalse((Path(self.temp.name) / ".telegram-token.dpapi").exists())

    def test_replayed_old_update_does_not_move_offset_backwards(self):
        self.pair()
        key = "telegram_offset_" + self.bridge._fingerprint(TOKEN)
        self.store.set_setting(key, 40)
        self.updates = [self.message(42, "Already acknowledged", 20)]
        self.bridge._poll_once(TOKEN, self.bridge._config)
        self.assertEqual(self.store.get_setting(key), 40)
        self.assertEqual(self.store.sources, [])

    def test_unsafe_url_preserves_raw_and_does_not_poison_real_store_intake(self):
        data_dir = Path(self.temp.name) / "real-store"
        store = Store(data_dir)
        bridge = TelegramBridge(store, data_dir, transport=self.bridge._transport)
        self.addCleanup(bridge.stop)
        with patch("laboratory.telegram._dpapi", side_effect=lambda data, decrypt=False: b"encrypted-test-data"):
            status = bridge.configure(TOKEN)
        bridge._handle_update(TOKEN, self.message(42, "/start " + status["pairing_code"]))
        offset_key = "telegram_offset_" + bridge._fingerprint(TOKEN)

        unsafe = self.message(42, "ИИ https://user:pass@example.com", 40)
        self.updates = [unsafe]
        bridge._poll_once(TOKEN, bridge._config)
        self.assertEqual(store.get_setting(offset_key), 41)
        stored_unsafe = store.sources()[0]
        self.assertEqual(stored_unsafe["text"], unsafe["message"]["text"])
        self.assertEqual(stored_unsafe["url"], "")
        self.assertEqual(stored_unsafe["origins"][0]["raw"], unsafe["message"])

        following = self.message(42, "Следующее исследование ИИ https://example.org/paper", 41)
        self.updates = [following]
        bridge._poll_once(TOKEN, bridge._config)
        self.assertEqual(store.get_setting(offset_key), 42)
        rows = store.sources()
        self.assertEqual(len(rows), 2)
        stored_following = next(row for row in rows if row["text"] == following["message"]["text"])
        self.assertEqual(stored_following["url"], "https://example.org/paper")
        self.assertEqual(stored_following["origins"][0]["raw"], following["message"])
        poll_calls = [payload for method, payload in self.calls if method == "getUpdates"]
        self.assertEqual(poll_calls[-1]["offset"], 41)

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI")
    def test_restart_restores_protected_dummy_token_and_same_owner(self):
        self.bridge.configure(TOKEN)
        code = self.bridge.status()["pairing_code"]
        self.bridge._handle_update(TOKEN, self.message(42, "/start " + code))
        encrypted = (Path(self.temp.name) / ".telegram-token.dpapi").read_bytes()
        self.assertNotIn(TOKEN.encode(), encrypted)
        restored = TelegramBridge(self.store, self.temp.name, transport=self.bridge._transport)
        self.assertTrue(restored.status()["configured"])
        self.assertEqual(restored.status()["owner_id"], 42)
        self.assertEqual(restored.status()["pairing_code"], "")
        self.assertNotIn(TOKEN, json.dumps(restored.status()))

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI")
    def test_dpapi_roundtrip_of_nonsecret_fixture(self):
        fixture = b"laboratory-test-fixture-not-a-credential"
        protected = _dpapi(fixture)
        self.assertNotEqual(protected, fixture)
        self.assertEqual(_dpapi(protected, decrypt=True), fixture)


if __name__ == "__main__":
    unittest.main()
