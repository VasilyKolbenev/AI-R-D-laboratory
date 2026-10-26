"""Public protocol seams only; no CLI, model, network or saved-run mutation."""
from copy import deepcopy
import unittest

from laboratory.research_protocol import build_protocol, comparison_context
from laboratory.research_protocol import phase_prompt, validate_protocol


def plan(total=360, grounded=True):
    source = {'id': 'a' * 32, 'title': 'TEST_ONLY source', 'content_hash': 'b' * 64,
              'url': 'https://example.org/paper', 'text': 'Baseline 12 ms; candidate 8 ms.'}
    value = {'question': 'TEST_ONLY compare source evidence', 'timeout_seconds': total,
             'web_search': True, 'sources': [source], 'memory': {'enabled': False},
             'study_context': None}
    if grounded:
        value['evidence_bundle'] = {
            'version': 'source-bundle-v1', 'limitations': [], 'documents': [{
                'asset_id': 'd' * 64, 'document_id': 'd' * 64,
                'source_id': source['id'], 'url': source['url'],
                'kind': 'fetched_html', 'status': 'captured', 'sha256': 'e' * 64,
                'segments': [{'id': 's1', 'locator': 'html:table:1',
                              'text': source['text']}], 'limitations': []}]}
    value['comparison_context'] = comparison_context(value)
    return value


class WebBudgetTests(unittest.TestCase):
    def test_public_build_360_freezes_v3_literal_schedule_and_validates(self):
        try:
            protocol = build_protocol(plan())
        except ValueError as exc:
            self.fail('The public grounded builder must accept 360 seconds: ' + str(exc))
        self.assertEqual(protocol['version'], 'three-pass-v3')
        self.assertEqual(protocol['phase_timeouts'], [130, 100, 110])
        self.assertEqual(protocol['cleanup_reserve_seconds'], 20)
        self.assertEqual(protocol['max_calls'], 3)
        self.assertIsNone(validate_protocol(protocol))

    def test_historical_v1_v2_and_all_non_time_parameters_are_unchanged(self):
        legacy = build_protocol(plan(240, grounded=False))
        old = build_protocol(plan(240))
        new = build_protocol(plan(360))
        self.assertEqual(legacy['version'], 'three-pass-v1')
        self.assertEqual(old['version'], 'three-pass-v2')
        self.assertEqual(legacy['phase_timeouts'], [100, 60, 60])
        self.assertEqual(old['phase_timeouts'], [100, 60, 60])
        ignored = {'version', 'phase_timeouts', 'total_timeout_seconds'}
        self.assertEqual({key: value for key, value in old.items() if key not in ignored},
                         {key: value for key, value in new.items() if key not in ignored})
        self.assertIsNone(validate_protocol(legacy))
        self.assertIsNone(validate_protocol(old))

    def test_each_integer_v3_budget_preserves_full_envelope(self):
        for total in range(241, 361):
            with self.subTest(total=total):
                protocol = build_protocol(plan(total))
                extra = total - 240
                expected = [100 + extra // 4, 60 + extra // 3,
                            60 + extra - extra // 4 - extra // 3]
                self.assertEqual(protocol['phase_timeouts'], expected)
                self.assertEqual(sum(expected) + 20, total)
                validate_protocol(protocol)

    def test_invalid_versions_boundaries_and_changed_web_recipe_are_rejected(self):
        for total in (199, 361, True, 240.5):
            with self.subTest(total=total), self.assertRaises(ValueError):
                build_protocol(plan(total))
        with self.assertRaises(ValueError):
            build_protocol(plan(360, grounded=False))
        for version, total in [('three-pass-v2', 360), ('three-pass-v3', 240)]:
            protocol = build_protocol(plan(total))
            protocol['version'] = version
            with self.assertRaises(ValueError):
                validate_protocol(protocol)
        for key, value in [('max_calls', 4), ('auto_retry', True),
                           ('phase_timeouts', [130, 110, 110]),
                           ('web_search_roles', ['researcher'])]:
            protocol = build_protocol(plan())
            protocol[key] = value
            with self.assertRaises(ValueError):
                validate_protocol(protocol)

    def test_v3_dispatch_keeps_blind_critic_web_and_source_rules(self):
        value = plan()
        value['research_protocol'] = build_protocol(value)
        marker = 'TEST_ONLY_PRIVATE_RESEARCHER_MARKER'
        critic = phase_prompt(value, 1, [marker])
        reviewer = phase_prompt(value, 2, [marker, 'TEST_ONLY critic'])
        self.assertNotIn(marker, critic)
        self.assertIn(marker, reviewer)
        self.assertIn('Baseline 12 ms; candidate 8 ms.', critic)
        self.assertIn('"web_search":true', critic)
        self.assertIn('"web_search":false', reviewer)
        self.assertIn('evidence_checks', reviewer)


if __name__ == '__main__':
    unittest.main()
