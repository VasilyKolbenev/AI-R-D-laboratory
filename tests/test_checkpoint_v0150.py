"""Public checkpoint seams; all provider results are fresh local fixtures."""
from copy import deepcopy
import importlib
import importlib.util
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from laboratory.core import Store
from laboratory.orchestration import execute
from test_grounded_flow_v0140 import packets


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / 'outputs' / 'checkpoint-v0150'


class CheckpointTests(unittest.TestCase):
    def api(self):
        specification = importlib.util.find_spec('laboratory.research_continuation')
        self.assertIsNotNone(specification,
                             'Public editor-only checkpoint preparation must exist')
        module = importlib.import_module('laboratory.research_continuation')
        self.assertTrue(callable(getattr(module, 'create', None)),
                        'Checkpoint preparation must be a callable public seam')
        return module

    def parent(self, store, web=False):
        store.update_settings({'research_mode': 'reviewed', 'timeout_seconds': 360,
                               'source_grounding': True, 'capture_originals': False,
                               'daily_run_limit': 6})
        source, _ = store.add_source(
            'Latency is 10 ms for baseline and 8 ms for candidate.',
            'TEST_ONLY checkpoint source', 'https://example.org/paper')
        run = store.create_plan({'source_ids': [source['id']], 'web_search': web})
        store.approve(run['id'], run['plan_hash'], True, 'TEST_ONLY-parent')
        answers = packets(run)
        if web:
            import re
            match = re.search(r'<lab_critic>(.*?)</lab_critic>', answers[1], re.S)
            packet = json.loads(match[1])
            packet['checked_sources'] = [{
                'id': 'c1', 'source_url': 'https://example.org/independent',
                'locator': 'TEST_ONLY table',
                'excerpt': 'Latency is 10 ms for baseline and 8 ms for candidate.',
                'claim': 'TEST_ONLY independent source claim',
                'limitations': 'TEST_ONLY bounded independent check'}]
            packet['counter_evidence']['status'] = 'not_found'
            packet['counter_evidence']['sources'] = []
            body = ('Latency is 10 ms for baseline and 8 ms for candidate.\n'
                    'https://example.org/independent\n')
            answers[1] = body + '<lab_critic>' + json.dumps(packet) + '</lab_critic>'
        clock, calls = [0.0], []

        def runner(plan, prompt, directory, cancel):
            index = len(calls); calls.append(index)
            clock[0] += [106.515, 82.453, 110.235][index]
            if index == 2:
                return {'status': 'outcome_unknown', 'text': '', 'usage': {},
                        'error': 'TEST_ONLY timeout', 'raw': {'dispatched': True}}
            return {'status': 'completed', 'text': answers[index],
                    'usage': {'input_tokens': 100 + index, 'output_tokens': 10},
                    'raw': {'dispatched': True}}

        with patch('laboratory.orchestration.time.monotonic',
                   side_effect=lambda: clock[0]):
            result = execute(store, store.run(run['id']), runner,
                             Path(store.path).parent / 'jobs', threading.Event())
        self.assertEqual(result['status'], 'outcome_unknown', result.get('error'))
        store.finish(run['id'], result)
        self.assertEqual(calls, [0, 1, 2])
        return store.run(run['id'], include_raw=True)

    def folder(self):
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        folder = TemporaryDirectory(dir=ARTIFACTS)
        self.addCleanup(folder.cleanup)
        return folder.name

    def test_public_prepare_requires_a_real_terminal_grounded_parent(self):
        api = self.api(); store = Store(self.folder())
        with self.assertRaises(ValueError):
            api.create(store, 'a' * 32)
        self.assertEqual(store.runs(), [])

    def test_exact_prefix_one_editor_budget_and_parent_immutability(self):
        api = self.api(); store = Store(self.folder()); parent = self.parent(store)
        original = deepcopy(parent)
        child = api.create(store, parent['id'])
        self.assertEqual(child['plan']['timeout_seconds'], 171)
        protocol = child['plan']['research_protocol']
        self.assertEqual(protocol['version'], 'editor-resume-v1')
        self.assertEqual(protocol['roles'], ['reviewer'])
        self.assertEqual(protocol['phase_timeouts'], [151])
        self.assertEqual(protocol['max_calls'], 1)
        self.assertEqual(protocol['web_search_roles'], [])
        self.assertEqual(store.run(parent['id'], include_raw=True), original)
        self.assertEqual(api.create(store, parent['id'])['id'], child['id'])
        self.assertEqual(len(api.prefix_outputs(child['plan'])), 2)
        self.assertAlmostEqual(
            child['plan']['continuation']['successful_prefix_seconds'], 188.968)
        self.assertAlmostEqual(
            child['plan']['continuation']['prior_editor']['elapsed_seconds'], 110.235)
        for key in ('sources', 'study_context', 'memory', 'comparison_context',
                    'evidence_bundle', 'registry_context'):
            self.assertEqual(child['plan'].get(key), parent['plan'].get(key), key)
        self.assertTrue(all(row['status'] == 'reused'
                            for row in api.reused_view(child['plan'])))

    def test_forged_prefix_or_parent_source_fails_closed(self):
        api = self.api(); store = Store(self.folder()); parent = self.parent(store)
        child = api.create(store, parent['id'])
        damaged = deepcopy(child['plan'])
        damaged['continuation']['prefix'][0]['output'] += '\nFORGED'
        with self.assertRaises(ValueError):
            api.validate_plan(damaged)
        with store.connect() as db:
            api.validate_bound(db, child['plan'])
            original = db.execute('SELECT plan FROM runs WHERE id=?',
                                  (parent['id'],)).fetchone()[0]
            altered = json.loads(original)
            altered['sources'][0]['text'] = 'FORGED source'
            db.execute('UPDATE runs SET plan=? WHERE id=?',
                       (json.dumps(altered), parent['id']))
            with self.assertRaises(ValueError):
                api.validate_bound(db, child['plan'])

    def test_missing_or_not_dispatched_success_cannot_be_reused(self):
        api = self.api(); store = Store(self.folder()); parent = self.parent(store)
        with store.connect() as db:
            row = db.execute('SELECT record FROM agent_phases WHERE run_id=? AND phase_index=1',
                             (parent['id'],)).fetchone()
            record = json.loads(row[0]); record['dispatched'] = False
            db.execute('UPDATE agent_phases SET record=? WHERE run_id=? AND phase_index=1',
                       (json.dumps(record), parent['id']))
        with self.assertRaises(ValueError):
            api.create(store, parent['id'])
        self.assertEqual(len(store.runs()), 1)

    def test_rehashed_child_source_and_output_forgery_still_fail_parent_binding(self):
        api = self.api(); store = Store(self.folder()); parent = self.parent(store)
        child = api.create(store, parent['id'])
        for target in ('source', 'output'):
            plan = deepcopy(child['plan'])
            if target == 'source':
                plan['sources'][0]['text'] = 'TEST_ONLY forged child source'
            else:
                import hashlib
                value = plan['continuation']
                value['prefix'][0]['output'] += '\nTEST_ONLY forged claim'
                value['prefix'][0]['output_sha256'] = hashlib.sha256(
                    value['prefix'][0]['output'].encode()).hexdigest()
                value['hash'] = api._digest({key: item for key, item in value.items()
                                             if key != 'hash'})
                plan['research_protocol']['checkpoint_sha256'] = value['hash']
            with self.subTest(target=target), store.connect() as db:
                with self.assertRaises(ValueError):
                    api.validate_bound(db, plan)

    def test_backup_parent_reference_and_prefix_integrity_are_required(self):
        api = self.api(); store = Store(self.folder()); parent = self.parent(store)
        child = api.create(store, parent['id'])
        with store.connect() as db:
            api.validate_backup(db)
            db.execute('DELETE FROM agent_phases WHERE run_id=? AND phase_index=1',
                       (parent['id'],))
            with self.assertRaises(ValueError):
                api.validate_backup(db)
        self.assertEqual(store.run(child['id'])['status'], 'planned')

    def test_recursive_continuation_and_wrong_new_phase_order_are_rejected(self):
        api = self.api(); store = Store(self.folder()); parent = self.parent(store)
        child = api.create(store, parent['id'])
        for index, prior in ((1, []), (0, ['do not rerun'])):
            with self.subTest(index=index), self.assertRaises(ValueError):
                api.prompt(child['plan'], index, prior)
        with store.connect() as db:
            db.execute("UPDATE runs SET status='failed' WHERE id=?", (child['id'],))
        with self.assertRaises(ValueError):
            api.create(store, child['id'])

    def test_new_memory_is_not_selected_for_the_frozen_checkpoint_or_approval(self):
        api = self.api(); store = Store(self.folder()); parent = self.parent(store)
        profile = store.memory.profile()
        store.memory.save_profile({'expected_version': profile['version'],
                                   'goals': 'TEST_ONLY new owner goal after original run'})
        child = api.create(store, parent['id'])
        self.assertEqual(child['plan']['memory'], parent['plan']['memory'])
        self.assertEqual(child['plan']['sources'], parent['plan']['sources'])
        self.assertTrue(store.approve(child['id'], child['plan_hash'], True,
                                      'TEST_ONLY-resume-frozen'))

    def test_original_web_permission_is_preserved_without_editor_web_permission(self):
        api = self.api(); store = Store(self.folder()); parent = self.parent(store, web=True)
        child = api.create(store, parent['id'])
        self.assertIs(child['plan']['web_search'], False)
        self.assertIs(child['plan']['continuation'].get('parent_web_search'), True)
        self.assertIn('https://example.org/independent', api.prefix_outputs(child['plan'])[1])
        with store.connect() as db:
            api.validate_bound(db, child['plan'])


