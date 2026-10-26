"""Applied-task integration checks. Fixtures only; no provider or Telegram calls."""
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest

from laboratory.core import Store, canonical, digest, research_prompt
from laboratory.server import Laboratory
from test_core import NoTelegram


class StudyFlowTests(unittest.TestCase):
    def setUp(self):
        tmp = Path(__file__).parent / ".tmp"
        tmp.mkdir(exist_ok=True)
        self.temp = TemporaryDirectory(dir=tmp)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "data")
        self.source = self.store.add_source("TEST_ONLY: ИИ поиск и память RAG", "Источник")[0]
        self.task = self.save_task()

    def tearDown(self):
        self.temp.cleanup()

    def save_task(self):
        body = copy.deepcopy(self.store.study.schema()["template"])
        body.update(title="TEST_ONLY поиск для аналитика", task_type="retrieval", business_goal="Сократить ручной поиск с проверкой источников", dataset="20 размеченных кейсов, предложение пилота", evaluation="Одинаковые кейсы и scorer; измерений пока нет")
        body["baseline"]["name"] = "Ручной поиск"
        body["self_hosted"].update(gpu="Неизвестно", candidate_profiles="Для каждого кандидата нужна отдельная оценка нагрузки")
        body["metrics"] = [{"name": "Правильность ответа", "definition": "Доля полностью верных ответов на фиксированных кейсах", "unit": "fraction", "direction": "maximize", "primary": True, "target": "Порог согласовать до пилота", "expected": "Неизвестно", "evidence_level": "unknown", "evidence_url": ""}]
        return self.store.study.save({"expected_version": 0, "status": "active", "body": body})

    def plan(self, **values):
        return self.store.create_plan({"source_ids": [self.source["id"]], "question": "Оцени применимость ИИ памяти", "task_id": self.task["id"], **values})

    def test_task_memory_and_exact_evidence_labels_reach_one_frozen_prompt(self):
        self.store.memory.save_correction({"text": "TEST_ONLY: Отделять прогноз от измерения"})
        run = self.plan()
        study = run["plan"]["study_context"]
        prompt = research_prompt(run["plan"])
        self.assertIn(canonical(study), prompt)
        self.assertIn(study["task"]["business_goal"], prompt)
        self.assertIn("Отделять прогноз от измерения", prompt)
        self.assertEqual(study["task"]["metrics"][0]["evidence_level"], "unknown")
        self.assertEqual(run["status"], "planned")

    def test_edit_task_preserves_old_snapshot_blocks_start_and_rebuilds_both_contexts(self):
        run = self.plan()
        frozen = copy.deepcopy(run["plan"])
        body = copy.deepcopy(self.task["body"])
        body["baseline"]["name"] = "Другой текущий процесс"
        self.store.study.save({"id": self.task["id"], "expected_version": 1, "body": body})
        with self.assertRaises(ValueError):
            self.store.approve(run["id"], run["plan_hash"], True, "study-stale-command")
        self.assertEqual(self.store.run(run["id"])["plan"], frozen)
        rebuilt = self.store.replan_context(run["id"], {})
        self.assertNotEqual(rebuilt["plan_hash"], run["plan_hash"])
        self.assertEqual(rebuilt["plan"]["study_context"]["task_version"], 2)
        self.assertTrue(self.store.approve(run["id"], rebuilt["plan_hash"], True, "study-updated-command"))

    def test_archived_task_blocks_launch_but_preserves_history(self):
        run = self.plan()
        self.store.study.save({"id": self.task["id"], "expected_version": 1, "status": "archived"})
        with self.assertRaises(ValueError):
            self.store.approve(run["id"], run["plan_hash"], True, "study-archive-command")
        self.assertEqual(run["plan"]["study_context"]["task_version"], 1)
        self.assertEqual(len(self.store.study.task(self.task["id"])["history"]), 2)

    def test_finding_scope_survives_task_edit_and_refresh_uses_latest_task(self):
        run = self.plan()
        self.store.approve(run["id"], run["plan_hash"], True, "study-finding-command")
        self.store.finish(run["id"], {"status": "completed", "text": "TEST_ONLY память RAG требует проверки источников"})
        finding = self.store.save_finding(run["id"], {"title": "Результат поиска"})
        self.assertEqual(finding["memory"]["study_scope"]["task_version"], 1)
        body = copy.deepcopy(self.task["body"])
        body["constraints"] = "Иная нагрузка"
        self.store.study.save({"id": self.task["id"], "expected_version": 1, "body": body})
        history = self.store.memory.history(finding["id"])
        self.assertEqual(history["current"]["study_scope"]["task_version"], 1)
        refreshed = self.store.refresh_memory_plan(finding["id"])
        self.assertEqual(refreshed["plan"]["study_context"]["task_id"], self.task["id"])
        self.assertEqual(refreshed["plan"]["study_context"]["task_version"], 2)
        self.assertEqual(refreshed["plan"]["memory"]["items"][0]["study_scope"]["task_version"], 1)

    def test_backup_three_preserves_task_history_and_frozen_plan(self):
        run = self.plan()
        self.store.study.save({"id": self.task["id"], "expected_version": 1, "status": "archived"})
        backup = self.store.export()
        self.assertEqual(backup["schema_version"], 7)
        destination = Store(self.root / "restored")
        destination.restore(backup)
        self.assertEqual(destination.run(run["id"])["plan_hash"], run["plan_hash"])
        self.assertEqual(destination.study.task(self.task["id"])["status"], "archived")
        self.assertEqual(len(destination.study.task(self.task["id"])["history"]), 2)

    def test_backup_wrong_task_snapshot_rolls_back_all_content(self):
        run = self.plan()
        backup = self.store.export()
        row = next(row for row in backup["tables"]["runs"] if row["id"] == run["id"])
        plan = json.loads(row["plan"])
        snapshot = plan["study_context"]
        snapshot["task"]["baseline"]["name"] = "Подмена baseline"
        snapshot["hash"] = digest({key: value for key, value in snapshot.items() if key != "hash"})
        row["plan"], row["plan_hash"] = canonical(plan), digest(plan)
        destination = Store(self.root / "invalid")
        with self.assertRaises(ValueError):
            destination.restore(backup)
        self.assertEqual(destination.counts()["sources"], 0)
        self.assertEqual(destination.study.tasks(), [])

    def test_legacy_two_restore_does_not_rewrite_historical_hash(self):
        run = self.plan(task_id=None)
        backup = self.store.export()
        del backup["tables"]["study_task_revisions"]
        del backup["tables"]["lesson_revisions"]
        del backup["tables"]["run_contexts"]
        backup["schema_version"] = 2
        backup["tables"].pop("agent_phases")
        backup['tables'].pop('research_assets')
        backup['tables'].pop('research_asset_claims')
        backup["tables"].pop("research_review_revisions")
        row = backup["tables"]["runs"][0]
        plan = json.loads(row["plan"])
        del plan["study_context"]
        plan.pop("execution_context", None)
        row["plan"], row["plan_hash"] = canonical(plan), digest(plan)
        destination = Store(self.root / "legacy")
        destination.restore(backup)
        self.assertEqual(destination.run(run["id"])["plan_hash"], row["plan_hash"])
        rebuilt = destination.replan_context(run["id"], {})
        self.assertIn("study_context", rebuilt["plan"])

    def test_restore_never_overwrites_task_only_database(self):
        empty_backup = Store(self.root / "empty").export()
        destination = Store(self.root / "destination")
        destination.study.save({"body": self.task["body"]})
        with self.assertRaises(ValueError):
            destination.restore(empty_backup)
        self.assertEqual(len(destination.study.tasks()), 1)

    def test_task_edits_and_preview_do_not_dispatch_extra_calls(self):
        calls = []
        def runner(plan, prompt, work_dir, cancel):
            calls.append((plan, prompt))
            return {"status": "completed", "text": "TEST_ONLY applied analysis"}
        app = Laboratory(self.root / "server", runner=runner, telegram_factory=NoTelegram)
        try:
            task = app.store.study.save({"body": self.task["body"]})
            source = app.store.add_source("TEST_ONLY AI workflow")[0]
            run = app.store.create_plan({"source_ids": [source["id"]], "task_id": task["id"]})
            self.assertEqual(calls, [])
            consent = {"consent": True, "plan_hash": run["plan_hash"], "command_id": "study-one-call-command"}
            app.start_run(run["id"], consent)
            deadline = time.monotonic() + 3
            while app.jobs and time.monotonic() < deadline:
                time.sleep(0.01)
            app.start_run(run["id"], consent)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0]["study_context"], run["plan"]["study_context"])
        finally:
            app.close()


if __name__ == "__main__":
    unittest.main()
