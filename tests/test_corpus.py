"""TEST_ONLY counts, provenance, atomic import and portable sidecar recovery."""
from pathlib import Path
import json
import os
import tempfile
import unittest

from laboratory.core import Store
from laboratory.corpus import Corpus, verify_corpora
from laboratory.corpus_import import import_bundle, sha
from laboratory.operational_backups import OperationalBackups
from corpus_fixtures import rows, write_bundle


class CorpusTests(unittest.TestCase):
    def setUp(self):
        # Full backup paths include content hashes. Use Windows' short TEMP root
        # instead of nesting an already-long developer checkout path again.
        temporary = Path(os.environ['TEMP']) if os.name == 'nt' else Path(__file__).parent / '.tmp'
        temporary.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temporary)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / 'data'
        self.bundle = write_bundle(self.root / 'bundle')
        self.corpus = Corpus(self.data)

    def test_empty_reader_does_not_create_storage_or_launch_anything(self):
        self.assertFalse(self.corpus.overview()['available'])
        self.assertFalse(self.data.exists())

    def test_unique_papers_and_noise_denominator_with_source_drilldown(self):
        result = import_bundle(self.bundle, self.data)
        self.assertEqual(result['new_model_calls'], 0)
        overview = self.corpus.overview()
        self.assertEqual(overview['corpus']['counts'], {'papers': 24, 'claims': 24,
            'analytic_papers': 12, 'analytic_claims': 18, 'topics': 1, 'noise_claims': 6, 'papers_with_claims': 18})
        self.assertTrue(overview['corpus']['reproduction']['matched'])
        self.assertEqual(overview['corpus']['reproduction']['comparisons'], 12)
        point = next(t for t in overview['topics'] if t['id'] == 54)['trajectory'][0]
        self.assertEqual((point['numerator'], point['denominator'], point['share']), (1, 2, 50))
        numerator = self.corpus.topic(54, 2020)
        self.assertEqual(numerator['total'], 1)
        self.assertEqual(numerator['items'][0]['claim_count'], 2)
        denominator = self.corpus.topic(54, 2020, 'denominator', limit=1, offset=1)
        self.assertEqual(denominator['total'], 2)
        self.assertEqual(denominator['items'][0]['paper_id'], '2020.emnlp-main.2')
        paper = self.corpus.paper('2020.emnlp-main.1')
        self.assertEqual(len(paper['claims']), 2)
        self.assertIn('<script>', paper['paper']['abstract'])  # Data, never HTML.
        self.assertTrue(all(c['supporting_quote'] is None and c['validation_state'] == 'imported_unverified'
                            and c['origin'] == 'external_extraction' for c in paper['claims']))
        self.assertEqual(paper['paper']['url'], 'https://aclanthology.org/2020.emnlp-main.1/')

    def test_outside_sample_missing_claims_and_noise_are_distinct(self):
        import_bundle(self.bundle, self.data)
        self.assertEqual(self.corpus.paper('2020.emnlp-main.2')['claims'][0]['topic_id'], -1)
        outside = self.corpus.paper('2020.emnlp-main.3')
        self.assertIsNone(outside['claims'][0]['topic_id'])
        self.assertFalse(outside['paper']['in_analytic_sample'])
        self.assertEqual(self.corpus.paper('2020.emnlp-main.4')['claims'], [])

    def test_repeat_import_is_idempotent_and_preserves_owner_files(self):
        self.data.mkdir()
        owner_file = self.data / 'TEST_ONLY-owner-bytes'
        owner_file.write_bytes(b'TEST_ONLY owner bytes')
        first = import_bundle(self.bundle, self.data)
        files = {str(p.relative_to(self.data)): (sha(p), p.stat().st_mtime_ns)
                 for p in self.data.rglob('*') if p.is_file()}
        repeated = import_bundle(self.bundle, self.data)
        self.assertFalse(repeated['created'])
        self.assertEqual(first['snapshot_id'], repeated['snapshot_id'])
        self.assertEqual(files, {str(p.relative_to(self.data)): (sha(p), p.stat().st_mtime_ns)
                                for p in self.data.rglob('*') if p.is_file()})

    def test_inconsistent_counts_or_share_never_replace_active_snapshot(self):
        import_bundle(self.bundle, self.data)
        pointer = (self.data / 'corpora/active.json').read_bytes()
        for change in ('share', 'count', 'duplicate', 'orphan', 'year'):
            data = rows()
            if change == 'share': data['topics'][0]['published_years'][0]['share'] = 50.0002
            if change == 'count': data['topics'][0]['claims'] += 1
            if change == 'duplicate': data['papers'].append(data['papers'][0])
            if change == 'orphan': data['assignments'][0]['claim_id'] = 'TEST_ONLY missing'
            if change == 'year': data['claims'][0]['year'] = 2025
            broken = write_bundle(self.root / ('broken-' + change), data)
            with self.subTest(change=change), self.assertRaises(ValueError):
                import_bundle(broken, self.data)
            self.assertEqual(pointer, (self.data / 'corpora/active.json').read_bytes())
            self.assertTrue(self.corpus.overview()['available'])

    def test_changed_input_or_database_is_rejected(self):
        import_bundle(self.bundle, self.data)
        (self.bundle / 'papers.jsonl.gz').write_bytes(b'TEST_ONLY corruption')
        with self.assertRaises(ValueError):
            import_bundle(self.bundle, self.data)
        database = next((self.data / 'corpora').glob('*/corpus.sqlite3'))
        database.write_bytes(database.read_bytes() + b'TEST_ONLY altered bytes')
        with self.assertRaises(ValueError):
            self.corpus.overview()

    def test_wrong_revision_source_or_manifest_path_is_rejected_before_storage(self):
        path = self.bundle / 'manifest.json'
        original = json.loads(path.read_text(encoding='utf-8'))
        for change in ('revision', 'source_hash', 'path'):
            manifest = json.loads(json.dumps(original))
            if change == 'revision': manifest['revision'] = '0' * 40
            if change == 'source_hash': manifest['source_hashes']['papers.parquet'] = '0' * 64
            if change == 'path': manifest['files']['../../private.json'] = manifest['files'].pop('papers.jsonl.gz')
            path.write_text(json.dumps(manifest), encoding='utf-8')
            with self.subTest(change=change), self.assertRaises(ValueError):
                import_bundle(self.bundle, self.data)
            self.assertFalse(self.data.exists())

    def test_invalid_pagination_ids_and_cohorts_do_not_read_arbitrary_files(self):
        import_bundle(self.bundle, self.data)
        for kwargs in ({'year': 2019}, {'cohort': 'all'}, {'offset': -1}, {'limit': 100000}):
            with self.assertRaises(ValueError):
                self.corpus.topic(54, **kwargs)
        with self.assertRaises(ValueError):
            self.corpus.paper('../../config.toml')

    def test_full_operational_backup_restores_exact_corpus_without_research(self):
        store = Store(self.data)
        original = store.export()['tables']
        import_bundle(self.bundle, self.data)
        backups = OperationalBackups(store)
        backup = backups.create()
        restored = self.root / 'restored'
        result = backups.drill(backup['id'], restored)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(verify_corpora(restored), 1)
        self.assertEqual(Corpus(restored).overview()['topics'], self.corpus.overview()['topics'])
        self.assertEqual(store.export()['tables'], original)


if __name__ == '__main__':
    unittest.main()
