"""Evidence emphasis adds no measurements and preserves approved package skins."""
from copy import deepcopy
import unittest

from laboratory.motion_dashboard import layout
from laboratory.visual_skin import rotation_skin
from test_compact_dashboard_v0121 import compact_sample, visible_text


class EvidenceVisualTests(unittest.TestCase):
    def test_disagreement_story_keeps_unknown_and_skin_for_both_packages(self):
        for position in (1, 2):
            data = compact_sample()
            data['visual_skin'] = rotation_skin(position)
            data['evidence_story'] = {
                'focus': 'disagreement', 'summary': 'TEST_ONLY conflicting conditions',
                'limitations': ['TEST_ONLY magnitude remains unknown'], 'source_refs': [],
            }
            before = deepcopy(data)
            visible = visible_text(data)
            self.assertIn('ГДЕ ИСТОЧНИКИ РАСХОДЯТСЯ', visible)
            self.assertIn('TEST_ONLY conflicting conditions', visible)
            self.assertIn('TEST_ONLY magnitude remains unknown', visible)
            self.assertEqual(before, data)
            self.assertLessEqual(layout(data)[0], 3000)

    def test_unknown_focus_leaves_legacy_layout_unchanged(self):
        data = compact_sample()
        before = layout(data)
        data['evidence_story'] = {'focus': 'unsupported', 'summary': 'PRIVATE_UNUSED'}
        self.assertEqual(layout(data), before)


if __name__ == '__main__':
    unittest.main()
