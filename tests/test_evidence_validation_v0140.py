import copy
import unittest


class EvidenceValidationTests(unittest.TestCase):
    def fixture(self):
        document = {'asset_id': 'd' * 64, 'document_id': 'd' * 64,
                    'source_id': 'a' * 32, 'url': 'https://example.org/paper',
                    'kind': 'fetched_html', 'status': 'captured', 'sha256': 'e' * 64,
                    'segments': [{'id': 's1', 'locator': 'html:table:1:row:2',
                                  'text': 'Baseline 12 ms; candidate 8 ms.'}],
                    'limitations': []}
        plan = {'research_protocol': {'version': 'three-pass-v2'},
                'evidence_bundle': {'version': 'source-bundle-v1',
                                    'documents': [document], 'limitations': []}}
        evidence = [{'id': 'e1', 'source_url': document['url']}]
        parsed = {'evidence_checks': [{'evidence_id': 'e1', 'document_id': 'd' * 64,
                   'segment_id': 's1', 'quote': document['segments'][0]['text'],
                   'relation': 'supports', 'reason': 'Literal reported numbers'}],
                  'applied_analysis': {'rows': [
                      {'baseline': {'value': 12, 'evidence_ids': ['e1']},
                       'candidate': {'value': 8, 'evidence_ids': ['e1']}}]}}
        return plan, parsed, evidence

    def test_exact_source_quote_is_bound_but_not_semantically_certified(self):
        from laboratory.evidence_validation import validate_checks
        plan, parsed, evidence = self.fixture()
        result = validate_checks(plan, parsed, 'report', evidence)
        self.assertEqual(result['status'], 'ready', result)
        self.assertTrue(result['checks'][0]['literal_quote'])
        self.assertIn('семантичес', result['notice'].lower())
        invalid = copy.deepcopy(parsed)
        invalid['evidence_checks'][0]['quote'] = 'Candidate 99 ms.'
        self.assertEqual(validate_checks(plan, invalid, 'report', evidence)['status'], 'incomplete')

    def test_counter_or_insufficient_quote_cannot_authorize_known_numeric_side(self):
        from laboratory.evidence_validation import validate_checks
        for relation in ('contradicts', 'insufficient'):
            plan, parsed, evidence = self.fixture()
            parsed['evidence_checks'][0]['relation'] = relation
            result = validate_checks(plan, parsed, 'report', evidence)
            self.assertEqual(result['status'], 'incomplete', relation)

    def test_all_material_evidence_needs_binding_but_explicit_unknown_is_legitimate(self):
        from laboratory.evidence_validation import validate_checks
        plan, parsed, evidence = self.fixture()
        parsed['applied_analysis']['rows'] = []
        parsed['evidence_checks'] = []
        self.assertEqual(validate_checks(plan, parsed, 'report', evidence)['status'], 'incomplete')
        self.assertEqual(validate_checks(plan, parsed, 'unknown', [])['status'], 'ready')

    def test_wrong_url_segment_and_number_swapping_fail_at_public_seam(self):
        from laboratory.evidence_validation import validate_checks
        for change in ('url', 'segment', 'number'):
            plan, parsed, evidence = self.fixture()
            if change == 'url':
                evidence[0]['source_url'] = 'https://example.org/different'
            elif change == 'segment':
                parsed['evidence_checks'][0]['segment_id'] = 's2'
            else:
                parsed['applied_analysis']['rows'][0]['candidate']['value'] = 99
            self.assertEqual(validate_checks(plan, parsed, 'report', evidence)['status'],
                             'incomplete', change)

    def test_legacy_is_not_retroactively_certified_and_assessment_validates_locally(self):
        from laboratory.evidence_validation import (assessment_payload, validate_asset,
                                                     validate_checks)
        plan, parsed, evidence = self.fixture()
        result = validate_checks(plan, parsed, 'report', evidence)
        payload = assessment_payload({'id': 'f' * 32, 'plan': plan, 'output': 'report'}, result)
        validate_asset('evidence_assessment', payload)
        payload['checks'][0]['assessment_origin'] = 'scientific_truth'
        with self.assertRaises(ValueError):
            validate_asset('evidence_assessment', payload)
        plan['research_protocol']['version'] = 'three-pass-v1'
        self.assertEqual(validate_checks(plan, parsed, 'report', evidence)['status'], 'legacy')


if __name__ == '__main__':
    unittest.main()
