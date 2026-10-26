"""Local operational snapshots; no service or credential decryption is started."""
from datetime import datetime, timezone
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import threading
import time
import uuid

from .core import canonical, digest
from .publication import CONFIG_KEY, QUEUE_KEY

FORMAT = 'ai-rd-operational-backup-v1'
IDS = re.compile(r'backup-\d{8}T\d{6}Z-[0-9a-f]{8}')
MAX_FILES, MAX_BYTES = 10000, 2 * 1024 ** 3
EXCLUDED = {'.lab-backups', '.lab-operations', 'backups', 'logs', 'tmp', 'temp', '__pycache__'}


def _linked(path):
    return path.is_symlink() or bool(path.lstat().st_file_attributes & 1024) if os.name == 'nt' else path.is_symlink()


def _files(root, filtered=True):
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(name for name in dirs if not filtered or name not in EXCLUDED)
        for name in [*dirs, *files]:
            if _linked(Path(directory) / name):
                raise ValueError('Ссылки и точки повторного анализа в копии запрещены.')
        for name in sorted(files):
            if filtered and (name.endswith(('-wal', '-shm', '.lock', '.log', '.tmp', '.temp')) or
                             name.startswith('.pending-')):
                continue
            yield Path(directory) / name


def _hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _json(path):
    if _linked(path) or path.stat().st_size > 2 * 1024 ** 2:
        raise ValueError('Повреждён локальный манифест.')
    return json.loads(path.read_text(encoding='utf-8'))


def _database(path):
    return closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True))


def _database_checks(path, payload):
    with _database(path) as db:
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or db.execute(
                'PRAGMA foreign_key_check').fetchone():
            raise ValueError('База копии не прошла проверку целостности.')
        row = db.execute('SELECT value FROM settings WHERE key=?', (QUEUE_KEY,)).fetchone()
        queue = json.loads(row[0]) if row else {}
    for identifier, entry in queue.items():
        if not re.fullmatch(r'[A-Za-z0-9_-]{16}', identifier):
            raise ValueError('Некорректный пакет очереди.')
        directory = payload / 'publications' / identifier
        manifest = _json(directory / 'manifest.json')
        if (digest(manifest) != entry['package_sha256'] or manifest['files'] != entry['files'] or
                manifest['binding'] != entry['binding']):
            raise ValueError('Пакет публикации отличается от снимка очереди.')
        for name, expected in manifest['files'].items():
            if name not in {'post.txt', 'card.png', 'animation.mp4'}:
                raise ValueError('Неизвестный файл публикации.')
            path = directory / name
            if path.stat().st_size != expected['bytes'] or _hash(path) != expected['sha256']:
                raise ValueError('Файл публикационного пакета повреждён.')
    return len(queue)


