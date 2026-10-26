from pathlib import Path
import copy
import json
import tempfile
import threading
import unittest

from laboratory.core import LabError, Store, digest, research_prompt
from laboratory.server import Laboratory
from laboratory.telegram import import_telegram


TMP = Path(__file__).parent / ".tmp"
TMP.mkdir(exist_ok=True)


class NoTelegram:
    def __init__(self, *args):
        pass

    def status(self):
        return {"configured": False, "owner_id": None, "status": "not_configured"}

    def stop(self):
        pass


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TMP)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "data")

    def tearDown(self):
        self.temp.cleanup()

    def source(self, text="Новая память для ИИ", **kwargs):
        return self.store.add_source(text, **kwargs)[0]

    def plan(self, source=None, **kwargs):
        source = source or self.source()
        return self.store.create_plan({"source_ids": [source["id"]], "question": "Какие доказательства есть?", **kwargs})

    def test_material_dedup_preserves_distinct_provenance_and_unicode(self):
        first, created = self.store.add_source("ИИ: память", origin={"kind": "manual"})
        again, duplicate = self.store.add_source("ИИ: память", origin={"kind": "telegram", "message_id": 12})
        self.assertTrue(created)
        self.assertFalse(duplicate)
        self.assertEqual(first["id"], again["id"])
        self.assertEqual(len(again["origins"]), 2)
        self.assertEqual(self.store.sources("ПАМЯТЬ")[0]["id"], first["id"])
        self.assertEqual(Store(self.root / "data").counts()["sources"], 1)

    def test_approval_is_exact_immutable_and_idempotent(self):
        run = self.plan()
        with self.assertRaises(LabError):
            self.store.approve(run["id"], "wrong", True, "command-0001")
        with self.assertRaises(LabError):
            self.store.approve(run["id"], run["plan_hash"], False, "command-0001")
        self.assertTrue(self.store.approve(run["id"], run["plan_hash"], True, "command-0001"))
        self.assertFalse(self.store.approve(run["id"], run["plan_hash"], True, "command-0001"))
        self.assertEqual(digest(self.store.run(run["id"])["plan"]), run["plan_hash"])

    def test_concurrent_approval_allows_only_one_dispatch(self):
        runs = [self.plan(self.source(str(i))) for i in range(2)]
        barrier = threading.Barrier(2)
        outcomes = []

        def start(index):
            barrier.wait()
            try:
                self.store.approve(runs[index]["id"], runs[index]["plan_hash"], True, f"command-{index:04d}")
                outcomes.append("approved")
            except LabError:
                outcomes.append("denied")

        threads = [threading.Thread(target=start, args=(i,)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertCountEqual(outcomes, ["approved", "denied"])

    def test_rolling_limit_includes_failed_and_unknown_attempts(self):
        self.store.update_settings({"daily_run_limit": 1})
        first, second = self.plan(), self.plan()
        self.store.approve(first["id"], first["plan_hash"], True, "command-first")
        self.store.finish(first["id"], {"status": "outcome_unknown", "error": "timeout"})
        with self.assertRaises(LabError):
            self.store.approve(second["id"], second["plan_hash"], True, "command-second")
        with self.assertRaises(LabError):
            self.store.save_finding(first["id"], {})

    def test_source_to_report_knowledge_backup_and_restore(self):
        calls = []

        def runner(plan, prompt, directory, cancel):
            calls.append(prompt)
            return {"status": "completed", "text": "# Вывод\nПамять модели требует независимой проверки.", "usage": {"output_tokens": 12}, "raw": {"fixture": True}}

        app = Laboratory(self.root / "data", runner=runner, telegram_factory=NoTelegram)
        run = self.plan()
        body = {"plan_hash": run["plan_hash"], "consent": True, "command_id": "command-flow"}
        app.start_run(run["id"], body)
        with app.lock:
            worker = app.jobs.get(run["id"])
        if worker:
            worker[1].join(3)
        app.start_run(run["id"], body)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.store.run(run["id"])["status"], "completed")
        finding = self.store.save_finding(run["id"], {"title": "Память ИИ", "tags": ["memory"]})
        self.assertEqual(self.store.knowledge("ПРОВЕРКИ")[0]["id"], finding["id"])
        backup = self.store.export()
        self.assertNotIn("settings", backup["tables"])
        destination = Store(self.root / "restore")
        self.assertEqual(destination.restore(backup)["knowledge"], 1)
        self.assertEqual(destination.knowledge()[0]["output"], finding["output"])
        with self.assertRaises(LabError):
            destination.restore(backup)
        app.close()

    def test_corrupt_backup_rolls_back_and_preserves_empty_destination(self):
        self.source()
        backup = self.store.export()
        backup["tables"]["sources"][0]["text"] += "tampered"
        destination = Store(self.root / "restore")
        with self.assertRaises(LabError):
            destination.restore(backup)
        self.assertEqual(destination.counts(), {"sources": 0, "runs": 0, "knowledge": 0})

    def test_malformed_nested_backup_json_is_rejected_before_commit(self):
        self.source()
        backup = self.store.export()
        backup["tables"]["origins"][0]["payload"] = "{broken"
        destination = Store(self.root / "restore")
        with self.assertRaises(ValueError):
            destination.restore(backup)
        self.assertEqual(destination.sources(), [])

    def test_tampered_saved_report_is_rejected(self):
        run = self.plan()
        self.store.approve(run["id"], run["plan_hash"], True, "command-backup")
        self.store.finish(run["id"], {"status": "completed", "text": "Сохранённый вывод"})
        self.store.save_finding(run["id"], {})
        backup = self.store.export()
        backup["tables"]["knowledge"][0]["output"] = "Подменённый вывод"
        destination = Store(self.root / "restore")
        with self.assertRaises(LabError):
            destination.restore(backup)
        self.assertEqual(destination.counts()["sources"], 0)

    def test_restart_does_not_repeat_unknown_external_run(self):
        run = self.plan()
        self.store.approve(run["id"], run["plan_hash"], True, "command-crash")
        calls = []
        app = Laboratory(self.root / "data", runner=lambda *args: calls.append(args), telegram_factory=NoTelegram)
        self.assertEqual(app.store.run(run["id"])["status"], "outcome_unknown")
        self.assertEqual(calls, [])
        app.close()

    def test_telegram_import_is_intake_only_and_preserves_rich_links(self):
        export = {"type": "saved_messages", "id": 12, "messages": [{"id": 1, "type": "message", "text": ["ИИ статья ", {"type": "text_link", "text": "paper", "href": "https://arxiv.org/abs/1234.56789"}]}]}
        self.assertEqual(import_telegram(export, self.store)["imported"], 1)
        self.assertEqual(import_telegram(export, self.store)["duplicates"], 1)
        self.assertEqual(self.store.counts()["runs"], 0)
        run = self.plan(self.store.sources()[0])
        prompt = research_prompt(run["plan"])
        self.assertIn("недоверенное", prompt)
        self.assertIn("Веб-поиск отключён", prompt)


if __name__ == "__main__":
    unittest.main()
