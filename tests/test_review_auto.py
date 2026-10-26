"""Automatic journals from stored fixture reports; no models, network or Telegram."""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from laboratory.core import Store
from laboratory.presentation import build_presentation
from laboratory.review import AUTOMATIC_NOTE, TABLES, template, validate_backup, validate_backup_table


class AutomaticReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'data')
        self.review = self.store.review
        self.serial = 0

    def tearDown(self):
        self.temp.cleanup()

    def run_record(self, output='TEST_ONLY stored report', status='completed'):
        self.serial += 1
        source = self.store.add_source('TEST_ONLY fixture ' + str(self.serial), url='https://example.org/paper')[0]
        run = self.store.create_plan({'source_ids': [source['id']]})
        with self.store.connect() as db:
            db.execute('UPDATE runs SET status=?,output=?,usage=?,raw=? WHERE id=?',
                       (status, output, json.dumps({'input_tokens': 120, 'cached_input_tokens': 70, 'output_tokens': 30}),
                        json.dumps({'dispatched': True, 'test_only': True}), run['id']))
        return self.store.run(run['id'])

    def checked_data(self):
        return {'provenance': {'mode': 'model_structured', 'presentation_block_valid': True},
                'evidence': [{'id': 'e1', 'claim': 'TEST_ONLY: calls changed from 10 to 8',
                              'source_url': 'https://example.org/paper', 'locator': 'Table 1',
                              'excerpt': 'TEST_ONLY: calls changed from 10 to 8.',
                              'limitations': 'Author measurements; not reproduced.', 'basis': 'saved_report'}],
                'comparisons': [{'label': 'TEST_ONLY calls', 'conditions': 'Same fixture task; author result.',
                                 'evidence_ids': ['e1']}],
                'publication_checks': {'status': 'ready', 'issues': [], 'automatic': True,
                                       'numeric_data': 'supported',
                                       'notice': 'TEST_ONLY: numbers linked to a saved report excerpt; not independently verified.'}}

    def seed(self, run, data=None):
        with patch('laboratory.presentation.build_presentation', return_value=data or self.checked_data()) as renderer:
            result = self.review.seed_automatic(run['id'])
        return result, renderer

    def test_idempotent_seed_keeps_report_and_actual_costs_unmodified(self):
        run = self.run_record()
        before = self.store.run(run['id'], include_raw=True)
        result, renderer = self.seed(run)
        self.assertEqual(result, {'status': 'inserted', 'version': 1})
        renderer.assert_called_once_with(run)
        value = self.review.get(run['id'])
        body = value['current']['body']
        self.assertEqual(body['origin'], 'automatic_report')
        self.assertEqual(body['editorial'], {})
        self.assertEqual(body['evidence'][0]['basis'], 'saved_report')
        self.assertEqual(body['decisions'][0]['evidence_ids'], ['e1'])
        self.assertEqual(body['decisions'][0]['next_step'], '')
        self.assertTrue(all(row['score'] is None and row['note'] == AUTOMATIC_NOTE for row in body['rubric'].values()))
        self.assertEqual(value['quality']['kind'], 'automatic_unscored')
        self.assertIsNone(value['quality']['total'])
        self.assertFalse(value['quality']['publish_approved'])
        self.assertEqual(value['costs']['primary']['usage']['input_tokens'], 120)
        self.assertIsNone(value['costs']['manual']['human_minutes'])
        self.assertIsNone(value['costs']['manual']['money_amount'])
        result, renderer = self.seed(run)
        self.assertEqual(result['status'], 'existing')
        renderer.assert_not_called()
        self.assertEqual(len(self.review.get(run['id'])['history']), 1)
        self.assertEqual(self.store.run(run['id'], include_raw=True), before)

    def test_existing_owner_journal_is_preserved_without_parsing(self):
        run = self.run_record()
        owner = template()
        owner['costs']['notes'] = 'TEST_ONLY owner note'
        saved = self.review.save(run['id'], {'expected_version': 0, 'body': owner})
        result, renderer = self.seed(run)
        self.assertEqual(result['status'], 'existing')
        renderer.assert_not_called()
        self.assertEqual(self.review.get(run['id']), saved)

    def test_manual_save_of_seed_becomes_a_distinct_manual_revision(self):
        run = self.run_record()
        self.seed(run)
        body = self.review.get(run['id'])['current']['body']
        body['rubric']['task'].update(score=1, note='TEST_ONLY owner assessment')
        value = self.review.save(run['id'], {'expected_version': 1, 'body': body})
        self.assertNotIn('origin', value['current']['body'])
        self.assertEqual(value['history'][1]['body']['origin'], 'automatic_report')
        self.assertEqual(value['quality']['kind'], 'manual_editorial_review')
        self.assertEqual(value['quality']['scored'], 1)
        self.assertFalse(value['quality']['publish_approved'])

    def test_concurrent_seeding_is_one_revision(self):
        run = self.run_record()
        barrier = threading.Barrier(2)
        def render(_run):
            barrier.wait(timeout=5)
            return self.checked_data()
        with patch('laboratory.presentation.build_presentation', side_effect=render):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: self.review.seed_automatic(run['id']), range(2)))
        self.assertEqual(sorted(item['status'] for item in results), ['existing', 'inserted'])
        self.assertEqual(len(self.review.get(run['id'])['history']), 1)

    def test_owner_revision_written_during_parse_wins(self):
        run = self.run_record()
        def render(_run):
            owner = template(); owner['costs']['notes'] = 'TEST_ONLY owner won race'
            self.review.save(run['id'], {'expected_version': 0, 'body': owner})
            return self.checked_data()
        with patch('laboratory.presentation.build_presentation', side_effect=render):
            self.assertEqual(self.review.seed_automatic(run['id'])['status'], 'existing')
        body = self.review.get(run['id'])['current']['body']
        self.assertNotIn('origin', body)
        self.assertEqual(body['costs']['notes'], 'TEST_ONLY owner won race')

    def test_old_reports_and_malformed_blocks_do_not_gain_fake_review(self):
        for text in ('TEST_ONLY legacy report', 'TEST_ONLY <lab_presentation>{broken}</lab_presentation>'):
            run = self.run_record(text)
            self.assertEqual(self.review.seed_automatic(run['id']),
                             {'status': 'skipped', 'reason': 'no_valid_structured_report'})
            self.assertIsNone(self.review.get(run['id'])['current'])
        run = self.run_record(status='failed')
        with patch('laboratory.presentation.build_presentation') as renderer:
            self.assertEqual(self.review.seed_automatic(run['id'])['reason'], 'run_not_completed')
            renderer.assert_not_called()

    def test_invalid_evidence_refs_urls_or_check_metadata_are_not_journaled(self):
        for mutation in ('missing_ref', 'empty_ref', 'unsafe_url', 'empty_excerpt', 'invented_basis', 'missing_checks'):
            data = self.checked_data()
            if mutation == 'missing_ref': data['comparisons'][0]['evidence_ids'] = ['missing']
            if mutation == 'empty_ref': data['comparisons'][0]['evidence_ids'] = []
            if mutation == 'unsafe_url': data['evidence'][0]['source_url'] = 'https://user:password@example.org/paper'
            if mutation == 'empty_excerpt': data['evidence'][0]['excerpt'] = ''
            if mutation == 'invented_basis': data['evidence'][0]['basis'] = 'independently_proven'
            if mutation == 'missing_checks': data.pop('publication_checks')
            run = self.run_record()
            result, _ = self.seed(run, data)
            self.assertEqual(result['reason'], 'invalid_automatic_journal', mutation)
            self.assertIsNone(self.review.get(run['id'])['current'])

    def test_omitted_comparison_reason_is_saved_without_invented_action_plan(self):
        data = self.checked_data()
        data['comparisons'] = []
        data['publication_checks'].update(numeric_data='rejected', status='incomplete',
                                          issues=['TEST_ONLY: result value is absent from the excerpt.'])
        run = self.run_record(); self.seed(run, data)
        decision = self.review.get(run['id'])['current']['body']['decisions'][0]
        self.assertIn('TEST_ONLY: result value is absent', decision['reason'])
        self.assertEqual(decision['evidence_ids'], [])
        self.assertEqual(decision['conditions'], '')
        self.assertEqual(decision['next_step'], '')
        data = self.checked_data()
        data['publication_checks'].update(status='incomplete', issues=['TEST_ONLY: second comparison rejected.'])
        run = self.run_record(); self.seed(run, data)
        decisions = self.review.get(run['id'])['current']['body']['decisions']
        self.assertEqual(len(decisions), 2)
        self.assertEqual(decisions[0]['id'], 'comparison_1')
        self.assertIn('second comparison rejected', decisions[1]['reason'])

    def test_automatic_origin_is_backup_compatible_but_not_a_manual_score(self):
        run = self.run_record(); self.seed(run)
        with self.store.connect() as db:
            validate_backup(db)
            row = dict(db.execute('SELECT * FROM research_review_revisions').fetchone())
            validate_backup_table(TABLES[0], row, db)
            body = json.loads(row['body'])
            for changes in ({'origin': 'manual_scientific_proof'},
                            {'rubric': {**body['rubric'], 'task': {'score': 1, 'note': 'Fake manual score', 'evidence_ids': []}}},
                            {'editorial': {'title': 'Fake owner story'}}):
                broken = copy.deepcopy(row); changed = {**body, **changes}; broken['body'] = json.dumps(changed)
                with self.assertRaises(ValueError): validate_backup_table(TABLES[0], broken, db)
        old = self.run_record()
        value = self.review.save(old['id'], {'expected_version': 0, 'body': template()})
        self.assertNotIn('origin', value['current']['body'])
        with self.store.connect() as db: validate_backup(db)

    def test_valid_presentation_block_supplies_evidence_without_new_model(self):
        excerpt = 'TEST_ONLY: calls changed from 10 to 8.'
        block = {'title': 'TEST_ONLY efficient search', 'problem': 'Reduce search calls.',
                 'audience': 'Teams with an evaluator.', 'use_case': 'Optimize a fixed coding task.',
                 'mechanism': ['Record attempts', 'Compare branches', 'Select strategy'],
                 'findings': [excerpt], 'limitations': ['Authors only; not reproduced.'],
                 'resources': ['Evaluator and stored attempts.'], 'public_takeaway': 'Useful under the same evaluation conditions.',
                 'next_step': 'Choose one existing task.',
                 'evidence': [{key: value for key, value in self.checked_data()['evidence'][0].items() if key != 'basis'}],
                 'comparisons': [{'label': 'Calls', 'unit': 'calls', 'baseline_label': 'Fixed', 'baseline_value': 10,
                                  'result_label': 'Adapted', 'result_value': 8, 'conditions': 'Same fixture task; author data.',
                                  'evidence_ids': ['e1']}]}
        output = excerpt + '\nhttps://example.org/paper\n<lab_presentation>' + json.dumps(block) + '</lab_presentation>'
        run = self.run_record(output)
        self.assertEqual(self.review.seed_automatic(run['id'])['status'], 'inserted')
        review = self.review.get(run['id'])
        self.assertEqual(review['current']['body']['evidence'][0]['excerpt'], excerpt)
        presentation = build_presentation(run, review)
        self.assertEqual(presentation['provenance']['mode'], 'model_structured')
        self.assertEqual(len(presentation['comparisons']), 1)
        self.assertEqual(review['quality']['scored'], 0)


if __name__ == '__main__':
    unittest.main()
