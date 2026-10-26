from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import uuid

from laboratory.core import Store
from laboratory.memory import Memory, TABLES, MAX_SNAPSHOT_CHARS, validate_backup_table, validate_backup


class MemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_root = Path(__file__).parent / ".tmp"
        cls.temp_root.mkdir(exist_ok=True)

    def setUp(self):
        self.temporary = TemporaryDirectory(dir=self.temp_root)
        self.store = Store(Path(self.temporary.name))
        self.memory = Memory(self.store)
        self.memory.initialize()

    def tearDown(self):
        self.temporary.cleanup()

    def source(self, text="ИИ память retrieval и долгосрочное хранение", title="Memory"):
        return self.store.add_source(text, title)[0]

    def finding(self, title="Memory retrieval", claim="Retrieval memory improves factual recall", notes="Нужна проверка", review_at=None):
        source = self.source(claim, title)
        run_id, knowledge_id = uuid.uuid4().hex, uuid.uuid4().hex
        plan = {"sources": [source], "memory": self.memory.snapshot({"source_ids": [source["id"]], "question": title})}
        created = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.store.connect() as db:
            db.execute("INSERT INTO runs(id,plan,plan_hash,status,created_at,output) VALUES (?,?,?,'completed',?,?)", (run_id, json.dumps(plan), "fixture", created, claim))
            db.execute("INSERT INTO knowledge VALUES (?,?,?,?,?,?,?,?)", (knowledge_id, run_id, title, '["ai"]', notes, claim, json.dumps([source["id"]]), created))
        current = self.memory.register_finding(knowledge_id)
        if review_at:
            current = self.memory.revise(knowledge_id, {"expected_version": current["version"], "review_at": review_at})
        return current, source

    def report_run(self, memory_item, source, relation="contradicts", **changes):
        snapshot = self.memory.snapshot({"source_ids": [source["id"]], "question": "ИИ память", "memory_options": {"selected_ids": [memory_item["id"]]}})
        run_id = uuid.uuid4().hex
        plan = {"sources": [source], "memory": snapshot}
        proposal = {"memory_id": memory_item["id"], "memory_version": memory_item["version"], "relation": relation,
                    "rationale": "В новом источнике указано важное ограничение", "updated_claim": "Улучшение памяти наблюдается только на указанном наборе задач",
                    "evidence_source_ids": [source["id"]], "evidence_urls": []}
        proposal.update(changes)
        output = "Report\n<lab_memory_review>" + json.dumps({"comparisons": [proposal]}, ensure_ascii=False) + "</lab_memory_review>"
        with self.store.connect() as db:
            db.execute("INSERT INTO runs(id,plan,plan_hash,status,created_at,output) VALUES (?,?,?,'completed',?,?)", (run_id, json.dumps(plan), "fixture", datetime.now(timezone.utc).isoformat(), output))
        return run_id, output

    def test_default_profile_only_records_known_ai_scope(self):
        profile = self.memory.profile()
        self.assertEqual(profile["interests"], "")
        self.assertEqual(profile["goals"], "")
        self.assertEqual(profile["preferences"], "")
        self.assertEqual(profile["review_days"], 30)
        self.assertIn("Только ИИ", profile["scope"])
        with self.store.connect() as db:
            self.assertFalse(self.memory.has_user_data(db))

    def test_profile_and_correction_changes_are_versioned(self):
        profile = self.memory.save_profile({"expected_version": 1, "interests": "Память агентов", "review_days": 14})
        self.assertEqual(profile["version"], 2)
        with self.assertRaises(ValueError):
            self.memory.save_profile({"expected_version": 1, "goals": "stale edit"})
        correction = self.memory.save_correction({"text": "Не путать заявление автора с измерением лаборатории"})
        self.assertEqual(correction["version"], 1)
        self.memory.save_correction({"id": correction["id"], "expected_version": 1, "active": False})
        self.assertFalse(self.memory.corrections()[0]["active"])
        self.assertEqual(self.memory.corrections()[0]["version"], 2)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM memory_correction_revisions").fetchone()[0], 2)

    def test_retrieval_cross_language_aliases_and_explicit_empty_selection(self):
        relevant, source = self.finding()
        other, _ = self.finding("GPU quantization", "Quantization reduces GPU inference memory footprint")
        preview = self.memory.candidates({"source_ids": [source["id"]], "question": "Что известно о долговременной памяти?"})
        self.assertEqual(preview["suggested_ids"][0], relevant["id"])
        self.assertGreater(preview["candidates"][0]["score"], 0)
        self.assertIn("reason", preview["candidates"][0])
        snapshot = self.memory.snapshot({"source_ids": [source["id"]], "question": "память", "memory_options": {"selected_ids": []}})
        self.assertEqual(snapshot["items"], [])
        self.assertNotEqual(relevant["id"], other["id"])

    def test_stale_refresh_is_forced_and_retired_not_suggested(self):
        item, source = self.finding(review_at="2000-01-01")
        self.assertTrue(item["stale"])
        retired = self.memory.revise(item["id"], {"expected_version": item["version"], "status": "retired"})
        preview = self.memory.candidates({"question": "память"})
        self.assertNotIn(item["id"], preview["suggested_ids"])
        snapshot = self.memory.snapshot({"source_ids": [source["id"]], "question": "другая тема", "memory_options": {"selected_ids": [], "refresh_id": item["id"]}})
        self.assertEqual(snapshot["items"][0]["id"], item["id"])
        self.assertEqual(snapshot["items"][0]["version"], retired["version"])
        self.assertTrue(snapshot["items"][0]["stale"])

    def test_snapshot_is_bounded_exact_and_old_generation_rejected(self):
        self.memory.save_profile({"expected_version": 1, "interests": "а" * 1000, "goals": "б" * 1000, "preferences": "в" * 1000})
        items = [self.finding(f"Memory {index}", "Memory " + "x" * 3900, "Notes " + "y" * 3900)[0] for index in range(5)]
        for index in range(6):
            self.memory.save_correction({"text": str(index) + "Учитывать ограничения " * 40})
        values = {"question": "ИИ память", "memory_options": {"selected_ids": [item["id"] for item in items]}}
        snapshot = self.memory.snapshot(values)
        self.assertLessEqual(len(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), sort_keys=True)), MAX_SNAPSHOT_CHARS)
        self.assertTrue(any(item.get("text_truncated") for item in snapshot["items"]))
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.memory.validate(db, snapshot)
        self.memory.save_correction({"text": "Новая поправка владельца"})
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            with self.assertRaises(ValueError):
                self.memory.validate(db, snapshot)

    def test_disabled_memory_sends_no_profile_corrections_or_findings(self):
        item, _ = self.finding()
        self.memory.save_correction({"text": "Личная поправка"})
        snapshot = self.memory.snapshot({"question": "память", "memory_options": {"enabled": False}})
        self.assertFalse(snapshot["enabled"])
        self.assertIsNone(snapshot["profile"])
        self.assertEqual(snapshot["items"], [])
        self.assertEqual(snapshot["corrections"], [])

    def test_revisions_keep_original_output_and_history(self):
        item, _ = self.finding(claim="Original report")
        new = self.memory.revise(item["id"], {"expected_version": 1, "claim": "Исправленная трактовка", "title": "Новое название"})
        history = self.memory.history(item["id"])
        self.assertEqual(new["version"], 2)
        self.assertEqual(len(history["versions"]), 2)
        self.assertEqual(history["versions"][1]["claim"], "Original report")
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT output FROM knowledge WHERE id=?", (item["id"],)).fetchone()[0], "Original report")
        with self.assertRaises(ValueError):
            self.memory.revise(item["id"], {"expected_version": 1, "claim": "stale edit"})

    def test_contradiction_requires_owner_acceptance_and_preserves_evidence(self):
        item, source = self.finding()
        run_id, output = self.report_run(item, source)
        metadata = self.memory.ingest_review(run_id, output)
        self.assertEqual(metadata["errors"], [])
        self.assertEqual(len(metadata["created_ids"]), 1)
        before = self.memory.history(item["id"])["current"]
        self.assertEqual(before["version"], 1)
        self.assertEqual(before["effective_status"], "disputed")
        review = self.memory.reviews()[0]
        accepted = self.memory.resolve_review(review["id"], {"action": "accept", "expected_version": 1})
        self.assertEqual(accepted["status"], "accepted")
        self.assertEqual(accepted["current"]["version"], 2)
        self.assertEqual(accepted["current"]["evidence_run_id"], run_id)
        self.assertEqual(accepted["current"]["source_ids"], [source["id"]])
        self.assertEqual(self.memory.ingest_review(run_id, output), metadata)
        self.assertEqual(len(self.memory.reviews()), 1)

    def test_unknown_memory_or_wrong_evidence_never_creates_proposal(self):
        item, source = self.finding()
        for changes in ({"memory_id": "injected"}, {"memory_version": 999}, {"evidence_source_ids": ["unrelated"]}, {"evidence_source_ids": [], "evidence_urls": ["http://127.0.0.1/private"]}):
            run_id, output = self.report_run(item, source, **changes)
            metadata = self.memory.ingest_review(run_id, output)
            self.assertEqual(metadata["created_ids"], [])
            self.assertTrue(metadata["errors"])
            self.assertEqual(self.memory.review_metadata(run_id), metadata)
        self.assertEqual(self.memory.reviews(), [])

    def test_malformed_review_is_metadata_not_report_failure(self):
        item, source = self.finding()
        run_id, _ = self.report_run(item, source)
        metadata = self.memory.ingest_review(run_id, "Text <lab_memory_review>{invalid</lab_memory_review>")
        self.assertEqual(metadata["status"], "invalid")
        self.assertTrue(metadata["errors"])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()[0], "completed")

    def test_old_review_cannot_overwrite_a_new_owner_revision(self):
        item, source = self.finding()
        run_id, output = self.report_run(item, source, relation="supersedes")
        self.memory.ingest_review(run_id, output)
        review = self.memory.reviews()[0]
        self.memory.revise(item["id"], {"expected_version": 1, "claim": "Последняя поправка владельца"})
        with self.assertRaises(ValueError):
            self.memory.resolve_review(review["id"], {"action": "accept", "expected_version": 1})
        dismissed = self.memory.resolve_review(review["id"], {"action": "dismiss", "expected_version": 1})
        self.assertEqual(dismissed["status"], "dismissed")
        self.assertEqual(dismissed["current"]["claim"], "Последняя поправка владельца")

    def test_backup_rows_validate_and_invalid_json_is_rejected(self):
        item, source = self.finding()
        self.memory.save_correction({"text": "Владелец поправил вывод", "knowledge_id": item["id"]})
        run_id, output = self.report_run(item, source)
        self.memory.ingest_review(run_id, output)
        with self.store.connect() as db:
            for table in TABLES:
                for row in db.execute(f"SELECT * FROM {table}").fetchall():
                    validate_backup_table(table, dict(row), db)
            validate_backup(db)
            row = dict(db.execute("SELECT * FROM knowledge_revisions LIMIT 1").fetchone())
            row["source_ids"] = "{invalid"
            with self.assertRaises(ValueError):
                validate_backup_table("knowledge_revisions", row, db)


if __name__ == "__main__":
    unittest.main()
