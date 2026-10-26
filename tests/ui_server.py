"""TEST_ONLY local UI harness. Never loads Telegram or dispatches a real model."""
from pathlib import Path
import argparse
import json
import threading

from laboratory.server import Handler, Laboratory, LocalServer
from laboratory.core import canonical, digest, now


class NoTelegram:
    def __init__(self, *args):
        pass

    def status(self):
        return {"configured": False, "owner_id": None, "status": "TEST_ONLY: Telegram отключён"}

    def stop(self):
        pass


dispatches = 0
release = threading.Event()
last_prompt = ""
last_plan = {}


def fake_runner(plan, prompt, work_dir, cancel):
    global dispatches, last_prompt, last_plan
    dispatches += 1
    last_prompt = prompt
    last_plan = plan
    release.wait(timeout=15)
    comparisons = []
    if plan.get("memory", {}).get("items"):
        memory = plan["memory"]["items"][0]
        for relation in ("contradicts", "supports"):
            comparisons.append({"memory_id": memory.get("id", memory.get("knowledge_id")),
                "memory_version": memory["version"], "relation": relation,
                "rationale": "TEST_ONLY: фикстура сравнения, не научное доказательство",
                "updated_claim": "TEST_ONLY: уточнённая память ИИ после решения владельца",
                "evidence_source_ids": [plan["sources"][0]["id"]],
                "evidence_urls": ["https://example.org/test-only"]})
    review = "\n<lab_memory_review>" + json.dumps({"comparisons": comparisons}, ensure_ascii=False) + "</lab_memory_review>" if comparisons else ""
    return {
        "status": "completed",
        "text": "TEST_ONLY — Синтетический отчёт проверки интерфейса.\n\n"
                "ИИ и память: это фикстура, не настоящее исследование.\n"
                "<script>window.__reportExecuted = true</script>\n"
                "Ссылка фикстуры: https://example.org/test-only" + review,
        "usage": {"input_tokens": 10, "output_tokens": 20, "test_only": True},
        "raw": {"test_only": True},
    }


class TestHandler(Handler):
    def do_GET(self):
        if self.path == "/__test__/stats":
            self.check_host()
            return self.send({"dispatches": dispatches, "counts": self.app.store.counts(), "last_prompt": last_prompt, "last_plan": last_plan})
        return super().do_GET()

    def do_POST(self):
        if self.path == "/__test__/legacy":
            self.check_host()
            original = next(item for item in self.app.store.runs() if item["status"] == "completed")
            plan = json.loads(json.dumps(original["plan"]))
            plan.pop("execution_context", None)
            plan["question"] = "TEST_ONLY: старый отчёт без записи контекста"
            run_id = "00000000000000000000000000000001"
            with self.app.store.connect() as db:
                db.execute("INSERT INTO runs(id,plan,plan_hash,status,output,created_at) VALUES (?,?,?,?,?,?)",
                           (run_id, canonical(plan), digest(plan), "completed", "TEST_ONLY: старый синтетический отчёт", now()))
            return self.send({"id": run_id})
        if self.path in {"/__test__/release", "/__test__/shutdown"}:
            self.check_host()
            self.send({"test_only": True})
            release.set()
            if self.path == "/__test__/shutdown":
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        return super().do_POST()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    app = Laboratory(args.data_dir, runner=fake_runner, telegram_factory=NoTelegram)
    server = LocalServer(("127.0.0.1", 8796), TestHandler)
    server.app = app
    try:
        print("TEST_ONLY ready http://127.0.0.1:8796", flush=True)
        server.serve_forever(poll_interval=0.1)
    finally:
        release.set()
        app.close()
        server.server_close()


if __name__ == "__main__":
    main()