class OperationalBackups:
    def __init__(self, store, backup_dir=None, clock=None, retention=14):
        self.store, self.data = store, Path(store.data_dir).resolve()
        candidate = Path(backup_dir) if backup_dir else self.data.parent / '.lab-backups'
        if candidate.exists() and _linked(candidate):
            raise ValueError('Каталог копий не должен быть ссылкой.')
        self.root = candidate.resolve()
        if self.root.is_relative_to(self.data) or self.data.is_relative_to(self.root):
            raise ValueError('Резервные копии должны храниться вне рабочего каталога данных.')
        if type(retention) is not int or not 1 <= retention <= 90:
            raise ValueError('Хранение: от 1 до 90 полных локальных копий.')
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.retention, self.lock, self.error = retention, threading.RLock(), None

    def _now(self):
        value = self.clock()
        if value.tzinfo is None:
            raise ValueError('Для резервирования требуется время с часовым поясом.')
        return value.astimezone(timezone.utc)

    def _path(self, identifier):
        if not isinstance(identifier, str) or not IDS.fullmatch(identifier):
            raise ValueError('Некорректный идентификатор резервной копии.')
        path = self.root / identifier
        if not path.is_dir():
            raise ValueError('Локальная резервная копия не найдена.')
        if _linked(path) or path.resolve().parent != self.root:
            raise ValueError('Некорректный путь резервной копии.')
        return path

    def _manifest(self, folder):
        manifest = _json(folder / 'manifest.json')
        if (not isinstance(manifest, dict) or manifest.get('format') != FORMAT or
                manifest.get('complete') is not True or not isinstance(manifest.get('files'), list)
                or not 1 <= len(manifest['files']) <= MAX_FILES):
            raise ValueError('Незавершённая или повреждённая локальная копия.')
        if datetime.fromisoformat(manifest['created_at']).tzinfo is None:
            raise ValueError('Время копии не содержит часового пояса.')
        return manifest

    @staticmethod
    def _summary(folder, manifest):
        return {'id': folder.name, 'created_at': manifest['created_at'], 'verified': True,
                'files': len(manifest['files']), 'bytes': sum(row['size'] for row in manifest['files']),
                'snapshot_sha256': digest(manifest)}

    def _verify(self, folder, payload=None):
        manifest = self._manifest(folder)
        payload = payload or folder / 'payload'
        if not payload.is_dir() or _linked(payload):
            raise ValueError('Каталог содержимого копии повреждён.')
        expected, total = {}, 0
        for row in manifest['files']:
            name = row.get('path') if isinstance(row, dict) else None
            if (not isinstance(name, str) or not name or '\\' in name or ':' in name or
                    PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts or
                    str(PurePosixPath(name)) != name or name in expected or
                    type(row.get('size')) is not int or row['size'] < 0 or
                    not re.fullmatch(r'[0-9a-f]{64}', str(row.get('sha256', '')))):
                raise ValueError('Повреждён перечень файлов копии.')
            total += row['size']
            if total > MAX_BYTES:
                raise ValueError('Локальная копия превышает предел размера.')
            expected[name] = row
        actual = {path.relative_to(payload).as_posix(): path for path in _files(payload, False)}
        if set(actual) != set(expected) or 'laboratory.sqlite3' not in expected:
            raise ValueError('В копии отсутствуют файлы либо появились лишние файлы.')
        for name, path in actual.items():
            if path.stat().st_size != expected[name]['size'] or _hash(path) != expected[name]['sha256']:
                raise ValueError('Контрольная сумма файла копии не совпадает.')
        packages = _database_checks(payload / 'laboratory.sqlite3', payload)
        return manifest, {'valid': True, 'database_integrity': 'ok', 'publication_packages': packages}

    def validate(self, identifier):
        with self.lock:
            folder = self._path(identifier)
            manifest, checks = self._verify(folder)
            return {**self._summary(folder, manifest), **checks}

    def _history(self):
        rows = []
        for path in self.root.glob('backup-*'):
            if IDS.fullmatch(path.name) and path.is_dir() and not _linked(path):
                try:
                    rows.append(self._summary(path, self._manifest(path)))
                except (OSError, ValueError, KeyError, TypeError):
                    pass
        return sorted(rows, key=lambda row: (row['created_at'], row['id']))

    def status(self):
        with self.lock:
            rows = self._history()
            latest = rows[-1] if rows else None
            due = not latest or (self._now() - datetime.fromisoformat(
                latest['created_at'])).total_seconds() >= 86400
            drill_path = self.root / 'drill-status.json'
            try:
                record = _json(drill_path) if drill_path.is_file() else None
                drill = {key: record[key] for key in (
                    'status', 'completed_at', 'snapshot_exact', 'source_unchanged',
                    'hold_entries', 'snapshot_sha256') if key in record} if record else None
                if drill and drill.get('status') not in {'passed', 'failed'}:
                    drill = {'status': 'invalid'}
            except (OSError, ValueError, TypeError):
                drill = {'status': 'invalid'}
            return {'health': 'error' if self.error else 'ready' if latest else 'missing',
                    'latest': latest, 'due': due, 'complete_count': len(rows),
                    'retention': self.retention, 'last_drill': drill, 'error': self.error,
                    'verification': 'При создании; validate/drill повторяют полную проверку.',
                    'notice': 'Только локально. DPAPI доступен тому же профилю Windows. '
                              'Восстановленный каталог не запускает бот или сервер.'}

    def create(self):
        with self.lock:
            self.root.mkdir(parents=True, exist_ok=True)
            stamp = self._now()
            identifier = 'backup-' + stamp.strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:8]
            staging = self.root / ('.pending-' + identifier)
            payload = staging / 'payload'
            payload.mkdir(parents=True)
            try:
                inventory, source_bytes = {}, 0
                for path in _files(self.data):
                    if path == self.store.path:
                        continue
                    stat = path.stat()
                    inventory[path] = (stat.st_size, stat.st_mtime_ns, stat.st_ino)
                    source_bytes += stat.st_size
                    if len(inventory) >= MAX_FILES or source_bytes > MAX_BYTES:
                        raise ValueError('Превышена граница локальной копии.')
                deadline = time.monotonic() + 120
                def progress(*unused):
                    if time.monotonic() > deadline:
                        raise ValueError('Превышено время онлайн-копирования SQLite.')
                with self.store.connect() as source, closing(sqlite3.connect(
                        payload / 'laboratory.sqlite3')) as target:
                    source.backup(target, pages=256, progress=progress)
                    target.execute('PRAGMA journal_mode=DELETE')
                rows, total = [], 0
                for path in [payload / 'laboratory.sqlite3', *inventory]:
                    relative = ('laboratory.sqlite3' if path.parent == payload else
                                path.relative_to(self.data).as_posix())
                    before = path.stat()
                    if path in inventory and (before.st_size, before.st_mtime_ns,
                                              before.st_ino) != inventory[path]:
                        raise ValueError('Рабочие файлы изменились после снимка базы.')
                    total += before.st_size
                    if len(rows) >= MAX_FILES or total > MAX_BYTES:
                        raise ValueError('Превышена граница локальной копии.')
                    destination = payload / relative
                    if path != destination:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        with path.open('rb') as source, destination.open('xb') as target:
                            remaining = before.st_size
                            while remaining:
                                content = source.read(min(1024 ** 2, remaining))
                                if not content:
                                    raise ValueError('Файл изменился при резервировании.')
                                target.write(content)
                                remaining -= len(content)
                            after = path.stat()
                            if (source.read(1) or after.st_size != before.st_size or
                                    after.st_mtime_ns != before.st_mtime_ns):
                                raise ValueError('Файл изменился при резервировании.')
                    rows.append({'path': relative, 'size': before.st_size, 'sha256': _hash(destination)})
                current = {path: (path.stat().st_size, path.stat().st_mtime_ns, path.stat().st_ino)
                           for path in _files(self.data) if path != self.store.path}
                if current != inventory:
                    raise ValueError('Рабочие файлы изменились во время резервирования.')
                manifest = {'format': FORMAT, 'complete': True,
                            'created_at': stamp.isoformat(timespec='seconds'), 'files': rows}
                (staging / 'manifest.json').write_text(canonical(manifest), encoding='utf-8')
                self._verify(staging)
                staging.rename(self.root / identifier)
                self.error = None
                for old in self._history()[:-self.retention]:
                    shutil.rmtree(self._path(old['id']))
                return self._summary(self.root / identifier, manifest)
            except Exception:
                self.error = 'Локальная резервная копия не подтверждена.'
                raise
            finally:
                if staging.exists() and staging.resolve().parent == self.root:
                    shutil.rmtree(staging)

    def maintenance(self):
        with self.lock:
            if self.status()['due']:
                try:
                    self.create()
                except (OSError, ValueError, sqlite3.Error):
                    pass
            return self.status()

    def drill(self, identifier, destination):
        with self.lock:
            try:
                return self._drill(identifier, destination)
            except Exception:
                self._record_drill({'status': 'failed', 'snapshot_exact': None,
                                    'completed_at': self._now().isoformat(timespec='seconds')})
                raise

    def _record_drill(self, result):
        if self.root.is_dir():
            temporary = self.root / 'drill-status.tmp'
            temporary.write_text(canonical(result), encoding='utf-8')
            temporary.replace(self.root / 'drill-status.json')

    def _drill(self, identifier, destination):
        with self.lock:
            folder = self._path(identifier)
            manifest, checks = self._verify(folder)
            target = Path(destination)
            if target.exists() and (_linked(target) or not target.is_dir() or any(target.iterdir())):
                raise ValueError('Проверочное восстановление требует пустой отдельный каталог.')
            target = target.resolve()
            if any(target.is_relative_to(path) or path.is_relative_to(target)
                   for path in (self.data, self.root)):
                raise ValueError('Проверочное восстановление запрещено в рабочие данные или копии.')
            target.mkdir(parents=True, exist_ok=True)
            for row in manifest['files']:
                output = target / row['path']
                output.parent.mkdir(parents=True, exist_ok=True)
                with (folder / 'payload' / row['path']).open('rb') as source, output.open('xb') as dest:
                    shutil.copyfileobj(source, dest, 1024 ** 2)
            self._verify(folder, target)
            with closing(sqlite3.connect(target / 'laboratory.sqlite3')) as db, db:
                values = {key: json.loads(value) for key, value in db.execute('SELECT * FROM settings')}
                queue, count = values.get(QUEUE_KEY, {}), 0
                for entry in queue.values():
                    if entry['state'] in {'queued', 'publishing', 'publication_uncertain'}:
                        uncertain = entry['state'] in {'publishing', 'publication_uncertain'}
                        entry.update(state='publication_uncertain' if uncertain else 'blocked', due_at=None,
                                     reason='HOLD: исход прежней отправки неизвестен; автоматического повтора нет.'
                                     if uncertain else 'HOLD: восстановленная копия; сверьте канал до нового апрува.')
                        count += 1
                config = {**values.get(CONFIG_KEY, {}), 'enabled': False}
                for key, value in ((QUEUE_KEY, queue), (CONFIG_KEY, config)):
                    db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, canonical(value)))
            _database_checks(target / 'laboratory.sqlite3', target)
            self._verify(folder)
            result = {'id': identifier, 'status': 'passed', 'snapshot_exact': True,
                      'source_unchanged': True, 'hold_entries': count, **checks,
                      'snapshot_sha256': digest(manifest),
                      'completed_at': self._now().isoformat(timespec='seconds')}
            self._record_drill(result)
            return result
