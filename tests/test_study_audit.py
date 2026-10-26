"""Focused regression probes for standalone frozen task context; no provider calls."""
import copy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from laboratory.core import Store


class StudyAuditTests(unittest.TestCase):
    def setUp(self):
        tmp = Path(__file__).parent / ".tmp"
        tmp.mkdir(exist_ok=True)
        self.temp = TemporaryDirectory(dir=tmp)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "data")
        self.source = self.store.add_source("TEST_ONLY AI extraction study", "AI study")[0]
        self.task = copy.deepcopy(self.store.study.schema()["template"])
        self.task.update(title="TEST_ONLY one-off invoice extraction", task_type="extraction",
                         business_goal="TEST_ONLY cut invoice review time", constraints="TEST_ONLY no cloud storage")
        self.task["baseline"]["name"] = "TEST_ONLY manual verification"
        self.task["metrics"] = [{"name": "TEST_ONLY correct invoices", "primary": True,
                                 "direction": "maximize", "definition": "TEST_ONLY all fields correct"}]

    def tearDown(self):
        self.temp.cleanup()

    def plan(self):
        return self.store.create_plan({"source_ids": [self.source["id"]], "question": "TEST_ONLY assess extraction",
                                       "study_task": self.task})

    def test_memory_only_rebuild_preserves_standalone_context(self):
        before = self.plan()
        rebuilt = self.store.replan_memory(before["id"], {"memory_options": {"enabled": False}})
        self.assertEqual(rebuilt["plan"]["study_context"]["task"], before["plan"]["study_context"]["task"],
                         "Changing memory must not erase the standalone business task")
        self.assertFalse(rebuilt["plan"]["memory"]["enabled"])

    def test_freshness_plan_preserves_standalone_context_of_knowledge(self):
        original = self.plan()
        self.store.approve(original["id"], original["plan_hash"], True, "study-audit-complete")
        self.store.finish(original["id"], {"status": "completed", "text": "TEST_ONLY extraction report"})
        finding = self.store.save_finding(original["id"], {"title": "TEST_ONLY extraction finding"})
        refreshed = self.store.refresh_memory_plan(finding["id"])
        self.assertEqual(refreshed["plan"]["study_context"]["task"], original["plan"]["study_context"]["task"],
                         "A knowledge freshness check must keep the applicability context of its standalone study")


if __name__ == "__main__":
    unittest.main()
