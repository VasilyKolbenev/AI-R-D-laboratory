"""Local maintenance only: no provider, Telegram delivery or publication tick."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import threading


def _read(path):
    try:
        if path.is_symlink() or path.stat().st_size > 512 * 1024:
            return {}
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.pending')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


class Operations:
    def __init__(self, store, project_dir, port=8795, backups=None, snapshot_lock=None):
        from .operational_backups import OperationalBackups
        self.store = store
        self.project_dir = Path(project_dir).resolve()
        self.port = port
        self.state_dir = self.project_dir / '.lab-operations'
        self.backups = backups or OperationalBackups(store)
        self.stop_event = threading.Event()
        self.thread = None
        self.lock = threading.RLock()
        self.snapshot_lock = snapshot_lock or threading.RLock()

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._loop, name='local-maintenance', daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=1)

    def _loop(self):
        while not self.stop_event.is_set():
            try:
                self.maintenance_once()
            except Exception as exc:
                _write(self.state_dir / 'maintenance.json', {
                    'status': 'error', 'error_type': type(exc).__name__,
                    'notice': 'Обслуживание не завершено. Исследования и публикации не повторялись.',
                    'checked_at': datetime.now(timezone.utc).isoformat()})
                if self.stop_event.wait(15 * 60):
                    return
            self.stop_event.wait(60)

    def maintenance_once(self):
        with self.lock:
            with self.snapshot_lock:
                self.backups.maintenance()
            status = self.backups.status()
            if status.get('error'):
                # The snapshot manager reports safe copy failures as status.
                # Propagate to the maintenance loop's error/backoff path rather
                # than recording completion and retrying a large copy each minute.
                raise ValueError('Local operational backup was not confirmed')
            latest = status.get('latest')
            backup_id = latest.get('id') if isinstance(latest, dict) else None
            drill = _read(self.state_dir / 'restore-drill.json')
            if backup_id and drill.get('backup_id') != backup_id:
                self.drill(backup_id)
            from .quality_audit import run_control_corpus
            if not _read(self.state_dir / 'quality-controls.json'):
                _write(self.state_dir / 'quality-controls.json', run_control_corpus())
            _write(self.state_dir / 'maintenance.json', {
                'status': 'completed', 'checked_at': datetime.now(timezone.utc).isoformat(),
                'model_calls': 0, 'publication_sends': 0})
            return self.status()

    def create_backup(self):
        with self.lock:
            with self.snapshot_lock:
                created = self.backups.create()
            self.drill(created['id'])
            return self.status()

    def drill(self, backup_id):
        with self.lock:
            parent = self.state_dir / 'restore-drills'
            parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='check-', dir=parent) as directory:
                target = Path(directory).resolve()
                if not target.is_relative_to(parent.resolve()) or target == parent.resolve():
                    raise ValueError('Недопустимая папка проверки восстановления.')
                result = self.backups.drill(backup_id, target)
            report = {**result, 'backup_id': backup_id,
                      'checked_at': datetime.now(timezone.utc).isoformat(),
                      'live_data_overwritten': False, 'server_started': False,
                      'model_calls': 0, 'publication_sends': 0}
            _write(self.state_dir / 'restore-drill.json', report)
            return report

    def quality(self, run, presentation, review):
        from .quality_audit import audit_saved_quality
        return audit_saved_quality(run, presentation, review)

    def status(self):
        heartbeat = _read(self.state_dir / 'readiness.json')
        checked = heartbeat.get('updated_at') or heartbeat.get('checked_at') or heartbeat.get('timestamp')
        fresh = False
        if isinstance(checked, str):
            try:
                stamp = datetime.fromisoformat(checked.replace('Z', '+00:00'))
                fresh = stamp.tzinfo is not None and 0 <= (datetime.now(timezone.utc) - stamp).total_seconds() < 90
            except (ValueError, OverflowError):
                pass
        identity = (heartbeat.get('project') == 'AI-R-D-laboratory'
                    and heartbeat.get('root') == str(self.project_dir)
                    and heartbeat.get('data_dir') == str(self.store.data_dir.resolve())
                    and heartbeat.get('port') == self.port)
        return {'scope': 'local_personal_operation',
                'backup': self.backups.status(),
                'restore_drill': _read(self.state_dir / 'restore-drill.json'),
                'quality_controls': _read(self.state_dir / 'quality-controls.json'),
                'maintenance': _read(self.state_dir / 'maintenance.json'),
                'supervisor': {'fresh': bool(fresh and identity),
                               'status': heartbeat.get('status', 'not_observed') if fresh and identity else 'not_observed',
                               'checked_at': checked if identity else None},
                'startup': {key: value for key, value in _read(self.state_dir / 'startup.json').items()
                            if key in {'mode', 'configured', 'checked_at', 'task_name'}},
                'limits': ['Компьютер должен быть включён и доступен в сети.',
                           'DPAPI-копии токенов восстанавливаются в том же профиле Windows.',
                           'Автоматические проверки не доказывают научную истинность выводов.']}


def stop_file(data_dir):
    return Path(data_dir).resolve() / '.operations-stop'


def mark_intentional_stop(data_dir):
    path = stop_file(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(datetime.now(timezone.utc).isoformat(), encoding='ascii')


def start_supervisor(project_dir, data_dir, port=8795):
    """Explicit local launch; the supervisor lock prevents a second watchdog."""
    import subprocess
    import sys
    python = Path(sys.executable)
    gui_python = python.with_name('pythonw.exe')
    if os.name == 'nt' and gui_python.is_file():
        python = gui_python
    environment = dict(os.environ)
    environment.pop('PYTHONPATH', None)
    environment.pop('PYTHONHOME', None)
    arguments = [str(python), '-E', '-m', 'laboratory.operations_supervisor',
                 '--project-dir', str(Path(project_dir).resolve()),
                 '--data-dir', str(Path(data_dir).resolve()), '--port', str(port),
                 '--state-dir', str(Path(project_dir).resolve() / '.lab-operations')]
    options = {'cwd': str(project_dir), 'env': environment, 'stdin': subprocess.DEVNULL,
               'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL, 'close_fds': True}
    if os.name == 'nt':
        options['creationflags'] = subprocess.CREATE_NO_WINDOW
    return subprocess.Popen(arguments, **options)


def main(argv=None):
    """Backup/restore utility. Restoration never starts a server or bot."""
    import argparse
    from contextlib import contextmanager, closing
    import sqlite3
    from .operational_backups import OperationalBackups
    parser = argparse.ArgumentParser(description='Local operational backup and safe restoration')
    parser.add_argument('action', choices=['status', 'backup', 'drill', 'restore'])
    parser.add_argument('--data-dir', type=Path, default=Path(__file__).resolve().parents[1] / '.lab-data')
    parser.add_argument('--backup-dir', type=Path)
    parser.add_argument('--backup-id')
    parser.add_argument('--destination', type=Path)
    args = parser.parse_args(argv)
    class SnapshotStore:
        data_dir = args.data_dir.resolve()
        path = data_dir / 'laboratory.sqlite3'
        @contextmanager
        def connect(self):
            with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)) as db:
                yield db
    backups = OperationalBackups(SnapshotStore(), args.backup_dir)
    if args.action == 'status':
        result = backups.status()
    elif args.action == 'backup':
        # A separate CLI process cannot share Telegram's configuration mutex.
        # Refuse a live application; its authenticated HTTP path holds that lock.
        from .server import InstanceLock
        with InstanceLock(args.data_dir):
            result = backups.create()
    else:
        if not args.backup_id or args.destination is None:
            parser.error('drill/restore require --backup-id and --destination (an empty separate directory)')
        result = backups.drill(args.backup_id, args.destination)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
