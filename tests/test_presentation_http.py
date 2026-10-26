"""Fixture-only presentation/download and explicit Telegram endpoints."""
from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import threading
import unittest

from laboratory.server import Handler, Laboratory, LocalServer
from test_core import NoTelegram


class FixtureTelegram(NoTelegram):
    def __init__(self, *args):
        self.bound = False
        self.sent_plans = []
        self.sent_results = []

    def bind_workflow(self, start_run, cancel_run, builder):
        self.bound = callable(start_run) and callable(cancel_run) and callable(builder)

    def present_plan(self, run_id):
        self.sent_plans.append(run_id)
        return {'status': 'sent', 'run_id': run_id}

    def send_result(self, run_id):
        self.sent_results.append(run_id)
        return {'status': 'sent', 'run_id': run_id}


class PresentationHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Laboratory(self.temp.name, runner=lambda *args: {}, telegram_factory=FixtureTelegram)
        self.server = LocalServer(('127.0.0.1', 0), Handler)
        self.server.app = self.app
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        source = self.app.store.add_source('TEST_ONLY ИИ технология; <script>alert(1)</script>')[0]
        self.run = self.app.store.create_plan({'source_ids': [source['id']], 'question': 'TEST_ONLY AI applicability'})

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.app.close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, method, path, body=None, auth=True):
        conn = HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        headers = {'X-Lab-Token': self.app.csrf} if auth else {}
        conn.request(method, path, json.dumps(body) if body is not None else None, headers)
        response = conn.getresponse()
        result = response.status, response.getheaders(), response.read()
        conn.close()
        return result

    def complete_fixture(self):
        self.app.store.approve(self.run['id'], self.run['plan_hash'], True, 'TEST_ONLY-presentation')
        self.app.store.finish(self.run['id'], {'status': 'completed', 'text':
            '## Краткий вывод\nTEST_ONLY: требуется проверка.\n\n## Применимость к задаче\n'
            'TEST_ONLY: сравнить с baseline.\n<lab_memory_review>{"comparisons":[]}</lab_memory_review>'})

    def test_presentation_requires_completed_report(self):
        status, _, _ = self.request('GET', '/api/runs/' + self.run['id'] + '/presentation')
        self.assertEqual(status, 400)
        self.assertFalse(self.app.jobs)

    def test_exports_are_nonexecuting_and_preserve_original_report(self):
        self.complete_fixture()
        prefix = '/api/runs/' + self.run['id'] + '/'
        status, _, body = self.request('GET', prefix + 'presentation')
        self.assertEqual(status, 200)
        presentation = json.loads(body)
        self.assertTrue(presentation['visual']['svg_available'])
        self.assertIn('post_text', presentation)
        for artifact, mime in [('card.svg', 'image/svg+xml'), ('post.txt', 'text/plain'), ('report.txt', 'text/plain')]:
            status, headers, body = self.request('GET', prefix + artifact)
            self.assertEqual(status, 200)
            self.assertTrue(dict(headers)['Content-Type'].startswith(mime))
            self.assertIn('attachment', dict(headers)['Content-Disposition'])
            self.assertGreater(len(body), 10)
            if artifact == 'report.txt':
                self.assertNotIn(b'lab_memory_review', body)
                self.assertIn(b'TEST_ONLY', body)
        if presentation['visual']['png_available']:
            self.assertTrue(self.request('GET', prefix + 'card.png')[2].startswith(b'\x89PNG'))
            self.assertTrue(self.request('GET', prefix + 'animation.gif')[2].startswith(b'GIF'))
        self.assertIn('lab_memory_review', self.app.store.run(self.run['id'])['output'])
        self.assertFalse(self.app.jobs)

    def test_telegram_actions_require_local_csrf_and_do_not_dispatch_research(self):
        self.assertTrue(self.app.telegram.bound)
        body = {'run_id': self.run['id']}
        for action in ('plans', 'results'):
            self.assertEqual(self.request('POST', '/api/telegram/' + action, body, auth=False)[0], 403)
            self.assertEqual(self.request('POST', '/api/telegram/' + action, body)[0], 200)
        self.assertEqual(self.app.telegram.sent_plans, [self.run['id']])
        self.assertEqual(self.app.telegram.sent_results, [self.run['id']])
        self.assertEqual(self.app.store.run(self.run['id'])['status'], 'planned')
        self.assertFalse(self.app.jobs)


if __name__ == '__main__':
    unittest.main()
