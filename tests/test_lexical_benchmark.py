"""TEST_ONLY four-document fixtures; no network or official-dataset execution."""
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from laboratory.core import Store
from laboratory import lexical_benchmark as lexical
from laboratory import lexical_engine
from laboratory.research_assets import canonical, identity

TMP = Path(__file__).parent / '.tmp'
TMP.mkdir(exist_ok=True)


class LexicalBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TMP)
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.runner = lexical.LexicalBenchmark(self.store)
        self.runner.root.joinpath('qrels').mkdir(parents=True)
        corpus = [
            {'_id': 'TEST_ONLY_d1', 'title': 'Alpha', 'text': 'alpha alpha evidence study'},
            {'_id': 'TEST_ONLY_d2', 'title': 'Beta', 'text': 'beta study'},
            {'_id': 'TEST_ONLY_d3', 'title': 'Gamma', 'text': 'gamma gamma gamma'},
            {'_id': 'TEST_ONLY_d4', 'title': 'Control', 'text': 'control unrelated'}]
        queries = [{'_id': 'TEST_ONLY_q1', 'text': 'alpha study'},
                   {'_id': 'TEST_ONLY_q2', 'text': 'beta study'}]
        contents = {'corpus.jsonl': ''.join(canonical(row) + '\n' for row in corpus).encode(),
                    'queries.jsonl': ''.join(canonical(row) + '\n' for row in queries).encode(),
                    'qrels/test.tsv': b'query-id\tcorpus-id\tscore\nTEST_ONLY_q1\tTEST_ONLY_d1\t1\nTEST_ONLY_q2\tTEST_ONLY_d2\t1\n'}
        archive = self.runner.root / 'scifact.zip'
        with zipfile.ZipFile(archive, 'w') as zipped:
            for name, data in contents.items():
                self.runner.root.joinpath(*name.split('/')).write_bytes(data)
                zipped.writestr('scifact/' + name, data)
        # Only this fixture replaces the production pinned official archive hash.
        self.pin = patch.object(lexical, 'OFFICIAL_ARCHIVE_MD5', hashlib.md5(archive.read_bytes()).hexdigest())
        self.pin.start()
        self.addCleanup(self.pin.stop)
        self.manifest = {'version': 'lexical-dataset-v1', 'dataset': 'beir-scifact',
            'source_url': lexical.SOURCE_URL, 'archive_sha256': lexical._sha(archive.read_bytes()),
            'archive_md5': lexical.OFFICIAL_ARCHIVE_MD5,
            'files': {name: {'sha256': lexical._sha(data), 'bytes': len(data),
                            'records': 4 if name == 'corpus.jsonl' else 2}
                      for name, data in contents.items()},
            'query_ids': ['TEST_ONLY_q1', 'TEST_ONLY_q2'],
            'counts': {'documents': 4, 'queries': 2, 'test_queries': 2, 'qrels': 2}}
        original_protocol = lexical._protocol()
        original_protocol['test_only'] = True
        self.protocol = patch.object(lexical, '_protocol', return_value=original_protocol)
        self.protocol.start()
        self.addCleanup(self.protocol.stop)
        self.calls = []
        real_run = lexical._run_engine

        def observed(corpus, queries, qrels, protocol, cancel):
            self.calls.append(1)
            self.assertEqual(len(corpus), 4)
            self.assertTrue(all(row['_id'].startswith('TEST_ONLY_') for row in corpus))
            self.assertTrue(protocol['test_only'])
            self.assertEqual(len(self.store.assets.list('lexical_approval')), 1)
            self.assertEqual(len(self.store.assets.list('lexical_intent')), 1)
            self.assertEqual(self.runner.status(self.current_plan['id'])['status'], 'running')
            return real_run(corpus, queries, qrels, protocol, cancel)
        self.engine = patch.object(lexical, '_run_engine', side_effect=observed)
        self.engine.start()
        self.addCleanup(self.engine.stop)

    def prepare(self):
        self.current_plan = self.runner.prepare(self.manifest)
        return self.current_plan

    def start(self, command='TEST_ONLY_command', **kwargs):
        return self.runner.start(self.current_plan['id'], self.current_plan['plan_hash'],
                                 True, command, **kwargs)

    def test_prepare_is_immutable_complete_and_does_not_execute(self):
        plan = self.prepare()
        self.assertEqual(self.calls, [])
        self.assertEqual(plan['kind'], 'lexical_plan')
        self.assertEqual(plan['payload']['manifest'], self.manifest)
        self.assertEqual(plan['payload']['limits']['external_model_calls'], 0)
        self.assertEqual(plan['payload']['limits']['repetitions'], 6)
        self.assertEqual(plan['payload']['limits']['estimated_peak_ram_mib'], 512)
        self.assertEqual(plan['payload']['protocol']['bm25_k1'], 1.2)
        self.assertEqual(plan['payload']['protocol']['bm25_b'], .75)
        self.assertEqual(len(plan['payload']['engine']['sha256']), 64)
        self.manifest['counts']['documents'] = 3
        self.assertEqual(self.store.assets.get(plan['id'])['payload']['manifest']['counts']['documents'], 4)
        self.assertEqual(self.runner.status(plan['id'])['status'], 'planned')
        self.assertEqual(len(self.runner.list()), 1)

    def test_explicit_exact_approval_then_durable_intent_and_local_receipt(self):
        plan = self.prepare()
        with self.assertRaises(ValueError):
            self.runner.start(plan['id'], plan['plan_hash'], False, 'TEST_ONLY_no_consent')
        with self.assertRaises(ValueError):
            self.runner.start(plan['id'], 'f' * 64, True, 'TEST_ONLY_bad_hash')
        self.assertEqual(self.store.assets.list('lexical_approval'), [])
        status = self.start()
        result = status['result']
        self.assertEqual(status['status'], 'completed')
        self.assertTrue(status['completed'])
        self.assertIs(type(status['passed']), bool)
        self.assertEqual(result['origin'], 'executed_local_lexical')
        self.assertEqual(result['scope'], lexical.SCOPE)
        self.assertEqual(result['raw']['environment']['evidence_scope'], 'TEST_ONLY fixture')
        self.assertEqual(result['source_algorithm_version'], lexical_engine.VERSION)
        self.assertEqual(result['external_model_calls'], 0)
        self.assertEqual(result['monetary_api_cost_usd'], 0)
        self.assertIsNone(result['local_energy_cost_usd'])
        self.assertEqual(result['metrics_sha256'], lexical._digest(result['raw']['metrics']))
        self.assertEqual(result['rankings_sha256'], lexical._digest(result['raw']['rankings']))
        self.assertEqual(result['raw']['counts'], {'documents': 4, 'queries': 2, 'judgments': 2})
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(self.store.assets.list('experiment_observation')), 0)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM runs').fetchone()[0], 0)
            lexical.validate_backup(db)

    def test_repeated_start_and_concurrent_clicks_execute_once(self):
        self.prepare()
        barrier = threading.Barrier(2)
        outputs, errors = [], []

        def clicked(index):
            try:
                barrier.wait(timeout=5)
                outputs.append(self.start('TEST_ONLY_click_' + str(index)))
            except BaseException as error:
                errors.append(error)
        threads = [threading.Thread(target=clicked, args=(index,)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(outputs[0]['result_id'], outputs[1]['result_id'])
        self.assertEqual(self.start()['result_id'], outputs[0]['result_id'])
        self.assertEqual(len(self.calls), 1)

    def test_dataset_archive_code_and_runtime_drift_block_before_approval(self):
        self.prepare()
        original_engine = lexical._engine_identity()
        with patch.object(lexical, '_engine_identity', return_value={**original_engine, 'sha256': 'f' * 64}):
            with self.assertRaises(ValueError):
                self.start()
        original_runtime = lexical._runtime()
        with patch.object(lexical, '_runtime', return_value={**original_runtime, 'cache_tag': 'TEST_ONLY_changed'}):
            with self.assertRaises(ValueError):
                self.start()
        corpus = self.runner.root / 'corpus.jsonl'
        original = corpus.read_bytes()
        corpus.write_bytes(original + b' ')
        with self.assertRaises(ValueError):
            self.start()
        corpus.write_bytes(original)
        archive = self.runner.root / 'scifact.zip'
        archive.write_bytes(archive.read_bytes() + b' ')
        with self.assertRaises(ValueError):
            self.start()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.store.assets.list('lexical_approval'), [])

    def test_interrupted_intent_is_unknown_and_cannot_retry_even_after_restore(self):
        self.prepare()
        with patch.object(lexical, '_run_engine', side_effect=KeyboardInterrupt('TEST_ONLY_crash')) as crashed:
            with self.assertRaises(KeyboardInterrupt):
                self.start()
            self.assertEqual(crashed.call_count, 1)
            self.assertEqual(self.runner.status(self.current_plan['id'])['status'], 'outcome_unknown')
            self.start('TEST_ONLY_after_crash')
            self.assertEqual(crashed.call_count, 1)
        restored = Store(Path(self.temp.name) / 'TEST_ONLY_restored_unknown')
        restored.restore(self.store.export())
        result = lexical.LexicalBenchmark(restored).start(
            self.current_plan['id'], self.current_plan['plan_hash'], True, 'TEST_ONLY_after_restore')
        self.assertEqual(result['status'], 'outcome_unknown')
        self.assertEqual(self.calls, [])

    def test_drift_after_approval_is_rechecked_after_intent_before_engine(self):
        self.prepare()
        original_claim = self.runner.assets.claim

        def changed_after_intent(kind, payload, claim_key):
            asset = original_claim(kind, payload, claim_key)
            if kind == 'lexical_intent':
                path = self.runner.root / 'corpus.jsonl'
                path.write_bytes(path.read_bytes() + b' ')
            return asset
        with patch.object(self.runner.assets, 'claim', side_effect=changed_after_intent):
            status = self.start()
        self.assertEqual(status['status'], 'failed')
        self.assertEqual(self.calls, [])
        self.assertEqual(len(self.store.assets.list('lexical_approval')), 1)
        self.assertEqual(len(self.store.assets.list('lexical_intent')), 1)
        self.assertIsNone(status['result']['raw'])
        self.assertEqual(self.start()['result_id'], status['result_id'])

    def test_failure_and_pre_cancel_are_terminal_and_preserve_no_false_metrics(self):
        self.prepare()
        with patch.object(lexical, '_run_engine', side_effect=TimeoutError('TEST_ONLY_timeout')):
            status = self.start()
        self.assertEqual(status['status'], 'failed')
        self.assertFalse(status['completed'])
        self.assertIsNone(status['passed'])
        self.assertIsNone(status['result']['raw'])
        self.assertEqual(self.start()['result_id'], status['result_id'])
        # A separate store gives a separate approval; cancellation dispatches no engine.
        second = Store(Path(self.temp.name) / 'TEST_ONLY_cancelled')
        runner = lexical.LexicalBenchmark(second)
        runner.root.mkdir(parents=True)
        for name in (*lexical.FILE_LIMITS, 'scifact.zip'):
            destination = runner.root.joinpath(*name.split('/'))
            destination.parent.mkdir(exist_ok=True)
            destination.write_bytes(self.runner.root.joinpath(*name.split('/')).read_bytes())
        plan = runner.prepare(self.manifest)
        cancel = threading.Event()
        cancel.set()
        status = runner.start(plan['id'], plan['plan_hash'], True, 'TEST_ONLY_cancel', cancel)
        self.assertEqual(status['status'], 'cancelled')
        self.assertIsNone(status['result']['raw'])
        self.assertEqual(self.calls, [])

    def test_command_id_cannot_authorize_another_plan(self):
        self.prepare()
        self.start()
        runtime = lexical._runtime()
        with patch.object(lexical, '_runtime', return_value={**runtime, 'cache_tag': 'TEST_ONLY_second'}):
            plan = self.prepare()
            with self.assertRaises(ValueError):
                self.start()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.runner.status(plan['id'])['status'], 'planned')

    def test_restore_preserves_receipt_without_dataset_and_rejects_tamper(self):
        self.prepare()
        completed = self.start()
        backup = self.store.export()
        restored = Store(Path(self.temp.name) / 'TEST_ONLY_restored_completed')
        restored.restore(backup)
        receipt = lexical.LexicalBenchmark(restored).status(self.current_plan['id'])
        self.assertEqual(receipt['result_id'], completed['result_id'])
        self.assertEqual(receipt['status'], 'completed')
        self.assertFalse(lexical.LexicalBenchmark(restored).root.exists())
        # Updating a metric without its receipt hashes is rejected immediately.
        payload = copy.deepcopy(completed['result'])
        payload['raw']['metrics']['tfidf']['ndcg_at_10'] = .123
        with self.assertRaises(ValueError):
            lexical.validate_asset('lexical_result', payload)
        payload = copy.deepcopy(completed['result'])
        payload['passed'] = int(payload['passed'])
        with self.assertRaises(ValueError):
            lexical.validate_asset('lexical_result', payload)
        # A content-addressed alteration with recomputed hashes still fails graph coverage.
        payload = copy.deepcopy(completed['result'])
        payload['manifest']['archive_sha256'] = 'f' * 64
        lexical.validate_asset('lexical_result', payload)
        with self.store.connect() as db:
            db.execute('INSERT INTO research_assets SELECT ?,kind,?,created_at FROM research_assets WHERE id=?',
                       (identity('lexical_result', payload), canonical(payload), completed['result_id']))
            db.execute('UPDATE research_asset_claims SET asset_id=? WHERE asset_id=?',
                       (identity('lexical_result', payload), completed['result_id']))
            db.execute('DELETE FROM research_assets WHERE id=?', (completed['result_id'],))
            with self.assertRaises(ValueError):
                lexical.validate_backup(db)

    def test_strict_schemas_paths_and_no_import_or_unclaimed_execution(self):
        for change in (
                {'path': '../TEST_ONLY.jsonl'}, {'source_url': 'https://example.com/scifact.zip'},
                {'archive_md5': '0' * 32}, {'query_ids': ['TEST_ONLY_q1', 'TEST_ONLY_q1']}):
            with self.assertRaises(ValueError):
                self.runner.prepare({**self.manifest, **change})
        plan = self.prepare()
        for key, value in (('limits', {**lexical.LIMITS, 'external_model_calls': False}),
                           ('protocol', {**plan['payload']['protocol'], 'repeats': 5}),
                           ('execute', True)):
            payload = {**plan['payload'], key: value}
            with self.assertRaises(ValueError):
                self.store.assets.put('lexical_plan', payload)
        approval = {'version': 'lexical-approval-v1', 'plan_id': plan['id'],
                    'plan_hash': plan['plan_hash'], 'consent': True,
                    'command_id': 'TEST_ONLY_direct', 'approved_at': datetime.now(timezone.utc).isoformat(),
                    **lexical._approval_hashes(plan['payload'])}
        with self.assertRaises(ValueError):
            self.store.assets.put('lexical_approval', approval)
        with self.assertRaises(ValueError):
            self.store.assets.claim('lexical_approval', approval, 'TEST_ONLY_wrong_claim_key')
        invalid = {**approval, 'runtime_sha256': 'f' * 64}
        with self.assertRaises(ValueError):
            self.store.assets.claim('lexical_approval', invalid, 'lexical-approval:' + plan['id'])
        self.assertFalse(hasattr(self.runner, 'imports'))
        self.assertEqual(self.calls, [])

    def test_relationship_claims_reject_unapproved_intent_and_detached_receipt(self):
        plan = self.prepare()
        intent = {'version': 'lexical-intent-v1', 'plan_id': plan['id'],
                  'plan_hash': plan['plan_hash'], 'approval_id': 'f' * 64,
                  'input_sha256': lexical._digest({'manifest': self.manifest,
                                                  'protocol': plan['payload']['protocol']}),
                  'started_at': datetime.now(timezone.utc).isoformat()}
        with self.assertRaises(ValueError):
            self.store.assets.claim('lexical_intent', intent, 'lexical-intent:' + plan['id'])
        status = self.start()
        with self.store.connect() as db:
            db.execute('DELETE FROM research_asset_claims WHERE claim_key=?',
                       ('lexical-intent:' + plan['id'],))
            with self.assertRaises(ValueError):
                lexical.validate_backup(db)
        self.assertEqual(status['result']['origin'], 'executed_local_lexical')

    def test_plan_list_reads_each_kind_once_and_omits_large_rankings(self):
        self.prepare()
        status = self.start()
        with patch.object(self.runner.assets, 'list', wraps=self.runner.assets.list) as listed:
            items = self.runner.list()
        self.assertEqual(listed.call_count, 4)
        self.assertEqual(items[0]['result_id'], status['result_id'])
        self.assertEqual(items[0]['metrics'], status['result']['raw']['metrics'])
        self.assertEqual(items[0]['counts'], status['result']['raw']['counts'])
        self.assertNotIn('raw', items[0])
        self.assertNotIn('result', items[0])
        self.assertNotIn('rankings', canonical(items))

    def test_receipt_budget_does_not_publish_truncated_completed_result(self):
        self.prepare()
        with patch.object(lexical, 'MAX_BYTES', 128):
            status = self.start()
        self.assertEqual(status['status'], 'failed')
        self.assertIsNone(status['result']['raw'])
        self.assertFalse(status['completed'])
        self.assertEqual(len(self.calls), 1)


if __name__ == '__main__':
    unittest.main()
