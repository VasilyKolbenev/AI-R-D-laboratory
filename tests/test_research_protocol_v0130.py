import copy
import json
import unittest

from laboratory.research_protocol import (build_protocol, comparison_context,
                                          phase_prompt, validate_protocol)


class ResearchProtocolTests(unittest.TestCase):
    def plan(self):
        plan = {'question': 'Compare latency', 'timeout_seconds': 240, 'web_search': True,
                'sources': [{'id': 'a' * 32, 'title': 'Paper', 'url': 'https://example.org/paper',
                             'text': 'SOURCE_START ' + 'x' * 1700 + ' SOURCE_TAIL', 'content_hash': 'b' * 64}],
                'study_context': {'task': {'metrics': [{'name': 'Latency', 'definition': 'Per request',
                    'unit': 'ms', 'direction': 'minimize', 'primary': True, 'target': '5',
                    'expected': 'Unverified', 'evidence_level': 'unknown', 'evidence_url': ''}]}},
                'memory': {'enabled': True, 'profile': {'interests': 'PRIVATE_PROFILE'}, 'items': [
                    {'id': 'c' * 32, 'version': 2, 'title': 'Old study', 'claim': 'PAST_CLAIM',
                     'effective_status': 'stale', 'study_scope': {'dataset': 'Different'}}]}}
        plan['comparison_context'] = comparison_context(plan)
        plan['research_protocol'] = build_protocol(plan)
        return plan

    def test_explicit_three_calls_and_budget_envelope(self):
        for total in (200, 220, 240):
            protocol = build_protocol({'timeout_seconds': total})
            validate_protocol(protocol)
            self.assertEqual(protocol['roles'], ['researcher', 'critic', 'reviewer'])
            self.assertEqual(protocol['max_calls'], 3)
            self.assertEqual(sum(protocol['phase_timeouts']) + protocol['cleanup_reserve_seconds'], total)
            self.assertTrue(all(value >= 60 for value in protocol['phase_timeouts']))
        self.assertEqual(build_protocol({'timeout_seconds': 240})['phase_timeouts'], [100, 60, 60])
        for invalid in (199, 241, True, '240', None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                build_protocol({'timeout_seconds': invalid})

    def test_recipe_fields_cannot_silently_change(self):
        protocol = self.plan()['research_protocol']
        for key, value in [('max_calls', 4), ('auto_retry', True), ('phase_timeouts', [120, 60, 60]),
                           ('web_search_roles', ['researcher']), ('unknown', True)]:
            changed = copy.deepcopy(protocol); changed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_protocol(changed)

    def test_historical_frozen_templates_are_used_exactly(self):
        plan = self.plan()
        plan['research_protocol']['templates'][1] = 'EXACT_APPROVED_HISTORICAL_CRITIC'
        validate_protocol(plan['research_protocol'])
        self.assertTrue(phase_prompt(plan, 1, ['DRAFT']).startswith('EXACT_APPROVED_HISTORICAL_CRITIC'))

    def test_selected_analogues_are_exact_and_preferences_are_not_evidence(self):
        context = self.plan()['comparison_context']
        row = context['analogues'][0]
        self.assertEqual((row['memory_id'], row['memory_version'], row['claim']), ('c' * 32, 2, 'PAST_CLAIM'))
        self.assertEqual(row['study_scope'], {'dataset': 'Different'})
        self.assertEqual(row['trust'], 'previous_claim_not_new_external_evidence')
        self.assertNotIn('PRIVATE_PROFILE', json.dumps(context))
        self.assertEqual(context['metric_checklist'][0]['direction'], 'minimize')

    def test_originals_once_then_bounded_excerpts_then_headers(self):
        plan = self.plan(); frozen = copy.deepcopy(plan)
        first = phase_prompt(plan, 0, [])
        critic = phase_prompt(plan, 1, ['RESEARCHER_PACKET'])
        reviewer = phase_prompt(plan, 2, ['RESEARCHER_PACKET', 'CRITIC_PACKET'])
        self.assertIn('SOURCE_TAIL', first)
        self.assertIn('SOURCE_START', critic)
        self.assertNotIn('SOURCE_TAIL', critic)
        self.assertIn('excerpt_clipped', critic)
        self.assertNotIn('SOURCE_START', reviewer)
        self.assertIn('RESEARCHER_PACKET', reviewer)
        self.assertIn('CRITIC_PACKET', reviewer)
        self.assertIn('"web_search":true', critic)
        self.assertIn('"web_search":false', reviewer)
        self.assertEqual(plan, frozen)

    def test_disabled_web_applies_to_both_research_and_critic(self):
        plan = self.plan(); plan['web_search'] = False
        for index, previous in [(0, []), (1, ['DRAFT'])]:
            prompt = phase_prompt(plan, index, previous)
            self.assertIn('"web_search":false', prompt)
            self.assertIn('Веб-поиск отключён', prompt)

    def test_invalid_upstream_or_context_stops_assembly(self):
        plan = self.plan()
        for index, outputs in [(0, ['x']), (1, []), (2, ['x']), (1, ['x' * 32001])]:
            with self.subTest(index=index), self.assertRaises(ValueError):
                phase_prompt(plan, index, outputs)
        plan['comparison_context']['analogues'][0]['memory_version'] = 3
        with self.assertRaises(ValueError):
            phase_prompt(plan, 0, [])


if __name__ == '__main__':
    unittest.main()
