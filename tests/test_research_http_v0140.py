from http.client import HTTPConnection
import json
from tempfile import TemporaryDirectory
import threading
import unittest

from laboratory.server import Handler, Laboratory, LocalServer
from test_core import NoTelegram


class ResearchHTTPTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()

        def forbidden(*args):
            self.fail('TEST_ONLY: no model dispatch is authorized by these HTTP tests')

        self.app = Laboratory(self.folder.name, runner=forbidden, telegram_factory=NoTelegram)
        self.server = LocalServer(('127.0.0.1', 0), Handler)
        self.server.app = self.app
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.app.close()
        self.thread.join()
        self.folder.cleanup()

    def request(self, method, path, body=None, authorized=True):
        connection = HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        headers = {'Content-Type': 'application/json'}
        if authorized:
            headers['X-Lab-Token'] = self.app.csrf
        connection.request(method, path, json.dumps(body) if body is not None else None, headers)
        response = connection.getresponse()
        raw = response.read()
        result = json.loads(raw) if 'json' in response.getheader('Content-Type', '') else raw
        connection.close()
        return response.status, result

    def test_workspace_and_pending_run_are_read_only_and_assets_are_served(self):
        source, _ = self.app.store.add_source('TEST_ONLY input', 'TEST_ONLY source')
        run = self.app.store.create_plan({'source_ids': [source['id']]})
        before = self.app.store.export()['tables']
        for _ in range(2):
            status, result = self.request('GET', '/api/research')
            self.assertEqual(status, 200)
            self.assertEqual(result['experiment_config']['configured'], False)
            self.assertEqual(result['evaluation']['coverage']['case_count'], 0)
            status, pending = self.request('GET', '/api/runs/' + run['id'] + '/research')
            self.assertEqual(status, 200)
            self.assertIsNone(pending['public_preview'])
        self.assertEqual(self.app.store.export()['tables'], before)
        status, script = self.request('GET', '/assets/research.js')
        self.assertEqual(status, 200)
        self.assertIn(b'LabResearch', script)

    def test_cost_has_csrf_and_unknown_prices_remain_unknown(self):
        inputs = {'requests': 1000, 'input_tokens': 1000, 'output_tokens': 100,
                  'input_usd_per_million': 1, 'output_usd_per_million': 2,
                  'fixed_cost_usd': 1}
        self.assertEqual(self.request('POST', '/api/research/cost', inputs, False)[0], 403)
        status, result = self.request('POST', '/api/research/cost', inputs)
        self.assertEqual(status, 200)
        self.assertEqual(result['estimated_cost_usd'], 2.2)
        status, result = self.request('POST', '/api/research/cost', {'requests': 1000})
        self.assertEqual(status, 200)
        self.assertIsNone(result['estimated_cost_usd'])

    def test_unconfigured_experiment_cannot_start_or_claim_paid_intent(self):
        values = {'cases': [{'id': 'TEST_ONLY', 'input': 'TEST_ONLY input'}],
                  'baseline': {'label': 'TEST_ONLY baseline', 'model': 'TEST_ONLY'},
                  'candidate': {'label': 'TEST_ONLY candidate', 'model': 'TEST_ONLY'}}
        status, plan = self.request('POST', '/api/research/experiments/plan', values)
        self.assertEqual(status, 200)
        status, result = self.request('POST', '/api/research/experiments/start', {
            'plan_id': plan['plan_id'], 'plan_hash': plan['plan_hash'],
            'consent': True, 'command_id': 'TEST_ONLY-start'})
        self.assertEqual(status, 400)
        self.assertIn('API', result['error'])
        self.assertEqual(self.app.store.assets.list('experiment_intent'), [])
        self.assertEqual(self.app.store.assets.list('experiment_approval'), [])
        self.assertEqual(self.app.store.settings()['daily_run_limit'], 3)


if __name__ == '__main__':
    unittest.main()
