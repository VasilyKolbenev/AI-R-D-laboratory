"""Paint selection preserves the compact research facts and approval binding."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from laboratory.presentation import build_presentation
from laboratory.publication import Publisher
from laboratory.visual_skin import select_visual_skin
try:
    from . import test_presentation_auto_v08 as fixtures
except ImportError:
    import test_presentation_auto_v08 as fixtures


def sample(kind='process'):
    return {'title': 'TEST_ONLY нейтральная технология', 'post_text': 'TEST_ONLY готовый пост',
            'comparisons': [],
            'motion_story': {'version': 'dataflow-v1', 'kind': kind,
                             'nodes': [{'id': 'a', 'label': 'TEST_ONLY вход'}], 'edges': []}}


def comparison():
    return {'label': 'TEST_ONLY задержка', 'unit': 'мс', 'baseline_label': 'До',
            'result_label': 'После', 'baseline_value': 10, 'result_value': 8,
            'conditions': 'TEST_ONLY одна нагрузка, авторские данные.',
            'evidence_ids': ['TEST_ONLY-e1'],
            'evidence': [{'id': 'TEST_ONLY-e1', 'source_url': 'https://example.org/TEST_ONLY-paper'}]}


class VisualSkinTests(unittest.TestCase):
    def test_content_selects_both_skins_with_safe_legacy_default(self):
        for kind in ('feedback', 'process', 'review'):
            with self.subTest(kind=kind):
                self.assertEqual(select_visual_skin(sample(kind))['id'], 'blackboard')
        self.assertEqual(select_visual_skin(sample('inference'))['id'], 'dashboard')
        for value in ({}, None, {'motion_story': []},
                      {'motion_story': {'version': 'unknown', 'kind': 'feedback'}}, sample('unknown')):
            with self.subTest(value=value):
                self.assertEqual(select_visual_skin(value)['id'], 'dashboard')

    def test_supported_numbers_precede_kind_but_unbound_numbers_do_not(self):
        for kind in ('feedback', 'process', 'review', 'inference'):
            data = sample(kind); data['comparisons'] = [comparison()]
            self.assertEqual(select_visual_skin(data)['id'], 'dashboard')
        data = sample('feedback'); data['comparisons'] = [comparison()]
        data['comparisons'][0]['evidence_ids'] = ['TEST_ONLY-orphan']
        self.assertEqual(select_visual_skin(data)['id'], 'blackboard')
        data['comparisons'][0]['evidence_ids'] = ['TEST_ONLY-e1']
        data['comparisons'][0]['result_value'] = float('nan')
        self.assertEqual(select_visual_skin(data)['id'], 'blackboard')

    def test_selection_is_repeatable_brand_independent_and_does_not_mutate_facts(self):
        data = sample('feedback'); before = deepcopy(data)
        skin = select_visual_skin(data)
        self.assertEqual(skin, select_visual_skin(data))
        self.assertEqual(set(skin), {'version', 'id', 'label', 'reason'})
        self.assertEqual(skin['version'], 'skins-v1')
        self.assertTrue(skin['label'] and skin['reason'])
        self.assertEqual(data, before)
        data['title'] = 'TEST_ONLY произвольное другое имя'
        self.assertEqual(skin, select_visual_skin(data))
        skin['id'] = 'TEST_ONLY mutation'
        self.assertEqual(select_visual_skin(data)['id'], 'blackboard')

    def test_builder_preserves_post_and_skin_is_bound_to_existing_content_signature(self):
        fixture = fixtures.AutomaticPresentationTests()
        run = fixture.run_record()
        run.update(status='completed', plan_hash='TEST_ONLY-plan')
        original = deepcopy(run)
        data = build_presentation(run)
        self.assertEqual(run, original)
        self.assertEqual(data['motion_story']['version'], 'dataflow-v1')
        self.assertEqual(data['visual_skin'], select_visual_skin(data))
        alternate = {**data['visual_skin'], 'id': 'blackboard', 'reason': 'TEST_ONLY другой стиль'}
        with patch('laboratory.visual_skin.select_visual_skin', return_value=alternate):
            changed = build_presentation(run)
        for key in ('post_text', 'short_text', 'story', 'comparisons', 'motion_story', 'publication_checks'):
            self.assertEqual(data[key], changed[key], key)
        # Exercise the existing signature boundary without constructing a
        # publisher or opening a store, rendering media, or sending anything.
        publisher = Publisher.__new__(Publisher)
        publisher.store = SimpleNamespace(run=lambda _: run,
                                          review=SimpleNamespace(get=lambda _: {'current': None}))
        publisher.presentation_builder = lambda _: data
        _, before = publisher._content(run['id'])
        publisher.presentation_builder = lambda _: changed
        _, after = publisher._content(run['id'])
        self.assertNotEqual(before, after)


if __name__ == '__main__':
    unittest.main()
