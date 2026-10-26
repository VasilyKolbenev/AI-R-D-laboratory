from copy import deepcopy
from datetime import date, datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import uuid

from laboratory.core import Store
from laboratory.lessons import (Lessons, MAX_SNAPSHOT_CHARS, TABLES,
                                has_user_data, validate_backup, validate_backup_table)


class LessonsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_root = Path(__file__).parent / ".tmp"
        cls.temp_root.mkdir(exist_ok=True)

    def setUp(self):
        self.temporary = TemporaryDirectory(dir=self.temp_root)
        self.store = Store(Path(self.temporary.name))
        self.lessons = Lessons(self.store)
        self.lessons.initialize()

    def tearDown(self):
        self.temporary.cleanup()

    def body(self, **changes):
        body = self.lessons.schema()["template"]
        body.update(title="TEST_ONLY Retrieval memory", problem="Stored findings can be stale",
                    rule="Check provenance before using retrieval memory",
                    evidence_note="TEST_ONLY owner hypothesis; URL has not been verified",
                    applies_when="Retrieval memory for AI source analysis",
                    not_applicable_when="No supporting evidence or incompatible task",
                    limitations="This lesson is not a measured laboratory result",
                    review_at="2099-01-01", evidence_urls=["https://example.com/paper"])
        body.update(changes)
        return body

    def active(self, **changes):
        return self.lessons.save({"status": "active", "body": self.body(**changes)})

    def evidence_run(self, source=None, status="completed", knowledge=False):
        source = source or self.store.add_source("TEST_ONLY AI retrieval source " + uuid.uuid4().hex, "TEST_ONLY Memory")[0]
        run_id = uuid.uuid4().hex
        created = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.store.connect() as db:
            db.execute("INSERT INTO runs(id,plan,plan_hash,status,created_at,output) VALUES (?,?,?,?,?,?)",
                       (run_id, json.dumps({"sources": [source]}), "fixture", status, created, "TEST_ONLY report"))
            if knowledge:
                knowledge_id = uuid.uuid4().hex
                db.execute("INSERT INTO knowledge VALUES (?,?,?,?,?,?,?,?)",
                           (knowledge_id, run_id, "TEST_ONLY Finding", "[]", "Owner decision", "TEST_ONLY report", json.dumps([source["id"]]), created))
                return run_id, source, knowledge_id
        return run_id, source

    def test_empty_store_schema_and_additive_initialization(self):
        self.assertEqual(self.lessons.list(), [])
        with self.store.connect() as db:
            self.assertFalse(has_user_data(db))
        schema = self.lessons.schema()
        self.assertEqual(schema["limits"]["context_chars"], 6000)
        self.assertEqual(schema["template"]["evidence_level"], "hypothesis")
        self.assertEqual(schema["template"]["evidence_urls"], [])
        self.assertNotIn("lab_measurement", [item["id"] for item in schema["evidence_levels"]])
        schema["template"]["evidence_urls"].append("invented")
        self.assertEqual(self.lessons.schema()["template"]["evidence_urls"], [])
        draft = self.lessons.save({})
        self.lessons.initialize()
        self.assertEqual(self.lessons.list()[0], draft)
        with self.store.connect() as db:
            self.assertTrue(self.lessons.has_user_data(db))

    def test_draft_activation_history_and_optimistic_editing(self):
        draft = self.lessons.save({"body": {"title": "TEST_ONLY incomplete"}})
        self.assertEqual(draft["status"], "draft")
        self.assertEqual(draft["body"]["review_at"], "")
        with self.assertRaises(ValueError):
            self.lessons.save({"id": draft["id"], "expected_version": 1, "status": "active"})
        active = self.lessons.save({"id": draft["id"], "expected_version": 1, "status": "active", "body": self.body()})
        retired = self.lessons.save({"id": active["id"], "expected_version": 2, "status": "retired"})
        self.assertEqual(retired["body"], active["body"])
        history = self.lessons.get(active["id"])
        self.assertEqual([item["version"] for item in history["history"]], [3, 2, 1])
        self.assertEqual(history["history"][2]["body"]["title"], "TEST_ONLY incomplete")
        self.assertEqual(len(self.lessons.list()), 1)
        for expected in (1, True, "3"):
            with self.assertRaises(ValueError):
                self.lessons.save({"id": active["id"], "expected_version": expected, "body": self.body()})

    def test_active_requires_rule_evidence_scope_and_review_date(self):
        for field in ("rule", "evidence_note", "applies_when", "review_at"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.active(**{field: ""})
        for review_at in ("2099-2-01", "2099-02-30", "tomorrow", 2099):
            with self.subTest(review_at=review_at), self.assertRaises(ValueError):
                self.active(review_at=review_at)
        with self.assertRaises(ValueError):
            self.active(evidence_urls=[])
        self.assertEqual(self.lessons.list(), [])
        active = self.active(evidence_level="external_measurement")
        self.assertEqual(active["body"]["evidence_level"], "external_measurement")

    def test_completed_run_sources_and_knowledge_provenance(self):
        run_id, source, knowledge_id = self.evidence_run(knowledge=True)
        active = self.active(evidence_urls=[], evidence_run_id=run_id,
                             evidence_source_ids=[source["id"]], knowledge_id=knowledge_id,
                             evidence_level="source_analysis")
        self.assertEqual(active["body"]["knowledge_id"], knowledge_id)
        other_run, other_source = self.evidence_run()
        failed_run, _ = self.evidence_run(status="failed")
        for changes in ({"evidence_run_id": other_run, "evidence_source_ids": [source["id"]]},
                        {"evidence_run_id": failed_run},
                        {"evidence_source_ids": [other_source["id"]], "evidence_urls": []},
                        {"evidence_run_id": other_run, "knowledge_id": knowledge_id},
                        {"knowledge_id": knowledge_id},
                        {"evidence_run_id": uuid.uuid4().hex},
                        {"task_id": uuid.uuid4().hex}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.active(**changes)
        with self.assertRaises(ValueError):
            self.lessons.save({"status": "draft", "body": {"evidence_run_id": failed_run}})

    def test_public_evidence_links_and_strict_bounded_fields(self):
        for url in ("file:///secret", "http://localhost/path", "http://127.0.0.1/path",
                    "http://169.254.169.254/", "http://[::1]/", "http://10.0.0.1/",
                    "https://user:pass@example.com/", "https://example.com:8443/",
                    "https://a.internal/", "http://0177.0.0.1/", "http://0x7f.0.0.1/",
                    "https://foo..com/", "https://example.com/a\nb"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.active(evidence_urls=[url])
        for changes in ({"evidence_level": "lab_measurement"}, {"evidence_level": []},
                        {"rule": "x" * 1801}, {"evidence_urls": "https://example.com"},
                        {"evidence_urls": ["https://example.com"] * 11},
                        {"evidence_source_ids": [uuid.uuid4().hex] * 7},
                        {"unknown_permission": "run code"}, {"applies_when": 12}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.active(**changes)
        self.assertEqual(self.lessons.list(), [])

    def test_recommendations_are_relevant_active_fresh_and_explicit_empty_disables(self):
        relevant = self.active()
        unrelated = self.active(title="TEST_ONLY GPU quantization", problem="GPU weights", rule="Select quantization precision",
                                applies_when="GPU inference", not_applicable_when="Training", limitations="Unknown", evidence_note="Hypothesis")
        stale = self.active(review_at="2000-01-01")
        draft = self.lessons.save({"body": self.body()})
        retired = self.active()
        self.lessons.save({"id": retired["id"], "expected_version": 1, "status": "retired"})
        preview = self.lessons.candidates({"question": "retrieval memory"})
        self.assertIn(relevant["id"], preview["suggested_ids"])
        for item in (stale, draft, retired, unrelated):
            self.assertNotIn(item["id"], preview["suggested_ids"])
        self.assertLessEqual(len(preview["suggested_ids"]), 3)
        self.assertEqual(self.lessons.snapshot({"question": "retrieval", "memory_options": {"lesson_ids": []}}), {"items": [], "notices": []})
        for item in (draft, retired):
            with self.assertRaises(ValueError):
                self.lessons.snapshot({"memory_options": {"lesson_ids": [item["id"]]}})

    def test_explicit_stale_selection_is_visible_and_launchable(self):
        stale = self.active(review_at="2000-01-01")
        frozen = self.lessons.snapshot({"question": "unrelated", "memory_options": {"lesson_ids": [stale["id"]]}})
        self.assertEqual(frozen["items"], [stale])
        self.assertTrue(frozen["notices"])
        with self.store.connect() as db:
            self.lessons.validate(db, frozen)
            self.lessons.validate(db, frozen["items"])

    def test_task_scope_matches_and_different_task_needs_explicit_selection(self):
        first = self.store.study.save({})
        second = self.store.study.save({})
        lesson = self.active(task_id=first["id"])
        same = self.lessons.candidates({"task_id": first["id"], "question": "unrelated"})
        self.assertEqual(same["suggested_ids"], [lesson["id"]])
        different = self.lessons.candidates({"task_id": second["id"], "question": "retrieval memory"})
        self.assertEqual(different["suggested_ids"], [])
        frozen = self.lessons.snapshot({"task_id": second["id"], "memory_options": {"lesson_ids": [lesson["id"]]}})
        self.assertEqual(frozen["items"], [lesson])
        self.assertTrue(frozen["notices"])

    def test_exact_snapshot_rejects_edits_retirement_and_tampering(self):
        lesson = self.active()
        frozen = self.lessons.snapshot({"memory_options": {"lesson_ids": [lesson["id"]]}})
        self.assertEqual(frozen["items"], [lesson])
        with self.store.connect() as db:
            self.lessons.validate(db, frozen)
            for mutate in (lambda item: item["body"].update(rule="Injected rule"),
                           lambda item: item.update(version=True),
                           lambda item: item.update(stale="false"),
                           lambda item: item.update(extra="hidden")):
                corrupt = deepcopy(frozen)
                mutate(corrupt["items"][0])
                with self.assertRaises(ValueError):
                    self.lessons.validate(db, corrupt)
        self.lessons.save({"id": lesson["id"], "expected_version": 1, "body": self.body(rule="Updated rule")})
        with self.store.connect() as db, self.assertRaises(ValueError):
            self.lessons.validate(db, frozen)
        latest = self.lessons.snapshot({"memory_options": {"lesson_ids": [lesson["id"]]}})
        self.lessons.save({"id": lesson["id"], "expected_version": 2, "status": "retired"})
        with self.store.connect() as db, self.assertRaises(ValueError):
            self.lessons.validate(db, latest)

    def test_utc_review_date_rollover_invalidates_approval(self):
        with patch("laboratory.lessons._today", return_value=date(2026, 10, 20)):
            lesson = self.active(review_at="2026-10-21")
            frozen = self.lessons.snapshot({"memory_options": {"lesson_ids": [lesson["id"]]}})
            self.assertFalse(frozen["items"][0]["stale"])
        with patch("laboratory.lessons._today", return_value=date(2026, 10, 21)):
            with self.store.connect() as db, self.assertRaises(ValueError):
                self.lessons.validate(db, frozen)

    def test_context_bound_omits_default_whole_items_and_rejects_explicit_overflow(self):
        lessons = [self.active(title="TEST_ONLY retrieval " + str(index), rule="retrieval " + "x" * 1700,
                               evidence_note="y" * 1000) for index in range(3)]
        frozen = self.lessons.snapshot({"question": "retrieval"})
        self.assertLess(len(frozen["items"]), 3)
        self.assertGreater(len(frozen["items"]), 0)
        self.assertTrue(frozen["notices"])
        self.assertLessEqual(len(json.dumps(frozen, ensure_ascii=False, sort_keys=True, separators=(",", ":"))), MAX_SNAPSHOT_CHARS)
        originals = {item["id"]: item for item in lessons}
        self.assertTrue(all(item == originals[item["id"]] for item in frozen["items"]))
        suggested = self.lessons.candidates({"question": "retrieval"})["suggested_ids"]
        explicit_suggestions = self.lessons.snapshot({"question": "retrieval", "memory_options": {"lesson_ids": suggested}})
        self.assertEqual([item["id"] for item in frozen["items"]], suggested)
        self.assertEqual([item["id"] for item in explicit_suggestions["items"]], suggested)
        with self.assertRaises(ValueError):
            self.lessons.snapshot({"question": "retrieval", "memory_options": {"lesson_ids": [item["id"] for item in lessons]}})
        oversized = self.active(title="TEST_ONLY giant retrieval", rule="retrieval " + "x" * 1700,
                                problem="p" * 1000, evidence_note="e" * 1200,
                                applies_when="a" * 1000, limitations="l" * 1000,
                                not_applicable_when="n" * 1000)
        self.assertGreater(len(json.dumps(oversized)), MAX_SNAPSHOT_CHARS)
        with self.assertRaises(ValueError):
            self.lessons.snapshot({"memory_options": {"lesson_ids": [oversized["id"]]}})

    def test_more_than_twelve_stale_candidates_do_not_hide_fresh_selection(self):
        for index in range(13):
            self.active(title="TEST_ONLY retrieval memory " + str(index), review_at="2000-01-01")
        fresh = self.active(title="TEST_ONLY retrieval", rule="retrieval", applies_when="retrieval",
                            problem="", evidence_note="Evidence", limitations="", not_applicable_when="")
        frozen = self.lessons.snapshot({"question": "retrieval memory"})
        self.assertEqual([item["id"] for item in frozen["items"]], [fresh["id"]])

    def test_backup_validates_rows_history_and_historical_frozen_crosslinks(self):
        lesson = self.active()
        frozen = self.lessons.snapshot({"memory_options": {"lesson_ids": [lesson["id"]]}})
        self.lessons.save({"id": lesson["id"], "expected_version": 1, "status": "retired"})
        run_id, _ = self.evidence_run()
        with self.store.connect() as db:
            plan = json.loads(db.execute("SELECT plan FROM runs WHERE id=?", (run_id,)).fetchone()[0])
            plan["memory"] = {"lessons": frozen["items"]}
            db.execute("UPDATE runs SET plan=? WHERE id=?", (json.dumps(plan), run_id))
            rows = [dict(row) for row in db.execute("SELECT * FROM lesson_revisions")]
            for row in rows:
                validate_backup_table(TABLES[0], row, db)
            validate_backup(db)  # A retired latest revision does not rewrite approved history.
            for changes in ({"created_at": "2026-10-20T10:00:00"}, {"version": True},
                            {"body": "{}"}, {"body": "{bad"}, {"extra": "unexpected"}):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    validate_backup_table(TABLES[0], dict(rows[0], **changes), db)
            gap_id = uuid.uuid4().hex
            db.execute("INSERT INTO lesson_revisions VALUES (?,?,?,?,?)", (gap_id, 2, rows[0]["body"], "active", rows[0]["created_at"]))
            with self.assertRaises(ValueError):
                validate_backup(db)
            db.execute("DELETE FROM lesson_revisions WHERE id=?", (gap_id,))
            plan["memory"]["lessons"][0]["body"]["rule"] = "Substitute frozen rule"
            db.execute("UPDATE runs SET plan=? WHERE id=?", (json.dumps(plan), run_id))
            with self.assertRaises(ValueError):
                validate_backup(db)

    def test_backup_checks_crosslinks_but_accepts_legacy_runs_without_lessons(self):
        self.evidence_run()
        self.active()
        with self.store.connect() as db:
            validate_backup(db)
            row = dict(db.execute("SELECT * FROM lesson_revisions").fetchone())
            body = json.loads(row["body"])
            body["evidence_run_id"] = uuid.uuid4().hex
            with self.assertRaises(ValueError):
                validate_backup_table(TABLES[0], dict(row, body=json.dumps(body)), db)


if __name__ == "__main__":
    unittest.main()
