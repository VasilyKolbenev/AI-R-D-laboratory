"""TEST_ONLY online SQLite, opaque encrypted bytes, and isolated restore drills."""
from copy import deepcopy
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from laboratory.core import Store, canonical, digest
from laboratory.operational_backups import OperationalBackups
from laboratory.publication import CONFIG_KEY, QUEUE_KEY, Publisher
import test_publication as fixtures


class OperationalBackupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=Path(__file__).parent / '.tmp')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.store = Store(self.base / '.lab-data')
        self.now = datetime(2026, 10, 24, tzinfo=timezone.utc)
        self.backups = OperationalBackups(self.store, clock=lambda: self.now, retention=2)
        self.secret = b'TEST_ONLY_OPAQUE_DPAPI_BYTES'
        (self.store.data_dir / '.telegram-token.dpapi').write_bytes(self.secret)
        self.store.set_setting(CONFIG_KEY, {'enabled': True, 'channel': {'id': -100123}})
        queue = {}
        for index, state in enumerate(('queued', 'publishing', 'publication_uncertain', 'published')):
            identifier = chr(65 + index) * 16
            directory = self.store.data_dir / 'publications' / identifier
            directory.mkdir(parents=True)
            files = {}
            for name in ('post.txt', 'card.png', 'animation.mp4'):
                content = ('TEST_ONLY ' + name).encode()
                (directory / name).write_bytes(content)
                files[name] = {'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content)}
            manifest = {'binding': {'channel_id': -100123}, 'files': files, 'run_id': 'TEST_ONLY'}
            (directory / 'manifest.json').write_text(canonical(manifest), encoding='utf-8')
            queue[identifier] = {'id': identifier, 'state': state, 'due_at': 'TEST_ONLY due',
                                 'binding': manifest['binding'], 'files': files,
                                 'package_sha256': digest(manifest), 'receipts': []}
        self.store.set_setting(QUEUE_KEY, queue)

    def payload(self, summary):
        return self.base / '.lab-backups' / summary['id'] / 'payload'

    def test_online_snapshot_includes_committed_wal_and_opaque_secret_not_volatile_files(self):
        for name in ('.instance.lock', 'debug.log', 'write.tmp'):
            (self.store.data_dir / name).write_bytes(b'TEST_ONLY excluded')
        jobs = self.store.data_dir / 'jobs'
        jobs.mkdir()
        (jobs / 'context.json').write_text('TEST_ONLY durable context', encoding='utf-8')
        operations = self.store.data_dir / '.lab-operations'
        operations.mkdir()
        (operations / 'never-recurse.txt').write_text('TEST_ONLY operational artifacts')
        db = sqlite3.connect(self.store.path)
        self.addCleanup(db.close)
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('INSERT INTO settings VALUES (?,?)', ('TEST_ONLY_wal', '42'))
        db.commit()
        self.assertTrue(Path(str(self.store.path) + '-wal').exists())
        with patch('laboratory.telegram._dpapi', side_effect=AssertionError('No decrypt')):
            result = self.backups.create()
        self.assertIsInstance(result, dict)
        self.assertTrue(self.backups.validate(result['id'])['valid'])
        payload = self.payload(result)
        self.assertFalse((payload / '.lab-operations').exists())
        self.assertEqual((payload / '.telegram-token.dpapi').read_bytes(), self.secret)
        self.assertEqual((payload / 'jobs/context.json').read_text(), 'TEST_ONLY durable context')
        with closing(sqlite3.connect(payload / 'laboratory.sqlite3')) as saved:
            self.assertEqual(saved.execute("SELECT value FROM settings WHERE key='TEST_ONLY_wal'")
                             .fetchone()[0], '42')
        for path in payload.rglob('*'):
            self.assertNotIn(path.name, {'.instance.lock', 'debug.log', 'write.tmp',
                                        'laboratory.sqlite3-wal', 'laboratory.sqlite3-shm'})
        self.assertNotIn(self.secret.decode(), json.dumps(self.backups.status()))

    def test_daily_due_gate_and_retention_keep_only_complete_snapshots(self):
        self.assertTrue(self.backups.status()['due'])
        first = self.backups.create()
        self.assertFalse(self.backups.status()['due'])
        self.backups.maintenance()
        self.assertEqual(self.backups.status()['complete_count'], 1)
        for _ in range(2):
            self.now += timedelta(days=1)
            self.backups.maintenance()
        status = self.backups.status()
        self.assertEqual(status['complete_count'], 2)
        self.assertFalse(self.payload(first).exists())
        self.assertEqual(status['latest']['created_at'], self.now.isoformat(timespec='seconds'))

    def test_failed_verification_never_exposes_complete_backup(self):
        with patch.object(self.backups, '_verify', side_effect=ValueError('TEST_ONLY failure')):
            with self.assertRaises(ValueError):
                self.backups.create()
        self.assertEqual(self.backups.status()['complete_count'], 0)
        self.assertEqual(list((self.base / '.lab-backups').glob('.pending-*')), [])
        self.assertEqual((self.store.data_dir / '.telegram-token.dpapi').read_bytes(), self.secret)

    def test_secret_replacement_during_database_snapshot_aborts_inconsistent_backup(self):
        connect = self.store.connect

        @contextmanager
        def changing_secret():
            with connect() as db:
                (self.store.data_dir / '.telegram-token.dpapi').write_bytes(b'TEST_ONLY new DPAPI')
                yield db

        with patch.object(self.store, 'connect', side_effect=changing_secret):
            with self.assertRaises(ValueError):
                self.backups.create()
        self.assertEqual(self.backups.status()['complete_count'], 0)
        self.assertEqual(list((self.base / '.lab-backups').glob('.pending-*')), [])

    def test_drill_verifies_exact_payload_then_holds_queue_without_touching_snapshot(self):
        original = deepcopy(self.store.get_setting(QUEUE_KEY))
        summary = self.backups.create()
        destination = self.base / 'restore-sandbox'
        result = self.backups.drill(summary['id'], destination)
        self.assertTrue(result['snapshot_exact'])
        self.assertTrue(result['source_unchanged'])
        self.assertEqual(result['hold_entries'], 3)
        self.assertEqual(result['snapshot_sha256'], summary['snapshot_sha256'])
        with closing(sqlite3.connect(destination / 'laboratory.sqlite3')) as db:
            config = json.loads(db.execute('SELECT value FROM settings WHERE key=?',
                                          (CONFIG_KEY,)).fetchone()[0])
            queue = json.loads(db.execute('SELECT value FROM settings WHERE key=?',
                                         (QUEUE_KEY,)).fetchone()[0])
        self.assertFalse(config['enabled'])
        self.assertEqual([entry['state'] for entry in queue.values()],
                         ['blocked', 'publication_uncertain', 'publication_uncertain', 'published'])
        self.assertEqual(self.store.get_setting(QUEUE_KEY), original)
        self.assertEqual((destination / '.telegram-token.dpapi').read_bytes(), self.secret)
        self.assertTrue(self.backups.validate(summary['id'])['valid'])
        self.assertEqual(self.backups.status()['last_drill']['status'], 'passed')

    def test_restored_ambiguous_send_keeps_receipts_and_prepare_never_reopens_approval(self):
        self.store.set_setting(QUEUE_KEY, {})
        self.store.set_setting(CONFIG_KEY, {'enabled': True, 'timezone': 'Europe/Moscow',
            'slots': [], 'channel': {'id': -100123, 'owner_id': 42,
                                    'fingerprint': 'TEST_ONLY_fingerprint'}})
        bridge = fixtures.FakeBridge()
        data = {'title': 'TEST_ONLY uncertain package', 'post_text': 'TEST_ONLY exact saved post.',
                'publication_checks': {'status': 'ready'},
                'publication_rules': {'version': 'TEST_ONLY_restore_guard'}}
        run = fixtures.PublicationTests.complete(self, 'uncertain')
        builder = lambda saved: deepcopy(data)
        publisher = Publisher(self.store, bridge, builder, clock=lambda: self.now)
        with patch('laboratory.presentation.render_png', return_value=b'TEST_ONLY_PNG') as png, \
                patch('laboratory.presentation.render_mp4', return_value=b'TEST_ONLY_MP4') as mp4:
            entry = publisher.prepare(run['id'])
            publisher.bind_preview(entry['id'], 91)
            png.reset_mock()
            mp4.reset_mock()
            receipt = {'method': 'sendMessage', 'message_id': 17,
                       'confirmed_at': '2026-10-24T00:00:00+00:00'}
            for state in ('publishing', 'publication_uncertain'):
                with self.subTest(state=state):
                    queue = self.store.get_setting(QUEUE_KEY)
                    queue[entry['id']].update(state=state, receipts=[receipt])
                    self.store.set_setting(QUEUE_KEY, queue)
                    summary = self.backups.create()
                    target = self.base / ('restored-' + state)
                    self.backups.drill(summary['id'], target)
                    restored = Store(target)
                    restarted = Publisher(restored, bridge, builder, clock=lambda: self.now)
                    before = restored.get_setting(QUEUE_KEY)
                    prepared = restarted.prepare(run['id'])
                    self.assertEqual(prepared['id'], entry['id'])
                    self.assertEqual(prepared['state'], 'publication_uncertain')
                    self.assertFalse(prepared['can_enqueue'])
                    self.assertEqual(prepared['receipts'], [receipt])
                    self.assertEqual(restored.get_setting(QUEUE_KEY), before)
                    self.assertEqual(len(before), 1)
                    self.assertIsNone(before[entry['id']]['due_at'])
                    self.assertFalse(restored.get_setting(CONFIG_KEY)['enabled'])
                    restarted.tick()
                    self.assertEqual(restored.get_setting(QUEUE_KEY), before)
                    self.assertEqual(self.store.get_setting(QUEUE_KEY), queue)
            png.assert_not_called()
            mp4.assert_not_called()
        self.assertEqual(bridge.calls, [])

    def test_corruption_and_unexpected_files_are_rejected_before_restore(self):
        summary = self.backups.create()
        payload = self.payload(summary)
        secret = payload / '.telegram-token.dpapi'
        secret.write_bytes(b'X' * len(self.secret))
        with self.assertRaises(ValueError):
            self.backups.validate(summary['id'])
        with self.assertRaises(ValueError):
            self.backups.drill(summary['id'], self.base / 'bad-drill')
        self.assertFalse((self.base / 'bad-drill').exists())
        self.assertEqual(self.backups.status()['last_drill']['status'], 'failed')
        secret.write_bytes(self.secret)
        (payload / 'unexpected.txt').write_text('TEST_ONLY unexpected')
        with self.assertRaises(ValueError):
            self.backups.validate(summary['id'])

    def test_manifest_traversal_invalid_sqlite_and_size_bounds_are_rejected(self):
        summary = self.backups.create()
        folder = self.payload(summary).parent
        manifest_path = folder / 'manifest.json'
        original = json.loads(manifest_path.read_text(encoding='utf-8'))
        changed = deepcopy(original)
        changed['files'][0]['path'] = '../outside'
        manifest_path.write_text(canonical(changed), encoding='utf-8')
        with self.assertRaises(ValueError):
            self.backups.drill(summary['id'], self.base / 'unsafe')
        self.assertFalse((self.base / 'unsafe').exists())
        manifest_path.write_text(canonical(original), encoding='utf-8')
        database = self.payload(summary) / 'laboratory.sqlite3'
        database.write_bytes(b'TEST_ONLY invalid SQLite')
        row = next(row for row in original['files'] if row['path'] == 'laboratory.sqlite3')
        row.update(size=database.stat().st_size,
                   sha256=hashlib.sha256(database.read_bytes()).hexdigest())
        manifest_path.write_text(canonical(original), encoding='utf-8')
        with self.assertRaises(sqlite3.DatabaseError):
            self.backups.validate(summary['id'])
        with patch('laboratory.operational_backups.MAX_FILES', 1):
            with self.assertRaises(ValueError):
                self.backups.create()

    def test_restore_refuses_live_backup_and_nonempty_targets(self):
        summary = self.backups.create()
        occupied = self.base / 'occupied'
        occupied.mkdir()
        (occupied / 'keep.txt').write_text('TEST_ONLY never overwrite')
        for target in (self.store.data_dir, self.base / '.lab-backups', occupied):
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.backups.drill(summary['id'], target)
        self.assertEqual((occupied / 'keep.txt').read_text(), 'TEST_ONLY never overwrite')
        with self.assertRaises(ValueError):
            OperationalBackups(self.store, self.store.data_dir / 'backups')


if __name__ == '__main__':
    unittest.main()
