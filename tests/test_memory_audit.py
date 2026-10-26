"""Focused acceptance probes; deterministic fixtures, no providers or user data."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from laboratory.core import Store


class MemoryAuditTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).parent / ".tmp"
        temp_root.mkdir(exist_ok=True)
        self.temp = TemporaryDirectory(dir=temp_root)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "original")
        self.store.update_settings({"daily_run_limit": 20})
        self.sequence = 0

    def tearDown(self):
        self.temp.cleanup()

    def completed(self, source, text="TEST_ONLY RAG memory report", memory_options=None):
        values = {"source_ids": [source["id"]], "question": "TEST_ONLY assess RAG memory"}
        if memory_options is not None:
            values["memory_options"] = memory_options
        run = self.store.create_plan(values)
        self.sequence += 1
        self.store.approve(run["id"], run["plan_hash"], True, "audit-command-" + str(self.sequence))
        self.store.finish(run["id"], {"status": "completed", "text": text})
        return self.store.run(run["id"])

    def finding(self):
        source = self.store.add_source("TEST_ONLY RAG retrieval study", "RAG study")[0]
        run = self.completed(source)
        finding = self.store.save_finding(run["id"], {"title": "TEST_ONLY RAG finding"})
        return source, run, finding

    def test_owner_accepting_support_after_freshness_research_refreshes_review_date(self):
        source, original, finding = self.finding()
        self.store.memory.revise(finding["id"], {"expected_version": 1, "review_at": "2000-01-01"})
        proposal = {"memory_id": finding["id"], "memory_version": 2, "relation": "supports",
                    "rationale": "TEST_ONLY fresh evidence confirms the earlier result",
                    "updated_claim": "", "evidence_source_ids": [source["id"]],
                    "evidence_urls": ["https://example.com/test-only-research"]}
        output = "TEST_ONLY fresh report\n<lab_memory_review>" + json.dumps({"comparisons": [proposal]}) + "</lab_memory_review>"
        fresh = self.completed(source, output, {"selected_ids": [finding["id"]], "refresh_id": finding["id"]})
        review = next(item for item in self.store.memory.reviews() if item["run_id"] == fresh["id"])
        self.store.memory.resolve_review(review["id"], {"action": "accept", "expected_version": 1})
        history = self.store.memory.history(finding["id"])
        self.assertFalse(history["current"]["stale"], "Accepted fresh confirmation must close the freshness check")
        self.assertEqual(history["current"]["evidence_run_id"], fresh["id"])
        self.assertIn(original["id"], [item["evidence_run_id"] for item in history["versions"]])

    def test_plan_crossing_review_deadline_requires_fresh_preview(self):
        source, _, finding = self.finding()
        tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
        self.store.memory.revise(finding["id"], {"expected_version": 1, "review_at": tomorrow.date().isoformat()})
        run = self.store.create_plan({"source_ids": [source["id"]], "question": "TEST_ONLY review memory",
                                     "memory_options": {"selected_ids": [finding["id"]]}})
        self.assertFalse(run["plan"]["memory"]["items"][0]["stale"])

        class Tomorrow(datetime):
            @classmethod
            def now(cls, tz=None):
                return tomorrow if tz else tomorrow.replace(tzinfo=None)

        with patch("laboratory.memory.datetime", Tomorrow):
            self.assertTrue(self.store.memory.history(finding["id"])["current"]["stale"])
            with self.assertRaises(ValueError, msg="The approved snapshot would mislabel expired knowledge as current"):
                self.store.approve(run["id"], run["plan_hash"], True, "audit-crossed-deadline")

    def test_backup_rejects_reassigning_original_revision_to_unrelated_research(self):
        _, _, finding = self.finding()
        other_source = self.store.add_source("TEST_ONLY unrelated image generation material", "Unrelated diffusion")[0]
        other_run = self.completed(other_source, "TEST_ONLY unrelated diffusion result", {"selected_ids": []})
        backup = copy.deepcopy(self.store.export())
        revision = next(item for item in backup["tables"]["knowledge_revisions"] if item["knowledge_id"] == finding["id"])
        revision["evidence_run_id"] = other_run["id"]
        revision["source_ids"] = json.dumps([other_source["id"]])
        destination = Store(self.root / "restore")
        with self.assertRaises(ValueError, msg="Revision 1 must preserve the saved finding's original evidence"):
            destination.restore(backup)
        self.assertEqual(destination.counts(), {"sources": 0, "runs": 0, "knowledge": 0})


if __name__ == "__main__":
    unittest.main()