def run_sentinels():
    """Two isolated function mutants; production files are never rewritten."""
    module = importlib.import_module('laboratory.research_continuation')
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    outcomes = []
    original_recipe = module._recipe

    def extra_calls(*args):
        result = original_recipe(*args)
        result['max_calls'] = 3
        return result

    cases = [
        ('parent-binding-disabled', 'validate_bound', lambda *args: None,
         'test_forged_prefix_or_parent_source_fails_closed'),
        ('extra-call-reservation', '_recipe', extra_calls,
         'test_exact_prefix_one_editor_budget_and_parent_immutability')]
    for name, target, replacement, test_name in cases:
        output = io.StringIO()
        with patch.object(module, target, replacement):
            result = unittest.TextTestRunner(stream=output, verbosity=2).run(
                unittest.TestSuite([CheckpointTests(test_name)]))
        killed = not result.wasSuccessful()
        (ARTIFACTS / ('a-mutant-' + name + '.log')).write_text(
            output.getvalue() + '\nMUTANT_KILLED=' + str(killed) + '\n', encoding='utf-8')
        outcomes.append({'mutant': name, 'killed': killed, 'tests': result.testsRun,
                         'failures': len(result.failures), 'errors': len(result.errors)})
    print(json.dumps(outcomes))
    if not all(item['killed'] for item in outcomes):
        raise AssertionError('A sentinel mutant survived')


if __name__ == '__main__':
    unittest.main()
