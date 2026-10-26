"""A paid-format packet is assembled once; post packing never invokes a model."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest

from laboratory.orchestration import execute
from laboratory.presentation import build_presentation, utf16_len
from test_checkpoint_integration_v0150 import source_attempt
import test_telegram_workflow as tg


class CompletePostTests(unittest.TestCase):
    def test_long_packet_keeps_gates_and_all_caveats_with_whole_findings(self):
        with TemporaryDirectory(dir=tg.TMP) as folder:
            store, parent, answers = source_attempt(folder)
            run = store.create_continuation(parent['id'])
            store.grant_pilot(run['id'], run['plan_hash'])
            store.approve(run['id'], run['plan_hash'], True, 'TEST_ONLY-layout')
            raw = answers[2].split('<lab_presentation>')[1].split('</lab_presentation>')[0]
            packet = json.loads(raw)
            sentence = 'TEST_ONLY: условия переноса и полезность требуют отдельной проверки. '
            packet.update(problem=sentence * 4, audience=sentence * 2,
                          use_case=sentence * 4, public_takeaway=sentence * 4,
                          next_step=sentence * 3)
            packet['findings'] = [sentence * 5] * 3
            packet['limitations'] = [sentence * 3] * 3
            packet['resources'] = [sentence * 3] * 3
            raw = '<lab_presentation>' + json.dumps(packet, ensure_ascii=False)
            raw += '</lab_presentation>'
            calls = []

            def editor(*args):
                calls.append(1)
                return {'status': 'completed', 'text': raw, 'usage': {},
                        'raw': {'dispatched': True}}

            result = execute(store, store.run(run['id']), editor,
                             Path(folder) / 'editor', threading.Event())
            self.assertEqual(result['status'], 'completed',
                             ((result.get('raw') or {}).get('editor_assembly') or {}).get('error'))
            store.finish(run['id'], result)
            saved = store.run(run['id'])
            original = deepcopy(saved)
            data = build_presentation(saved)
            self.assertEqual(data['source_validation']['status'], 'ready')
            self.assertEqual(data['agent_review']['status'], 'ready')
            self.assertEqual(data['publication_checks']['status'], 'ready')
            self.assertEqual(saved, original)
            self.assertEqual(len(calls), 1)
            self.assertLessEqual(utf16_len(data['post_text']), 3500)
            self.assertNotIn('…', data['post_text'])
            self.assertEqual(data['post_layout']['version'], 'whole-findings-v1')
            for text in (packet['problem'], packet['audience'], packet['use_case'],
                         packet['public_takeaway'], packet['next_step'],
                         *packet['resources'], *packet['limitations']):
                self.assertIn(text.strip(), data['post_text'])
            self.assertTrue(data['post_layout']['omitted_findings'])
            corrupt = deepcopy(saved)
            corrupt['agent_pipeline']['phases'][0]['dispatched'] = False
            self.assertEqual(build_presentation(corrupt)['publication_checks']['status'],
                             'incomplete')


if __name__ == '__main__':
    unittest.main()
