import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from laboratory.core import Store


class ResearchAssetsContractTests(unittest.TestCase):
    def test_backup_contains_new_immutable_assets_and_claims(self):
        with TemporaryDirectory() as folder:
            store = Store(Path(folder))
            exported = store.export()
            self.assertEqual(exported['schema_version'], 7)
            self.assertEqual(exported['tables']['research_assets'], [])
            self.assertEqual(exported['tables']['research_asset_claims'], [])

    def test_semantic_claim_survives_round_trip_and_cannot_be_replayed(self):
        from laboratory.evidence_archive import Archive
        with TemporaryDirectory() as folder:
            store = Store(folder)
            source, _ = store.add_source('TEST_ONLY immutable source', 'TEST_ONLY source')
            captured = Archive(store).capture(source)
            claimed = store.assets.claim('source_capture', captured['payload'], 'TEST_ONLY-once')
            self.assertEqual(claimed['id'], captured['id'])
            with self.assertRaises(ValueError):
                store.assets.claim('source_capture', captured['payload'], 'TEST_ONLY-once')
            restored = Store(Path(folder) / 'restored')
            restored.restore(store.export())
            with self.assertRaises(ValueError):
                restored.assets.claim('source_capture', captured['payload'], 'TEST_ONLY-once')


if __name__ == '__main__':
    unittest.main()
