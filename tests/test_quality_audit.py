"""TEST_ONLY audit controls: no providers, browser, live store, or publication."""
from copy import deepcopy
import hashlib
import json
import unittest
from unittest.mock import patch

from laboratory.quality_audit import (VERSION, audit_saved_quality, control_corpus,
                                      run_control_corpus, summarize_audits)


class QualityAuditTests(unittest.TestCase):
    def fixture(self):
        case = control_corpus()[0]
        return case['run'], case['presentation']

    def finding(self, audit, identifier):
        return next(row for row in audit['findings'] if row['id'] == identifier)

    def test_control_corpus_detects_all_ten_expected_cases_without_false_numeric_requirement(self):
        result = run_control_corpus()
        self.assertTrue(result['test_only'])
        self.assertEqual(result['case_count'], 10)
        self.assertEqual(result['matched_case_count'], 10, result)
        for case in result['cases']:
            self.assertTrue(case['id'].startswith('TEST_ONLY-'))
            self.assertEqual(case['observed'], case['expected'])
        self.assertEqual(result['cases'][7]['observed']['numbers.no_pair'], 'not_applicable')

    def test_supported_record_pass_is_explicitly_not_independent_scientific_verification(self):
        run, data = self.fixture()
        result = audit_saved_quality(run, data)
        self.assertEqual(result['overall_status'], 'pass', result['findings'])
        self.assertFalse(result['independent_verification'])
        self.assertFalse(result['publication_approved'])
        self.assertEqual(result['source_provenance']['level'], 'original_segments_bound')
        self.assertFalse(result['source_provenance']['independently_verified'])
        self.assertEqual(self.finding(result, 'scope.scientific_truth')['status'], 'not_applicable')
        self.assertEqual(self.finding(result, 'format.publication')['category'], 'format_validation')
        self.assertNotIn('score', json.dumps(result))
        json.dumps(result, ensure_ascii=False, allow_nan=False)

    def test_saved_ready_flags_cannot_hide_changed_original_number_or_source(self):
        for mutation in ('text', 'url', 'number'):
            run, data = self.fixture()
            if mutation == 'text':
                run['plan']['evidence_bundle']['documents'][0]['segments'][0]['text'] = 'TEST_ONLY: no reported numbers here.'
            elif mutation == 'url':
                run['plan']['evidence_bundle']['documents'][0]['url'] = 'https://example.org/TEST_ONLY-unrelated'
            else:
                data['applied_analysis']['rows'][0]['candidate']['value'] = 999
            data['source_validation']['status'] = 'ready'
            data['publication_checks']['status'] = 'ready'
            audit = audit_saved_quality(run, data)
            self.assertEqual(audit['overall_status'], 'needs_review')
            self.assertEqual(self.finding(audit, 'sources.original_binding')['status'], 'needs_review')
            self.assertEqual(self.finding(audit, 'numbers.binding.0.candidate')['status'], 'needs_review')

    def test_missing_evidence_never_gets_pass_from_empty_registry_or_manual_score(self):
        run, data = self.fixture()
        data['evidence'] = []
        data['source_validation'] = {'status': 'ready', 'checks': []}
        review = {'current': {'version': 1, 'body': {'rubric': {'evidence': {'score': 2, 'note': 'TEST_ONLY'}}}}}
        audit = audit_saved_quality(run, data, review)
        self.assertEqual(self.finding(audit, 'facts.registry')['status'], 'needs_review')
        self.assertEqual(self.finding(audit, 'sources.original_binding')['status'], 'needs_review')
        self.assertEqual(audit['source_provenance']['level'], 'missing_or_unread')
        self.assertNotIn('score', audit)

    def test_explicit_incompatible_table_without_chart_is_allowed_but_unknown_context_is_visible(self):
        run, data = self.fixture()
        row = data['applied_analysis']['rows'][0]
        row.update(comparability='not_comparable', comparability_reason='TEST_ONLY different datasets')
        data['comparisons'] = []
        audit = audit_saved_quality(run, data)
        self.assertEqual(self.finding(audit, 'comparability.context.0')['status'], 'pass')
        self.assertFalse(any(item['id'].startswith('comparability.chart.') for item in audit['findings']))
        row['comparability'] = 'comparable'
        row['measurement_context']['hardware'] = None
        audit = audit_saved_quality(run, data)
        self.assertEqual(self.finding(audit, 'comparability.context.0')['status'], 'needs_review')

    def test_contradiction_is_visible_even_when_literal_quote_binding_is_valid(self):
        run, data = self.fixture()
        data['applied_analysis']['rows'] = []
        data['comparisons'] = []
        data['source_validation']['checks'][0]['relation'] = 'contradicts'
        audit = audit_saved_quality(run, data)
        self.assertEqual(self.finding(audit, 'sources.original_binding')['status'], 'pass')
        self.assertEqual(self.finding(audit, 'facts.source_relation.0')['status'], 'needs_review')

    def test_observable_blocker_fix_is_record_check_while_missing_duplicate_and_unresolved_are_detected(self):
        run, data = self.fixture()
        issue = {'id': 'i1', 'severity': 'blocker'}
        data['agent_review']['critic']['issues'] = [issue]
        fix = {'issue_id': 'i1', 'status': 'fixed', 'reason': 'TEST_ONLY: the exact latency statement is retained with author attribution.',
               'resolution_excerpt': data['evidence'][0]['excerpt']}
        data['agent_review']['dispositions'] = [fix]
        self.assertEqual(self.finding(audit_saved_quality(run, data), 'critic.disposition.0')['status'], 'pass')
        for dispositions in ([], [fix, deepcopy(fix)], [{**fix, 'status': 'unresolved'}], [{**fix, 'resolution_excerpt': 'TEST_ONLY absent'}]):
            data['agent_review']['dispositions'] = dispositions
            self.assertEqual(self.finding(audit_saved_quality(run, data), 'critic.disposition.0')['status'], 'needs_review')

    def test_unknown_self_host_is_allowed_but_unqualified_resource_claim_is_flagged(self):
        run, data = self.fixture()
        self.assertEqual(self.finding(audit_saved_quality(run, data), 'self_hosted.unknowns')['status'], 'pass')
        data['applied_analysis']['unknowns'] = []
        data['story'][1]['items'] = ['TEST_ONLY: deploy on this GPU.']
        self.assertEqual(self.finding(audit_saved_quality(run, data), 'self_hosted.unknowns')['status'], 'needs_review')
        run['plan']['study_context'] = {'task': {'self_hosted': {'availability': 'not_applicable'}}}
        self.assertEqual(self.finding(audit_saved_quality(run, data), 'self_hosted.unknowns')['status'], 'not_applicable')

    def test_audit_and_corpus_are_read_only_offline_and_deterministic(self):
        run, data = self.fixture()
        review = {'body': {'decisions': []}}
        original = deepcopy((run, data, review))
        with patch('socket.socket', side_effect=AssertionError('TEST_ONLY network forbidden')), \
                patch('subprocess.Popen', side_effect=AssertionError('TEST_ONLY CLI forbidden')), \
                patch('laboratory.evidence_archive.pinned_fetch', side_effect=AssertionError('TEST_ONLY capture forbidden')):
            first = audit_saved_quality(run, data, review)
            second = audit_saved_quality(run, data, review)
            controls = run_control_corpus()
        self.assertEqual(first, second)
        self.assertEqual((run, data, review), original)
        self.assertEqual(controls['matched_case_count'], controls['case_count'])
        self.assertEqual(len({row['id'] for row in first['findings']}), len(first['findings']))
        for finding in first['findings']:
            self.assertIn(finding['status'], {'pass', 'needs_review', 'not_applicable'})
            self.assertTrue(finding['evidence_pointer'].startswith(('/run/', '/presentation/', '/review/')))

    def test_summary_counts_findings_and_records_without_quality_averages(self):
        cases = control_corpus()
        audits = [audit_saved_quality(case['run'], case['presentation']) for case in cases]
        summary = summarize_audits(audits)
        self.assertEqual(summary['version'], VERSION)
        self.assertEqual(summary['run_count'], 10)
        self.assertGreater(summary['status_counts']['needs_review'], 0)
        self.assertEqual(summary['finding_counts']['needs_review'], sum(a['counts']['needs_review'] for a in audits))
        self.assertFalse(summary['independent_verification'])
        self.assertNotIn('average', summary)

    def test_missing_lists_are_not_treated_as_success_and_raw_output_hash_preserves_newline(self):
        run, data = self.fixture()
        data['agent_review']['critic'] = {'version': 'critic-review-v1'}
        data['publication_checks'].pop('issues')
        audit = audit_saved_quality(run, data)
        self.assertEqual(self.finding(audit, 'critic.coverage')['status'], 'needs_review')
        self.assertEqual(self.finding(audit, 'format.publication')['status'], 'needs_review')
        run, data = self.fixture()
        run['output'] += '\n'
        data['agent_review']['final_output_sha256'] = hashlib.sha256(run['output'].encode('utf-8')).hexdigest()
        self.assertEqual(self.finding(audit_saved_quality(run, data), 'critic.saved_gate')['status'], 'pass')

    def test_omitted_presentation_uses_only_local_builder_and_handles_empty_input(self):
        run, data = self.fixture()
        with patch('laboratory.presentation.build_presentation', return_value=data) as builder:
            self.assertEqual(audit_saved_quality(run)['overall_status'], 'pass')
            builder.assert_called_once_with(run, None)
        result = audit_saved_quality({}, {})
        self.assertEqual(result['overall_status'], 'needs_review')
        self.assertGreater(result['counts']['needs_review'], 0)


if __name__ == '__main__':
    unittest.main()
