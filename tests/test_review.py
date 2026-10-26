"""Isolated review fixtures: no provider execution, network or real Telegram."""
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from laboratory.core import Store
from laboratory.review import Review, TABLES, template, validate_backup_table, validate_backup, has_user_data


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'data')
        self.review = Review(self.store)
        self.review.initialize()
        self.primary = self.finish('TEST_ONLY primary', {'input_tokens': 100, 'cached_input_tokens': 60, 'output_tokens': 20}, 95)
        self.related = self.finish('TEST_ONLY wrong image', {'input_tokens': 10, 'cached_input_tokens': 6, 'output_tokens': 4}, 54)

    def tearDown(self):
        self.temp.cleanup()

    def finish(self, text, usage, seconds):
        source = self.store.add_source(text, url='https://example.org/research')[0]
        run = self.store.create_plan({'source_ids': [source['id']], 'question': 'TEST_ONLY: compare AI methods'})
        self.store.approve(run['id'], run['plan_hash'], True, 'TEST_ONLY-review-' + run['id'])
        self.store.finish(run['id'], {'status': 'completed', 'text': 'TEST_ONLY original report <lab_memory_review>{"comparisons":[]}</lab_memory_review>',
                                      'usage': usage, 'raw': {'dispatched': True, 'test_only': True}})
        with self.store.connect() as db:
            db.execute('UPDATE runs SET approved_at=?,finished_at=? WHERE id=?',
                       ('2026-10-21T09:00:00+00:00', f'2026-10-21T09:{seconds // 60:02d}:{seconds % 60:02d}+00:00', run['id']))
        return self.store.run(run['id'])

    def body(self):
        body = template()
        body['evidence'] = [{'id': 'report', 'claim': 'TEST_ONLY: source analysis has no evaluator',
                             'basis': 'saved_report', 'locator': 'Report, section 5',
                             'source_url': 'https://example.org/paper', 'excerpt': 'TEST_ONLY report excerpt',
                             'limitations': 'Reported in the saved answer; not independently reproduced.'},
                            {'id': 'cost', 'claim': 'TEST_ONLY: primary elapsed time is 95 seconds',
                             'basis': 'local_record', 'locator': 'runs.finished_at / approved_at',
                             'source_url': '', 'excerpt': '', 'limitations': 'No monetary invoice returned by CLI.'}]
        body['decisions'] = [{'id': 'controller', 'target': 'Scope of the replay claim in the source',
                              'action': 'Attribute the result to recorded branches only',
                              'reason': 'Unrecorded alternatives cannot be observed in this fixture',
                              'evidence_ids': ['report'], 'conditions': 'Collect suitable data first',
                              'next_step': 'Draft a rubric on an existing report'}]
        body['costs']['related_run_ids'] = [self.related['id']]
        body['costs']['notes'] = 'TEST_ONLY: account for the failed-input attempt separately.'
        return body

    def save(self, body=None, version=0):
        return self.review.save(self.primary['id'], {'expected_version': version, 'body': body or self.body()})

    def test_versioned_manual_journal_preserves_provider_report(self):
        original = self.store.run(self.primary['id'])
        first = self.save()
        body = copy.deepcopy(first['current']['body'])
        body['decisions'][0]['reason'] = 'TEST_ONLY clarified scope'
        second = self.save(body, 1)
        self.assertEqual(second['current']['version'], 2)
        self.assertEqual([row['version'] for row in second['history']], [2, 1])
        self.assertNotEqual(second['history'][0]['body'], second['history'][1]['body'])
        self.assertEqual(self.store.run(self.primary['id']), original)
        with self.assertRaisesRegex(ValueError, 'уже изменён'):
            self.save(body, 1)
        self.assertEqual(self.review.get(self.primary['id'])['current']['version'], 2)

    def test_costs_are_derived_and_failed_input_is_not_hidden(self):
        value = self.save()
        costs = value['costs']
        self.assertEqual(costs['primary']['elapsed_seconds'], 95)
        self.assertEqual(costs['related'][0]['elapsed_seconds'], 54)
        self.assertEqual(costs['total_elapsed_seconds'], 149)
        self.assertEqual(costs['total_usage']['input_tokens'], 110)
        self.assertEqual(costs['total_usage']['cached_input_tokens'], 66)
        self.assertEqual(costs['total_usage']['output_tokens'], 24)
        self.assertEqual(costs['primary']['cli_invocations'], 1)
        self.assertIsNone(costs['primary']['money_amount'])
        self.assertIsNone(costs['primary']['api_request_count'])
        self.assertIsNone(costs['manual']['money_amount'])
        self.assertIsNone(costs['manual']['human_minutes'])

    def test_rubric_unknown_is_not_zero_or_automatic_publish_approval(self):
        value = self.save()
        self.assertIsNone(value['quality']['total'])
        self.assertEqual(value['quality']['scored'], 0)
        body = value['current']['body']
        for key, row in body['rubric'].items():
            row.update(score=2 if key == 'mechanism' else 1, note='TEST_ONLY manual assessment', evidence_ids=['report'])
        value = self.save(body, 1)
        self.assertEqual(value['quality']['total'], 6)
        self.assertFalse(value['quality']['publish_approved'])
        self.assertEqual(value['quality']['kind'], 'manual_editorial_review')
        self.assertIn('не вероятность', value['quality']['notice'])

    def test_scores_require_notes_and_maximum_score_requires_evidence(self):
        body = self.body()
        body['rubric']['task']['score'] = True
        with self.assertRaises(ValueError): self.save(body)
        body['rubric']['task']['score'] = 1
        with self.assertRaises(ValueError): self.save(body)
        body['rubric']['task'].update(score=2, note='TEST_ONLY rationale')
        with self.assertRaises(ValueError): self.save(body)
        body['rubric']['task']['evidence_ids'] = ['report']
        self.assertEqual(self.save(body)['quality']['scored'], 1)

    def test_decision_and_quality_references_must_exist(self):
        body = self.body()
        body['decisions'][0]['evidence_ids'] = ['missing']
        with self.assertRaisesRegex(ValueError, 'отсутствующее'): self.save(body)
        body = self.body()
        body['rubric']['task'].update(score=1, note='Reason', evidence_ids=['missing'])
        with self.assertRaisesRegex(ValueError, 'отсутствующее'): self.save(body)
        body = self.body()
        body['evidence'].append(copy.deepcopy(body['evidence'][0]))
        with self.assertRaisesRegex(ValueError, 'повторяются'): self.save(body)

    def test_money_is_manual_and_unknown_values_are_never_fabricated(self):
        body = self.body()
        body['costs']['money_amount'] = 1.25
        with self.assertRaisesRegex(ValueError, 'валюту'): self.save(body)
        body['costs']['currency'] = 'USD'
        body['costs']['human_minutes'] = 12.5
        value = self.save(body)
        self.assertEqual(value['costs']['manual']['money_amount'], 1.25)
        self.assertIsNone(value['costs']['primary']['money_amount'])
        body['costs']['human_minutes'] = float('nan')
        with self.assertRaises(ValueError): self.save(body, 1)

    def test_related_runs_cannot_duplicate_or_invent_usage(self):
        body = self.body()
        body['costs']['related_run_ids'] = [self.primary['id']]
        with self.assertRaisesRegex(ValueError, 'повторно'): self.save(body)
        body['costs']['related_run_ids'] = ['a' * 32]
        with self.assertRaisesRegex(ValueError, 'не найден'): self.save(body)
        body['costs']['related_run_ids'] = [self.related['id'], self.related['id']]
        with self.assertRaisesRegex(ValueError, 'повторяются'): self.save(body)

    def test_journal_for_planned_run_is_not_allowed(self):
        source = self.store.add_source('TEST_ONLY planned')[0]
        run = self.store.create_plan({'source_ids': [source['id']]})
        with self.assertRaisesRegex(ValueError, 'завершённого'):
            self.review.save(run['id'], {'expected_version': 0, 'body': template()})
        self.assertIsNone(self.review.get(run['id'])['current'])

    def test_editorial_is_plain_bounded_and_scope_is_explicit(self):
        body = self.body()
        body['editorial'] = {'title': 'TEST_ONLY research', 'problem': 'Which search strategy should we use?',
                             'mechanism': ['Record attempts', 'Replay known branches', 'Apply online'],
                             'resources': ['Evaluator required'], 'audience': 'A team optimizing code with a deterministic evaluator',
                             'use_case': 'Compare search strategies for the same code optimization task',
                             'public_takeaway': 'Recorded branches can support offline comparisons under stated limits',
                             'visual_kind': 'replay_tree'}
        value = self.save(body)
        self.assertEqual(value['current']['body']['editorial']['audience'], 'A team optimizing code with a deterministic evaluator')
        body['editorial']['lab_target'] = 'No laboratory rollout recommendations'
        with self.assertRaisesRegex(ValueError, 'неизвестные'): self.save(body, 1)
        del body['editorial']['lab_target']
        body['editorial']['problem'] = '<script>alert(1)</script>'
        with self.assertRaisesRegex(ValueError, 'HTML'): self.save(body, 1)
        body['editorial']['problem'] = 'safe'
        body['editorial']['mechanism'] = ['one']
        with self.assertRaisesRegex(ValueError, 'число'): self.save(body, 1)

    def test_evidence_urls_reject_local_credentials_and_tokens(self):
        for url in ['http://127.0.0.1/private', 'https://user:pass@example.org/paper',
                    'https://example.org/file?token=private', 'https://api.telegram.org/bot123456:abcdefghijklmnopqrstuvwxyz/sendMessage']:
            body = self.body(); body['evidence'][0]['source_url'] = url
            with self.assertRaises(ValueError, msg=url): self.save(body)
        body = self.body(); body['evidence'][0]['basis'] = 'independently_proven'
        with self.assertRaises(ValueError): self.save(body)

    def test_comparison_graphs_require_finite_values_and_existing_evidence(self):
        graph = {'label': 'TEST_ONLY agent calls', 'unit': 'calls',
                 'baseline_label': 'Fixed strategy', 'baseline_value': 550,
                 'result_label': 'Adapted strategy', 'result_value': 317,
                 'conditions': 'TEST_ONLY author result on six held-out datasets; not our experiment.',
                 'evidence_ids': ['report']}
        body = self.body(); body['editorial'] = {'comparisons': [graph]}
        value = self.save(body)
        saved = value['current']['body']['editorial']['comparisons'][0]
        self.assertEqual(saved, graph)
        with self.store.connect() as db:
            validate_backup(db)
        for field, invalid in [('baseline_value', float('nan')), ('result_value', float('inf')),
                               ('result_value', -1), ('baseline_value', None), ('result_value', True)]:
            broken = copy.deepcopy(body); broken['editorial']['comparisons'][0][field] = invalid
            with self.assertRaises(ValueError, msg=field + ':' + str(invalid)):
                self.save(broken, 1)
        for refs in ([], ['not-found']):
            broken = copy.deepcopy(body); broken['editorial']['comparisons'][0]['evidence_ids'] = refs
            with self.assertRaisesRegex(ValueError, 'доказательство'):
                self.save(broken, 1)
        self.assertEqual(self.review.get(self.primary['id'])['current']['version'], 1)

    def test_comparisons_remain_optional_for_older_editorial_revisions(self):
        body = self.body(); body['editorial'] = {'title': 'TEST_ONLY old editorial'}
        value = self.save(body)
        self.assertNotIn('comparisons', value['current']['body']['editorial'])
        body = value['current']['body']; body['editorial']['comparisons'] = []
        value = self.save(body, 1)
        self.assertEqual(value['current']['body']['editorial']['comparisons'], [])
        with self.store.connect() as db:
            validate_backup(db)

    def test_backup_validation_checks_references_history_and_dates(self):
        first = self.save()
        with self.store.connect() as db:
            self.assertTrue(has_user_data(db))
            row = dict(db.execute('SELECT * FROM research_review_revisions').fetchone())
            validate_backup_table(TABLES[0], row, db)
            validate_backup(db)
            broken = copy.deepcopy(row); broken['created_at'] = '2026-10-21T12:00:00'
            with self.assertRaises(ValueError): validate_backup_table(TABLES[0], broken, db)
            broken = copy.deepcopy(row); content = json.loads(broken['body']); content['costs']['related_run_ids']=['f'*32]; broken['body']=json.dumps(content)
            with self.assertRaises(ValueError): validate_backup_table(TABLES[0], broken, db)
            db.execute('UPDATE research_review_revisions SET version=3')
            with self.assertRaisesRegex(ValueError, 'неполна'): validate_backup(db)


if __name__ == '__main__':
    unittest.main()
