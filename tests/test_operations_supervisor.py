"""Offline operational tests: no real HTTP, child process, model or Telegram."""
import http.client
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from laboratory import operations_supervisor as ops


class OperationsSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project, self.data = self.root/'project', self.root/'data'
        self.project.mkdir(); self.data.mkdir()
        self.config = ops.Config(self.project, self.data, poll_seconds=2, health_timeout=.2,
                                 startup_grace=5, backoff_seconds=5, max_backoff_seconds=20)
        self.now = 0
        self.records = []
        self.children = []
        self.health = Mock(return_value='unavailable')
        self.occupied = Mock(return_value=False)
        self.start = Mock(side_effect=self.new_child)

    def new_child(self, _config):
        child = Mock(pid=100+len(self.children))
        child.poll.return_value = None
        child.terminate.side_effect = AssertionError('Must never terminate a server.')
        child.kill.side_effect = AssertionError('Must never kill a server.')
        self.children.append(child)
        return child

    def supervisor(self, **changes):
        return ops.Supervisor(self.config, health=self.health, occupied=self.occupied,
                              start=self.start, monotonic=lambda: self.now,
                              heartbeat=lambda _config, value: self.records.append(value), **changes)

    def payload(self, **changes):
        return {'project': ops.PROJECT, 'root': str(self.project), 'data_dir': str(self.data), **changes}

    def test_health_requires_exact_project_data_and_configured_port(self):
        self.assertTrue(ops.health_matches(self.payload(), self.config))
        self.assertTrue(ops.health_matches(self.payload(port=self.config.port), self.config))
        for payload in (None, [], self.payload(project='other'), self.payload(root=str(self.root)),
                        self.payload(data_dir=str(self.root)), self.payload(port=1234),
                        self.payload(port=True), self.payload(root=None)):
            with self.subTest(payload=payload):
                self.assertFalse(ops.health_matches(payload, self.config))

    def test_health_is_bounded_loopback_get_and_ignores_secret_fields(self):
        connection = Mock()
        response = connection.getresponse.return_value
        response.status = 200
        response.read.return_value = json.dumps(self.payload(csrf='SECRET', token='SECRET')).encode()
        with patch.object(http.client, 'HTTPConnection', return_value=connection) as create:
            self.assertEqual(ops.read_health(self.config), 'healthy')
        create.assert_called_once_with('127.0.0.1', self.config.port, timeout=.2)
        self.assertEqual(connection.request.call_args.args[:2], ('GET', '/api/health'))
        response.read.assert_called_once_with(16385)
        connection.close.assert_called_once()
        for content in (b'x'*16385, b'not json', b'[]', json.dumps(self.payload(project='other')).encode()):
            response.read.return_value = content
            with patch.object(http.client, 'HTTPConnection', return_value=connection):
                self.assertEqual(ops.read_health(self.config), 'foreign')

    def test_timeout_or_redirect_never_follows_another_endpoint(self):
        connection = Mock()
        connection.getresponse.side_effect = TimeoutError('SECRET must not be logged')
        with patch.object(http.client, 'HTTPConnection', return_value=connection):
            self.assertEqual(ops.read_health(self.config), 'unavailable')
        connection.getresponse.side_effect = None
        connection.getresponse.return_value.status = 302
        connection.request.reset_mock()
        with patch.object(http.client, 'HTTPConnection', return_value=connection):
            self.assertEqual(ops.read_health(self.config), 'unavailable')
        connection.request.assert_called_once()

    def test_only_connection_refused_proves_port_closed(self):
        for error, expected in ((ConnectionRefusedError(), False), (TimeoutError(), True), (OSError(), True)):
            with patch.object(socket, 'create_connection', side_effect=error):
                self.assertEqual(ops.port_occupied(self.config), expected)

    def test_child_is_hidden_exact_module_no_browser_and_no_raw_output_logs(self):
        with patch.dict(os.environ, {'PYTHONPATH': 'OTHER_PROJECT', 'PYTHONHOME': 'OTHER_RUNTIME'}), \
                patch.object(subprocess, 'Popen') as launch:
            ops.start_server(self.config)
        command = launch.call_args.args[0]
        options = launch.call_args.kwargs
        self.assertEqual(command, [str(self.config.python), '-E', '-m', 'laboratory', '--no-browser',
                                   '--data-dir', str(self.data), '--port', str(self.config.port)])
        self.assertEqual(options['cwd'], str(self.project))
        self.assertEqual(options['stdout'], subprocess.DEVNULL)
        self.assertEqual(options['stderr'], subprocess.DEVNULL)
        self.assertNotIn('PYTHONPATH', options['env']); self.assertNotIn('PYTHONHOME', options['env'])
        self.assertEqual(options['env']['LAB_OPERATIONS_STOP_FILE'], str(self.config.stop_file))
        if os.name == 'nt':
            self.assertEqual(options['creationflags'], subprocess.CREATE_NO_WINDOW)

    def test_existing_exact_healthy_server_is_monitored_without_start_or_kill(self):
        self.health.return_value = 'healthy'
        supervisor = self.supervisor()
        for _ in range(4):
            self.assertEqual(supervisor.tick(), (2, None))
        self.start.assert_not_called(); self.occupied.assert_not_called()
        self.assertEqual(self.records[-1]['status'], 'healthy')
        self.assertIsNone(self.records[-1]['owned_child_pid'])

    def test_foreign_identity_exits_without_starting_or_touching_server(self):
        self.health.return_value = 'foreign'
        self.assertEqual(self.supervisor().tick()[1], 3)
        self.start.assert_not_called()
        self.assertEqual(self.records[-1]['status'], 'port_conflict')

    def test_occupied_unverified_port_gets_retries_then_exits(self):
        self.occupied.return_value = True
        supervisor = self.supervisor()
        self.assertIsNone(supervisor.tick()[1]); self.assertIsNone(supervisor.tick()[1])
        self.assertEqual(supervisor.tick()[1], 3)
        self.start.assert_not_called()
        self.assertEqual(self.records[-1]['status'], 'port_unverified')

    def test_slow_health_on_previously_verified_server_never_restarts_it(self):
        supervisor = self.supervisor()
        self.health.return_value = 'healthy'; supervisor.tick()
        self.health.return_value = 'unavailable'; self.occupied.return_value = True
        for index in range(30):
            self.now = index*2
            self.assertIsNone(supervisor.tick()[1])
        self.start.assert_not_called()
        self.assertEqual(self.records[-1]['status'], 'degraded')

    def test_alive_owned_child_is_not_replaced_for_closed_port_or_slow_health(self):
        supervisor = self.supervisor(); supervisor.tick()
        for occupied in (False, True):
            self.occupied.return_value = occupied
            self.now = 100
            for _ in range(6):
                self.assertIsNone(supervisor.tick()[1])
        self.start.assert_called_once()
        self.children[0].kill.assert_not_called(); self.children[0].terminate.assert_not_called()
        self.assertEqual(self.records[-1]['status'], 'degraded')

    def test_exited_child_restarts_with_backoff_and_finite_budget(self):
        self.config = ops.Config(self.project, self.data, max_restarts=1, poll_seconds=2)
        supervisor = self.supervisor(); supervisor.tick()
        self.children[0].poll.return_value = 1
        self.assertIsNone(supervisor.tick()[1])
        self.assertEqual(self.records[-1]['status'], 'backoff')
        self.now = 4; supervisor.tick(); self.start.assert_called_once()
        self.now = 5; supervisor.tick(); self.assertEqual(self.start.call_count, 2)
        self.children[1].poll.return_value = 1
        self.now = 6; supervisor.tick()
        self.assertEqual(supervisor.next_start, 16)
        self.now = 16
        self.assertEqual(supervisor.tick()[1], 4)
        self.assertEqual(self.records[-1]['status'], 'restart_limit')
        self.assertEqual(self.start.call_count, 2)

    def test_failed_launch_is_bounded_and_does_not_log_exception_text(self):
        self.config = ops.Config(self.project, self.data, max_restarts=0, poll_seconds=2)
        self.start.side_effect = OSError('api_key=SECRET https://secret.example/?token=SECRET')
        supervisor = self.supervisor(); supervisor.tick()
        self.assertEqual(self.records[-1]['status'], 'start_failed')
        self.now = 5
        self.assertEqual(supervisor.tick()[1], 4)
        self.assertNotIn('SECRET', json.dumps(self.records))
        self.assertNotIn('api_key', json.dumps(self.records))

    def test_port_winner_between_probe_and_spawn_is_not_replaced(self):
        self.occupied.side_effect = [False, True]
        self.assertIsNone(self.supervisor().tick()[1])
        self.start.assert_not_called()

    def test_intentional_stop_and_signal_leave_owned_child_running(self):
        supervisor = self.supervisor(); supervisor.tick()
        self.config.stop_file.write_text('stop', encoding='utf-8')
        self.health.reset_mock()
        self.assertEqual(supervisor.tick()[1], 0)
        self.health.assert_not_called(); self.start.assert_called_once()
        self.children[0].terminate.assert_not_called(); self.children[0].kill.assert_not_called()
        self.config.stop_file.unlink()
        supervisor.stop.set()
        self.assertEqual(supervisor.tick()[1], 0)

    def test_intentional_stop_race_is_checked_again_before_launch(self):
        def occupied(_config):
            if self.occupied.call_count == 2:
                self.config.stop_file.write_text('stop', encoding='utf-8')
            return False
        self.occupied.side_effect = occupied
        self.assertEqual(self.supervisor().tick()[1], 0)
        self.start.assert_not_called()
        with patch.object(subprocess, 'Popen') as launch:
            with self.assertRaises(OSError):
                ops.start_server(self.config)
        launch.assert_not_called()

    def test_heartbeat_is_atomic_allowlisted_and_outside_data_backup(self):
        self.assertEqual(self.config.state_dir, self.project/'.lab-operations')
        supervisor = ops.Supervisor(self.config, health=Mock(return_value='healthy'))
        supervisor.tick()
        record = json.loads((self.config.state_dir/'readiness.json').read_text(encoding='utf-8'))
        self.assertEqual(record['status'], 'healthy')
        self.assertEqual(set(record), {'schema', 'updated_at', 'status', 'project', 'root', 'data_dir', 'host', 'port',
                                      'supervisor_pid', 'owned_child_pid', 'start_attempts', 'health_failures'})
        self.assertFalse((self.config.state_dir/'readiness.json.tmp').exists())
        self.assertFalse((self.data/'readiness.json').exists())

    def test_logs_rotate_and_only_contain_allowlisted_status_events(self):
        logger = ops.operations_logger(self.config)
        try:
            self.start.side_effect = OSError('SECRET')
            self.supervisor(logger=logger).tick()
            handler = logger.handlers[0]
            self.assertEqual(handler.maxBytes, 256*1024); self.assertEqual(handler.backupCount, 3)
            handler.flush()
            log = (self.config.state_dir/'supervisor.log').read_text(encoding='utf-8')
            self.assertIn('state=start_failed', log); self.assertNotIn('SECRET', log)
        finally:
            for handler in logger.handlers[:]:
                handler.close(); logger.removeHandler(handler)

    def test_os_lock_is_exclusive_and_released_without_pid_guessing(self):
        path = self.project/'watchdog.lock'
        with ops.SupervisorLock(path):
            with self.assertRaises(ops.AlreadySupervised):
                with ops.SupervisorLock(path):
                    self.fail('Second watchdog entered the same OS lock.')
        with ops.SupervisorLock(path):
            pass
        self.assertEqual(path.read_bytes(), b'0')

    def test_main_rejects_other_project_before_any_supervisor_or_process(self):
        with patch.object(ops, 'SupervisorLock') as lock, patch.object(subprocess, 'Popen') as launch, \
                patch('sys.stderr', new=io.StringIO()):
            with self.assertRaises(SystemExit):
                ops.main(['--project-dir', str(self.project), '--data-dir', str(self.data)])
        lock.assert_not_called(); launch.assert_not_called()

    def test_run_waits_between_ticks_and_signal_stops_without_busy_loop(self):
        supervisor = self.supervisor()
        supervisor.tick = Mock(side_effect=[(5, None), (2, 0)])
        supervisor.stop = Mock()
        self.assertEqual(supervisor.run(), 0)
        supervisor.stop.wait.assert_called_once_with(5)


if __name__ == '__main__':
    unittest.main()
