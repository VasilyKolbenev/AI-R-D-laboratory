"""Exact request and lesson integration. No real provider or Telegram calls."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from laboratory.core import Store, canonical, digest, research_prompt
from laboratory.server import Laboratory
from laboratory import trace
from test_core import NoTelegram


class TraceFlowTests(unittest.TestCase):
    def setUp(self):
        tmp = Path(__file__).parent / ".tmp"
        tmp.mkdir(exist_ok=True)
        self.temp = TemporaryDirectory(dir=tmp)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "data")
        self.source = self.store.add_source("TEST_ONLY: ИИ память RAG", "Исходник")[0]

    def tearDown(self):
        self.temp.cleanup()

    def plan(self, **values):
        return self.store.create_plan({"source_ids": [self.source["id"]], "question": "Проверь ИИ память RAG", **values})

    def evidence(self):
        run = self.plan()
        self.store.approve(run["id"], run["plan_hash"], True, "trace-evidence-command")
        self.store.finish(run["id"], {"status": "completed", "text": "TEST_ONLY исходный анализ источников"})
        finding = self.store.save_finding(run["id"], {"title": "Исходный анализ"})
        return run, finding

    def lesson(self):
        run, finding = self.evidence()
        body = self.store.lessons.schema()["template"]
        body.update(title="Урок RAG", problem="Память ИИ может обобщить лишнее", rule="UNIQUE_LESSON_RULE: проверять область применимости памяти RAG",
                    evidence_note="Отчёт анализирует источник; эффективность урока не измерена", applies_when="Повторное применение вывода RAG",
                    not_applicable_when="Иной домен или изменённый набор данных", limitations="Гипотеза, а не результат эксперимента",
                    review_at=(datetime.now(timezone.utc)+timedelta(days=30)).date().isoformat(),
                    evidence_run_id=run["id"], knowledge_id=finding["id"], evidence_source_ids=[self.source["id"]], evidence_level="source_analysis")
        return self.store.lessons.save({"body": body, "status": "active"})

    def test_exact_context_exists_before_approval_and_prompt_hash_matches(self):
        run = self.plan()
        record = self.store.trace.get(run["id"])
        self.assertEqual(record["status"], "prepared")
        self.assertEqual(record["prompt"], research_prompt(run["plan"]))
        self.assertEqual(record["prompt_sha256"], trace.sha(record["prompt"]))
        self.assertIn("Hidden provider/CLI", record["manifest"]["coverage"])
        self.assertIsNone(record["manifest"]["actual_model"])
        self.assertNotIn("environment", record["manifest"])

    def test_context_record_is_saved_before_one_fake_executor_call(self):
        calls = []
        app = None
        def runner(plan, prompt, directory, cancel):
            record = app.store.trace.get(run["id"])
            self.assertEqual(record["status"], "captured")
            self.assertEqual(record["prompt"], prompt)
            calls.append(prompt)
            return {"status": "completed", "text": "TEST_ONLY completed"}
        app = Laboratory(self.root / "server", runner=runner, telegram_factory=NoTelegram)
        try:
            source = app.store.add_source("TEST_ONLY ИИ материал")[0]
            run = app.store.create_plan({"source_ids": [source["id"]]})
            consent = {"consent": True, "plan_hash": run["plan_hash"], "command_id": "trace-one-command"}
            app.start_run(run["id"], consent)
            until = time.monotonic()+3
            while app.jobs and time.monotonic()<until:
                time.sleep(.01)
            self.assertEqual(len(calls), 1)
            self.assertEqual(app.store.run(run["id"])["status"], "completed")
            app.start_run(run["id"], consent)
            self.assertEqual(len(calls), 1)
        finally:
            app.close()

    def test_changed_local_configuration_requires_new_approval(self):
        run = self.plan()
        changed = trace.descriptor(run["plan"])
        changed["template_version"] = "different"
        with patch("laboratory.trace.descriptor", return_value=changed):
            with self.assertRaises(ValueError):
                self.store.approve(run["id"], run["plan_hash"], True, "trace-changed-command")
        self.assertEqual(self.store.run(run["id"])["status"], "planned")

    def test_lesson_exclusion_removes_it_from_exact_prompt_and_edit_invalidates_approval(self):
        lesson = self.lesson()
        run = self.plan(memory_options={"lesson_ids": [lesson["id"]]})
        self.assertIn("UNIQUE_LESSON_RULE", research_prompt(run["plan"]))
        excluded = self.plan(memory_options={"lesson_ids": [], "selected_ids": []})
        self.assertNotIn("UNIQUE_LESSON_RULE", research_prompt(excluded["plan"]))
        body = copy.deepcopy(lesson["body"])
        body["rule"] = "UNIQUE_UPDATED_RULE"
        self.store.lessons.save({"id": lesson["id"], "expected_version": 1, "body": body})
        self.assertIn("UNIQUE_LESSON_RULE", research_prompt(self.store.run(run["id"])["plan"]))
        with self.assertRaises(ValueError):
            self.store.approve(run["id"], run["plan_hash"], True, "trace-lesson-edit")
        rebuilt = self.store.replan_memory(run["id"], {})
        self.assertIn("UNIQUE_UPDATED_RULE", research_prompt(rebuilt["plan"]))
        self.assertNotEqual(rebuilt["plan_hash"], run["plan_hash"])

    def test_legacy_context_is_not_reconstructed_as_historical_original(self):
        run, _ = self.evidence()
        plan = copy.deepcopy(run["plan"])
        plan.pop("execution_context")
        with self.store.connect() as db:
            db.execute("UPDATE runs SET plan=?,plan_hash=? WHERE id=?", (canonical(plan), digest(plan), run["id"]))
        record = self.store.trace.get(run["id"])
        self.assertEqual(record["status"], "legacy_unavailable")
        self.assertEqual(record["prompt"], "")

    def test_schema_four_roundtrip_keeps_context_and_lesson_history(self):
        lesson = self.lesson()
        run = self.plan(memory_options={"lesson_ids": [lesson["id"]]})
        self.store.approve(run["id"], run["plan_hash"], True, "trace-roundtrip-command")
        self.store.trace.capture(self.store.run(run["id"]))
        self.store.finish(run["id"], {"status": "completed", "text": "TEST_ONLY scoped result"})
        self.store.lessons.save({"id": lesson["id"], "expected_version": 1, "status": "retired"})
        backup = self.store.export()
        self.assertEqual(backup["schema_version"], 7)
        destination = Store(self.root / "restored")
        destination.restore(backup)
        self.assertEqual(destination.trace.get(run["id"])["prompt"], self.store.trace.get(run["id"])["prompt"])
        self.assertEqual(len(destination.lessons.get(lesson["id"])["history"]), 2)

    def test_corrupt_dispatch_context_backup_rolls_back_all_data(self):
        run = self.plan()
        self.store.approve(run["id"], run["plan_hash"], True, "trace-corrupt-command")
        self.store.trace.capture(self.store.run(run["id"]))
        self.store.finish(run["id"], {"status": "completed", "text": "TEST_ONLY result"})
        backup = self.store.export()
        body = json.loads(backup["tables"]["run_contexts"][0]["context"])
        body["prompt"] += " tampered"
        backup["tables"]["run_contexts"][0]["context"] = canonical(body)
        destination = Store(self.root / "corrupt")
        with self.assertRaises(ValueError):
            destination.restore(backup)
        self.assertEqual(destination.counts()["runs"], 0)

    def test_legacy_three_preserves_old_plan_hash_without_fabricating_context(self):
        run = self.plan()
        backup = self.store.export()
        backup["schema_version"] = 3
        backup["tables"].pop("agent_phases")
        backup['tables'].pop('research_assets')
        backup['tables'].pop('research_asset_claims')
        backup["tables"].pop("research_review_revisions")
        backup["tables"].pop("lesson_revisions")
        backup["tables"].pop("run_contexts")
        row = backup["tables"]["runs"][0]
        plan = json.loads(row["plan"])
        plan.pop("execution_context")
        row["plan"], row["plan_hash"] = canonical(plan), digest(plan)
        destination = Store(self.root / "v3")
        destination.restore(backup)
        self.assertEqual(destination.run(run["id"])["plan_hash"], row["plan_hash"])
        self.assertEqual(destination.trace.get(run["id"])["status"], "legacy_unavailable")


if __name__ == "__main__":
    unittest.main()
