from http.client import HTTPConnection
from pathlib import Path
import json
import select
import tempfile
import threading
import time
import unittest

from laboratory.server import Handler, Laboratory, LocalServer
from test_core import NoTelegram


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent / ".tmp")
        self.app = Laboratory(self.temp.name, runner=lambda *args: {}, telegram_factory=NoTelegram)
        self.server = LocalServer(("127.0.0.1", 0), Handler)
        self.server.app = self.app
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.app.close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        payload = json.dumps(body) if body is not None else None
        conn.request(method, path, payload, headers or {})
        result = conn.getresponse()
        status, data = result.status, result.read()
        conn.close()
        return status, data

    def test_csrf_origin_and_host_protection(self):
        body = {"text": "ИИ материал"}
        self.assertEqual(self.request("POST", "/api/sources", body)[0], 403)
        headers = {"X-Lab-Token": self.app.csrf, "Origin": "https://evil.example"}
        self.assertEqual(self.request("POST", "/api/sources", body, headers)[0], 403)
        self.assertEqual(self.request("GET", "/api/bootstrap", headers={"Host": "evil.example"})[0], 400)
        self.assertEqual(self.app.store.counts()["sources"], 0)

    def test_early_403_drains_fragmented_body_before_closing_without_mutation(self):
        entered = threading.Event()
        class ObservedHandler(Handler):
            def check_host(handler):
                super().check_host()
                entered.set()
        self.server.RequestHandlerClass = ObservedHandler
        payload = b'{"text":"' + b'x' * 16000 + b'"}'
        for origin in (None, "https://evil.example"):
            entered.clear()
            conn = HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
            try:
                conn.putrequest("POST", "/api/sources")
                conn.putheader("Content-Length", str(len(payload)))
                if origin:
                    conn.putheader("Origin", origin)
                    conn.putheader("X-Lab-Token", self.app.csrf)
                conn.endheaders(payload[:20])
                self.assertTrue(entered.wait(1))
                # The response must wait for the body, instead of closing a
                # Windows socket while its remaining bytes are still arriving.
                self.assertFalse(select.select([conn.sock], [], [], 0.03)[0])
                conn.send(payload[20:])
                response = conn.getresponse()
                self.assertEqual(response.status, 403)
                self.assertIn("error", json.loads(response.read()))
            finally:
                conn.close()
        self.assertEqual(self.app.store.counts()["sources"], 0)

    def test_early_403_drain_has_deadline_and_rejects_oversized_length(self):
        for length in (32, 65537):
            conn = HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
            started = time.monotonic()
            try:
                conn.putrequest("POST", "/api/sources")
                conn.putheader("Content-Length", str(length))
                conn.endheaders()  # Deliberately omit the declared body.
                response = conn.getresponse()
                self.assertEqual(response.status, 403)
                response.read()
                self.assertLess(time.monotonic() - started, 1.5)
            finally:
                conn.close()
        self.assertEqual(self.app.store.counts()["sources"], 0)

    def test_private_database_and_secret_files_are_never_served(self):
        for path in ["/.lab-data/laboratory.sqlite3", "/.telegram-token.dpapi", "/../core.py", "/.git/config"]:
            self.assertEqual(self.request("GET", path)[0], 404)

    def test_bootstrap_source_and_static_workflow(self):
        status, payload = self.request("GET", "/api/bootstrap")
        self.assertEqual(status, 200)
        token = json.loads(payload)["csrf"]
        status, payload = self.request("POST", "/api/sources", {"text": "ИИ <script>alert(1)</script>"}, {"X-Lab-Token": token})
        self.assertEqual(status, 200)
        self.assertIn("<script>", json.loads(payload)["text"])
        self.assertEqual(self.request("GET", "/")[0], 200)

    def test_memory_http_flow_uses_one_frozen_research_call(self):
        calls = []
        def runner(plan, prompt, work_dir, cancel):
            calls.append((plan, prompt))
            return {"status": "completed", "text": "ИИ: память retrieval полезна при проверенных источниках.\n<lab_memory_review>{\"comparisons\":[]}</lab_memory_review>"}
        self.app.runner = runner
        headers = {"X-Lab-Token": self.app.csrf}
        def post(path, body):
            status, result = self.request("POST", path, body, headers)
            self.assertEqual(status, 200, result)
            return json.loads(result)
        profile = json.loads(self.request("GET", "/api/memory")[1])["profile"]
        post("/api/memory/profile", {"expected_version": profile["version"], "interests": "ИИ память агентов"})
        post("/api/memory/corrections", {"text": "Отмечать ограничения доказательств"})
        source = post("/api/sources", {"text": "ИИ: retrieval memory со ссылками", "title": "Memory"})
        values = {"question": "Как проверить память RAG?", "source_ids": [source["id"]]}
        self.assertEqual(post("/api/memory/preview", values)["profile"]["interests"], "ИИ память агентов")
        run = post("/api/plans", values)
        self.assertEqual(calls, [])
        approved = {"consent": True, "plan_hash": run["plan_hash"], "command_id": "memory-http-command"}
        post(f"/api/runs/{run['id']}/start", approved)
        deadline = time.monotonic() + 3
        while self.app.jobs and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0]["memory"], run["plan"]["memory"])
        self.assertIn("Отмечать ограничения доказательств", calls[0][1])
        post(f"/api/runs/{run['id']}/start", approved)
        self.assertEqual(len(calls), 1)
        finding = post(f"/api/runs/{run['id']}/save", {"title": "Память агентов"})
        history = json.loads(self.request("GET", f"/api/memory/{finding['id']}")[1])
        self.assertEqual(history["current"]["version"], 1)
        post(f"/api/memory/{finding['id']}/revise", {"expected_version": 1, "claim": "RAG требует проверки качества поиска"})
        refreshed = post(f"/api/memory/{finding['id']}/refresh-plan", {})
        self.assertTrue(refreshed["plan"]["web_search"])
        self.assertEqual(refreshed["plan"]["memory_options"]["refresh_id"], finding["id"])
        self.assertEqual(len(calls), 1)

    def test_memory_version_error_prevents_dispatch_and_requires_rebuild(self):
        headers = {"X-Lab-Token": self.app.csrf}
        source = self.app.store.add_source("ИИ память retrieval")[0]
        run = self.app.store.create_plan({"source_ids": [source["id"]]})
        self.app.store.memory.save_profile({"expected_version": 1, "goals": "Проверять память"})
        approval = {"consent": True, "plan_hash": run["plan_hash"], "command_id": "memory-stale-command"}
        self.assertEqual(self.request("POST", f"/api/runs/{run['id']}/start", approval, headers)[0], 400)
        self.assertFalse(self.app.jobs)
        status, payload = self.request("POST", f"/api/plans/{run['id']}/memory", {"memory_options": {"selected_ids": []}}, headers)
        self.assertEqual(status, 200)
        rebuilt = json.loads(payload)
        self.assertNotEqual(rebuilt["plan_hash"], run["plan_hash"])
        self.assertEqual(rebuilt["plan"]["memory"]["profile"]["goals"], "Проверять память")

    def test_task_catalog_and_combined_context_http_versioning(self):
        headers = {"X-Lab-Token": self.app.csrf}
        status, payload = self.request("GET", "/api/study/schema")
        self.assertEqual(status, 200)
        body = json.loads(payload)["template"]
        body.update(title="TEST_ONLY бизнес-задача", business_goal="Сократить проверку ИИ материалов", task_type="tool_use")
        body["baseline"]["name"] = "Ручная проверка"
        self.assertEqual(self.request("POST", "/api/tasks", {"body": body})[0], 403)
        status, payload = self.request("POST", "/api/tasks", {"body": body}, headers)
        self.assertEqual(status, 200, payload)
        task = json.loads(payload)
        source = self.app.store.add_source("TEST_ONLY Harness для ИИ агентов")[0]
        status, payload = self.request("POST", "/api/plans", {"source_ids": [source["id"]], "task_id": task["id"]}, headers)
        self.assertEqual(status, 200, payload)
        run = json.loads(payload)
        self.assertEqual(run["plan"]["study_context"]["task"]["business_goal"], body["business_goal"])
        self.assertIn("memory", run["plan"])
        body["baseline"]["name"] = "Текущий процесс изменился"
        self.assertEqual(self.request("POST", "/api/tasks", {"id": task["id"], "expected_version": 1, "body": body}, headers)[0], 200)
        status, payload = self.request("POST", f"/api/plans/{run['id']}/context", {"task_id": task["id"]}, headers)
        self.assertEqual(status, 200, payload)
        self.assertNotEqual(json.loads(payload)["plan_hash"], run["plan_hash"])
        history = json.loads(self.request("GET", f"/api/tasks/{task['id']}")[1])
        self.assertEqual(len(history["history"]), 2)
        self.assertEqual(len(json.loads(self.request("GET", "/api/tasks")[1])["items"]), 1)
        self.assertFalse(self.app.jobs)


if __name__ == "__main__":
    unittest.main()
