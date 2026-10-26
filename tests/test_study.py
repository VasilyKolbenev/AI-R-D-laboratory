from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import uuid

from laboratory.core import Store
from laboratory.study import Study, MAX_CONTEXT_CHARS, TABLES, query_text, validate_backup_table, validate_backup


class StudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_root = Path(__file__).parent / ".tmp"
        cls.temp_root.mkdir(exist_ok=True)

    def setUp(self):
        self.temporary = TemporaryDirectory(dir=self.temp_root)
        self.store = Store(Path(self.temporary.name))
        self.study = Study(self.store)
        self.study.initialize()

    def tearDown(self):
        self.temporary.cleanup()

    def body(self):
        value = self.study.schema()["template"]
        value.update(title="TEST_ONLY Search assistant", task_type="retrieval", business_goal="Find relevant AI research for an analyst",
                     beneficiary="TEST_ONLY analyst", research_question="Can RAG help recover saved findings?",
                     inputs="Saved research notes", expected_output="Answer with source references", dataset="Not selected yet",
                     evaluation="Compare source coverage", success_criteria="Owner evaluates usefulness")
        value["baseline"] = {"name": "Manual search", "version": "current", "description": "Analyst searches the archive", "limitations": "Time-consuming"}
        return value

    def metric(self, **changes):
        value = {"name": "Citation coverage", "definition": "Share of claims with a source", "unit": "%",
                 "direction": "maximize", "primary": True, "target": ">=90%", "expected": "Unknown before testing",
                 "evidence_level": "hypothesis", "evidence_url": ""}
        value.update(changes)
        return value

    def test_template_is_unknown_not_fabricated_and_has_no_initial_user_records(self):
        first = self.study.schema()
        self.assertEqual(first["execution_mode"], "source_analysis")
        self.assertEqual(first["template"]["self_hosted"]["availability"], "unknown")
        for key in ("business_goal", "dataset", "evaluation", "success_criteria"):
            self.assertEqual(first["template"][key], "")
        self.assertEqual(first["template"]["candidates"], [])
        first["template"]["self_hosted"]["gpu"] = "invented"
        self.assertEqual(self.study.schema()["template"]["self_hosted"]["gpu"], "")
        with self.store.connect() as db:
            self.assertFalse(self.study.has_user_data(db))

    def test_exploratory_snapshot_has_explicit_unknown_notices(self):
        snapshot = self.study.snapshot({"question": "How does AI agent memory work?"})
        self.assertIsNone(snapshot["task_id"])
        self.assertIsNone(snapshot["task_version"])
        self.assertEqual(snapshot["task"]["research_question"], "How does AI agent memory work?")
        self.assertEqual(snapshot["task"]["task_type"], "exploratory")
        self.assertTrue(any("Baseline" in notice for notice in snapshot["notices"]))
        self.assertTrue(any("Self-hosted" in notice or "self-hosted" in notice for notice in snapshot["notices"]))
        with self.store.connect() as db:
            self.study.validate(db, snapshot)

    def test_saved_task_versions_and_optimistic_editing(self):
        first = self.study.save({"expected_version": 0, "body": self.body()})
        self.assertEqual(first["version"], 1)
        changed = deepcopy(first["body"])
        changed["business_goal"] = "TEST_ONLY new business question"
        second = self.study.save({"id": first["id"], "expected_version": 1, "body": changed})
        self.assertEqual(second["version"], 2)
        history = self.study.task(first["id"])
        self.assertEqual([item["version"] for item in history["history"]], [2, 1])
        self.assertEqual(history["history"][1]["body"]["business_goal"], first["body"]["business_goal"])
        self.assertEqual(len(self.study.tasks()), 1)
        with self.assertRaises(ValueError):
            self.study.save({"id": first["id"], "expected_version": 1, "body": changed})

    def test_task_edit_and_archive_invalidate_old_approval_context(self):
        first = self.study.save({"body": self.body()})
        snapshot = self.study.snapshot({"task_id": first["id"], "task_version": 1})
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.study.validate(db, snapshot)
        archived = self.study.save({"id": first["id"], "expected_version": 1, "status": "archived"})
        self.assertEqual(archived["body"], first["body"])
        with self.store.connect() as db:
            with self.assertRaises(ValueError):
                self.study.validate(db, snapshot)
        with self.assertRaises(ValueError):
            self.study.snapshot({"task_id": first["id"]})
        self.assertEqual(snapshot["task"], first["body"])

    def test_applied_task_requires_named_baseline_but_unknown_other_fields_are_visible(self):
        body = self.body()
        body["baseline"]["name"] = ""
        with self.assertRaises(ValueError):
            self.study.save({"body": body})
        body["task_type"] = "exploratory"
        saved = self.study.save({"body": body})
        self.assertTrue(any("Baseline" in notice for notice in saved["notices"]))

    def test_primary_metric_exactly_one_and_metric_value_types_are_explicit(self):
        for metrics in ([self.metric(primary=False)], [self.metric(), self.metric(name="Latency")], [self.metric(target=90)]):
            body = self.body()
            body["metrics"] = metrics
            with self.assertRaises(ValueError):
                self.study.save({"body": body})
        body = self.body()
        body["metrics"] = [self.metric(), self.metric(name="Latency", primary=False, direction="minimize", unit="ms")]
        saved = self.study.save({"body": body})
        self.assertEqual(sum(item["primary"] for item in saved["body"]["metrics"]), 1)
        self.assertEqual(saved["body"]["metrics"][0]["target"], ">=90%")

    def test_laboratory_measurement_and_private_evidence_links_are_rejected(self):
        for changes in ({"evidence_level": "lab_measurement"}, {"evidence_level": ["unknown"]},
                        {"evidence_url": "http://127.0.0.1/secret"}, {"evidence_url": "https://user:pass@example.com"},
                        {"evidence_url": "file:///C:/secret"}):
            body = self.body()
            body["metrics"] = [self.metric(**changes)]
            with self.assertRaises(ValueError):
                self.study.save({"body": body})
        body = self.body()
        body["metrics"] = [self.metric(evidence_level="external_measurement", evidence_url="https://example.com/paper")]
        self.assertEqual(self.study.save({"body": body})["body"]["metrics"][0]["evidence_level"], "external_measurement")

    def test_no_hidden_truncation_for_self_hosted_and_candidate_profiles(self):
        body = self.body()
        body["self_hosted"].update(availability="available", model="TEST_ONLY open model", ram="Unknown until measured",
                                   candidate_profiles="Variant A: CPU. Variant B: requirements unknown.", evidence_level="estimate")
        saved = self.study.save({"body": body})
        frozen = self.study.snapshot({"task_id": saved["id"]})
        self.assertEqual(frozen["task"]["self_hosted"], saved["body"]["self_hosted"])
        self.assertIsInstance(frozen["task"]["self_hosted"]["candidate_profiles"], str)
        self.assertIn("не являются измерениями", " ".join(frozen["notices"]))
        self.assertLessEqual(len(json.dumps(frozen, ensure_ascii=False, sort_keys=True, separators=(",", ":"))), MAX_CONTEXT_CHARS)

    def test_unknown_fields_and_total_context_overflow_are_rejected(self):
        body = self.body()
        body["execute_benchmark"] = True
        with self.assertRaises(ValueError):
            self.study.save({"body": body})
        body = self.body()
        body["candidates"] = [{"name": str(index), "description": "x" * 2000, "applicability": "y" * 2000,
                               "advantages": "z" * 1600, "limitations": "q" * 2000} for index in range(5)]
        with self.assertRaises(ValueError):
            self.study.save({"body": body})
        self.assertEqual(self.study.tasks(), [])

    def test_frozen_context_tampering_is_rejected(self):
        task = self.study.save({"body": self.body()})
        frozen = self.study.snapshot({"task_id": task["id"]})
        frozen["task"]["baseline"]["name"] = "unapproved substitute"
        with self.store.connect() as db:
            with self.assertRaises(ValueError):
                self.study.validate(db, frozen)

    def test_retrieval_query_includes_business_context_and_versions_do_not_get_lost(self):
        body = self.body()
        task = self.study.save({"body": body})
        frozen = self.study.snapshot({"task_id": task["id"]})
        text = query_text(frozen)
        self.assertIn(body["business_goal"], text)
        self.assertIn(body["baseline"]["name"], text)
        self.assertLessEqual(len(text), 2000)
        self.assertEqual(frozen["task_version"], task["version"])
        with self.assertRaises(ValueError):
            self.study.snapshot({"task_id": task["id"], "task_version": task["version"] + 1})

    def test_backup_validates_full_history_and_rejects_gaps_or_bad_body(self):
        task = self.study.save({"body": self.body()})
        with self.store.connect() as db:
            rows = [dict(row) for row in db.execute("SELECT * FROM study_task_revisions")]
            for row in rows:
                validate_backup_table(TABLES[0], row, db)
            validate_backup(db)
            bad = dict(rows[0], body="{invalid")
            with self.assertRaises(ValueError):
                validate_backup_table(TABLES[0], bad, db)
            gap = dict(rows[0], task_id=uuid.uuid4().hex, version=2)
            db.execute("INSERT INTO study_task_revisions VALUES (?,?,?,?,?)", tuple(gap[key] for key in ("task_id", "version", "body", "status", "created_at")))
            with self.assertRaises(ValueError):
                validate_backup(db)


if __name__ == "__main__":
    unittest.main()
