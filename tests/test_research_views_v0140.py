"""Local view projections omit byte blobs and leave source meanings distinct."""
import unittest
from pathlib import Path
import tempfile

from laboratory.research_views import run_view, source_view, workspace


class SourceViewTests(unittest.TestCase):
    def test_planned_run_without_presentation_is_read_only_and_has_no_public_preview(self):
        from laboratory.core import Store
        temporary_root = Path(__file__).parent / '.tmp'
        temporary_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as directory:
            store = Store(Path(directory) / 'data')
            source, _ = store.add_source('TEST_ONLY source about AI methods')
            run = store.create_plan({'source_ids': [source['id']],
                                     'question': 'TEST_ONLY what is supported?'})
            before = store.assets.list()
            result = run_view(store, run, None)
            self.assertIsNone(result['public_preview'])
            self.assertEqual(result['evidence']['status'], 'pending')
            self.assertEqual(workspace(store)['experiment_config']['configured'], False)
            self.assertEqual(store.assets.list(), before)

    def test_capture_view_has_locators_and_integrity_not_raw_original(self):
        view = source_view({'id': 'a' * 64, 'payload': {
            'source_id': 'TEST_ONLY', 'url': 'https://example.org/paper',
            'kind': 'supplied_text', 'status': 'captured', 'sha256': 'b' * 64,
            'raw_b64': 'PRIVATE_RAW_BYTES', 'credential': 'PRIVATE_KEY',
            'segments': [{'id': 's1', 'locator': 'paragraph 1', 'text': 'TEST_ONLY quote',
                          'raw': 'PRIVATE_SEGMENT_DATA'}],
            'limitations': ['Supplied text is not an independent original'],
        }})
        self.assertEqual(view['status'], 'captured')
        self.assertEqual(view['kind'], 'supplied_text')
        self.assertEqual(view['segments'][0]['locator'], 'paragraph 1')
        self.assertNotIn('PRIVATE_', str(view))
        self.assertNotIn('verified', view)


if __name__ == '__main__':
    unittest.main()
