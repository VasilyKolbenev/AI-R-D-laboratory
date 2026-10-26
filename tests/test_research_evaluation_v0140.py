"""Human gold and pending coverage never come from model/parser predictions."""
from pathlib import Path
import tempfile
import unittest

from laboratory.core import Store
from laboratory.research_evaluation import Evaluation

TMP = Path(__file__).parent / '.tmp'
TMP.mkdir(exist_ok=True)


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TMP)
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.corpus = Evaluation(self.store)
        self.run = {'id': 'a' * 32, 'status': 'completed', 'output': 'TEST_ONLY report',
                    'plan': {'sources': [{'id': 'b' * 32, 'content_hash': 'c' * 64}]}}

    def test_get_does_not_seed_and_seeded_reports_are_ungraded(self):
        self.assertEqual(self.corpus.summary()['coverage']['case_count'], 0)
        first = self.corpus.seed([self.run])
        self.assertEqual(first, self.corpus.seed([self.run]))
        summary = self.corpus.summary()
        self.assertEqual(summary['coverage']['pending_cases'], 1)
        self.assertIsNone(summary['metrics']['factual_support']['rate'])
        self.assertEqual(summary['metrics']['factual_support']['graded'], 0)

    def test_annotation_is_human_bound_and_revision_does_not_double_denominator(self):
        case = self.corpus.seed([self.run])[0]
        first = self.corpus.annotate({
            'case_id': case['id'], 'annotator': 'TEST_ONLY owner',
            'labels': {'factual_support': 'uncertain', 'number_extraction': 'correct'},
            'notes': 'Human inspected source; support remains uncertain.'})
        second = self.corpus.annotate({
            'case_id': case['id'], 'annotator': 'TEST_ONLY owner',
            'supersedes': first['id'],
            'labels': {'factual_support': 'supported'}, 'notes': 'Read primary source.'})
        self.assertEqual(second['payload']['origin'], 'human')
        summary = self.corpus.summary()
        self.assertEqual(summary['metrics']['factual_support']['graded'], 1)
        self.assertEqual(summary['metrics']['factual_support']['rate'], 1)
        self.assertEqual(summary['metrics']['reader_comprehension']['graded'], 0)
        self.assertEqual(len(summary['annotations']), 2)
        with self.assertRaises(ValueError):
            self.corpus.annotate({
                'case_id': case['id'], 'annotator': 'TEST_ONLY owner',
                'labels': {'factual_support': 'supported'}, 'origin': 'automatic'})

    def test_uncertain_gold_is_not_counted_as_a_factual_failure(self):
        case = self.corpus.seed([self.run])[0]
        self.corpus.annotate({
            'case_id': case['id'], 'annotator': 'TEST_ONLY human',
            'labels': {'factual_support': 'uncertain'}, 'notes': 'Primary source not decisive.'})
        factual = self.corpus.summary()['metrics']['factual_support']
        self.assertEqual(factual['graded'], 0)
        self.assertEqual(factual['uncertain'], 1)
        self.assertIsNone(factual['rate'])

    def test_stale_human_revision_is_rejected_without_branching(self):
        case = self.corpus.seed([self.run])[0]
        values = {'case_id': case['id'], 'annotator': 'TEST_ONLY human',
                  'labels': {'number_extraction': 'correct'}, 'notes': 'Inspected.'}
        self.corpus.annotate(values)
        with self.assertRaises(ValueError):
            self.corpus.annotate(values)
        self.assertEqual(len(self.corpus.summary()['annotations']), 1)


if __name__ == '__main__':
    unittest.main()
