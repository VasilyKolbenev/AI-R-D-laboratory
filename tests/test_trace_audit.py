"""Trace audit regressions: no real process, provider, or network call."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from laboratory import providers
from laboratory.core import Store, canonical, digest


TMP = Path(__file__).parent / ".tmp"
TMP.mkdir(exist_ok=True)


class TraceAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TMP)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "data")
        self.source = self.store.add_source("TEST_ONLY ИИ: проверяемые данные 🚀")[0]

    def plan(self):
        return self.store.create_plan({"source_ids": [self.source["id"]],
                                       "question": "Какие доказательства есть?"})

    def test_malformed_manifest_cannot_restore_a_context_that_get_would_crash_on(self):
        with patch("laboratory.providers._executable", return_value=None):
            self.plan()
        backup = self.store.export()
        row = backup["tables"]["runs"][0]
        plan = json.loads(row["plan"])
        context = plan["execution_context"]
        del context["manifest"]["coverage"]
        context["hash"] = digest({key: value for key, value in context.items() if key != "hash"})
        row.update(plan=canonical(plan), plan_hash=digest(plan))
        destination = Store(self.root / "restored")
        with self.assertRaises(ValueError):
            destination.restore(backup)
        self.assertEqual(destination.counts(), {"sources": 0, "runs": 0, "knowledge": 0})

    def test_changed_resolved_cli_is_rejected_before_process_spawn(self):
        approved_cli = self.root / "approved.exe"
        resolved_cli = self.root / "replacement.exe"
        approved_cli.write_bytes(b"TEST_ONLY approved native binary bytes")
        resolved_cli.write_bytes(b"TEST_ONLY different native binary bytes")
        with patch("laboratory.providers._executable", return_value=str(approved_cli)):
            plan = self.plan()["plan"]
        with patch("laboratory.providers._executable", return_value=str(resolved_cli)), \
                patch("laboratory.providers.subprocess.Popen", side_effect=OSError("TEST_ONLY spawn guard")) as spawn:
            result = providers.run(plan, plan["execution_context"]["prompt"],
                                   self.root / "job", threading.Event())
        spawn.assert_not_called()
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["raw"]["dispatched"])


if __name__ == "__main__":
    unittest.main()
