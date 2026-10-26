"""Conservative per-user watchdog for this project's local HTTP server only.

It reads health, starts the configured application on a closed port, and writes
operational status. It never retries research, publishes, or terminates a server.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import http.client
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time


PROJECT = 'AI-R-D-laboratory'
MODULE_ROOT = Path(__file__).resolve().parents[1]
STOP_NAME = '.operations-stop'


def _path_key(value):
    return os.path.normcase(os.path.abspath(os.path.normpath(str(value))))


def default_state_dir(project_dir, data_dir, port):
    # This project lives in the owner's workspace. Keep dynamic locks/logs out
    # of the data directory and its backups; one watchdog owns the project.
    return Path(project_dir) / '.lab-operations'


@dataclass(frozen=True)
class Config:
    project_dir: Path
    data_dir: Path
    port: int = 8795
    state_dir: Path | None = None
    python: Path = Path(sys.executable)
    stop_file: Path | None = None
    poll_seconds: float = 15
    health_timeout: float = 3
    startup_grace: float = 60
    health_retries: int = 3
    max_restarts: int = 5
    backoff_seconds: float = 5
    max_backoff_seconds: float = 300

    def __post_init__(self):
        for field in ('project_dir', 'data_dir', 'python'):
            object.__setattr__(self, field, Path(getattr(self, field)).resolve())
        object.__setattr__(self, 'state_dir', Path(self.state_dir).resolve() if self.state_dir
                           else default_state_dir(self.project_dir, self.data_dir, self.port))
        object.__setattr__(self, 'stop_file', Path(self.stop_file).resolve() if self.stop_file
                           else self.data_dir / STOP_NAME)
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError('Port must be between 1 and 65535.')
        if not (1 <= self.poll_seconds <= 3600 and .1 <= self.health_timeout <= 30
                and 1 <= self.startup_grace <= 600 and 1 <= self.health_retries <= 20
                and 0 <= self.max_restarts <= 20 and 1 <= self.backoff_seconds <= self.max_backoff_seconds <= 3600):
            raise ValueError('Invalid supervisor timing or restart limits.')


class AlreadySupervised(Exception):
    pass


class SupervisorLock:
    """An OS lock, released on exit/crash; PID files alone are not ownership."""
    def __init__(self, path):
        self.path = Path(path)
        self.file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open('a+b')
        if os.fstat(self.file.fileno()).st_size == 0:
            self.file.write(b'0')
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            self.file = None
            raise AlreadySupervised('This configuration already has a supervisor.') from exc
        return self

    def __exit__(self, *args):
        if self.file is not None:
            self.file.close()
            self.file = None


def health_matches(payload, config):
    """Only the exact project/data identity at the configured port is accepted."""
    if not isinstance(payload, dict) or payload.get('project') != PROJECT:
        return False
    if not all(isinstance(payload.get(key), str) and payload[key] for key in ('root', 'data_dir')):
        return False
    return (_path_key(payload['root']) == _path_key(config.project_dir)
            and _path_key(payload['data_dir']) == _path_key(config.data_dir)
            and ('port' not in payload or type(payload['port']) is int and payload['port'] == config.port))


def read_health(config):
    """Bounded GET only; no cookies, proxy, redirect, bootstrap, or credentials."""
    connection = http.client.HTTPConnection('127.0.0.1', config.port, timeout=config.health_timeout)
    try:
        connection.request('GET', '/api/health', headers={'Accept': 'application/json', 'Connection': 'close'})
        response = connection.getresponse()
        if response.status != 200:
            return 'unavailable'
        content = response.read(16_385)
        if len(content) > 16_384:
            return 'foreign'
        try:
            payload = json.loads(content)
        except (ValueError, UnicodeError, RecursionError):
            return 'foreign'
        return 'healthy' if health_matches(payload, config) else 'foreign'
    except (OSError, http.client.HTTPException, ValueError):
        return 'unavailable'
    finally:
        connection.close()


def port_occupied(config):
    try:
        with socket.create_connection(('127.0.0.1', config.port), timeout=config.health_timeout):
            return True
    except ConnectionRefusedError:
        return False
    except OSError:
        # A timeout or permission error is not evidence of a closed port.
        return True


def start_server(config):
    if config.stop_file.exists():
        raise OSError('Intentional stop requested.')
    environment = os.environ.copy()
    environment.pop('PYTHONPATH', None)
    environment.pop('PYTHONHOME', None)
    environment['LAB_OPERATIONS_STOP_FILE'] = str(config.stop_file)
    command = [str(config.python), '-E', '-m', 'laboratory', '--no-browser',
               '--data-dir', str(config.data_dir), '--port', str(config.port)]
    options = {'cwd': str(config.project_dir), 'env': environment, 'stdin': subprocess.DEVNULL,
               'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL, 'close_fds': True}
    if os.name == 'nt':
        options['creationflags'] = subprocess.CREATE_NO_WINDOW
    return subprocess.Popen(command, **options)


def write_heartbeat(config, status):
    config.state_dir.mkdir(parents=True, exist_ok=True)
    target = config.state_dir / 'readiness.json'
    temporary = config.state_dir / 'readiness.json.tmp'
    temporary.write_text(json.dumps(status, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    os.replace(temporary, target)


def operations_logger(config):
    config.state_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger('laboratory.operations.'+str(os.getpid()))
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = RotatingFileHandler(config.state_dir / 'supervisor.log', maxBytes=256*1024,
                                 backupCount=3, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
    logger.addHandler(handler)
    return logger


class Supervisor:
    """One conservative state-machine tick at a time, with injectable I/O."""
    def __init__(self, config, *, health=read_health, occupied=port_occupied, start=start_server,
                 monotonic=time.monotonic, heartbeat=write_heartbeat, logger=None):
        self.config = config
        self.health, self.occupied, self.start = health, occupied, start
        self.monotonic, self.heartbeat, self.logger = monotonic, heartbeat, logger
        self.stop = threading.Event()
        self.child = None
        self.child_started = None
        self.attempts = 0
        self.failures = 0
        self.verified = False
        self.next_start = 0
        self.last_status = None

    def _record(self, status):
        # No HTTP payloads, exceptions, command lines, environment or tokens.
        result = {'schema': 'operations-readiness-v1', 'updated_at': datetime.now(timezone.utc).isoformat(),
                  'status': status, 'project': PROJECT, 'root': str(self.config.project_dir),
                  'data_dir': str(self.config.data_dir), 'host': '127.0.0.1', 'port': self.config.port,
                  'supervisor_pid': os.getpid(), 'owned_child_pid': self.child.pid if self.child else None,
                  'start_attempts': self.attempts, 'health_failures': self.failures}
        self.heartbeat(self.config, result)
        if status != self.last_status and self.logger:
            self.logger.info('state=%s start_attempts=%d health_failures=%d', status, self.attempts, self.failures)
        self.last_status = status

    def _backoff(self):
        return min(self.config.max_backoff_seconds, self.config.backoff_seconds * 2**max(0, self.attempts-1))

    def tick(self):
        """Return (seconds until next tick, optional process exit code)."""
        config, now = self.config, self.monotonic()
        if self.stop.is_set() or config.stop_file.exists():
            self._record('stopped')
            return config.poll_seconds, 0
        if self.child is not None and self.child.poll() is not None:
            self.child = None
            self.child_started = None
            self.next_start = now + self._backoff()
        health = self.health(config)
        if health == 'healthy':
            self.verified, self.failures = True, 0
            self._record('healthy')
            return config.poll_seconds, None
        if health == 'foreign':
            self._record('port_conflict')
            return config.poll_seconds, 3
        self.failures += 1
        if self.occupied(config):
            starting = self.child is not None and now-self.child_started < config.startup_grace
            if not self.verified and not starting and self.child is None and self.failures >= config.health_retries:
                self._record('port_unverified')
                return config.poll_seconds, 3
            self._record('health_retry' if starting or self.failures < config.health_retries else 'degraded')
            return config.poll_seconds, None
        if self.child is not None:
            # An alive process may be starting or busy. Never kill research to
            # fix an HTTP symptom, and never launch a duplicate alongside it.
            self._record('starting' if now-self.child_started < config.startup_grace else 'degraded')
            return config.poll_seconds, None
        if now < self.next_start:
            self._record('backoff')
            return min(config.poll_seconds, self.next_start-now), None
        if self.attempts >= 1+config.max_restarts:
            self._record('restart_limit')
            return config.poll_seconds, 4
        # Re-check immediately before spawning; another server may have won the
        # port while health was read. A bind race is still handled by the app.
        if self.occupied(config):
            self._record('health_retry')
            return config.poll_seconds, None
        if config.stop_file.exists():
            self._record('stopped')
            return config.poll_seconds, 0
        self.attempts += 1
        try:
            self.child = self.start(config)
            self.child_started = now
            self._record('starting')
        except OSError:
            self.child = None
            self.next_start = now+self._backoff()
            self._record('start_failed')
        return config.poll_seconds, None

    def run(self):
        while True:
            delay, code = self.tick()
            if code is not None:
                return code
            self.stop.wait(delay)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Watch only this configured local laboratory server.')
    parser.add_argument('--project-dir', type=Path, default=MODULE_ROOT)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8795)
    parser.add_argument('--state-dir', type=Path)
    parser.add_argument('--python', type=Path, default=Path(sys.executable))
    parser.add_argument('--stop-file', type=Path)
    parser.add_argument('--poll-seconds', type=float, default=15)
    parser.add_argument('--health-timeout', type=float, default=3)
    parser.add_argument('--startup-grace', type=float, default=60)
    parser.add_argument('--health-retries', type=int, default=3)
    parser.add_argument('--max-restarts', type=int, default=5)
    parser.add_argument('--backoff-seconds', type=float, default=5)
    parser.add_argument('--max-backoff-seconds', type=float, default=300)
    args = parser.parse_args(argv)
    try:
        config = Config(**vars(args))
        if config.project_dir != MODULE_ROOT or not config.python.is_file():
            raise ValueError('Run the supervisor from the configured project with an existing Python interpreter.')
    except ValueError as exc:
        parser.error(str(exc))
    try:
        with SupervisorLock(config.state_dir / 'supervisor.lock'):
            logger = operations_logger(config)
            supervisor = Supervisor(config, logger=logger)
            previous = {}
            try:
                for name in ('SIGINT', 'SIGTERM', 'SIGBREAK'):
                    number = getattr(signal, name, None)
                    if number is not None:
                        previous[number] = signal.signal(number, lambda *_: supervisor.stop.set())
                return supervisor.run()
            finally:
                for number, handler in previous.items():
                    signal.signal(number, handler)
                for handler in logger.handlers[:]:
                    handler.close()
                    logger.removeHandler(handler)
    except AlreadySupervised:
        return 2
    except OSError:
        # Keep exception/OS details out of scheduled-task output and logs.
        return 5


if __name__ == '__main__':
    raise SystemExit(main())
