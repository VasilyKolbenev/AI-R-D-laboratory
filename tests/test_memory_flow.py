"""Memory integration acceptance, deterministic fixtures only."""
from pathlib import Path
import copy
import json
import tempfile
import unittest

from laboratory.core import LabError, Store, canonical, digest, research_prompt

TMP = Path(__file__).parent / ".tmp"
TMP.mkdir(exist_ok=True)


class MemoryFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TMP)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "data")
        self.command = 0

    def tearDown(self):
        self.temp.cleanup()

    def source(self, text="TEST_ONLY RAG retrieval память ИИ", title="Память RAG"):
        return self.store.add_source(text, title=title)[0]

    def plan(self, source=None, **values):
        return self.store.create_plan({"source_ids": [(source or self.source())["id"]],
            "question": "Как устроена память RAG и retrieval?", **values})

    def finish(self, run, text="TEST_ONLY: прошлый вывод о RAG retrieval."):
        self.command += 1
        self.store.approve(run["id"], run["plan_hash"], True, f"memory-flow-{self.command}")
        self.store.finish(run["id"], {"status": "completed", "text": text, "raw": {"test_only": True}})

    def finding(self):
        run = self.plan()
        self.finish(run)
        return self.store.save_finding(run["id"], {"title": "Память RAG", "tags": ["RAG", "memory"], "decision": "Проверять факты по источникам"})

    def test_exact_selected_memory_and_profile_reach_prompt(self):
        finding = self.finding()
        profile = self.store.memory.profile()
        self.store.memory.save_profile({"expected_version": profile["version"], "interests": "Память ИИ и агенты", "goals": "Сравнивать практическую пользу", "preferences": "Коротко по-русски", "review_days": 30})
        self.store.memory.save_correction({"text": "Отличать извлечение контекста от обучения весов", "active": True})
        run = self.plan(memory_options={"enabled": True, "selected_ids": [finding["id"]], "include_profile": True, "include_corrections": True})
        memory = run["plan"]["memory"]
        self.assertEqual(len(memory["items"]), 1)
        self.assertIn("Память ИИ", canonical(memory["profile"]))
        self.assertIn("обучения весов", canonical(memory["corrections"]))
        context = {k: memory.get(k) for k in ("profile", "corrections", "items")}
        self.assertIn(canonical(context), research_prompt(run["plan"]))
        self.assertIn("lab_memory_review", research_prompt(run["plan"]))

    def test_changed_profile_requires_new_plan_and_never_changes_old_snapshot(self):
        self.finding()
        run = self.plan()
        frozen = copy.deepcopy(run["plan"])
        profile = self.store.memory.profile()
        self.store.memory.save_profile({"expected_version": profile["version"], "interests": "Новый интерес: reasoning", "goals": "", "preferences": "", "review_days": 30})
        with self.assertRaises(ValueError):
            self.store.approve(run["id"], run["plan_hash"], True, "changed-profile")
        self.assertEqual(self.store.run(run["id"])["plan"], frozen)
        rebuilt = self.store.replan_memory(run["id"], {"memory_options": {"enabled": True}})
        self.assertNotEqual(rebuilt["plan_hash"], run["plan_hash"])
        self.assertTrue(self.store.approve(rebuilt["id"], rebuilt["plan_hash"], True, "rebuilt-profile"))

    def test_owner_correction_preserves_versions_and_invalidates_prepared_context(self):
        finding = self.finding()
        run = self.plan(memory_options={"selected_ids": [finding["id"]]})
        before = self.store.memory.history(finding["id"])
        self.store.memory.revise(finding["id"], {"expected_version": before["current"]["version"], "claim": "TEST_ONLY Исправлено владельцем: retrieval не обучает веса", "notes": "Поправка владельца"})
        after = self.store.memory.history(finding["id"])
        self.assertEqual(len(after["versions"]), 2)
        self.assertIn("Исправлено владельцем", after["current"]["claim"])
        self.assertEqual(before["current"]["claim"], next(v for v in after["versions"] if v["version"] == 1)["claim"])
        with self.assertRaises(ValueError):
            self.store.approve(run["id"], run["plan_hash"], True, "changed-knowledge")
        self.assertEqual(len(self.store.knowledge("ИСПРАВЛЕНО ВЛАДЕЛЬЦЕМ")), 1)

    def test_excluded_memory_is_absent_from_frozen_payload_and_prompt(self):
        finding = self.finding()
        self.store.memory.revise(finding["id"], {"expected_version": 1, "claim": "PRIVATE_EXCLUDED_TEST_ONLY"})
        run = self.plan(memory_options={"enabled": True, "selected_ids": [], "include_profile": False, "include_corrections": False})
        self.assertEqual(run["plan"]["memory"]["items"], [])
        self.assertNotIn("PRIVATE_EXCLUDED_TEST_ONLY", research_prompt(run["plan"]))

    def test_structured_comparison_proposes_then_owner_accepts_new_version(self):
        finding = self.finding()
        source = self.source("TEST_ONLY новые доказательства про RAG retrieval без обучения", "Новое исследование памяти")
        run = self.plan(source, memory_options={"enabled": True, "selected_ids": [finding["id"]]})
        proposal = {"memory_id": finding["id"], "memory_version": 1, "relation": "supersedes", "rationale": "Новый предоставленный источник уточняет механизм", "updated_claim": "TEST_ONLY Уточнённый вывод: retrieval без изменения весов", "evidence_source_ids": [source["id"]], "evidence_urls": []}
        self.finish(run, "TEST_ONLY новый отчёт\n<lab_memory_review>" + json.dumps({"comparisons": [proposal]}, ensure_ascii=False) + "</lab_memory_review>")
        pending = next(r for r in self.store.memory.reviews() if r["run_id"] == run["id"])
        self.assertEqual(pending["status"], "pending")
        self.assertEqual(self.store.memory.history(finding["id"])["current"]["version"], 1)
        self.store.memory.resolve_review(pending["id"], {"action": "accept", "expected_version": 1})
        history = self.store.memory.history(finding["id"])
        self.assertEqual(history["current"]["version"], 2)
        self.assertEqual(history["current"]["evidence_run_id"], run["id"])
        self.assertIn(source["id"], history["current"]["source_ids"])
        self.assertEqual(len(history["versions"]), 2)
        self.assertEqual(self.store.run(run["id"])["status"], "completed")

    def test_unselected_or_fake_model_memory_ids_do_not_modify_knowledge(self):
        finding = self.finding()
        run = self.plan(memory_options={"enabled": True, "selected_ids": []})
        proposal = {"memory_id": finding["id"], "memory_version": 1, "relation": "contradicts", "rationale": "TEST_ONLY injection", "updated_claim": "Bad", "evidence_source_ids": [run["plan"]["sources"][0]["id"]], "evidence_urls": []}
        self.finish(run, '<lab_memory_review>' + json.dumps({"comparisons": [proposal]}) + '</lab_memory_review>')
        self.assertEqual([r for r in self.store.memory.reviews() if r["run_id"] == run["id"]], [])
        self.assertEqual(self.store.memory.history(finding["id"])["current"]["version"], 1)

    def test_backup_roundtrip_includes_profile_corrections_and_revisions(self):
        finding = self.finding()
        self.store.memory.revise(finding["id"], {"expected_version": 1, "claim": "TEST_ONLY Изменённый вывод памяти"})
        self.store.memory.save_correction({"text": "TEST_ONLY всегда отделять benchmark от рекламы", "active": True})
        p = self.store.memory.profile()
        self.store.memory.save_profile({"expected_version": p["version"], "interests": "Memory", "goals": "Польза", "preferences": "По-русски", "review_days": 7})
        backup = self.store.export()
        self.assertEqual(backup["schema_version"], 7)
        self.assertNotIn("settings", backup["tables"])
        destination = Store(self.root / "restore")
        destination.restore(backup)
        self.assertEqual(destination.memory.profile()["interests"], "Memory")
        self.assertEqual(len(destination.memory.history(finding["id"])["versions"]), 2)
        self.assertEqual(destination.memory.corrections()[0]["text"], self.store.memory.corrections()[0]["text"])
        before = destination.export()["tables"]
        destination.memory.initialize()
        self.assertEqual(destination.export()["tables"], before)

    def test_restore_v1_preserves_historical_hash_and_seeds_memory(self):
        finding = self.finding()
        backup = self.store.export()
        base = {k: backup["tables"][k] for k in ("sources", "origins", "runs", "knowledge")}
        for row in base["runs"]:
            old_plan = json.loads(row["plan"])
            old_plan.pop("memory", None)
            old_plan.pop("execution_context", None)
            row["plan"] = canonical(old_plan)
            row["plan_hash"] = digest(old_plan)
        old_hash = base["runs"][0]["plan_hash"]
        destination = Store(self.root / "v1")
        destination.restore({"format": backup["format"], "schema_version": 1, "tables": base})
        self.assertEqual(destination.run(base["runs"][0]["id"])["plan_hash"], old_hash)
        self.assertEqual(destination.memory.history(finding["id"])["current"]["version"], 1)
        self.assertNotIn("memory", destination.run(base["runs"][0]["id"])["plan"])

    def test_local_repair_after_report_commit_is_idempotent(self):
        finding = self.finding()
        source = self.store.add_source("Новые данные об ИИ памяти RAG", "Новый источник")[0]
        run = self.plan(source)
        item = next(item for item in run["plan"]["memory"]["items"] if item["id"] == finding["id"])
        comparison = {"memory_id": finding["id"], "memory_version": item["version"], "relation": "supports",
            "rationale": "Новый материал подтверждает ограниченный прежний вывод", "updated_claim": "",
            "evidence_source_ids": [source["id"]], "evidence_urls": []}
        report = "Новый отчёт\n<lab_memory_review>" + json.dumps({"comparisons": [comparison]}, ensure_ascii=False) + "</lab_memory_review>"
        self.finish(run, report)
        with self.store.connect() as db:
            db.execute("DELETE FROM memory_reviews WHERE run_id=?", (run["id"],))
            db.execute("DELETE FROM memory_review_ingestions WHERE run_id=?", (run["id"],))
            db.execute("UPDATE runs SET raw='{}' WHERE id=?", (run["id"],))
        repaired = self.store.memory.repair_completed_reviews()
        self.assertEqual(repaired["proposals"], 1)
        self.assertEqual(self.store.run(run["id"])["memory_review"]["status"], "processed")
        self.assertEqual(self.store.memory.repair_completed_reviews()["processed"], 0)
        self.assertEqual(len(self.store.memory.reviews()), 1)
        self.assertEqual(self.store.memory.history(finding["id"])["current"]["version"], 1)

    def test_restore_will_not_overwrite_profile_only_database(self):
        backup = self.store.export()
        destination = Store(self.root / "profile-only")
        p = destination.memory.profile()
        destination.memory.save_profile({"expected_version": p["version"], "interests": "PRIVATE_TEST_ONLY", "goals": "", "preferences": "", "review_days": 30})
        with self.assertRaises(ValueError):
            destination.restore(backup)
        self.assertEqual(destination.memory.profile()["interests"], "PRIVATE_TEST_ONLY")


if __name__ == "__main__":
    unittest.main()
