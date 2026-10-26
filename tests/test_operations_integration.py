"""TEST_ONLY maintenance and loopback APIs; no models or Telegram delivery."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from laboratory.core import LabError, canonical, digest
from laboratory.operations import Operations, mark_intentional_stop, stop_file, main as operations_main
from laboratory import operations_supervisor as supervisor
from laboratory.publication import CONFIG_KEY, QUEUE_KEY
from laboratory.server import Handler, InstanceLock, Laboratory, LocalServer, main
from test_core import NoTelegram
import test_publication as fixtures


class LockedNoTelegram(NoTelegram):
    def __init__(self, *args):
        self._configure_lock = threading.Lock()


class OperationsIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=Path(__file__).parent / '.tmp')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.calls = Mock(side_effect=AssertionError('TEST_ONLY no model calls'))
        with patch('laboratory.server.ROOT', self.base):
            self.app = Laboratory(self.base / '.lab-data', runner=self.calls,
                                  telegram_factory=LockedNoTelegram)
        self.addCleanup(self.app.close)
        self.store = self.app.store
        self.run = fixtures.PublicationTests.complete(self)
        self.now = datetime(2026, 10, 24, tzinfo=timezone.utc)
        self.ops = self.app.operations
        self.ops.backups.clock = lambda: self.now
        self.server = None
        self.tick_guard = patch.object(self.app.publisher, 'tick',
                                       side_effect=AssertionError('No publication tick'))
        self.tick = self.tick_guard.start()
        self.addCleanup(self.tick_guard.stop)
        self.saved_queue()
        self.before = self.store.run(self.run['id'], include_raw=True)
        self.queue_before = self.store.get_setting(QUEUE_KEY)

    def saved_queue(self):
        identifier = 'A' * 16
        directory = self.store.data_dir / 'publications' / identifier
        directory.mkdir(parents=True)
        files = {}
        for name in ('post.txt', 'card.png', 'animation.mp4'):
            content = ('TEST_ONLY ' + name).encode()
            (directory / name).write_bytes(content)
            files[name] = {'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content)}
        binding = {'owner_id': 42, 'fingerprint': 'TEST_ONLY', 'channel_id': -100123}
        manifest = {'binding': binding, 'files': files, 'run_id': self.run['id']}
        (directory / 'manifest.json').write_text(canonical(manifest), encoding='utf-8')
        self.store.set_setting(QUEUE_KEY, {identifier: {
            'id': identifier, 'run_id': self.run['id'], 'binding': binding, 'files': files,
            'package_sha256': digest(manifest), 'state': 'queued', 'due_at': 'TEST_ONLY slot',
            'approved_at': 'TEST_ONLY approval', 'created_at': 'TEST_ONLY creation',
            'title': 'TEST_ONLY queued result', 'post_text': 'TEST_ONLY exact saved post.',
            'receipts': [], 'token': 'TEST_ONLY_CALLBACK', 'reason': None}})
        self.store.set_setting(CONFIG_KEY, {'enabled': True, 'timezone': 'Europe/Moscow',
                                           'slots': [], 'channel': {'id': -100123}})

    def unchanged(self):
        self.assertEqual(self.store.run(self.run['id'], include_raw=True), self.before)
        self.assertEqual(self.store.get_setting(QUEUE_KEY), self.queue_before)
        self.calls.assert_not_called()
        self.tick.assert_not_called()

    def request(self, path, body=None, csrf=True):
        if self.server is None:
            self.server = LocalServer(('127.0.0.1', 0), Handler)
            self.server.app = self.app
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            self.addCleanup(self.close_server)
        connection = HTTPConnection('127.0.0.1', self.server.server_port, timeout=15)
        headers = {'Content-Type': 'application/json'}
        if csrf:
            headers['X-Lab-Token'] = self.app.csrf
        connection.request('POST' if body is not None else 'GET', path,
                           json.dumps(body) if body is not None else None, headers)
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        connection.close()
        return result

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_daily_maintenance_creates_verified_backup_and_drill_once_per_day(self):
        with patch.object(self.ops.backups, 'create', wraps=self.ops.backups.create) as create, \
                patch.object(self.ops.backups, 'drill', wraps=self.ops.backups.drill) as drill:
            first = self.ops.maintenance_once()
            second = self.ops.maintenance_once()
            self.assertEqual(first['backup']['latest'], second['backup']['latest'])
            self.assertEqual(create.call_count, 1)
            self.assertEqual(drill.call_count, 1)
            self.now += timedelta(days=1)
            third = self.ops.maintenance_once()
            self.assertEqual(create.call_count, 2)
            self.assertEqual(drill.call_count, 2)
        report = third['restore_drill']
        self.assertTrue(report['snapshot_exact'])
        self.assertEqual(report['status'], 'passed')
        self.assertFalse(report['live_data_overwritten'])
        self.assertFalse(report['server_started'])
        self.assertEqual(list((self.ops.state_dir / 'restore-drills').iterdir()), [])
        self.assertEqual(third['maintenance']['model_calls'], 0)
        self.assertEqual(third['maintenance']['publication_sends'], 0)
        self.unchanged()

    def test_backups_use_bridge_configuration_lock_and_controls_are_not_truth(self):
        self.assertIs(self.ops.snapshot_lock, self.app.telegram._configure_lock)
        create = self.ops.backups.create

        def guarded_create():
            self.assertTrue(self.app.telegram._configure_lock.locked())
            return create()

        with patch.object(self.ops.backups, 'create', side_effect=guarded_create):
            result = self.ops.maintenance_once()
        controls = result['quality_controls']
        self.assertTrue(controls['test_only'])
        self.assertEqual(controls['case_count'], 10)
        self.assertEqual(controls['matched_case_count'], 10)
        self.assertTrue(all(case['test_only'] for case in controls['cases']))
        self.assertIn('не научная', controls['notice'])
        self.assertNotIn('scientific_accuracy', controls)
        self.unchanged()

    def test_safe_copy_failure_uses_error_backoff_instead_of_completed_minute_loop(self):
        with patch.object(self.ops.backups, '_verify', side_effect=OSError('TEST_ONLY copy failure')), \
                patch.object(self.ops.stop_event, 'wait', return_value=True) as wait:
            self.ops._loop()
        wait.assert_called_once_with(15 * 60)
        maintenance = json.loads((self.ops.state_dir / 'maintenance.json').read_text(encoding='utf-8'))
        self.assertEqual(maintenance['status'], 'error')
        self.assertEqual(maintenance['error_type'], 'ValueError')
        self.assertIsNone(self.ops.backups.status()['latest'])
        self.assertFalse((self.ops.state_dir / 'restore-drill.json').exists())
        self.unchanged()

    def test_status_and_quality_reads_do_not_create_maintenance_artifacts_or_mutate_run(self):
        self.assertFalse(self.ops.state_dir.exists())
        for _ in range(2):
            self.assertEqual(self.request('/api/operations')[0], 200)
            code, quality = self.request('/api/runs/' + self.run['id'] + '/quality')
            self.assertEqual(code, 200)
            self.assertFalse(quality['independent_verification'])
            self.assertFalse(quality['publication_approved'])
            self.assertEqual(quality['run_id'], self.run['id'])
        self.assertFalse(self.ops.state_dir.exists())
        self.assertFalse(self.ops.backups.root.exists())
        self.unchanged()

    def test_concept_html_has_isolated_policy_without_weakening_live_api(self):
        self.request('/api/operations')  # Start this test's isolated loopback server.
        concepts = self.base / 'deliverables/ui/frontier-future'
        concepts.mkdir(parents=True)
        html_names = ('index.html', 'lens.html', 'atlas.html', 'story.html',
                      'v2.html', 'reactor.html', 'observatory.html', 'dispatch.html')
        for name in html_names:
            (concepts / name).write_text('<!doctype html><title>TEST_ONLY</title>', encoding='utf-8')
        (concepts / 'workbench.js').write_text('// TEST_ONLY', encoding='utf-8')
        (concepts / 'workbench.css').write_text('/* TEST_ONLY */', encoding='utf-8')
        def raw(path):
            connection = HTTPConnection('127.0.0.1', self.server.server_port, timeout=15)
            connection.request('GET', path)
            response = connection.getresponse()
            result = (response.status, response.getheader('Content-Security-Policy'),
                      response.read(), response.getheader('Content-Type'))
            connection.close()
            return result
        with patch('laboratory.server.ROOT', self.base):
            for path in ('/concepts/', *('/concepts/' + name for name in html_names[1:])):
                status, policy, content, content_type = raw(path)
                self.assertEqual(status, 200)
                self.assertIn(b'TEST_ONLY', content)
                self.assertEqual(content_type, 'text/html; charset=utf-8')
                self.assertIn("connect-src 'none'", policy)
                self.assertIn("form-action 'none'", policy)
            for extension, kind in (('js', 'text/javascript'), ('css', 'text/css')):
                status, policy, content, content_type = raw('/concepts/workbench.' + extension)
                self.assertEqual(status, 200)
                self.assertEqual(content_type, kind + '; charset=utf-8')
                self.assertIn("connect-src 'none'", policy)
            for path in ('/concepts/arbitrary.html', '/concepts/../laboratory.sqlite3'):
                self.assertEqual(raw(path)[0], 404)
            status, policy, content, content_type = raw('/api/health')
            self.assertEqual(status, 200)
            self.assertNotIn('unsafe-inline', policy)
            self.assertIn("connect-src 'self'", policy)
        self.unchanged()

    def test_backup_http_requires_csrf_empty_body_and_returns_real_verified_drill(self):
        self.assertEqual(self.request('/api/operations/backup', {}, csrf=False)[0], 403)
        self.assertEqual(self.request('/api/operations/backup', {'destination': 'ignored'})[0], 400)
        self.assertFalse(self.ops.backups.root.exists())
        code, result = self.request('/api/operations/backup', {})
        self.assertEqual(code, 200, result)
        self.assertEqual(result['backup']['complete_count'], 1)
        self.assertEqual(result['restore_drill']['status'], 'passed')
        self.assertTrue(result['restore_drill']['snapshot_exact'])
        self.unchanged()

    def test_live_frontier_assets_and_classic_keep_strict_csp_and_correct_types(self):
        self.request('/api/operations')
        for path in ('/', '/classic', '/assets/reactor.js', '/assets/reactor.css',
                     '/assets/observatory.js', '/assets/observatory.css',
                     '/assets/frontier-live.js', '/assets/frontier-shell.css'):
            connection = HTTPConnection('127.0.0.1', self.server.server_port, timeout=15)
            connection.request('GET', path)
            response = connection.getresponse()
            content = response.read()
            self.assertEqual(response.status, 200, path)
            self.assertTrue(content)
            policy = response.getheader('Content-Security-Policy')
            self.assertNotIn('unsafe-inline', policy)
            self.assertIn("connect-src 'self'", policy)
            kind = 'text/javascript' if path.endswith('.js') else 'text/css' if path.endswith('.css') else 'text/html'
            self.assertEqual(response.getheader('Content-Type'), kind + '; charset=utf-8')
            connection.close()
        self.unchanged()

    def test_fieldwork_routes_are_allowlisted_strict_csp_and_read_only(self):
        self.request('/api/operations')
        for path, kind in [('/workbench/', 'text/html; charset=utf-8'),
                           ('/workbench/library.js', 'text/javascript; charset=utf-8'),
                           ('/workbench/library.css', 'text/css; charset=utf-8'),
                           ('/workbench/fonts/Manrope.ttf', 'font/ttf')]:
            connection = HTTPConnection('127.0.0.1', self.server.server_port, timeout=15)
            connection.request('GET', path)
            response = connection.getresponse()
            content = response.read()
            self.assertEqual(response.status, 200, path)
            self.assertEqual(response.getheader('Content-Type'), kind)
            self.assertNotIn('unsafe-inline', response.getheader('Content-Security-Policy'))
            self.assertTrue(content)
            connection.close()
        self.assertEqual(self.request('/workbench/preview_server.py')[0], 404)
        self.assertEqual(self.request('/workbench/unknown.js')[0], 404)
        self.unchanged()

    def test_drill_http_rejects_unknown_ids_paths_extra_fields_and_missing_csrf(self):
        latest = self.ops.create_backup()['backup']['latest']['id']
        path = '/api/operations/drill'
        self.assertEqual(self.request(path, {'backup_id': latest}, csrf=False)[0], 403)
        bodies = [{}, {'backup_id': 1}, {'backup_id': '../outside'},
                  {'backup_id': 'backup-20000101T000000Z-00000000'},
                  {'backup_id': latest, 'destination': str(self.store.data_dir)}]
        for body in bodies:
            with self.subTest(body=body):
                self.assertEqual(self.request(path, body)[0], 400)
        code, result = self.request(path, {'backup_id': latest})
        self.assertEqual(code, 200, result)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['backup_id'], latest)
        self.assertEqual(list((self.ops.state_dir / 'restore-drills').iterdir()), [])
        self.unchanged()

    def test_failed_automatic_drill_is_not_recorded_as_passed_and_temp_is_cleaned(self):
        with patch.object(self.ops.backups, 'drill', side_effect=ValueError('TEST_ONLY failure')):
            with self.assertRaises(ValueError):
                self.ops.maintenance_once()
        self.assertFalse((self.ops.state_dir / 'restore-drill.json').exists())
        self.assertEqual(list((self.ops.state_dir / 'restore-drills').iterdir()), [])
        self.assertNotEqual(self.ops.status()['maintenance'].get('status'), 'completed')
        self.unchanged()

    def test_real_supervisor_heartbeat_updated_at_requires_current_identity_and_freshness(self):
        operations = Operations(self.store, self.base, port=4321)
        config = supervisor.Config(self.base, self.store.data_dir, port=4321)
        monitor = supervisor.Supervisor(config, health=Mock(return_value='healthy'),
                                        start=Mock(side_effect=AssertionError('No process start')))
        monitor.tick()
        path = config.state_dir / 'readiness.json'
        original = json.loads(path.read_text(encoding='utf-8'))
        accepted = operations.status()['supervisor']
        self.assertTrue(accepted['fresh'])
        self.assertEqual(accepted['checked_at'], original['updated_at'])
        self.assertEqual(accepted['status'], 'healthy')
        changes = [{'project': 'TEST_ONLY-other-project'}, {'port': 4322},
                   {'root': str(self.base / 'other')},
                   {'data_dir': str(self.base / 'other')},
                   {'updated_at': (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()},
                   {'updated_at': (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()}]
        for changed in changes:
            path.write_text(json.dumps({**original, **changed}), encoding='utf-8')
            self.assertFalse(operations.status()['supervisor']['fresh'])
        monitor.start.assert_not_called()
        self.unchanged()

    def test_managed_main_honors_intentional_stop_without_any_health_or_server_start(self):
        mark_intentional_stop(self.store.data_dir)
        marker = stop_file(self.store.data_dir)
        before = marker.read_bytes()
        args = ['laboratory', '--data-dir', str(self.store.data_dir), '--no-browser']
        with patch('sys.argv', args), patch.dict(os.environ, {
                'LAB_OPERATIONS_STOP_FILE': str(marker)}), \
                patch('laboratory.server.urlopen') as probe, \
                patch('laboratory.server.LocalServer') as serve, \
                patch('laboratory.server.Laboratory') as app:
            main()
        probe.assert_not_called()
        serve.assert_not_called()
        app.assert_not_called()
        self.assertEqual(marker.read_bytes(), before)
        self.unchanged()

    def test_custom_data_location_reads_supervisor_state_from_same_project_contract(self):
        project = self.base / 'separate-project'
        project.mkdir()
        operations = Operations(self.store, project, port=4321)
        config = supervisor.Config(project, self.store.data_dir, port=4321)
        monitor = supervisor.Supervisor(config, health=Mock(return_value='healthy'),
                                        start=Mock(side_effect=AssertionError('No process start')))
        monitor.tick()
        self.assertTrue((config.state_dir / 'readiness.json').exists())
        self.assertTrue(operations.status()['supervisor']['fresh'])
        monitor.start.assert_not_called()
        self.unchanged()

    def test_shutdown_http_marks_intentional_stop_only_after_csrf(self):
        self.assertEqual(self.request('/api/shutdown', {}, csrf=False)[0], 403)
        self.assertFalse(stop_file(self.store.data_dir).exists())
        code, result = self.request('/api/shutdown', {})
        self.assertEqual(code, 200)
        self.assertTrue(result['stopping'])
        datetime.fromisoformat(stop_file(self.store.data_dir).read_text(encoding='ascii'))
        self.unchanged()

    def test_backup_cli_refuses_active_instance_lock_before_copy_or_service_start(self):
        with InstanceLock(self.store.data_dir), \
                patch('laboratory.operational_backups.OperationalBackups.create') as create, \
                patch('laboratory.operations.start_supervisor') as launch, \
                patch('laboratory.server.Laboratory') as app:
            with self.assertRaises(LabError):
                operations_main(['backup', '--data-dir', str(self.store.data_dir)])
        create.assert_not_called()
        launch.assert_not_called()
        app.assert_not_called()
        self.assertFalse(self.ops.backups.root.exists())
        self.unchanged()


if __name__ == '__main__':
    unittest.main()
