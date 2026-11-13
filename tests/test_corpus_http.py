"""TEST_ONLY corpus API and existing workspace gates, with no provider or Telegram."""
from pathlib import Path

from corpus_fixtures import write_bundle
from laboratory.corpus_import import import_bundle
from test_research_http_v0140 import ResearchHTTPTests


class CorpusHTTPTests(ResearchHTTPTests):
    def test_corpus_read_routes_preserve_history_and_never_dispatch(self):
        self.assertFalse(self.request('GET', '/api/corpus')[1]['available'])
        bundle = write_bundle(Path(self.folder.name) / 'TEST_ONLY-bundle')
        import_bundle(bundle, self.folder.name)
        before = self.app.store.export()['tables']
        for path in ('/api/corpus', '/api/corpus/topics/54?year=2020',
                     '/api/corpus/topics/54?year=2020&cohort=denominator&limit=1&offset=1',
                     '/api/corpus/papers/2020.emnlp-main.1'):
            status, result = self.request('GET', path)
            self.assertEqual(status, 200, result)
        self.assertEqual(self.app.store.export()['tables'], before)
        self.assertEqual(self.app.jobs, {})
        for asset in ('corpus.js', 'corpus.css'):
            self.assertEqual(self.request('GET', '/workbench/' + asset)[0], 200)
        self.assertEqual(self.request('POST', '/api/corpus', {})[0], 404)
        self.assertEqual(self.app.store.export()['tables'], before)

    def test_invalid_corpus_queries_fail_without_changing_active_snapshot(self):
        import_bundle(write_bundle(Path(self.folder.name) / 'TEST_ONLY-bundle'), self.folder.name)
        for path in ('/api/corpus/topics/54?limit=10000', '/api/corpus/topics/54?year=2019',
                     '/api/corpus/topics/54?year=2020&year=2025', '/api/corpus/topics/54?cohort=everything',
                     '/api/corpus/topics/54?unknown=1'):
            self.assertEqual(self.request('GET', path)[0], 400, path)
        self.assertEqual(self.request('GET', '/api/corpus/papers/../../config.toml')[0], 404)
