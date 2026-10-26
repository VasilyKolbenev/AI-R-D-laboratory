import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest

from laboratory.core import Store
from laboratory.orchestration import execute
from laboratory.presentation import build_presentation
from laboratory.research_protocol import phase_prompt

TEXT = 'Latency is 10 ms for baseline and 8 ms for candidate.'
URL = 'https://example.org/paper'


def grounded(store):
    store.update_settings({'research_mode': 'reviewed', 'timeout_seconds': 240,
                           'source_grounding': True, 'capture_originals': False})
    source, _ = store.add_source(TEXT, 'TEST_ONLY primary text', URL)
    return store.create_plan({'source_ids': [source['id']],
                              'question': 'TEST_ONLY compare source evidence'})


def packets(run):
    from test_applied_analysis_v0130 import AppliedAnalysisTests
    _, research, critic, final = AppliedAnalysisTests().fixture()
    research['claims'][0]['source_ids'] = [run['plan']['sources'][0]['id']]
    critic['independent_conclusion'] = 'TEST_ONLY source reports a latency comparison.'
    critic['counter_evidence'] = {'status': 'not_searched', 'sources': [],
                                  'limitations': 'TEST_ONLY offline source analysis.'}
    document = run['plan']['evidence_bundle']['documents'][0]
    final['evidence_checks'] = [{
        'evidence_id': 'e1', 'document_id': document['asset_id'],
        'segment_id': document['segments'][0]['id'], 'quote': TEXT,
        'relation': 'supports', 'reason': 'TEST_ONLY literal reported latency pair.'}]
    return [TEXT + '\n' + URL + '\n<lab_research>' + json.dumps(research) + '</lab_research>',
            '<lab_critic>' + json.dumps(critic) + '</lab_critic>',
            TEXT + '\n' + URL + '\n<lab_presentation>' + json.dumps(final) +
            '</lab_presentation>']


class GroundedFlowTests(unittest.TestCase):
    def test_new_plan_freezes_original_and_blind_critic_within_existing_budget(self):
        with TemporaryDirectory() as folder:
            store = Store(folder)
            run = grounded(store)
            protocol = run['plan']['research_protocol']
            self.assertEqual(protocol['version'], 'three-pass-v2')
            self.assertEqual(protocol['max_calls'], 3)
            self.assertEqual(protocol['total_timeout_seconds'], 240)
            self.assertEqual(store.settings()['daily_run_limit'], 3)
            self.assertIn(TEXT, run['plan']['execution_context']['prompt'])
            marker = 'TEST_ONLY_RESEARCHER_VERDICT_MUST_BE_HIDDEN'
            critic = phase_prompt(run['plan'], 1, [marker])
            self.assertNotIn(marker, critic)
            self.assertIn(TEXT, critic)
            from laboratory.trace import inputs
            self.assertEqual(inputs(run['plan'])['evidence_bundle'],
                             run['plan']['evidence_bundle'])
            self.assertEqual(inputs(run['plan'])['registry_context'],
                             run['plan']['registry_context'])
            payload = json.loads(critic.split('(JSON):\n', 1)[1])
            self.assertEqual(payload['comparison_context']['registry_context'],
                             run['plan']['registry_context'])
            reviewer = phase_prompt(run['plan'], 2, [marker, 'TEST_ONLY critic'])
            self.assertIn(marker, reviewer)

    def test_completed_mock_pipeline_registers_observations_and_pending_quality(self):
        with TemporaryDirectory() as folder:
            store = Store(folder)
            run = grounded(store)
            outputs = packets(run)
            self.assertTrue(store.approve(run['id'], run['plan_hash'], True, 'TEST_ONLY-go'))
            calls = []

            def runner(plan, prompt, directory, cancel):
                index = len(calls)
                calls.append(prompt)
                return {'status': 'completed', 'text': outputs[index],
                        'usage': {'input_tokens': 10, 'output_tokens': 5},
                        'raw': {'dispatched': True}}

            result = execute(store, store.run(run['id']), runner, Path(folder), threading.Event())
            self.assertEqual(result['status'], 'completed', result['error'])
            store.finish(run['id'], result)
            saved = store.run(run['id'])
            data = build_presentation(saved, store.review.get(run['id']))
            self.assertEqual(len(calls), 3)
            self.assertEqual(data['source_validation']['status'], 'ready')
            self.assertEqual(data['publication_checks']['status'], 'ready')
            self.assertEqual(saved['research_ingestion']['status'], 'ready')
            self.assertEqual(len(store.assets.list('measurement')), 2)
            self.assertEqual(len(store.assets.list('evaluation_case')), 1)
            self.assertEqual(store.assets.list('evaluation_annotation'), [])
            backup = store.export()
            restored = Store(Path(folder) / 'restored')
            restored.restore(backup)
            self.assertEqual(restored.run(run['id'])['output'], outputs[2])
            self.assertEqual(len(restored.assets.list('source_capture')), 1)

    def test_corrupt_capture_restore_rolls_back_without_touching_destination(self):
        with TemporaryDirectory() as folder:
            store = Store(folder)
            grounded(store)
            backup = store.export()
            row = backup['tables']['research_assets'][0]
            row['payload'] = row['payload'].replace('10 ms', '99 ms')
            destination = Store(Path(folder) / 'destination')
            with self.assertRaises(ValueError):
                destination.restore(backup)
            self.assertEqual(destination.counts(), {'sources': 0, 'runs': 0, 'knowledge': 0})
            self.assertEqual(destination.assets.list(), [])

    def test_partial_excerpt_keeps_each_document_and_restores_original_captures(self):
        with TemporaryDirectory() as folder:
            store = Store(folder)
            store.update_settings({'research_mode': 'reviewed', 'timeout_seconds': 240,
                                   'source_grounding': True})
            source_ids = []
            for number in range(6):
                text = '\n'.join('TEST_ONLY-' + str(number) + '-' + str(index) + 'x' * 2980
                                 for index in range(3))
                source, _ = store.add_source(text, 'TEST_ONLY large source')
                source_ids.append(source['id'])
            run = store.create_plan({'source_ids': source_ids, 'question': 'TEST_ONLY compare'})
            documents = run['plan']['evidence_bundle']['documents']
            self.assertEqual(len(documents), 6)
            self.assertTrue(all(document['segments'] for document in documents))
            self.assertTrue(all(document['status'] == 'partial' for document in documents))
            restored = Store(Path(folder) / 'restored')
            restored.restore(store.export())
            self.assertEqual(len(restored.assets.list('source_capture')), 6)


if __name__ == '__main__':
    unittest.main()
