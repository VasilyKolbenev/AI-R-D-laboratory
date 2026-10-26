"""Native node geometry must contain the full labels in either visual style."""
import unittest

from laboratory import blackboard
from laboratory.motion_dashboard import _positions
from laboratory.reader_infographic import _wrap


class CompleteLabelHeightTests(unittest.TestCase):
    def test_layout_version_binds_a_new_preview_to_measured_geometry(self):
        import test_presentation_auto_v08 as fixture
        from laboratory.motion_dashboard import LAYOUT_VERSION
        from laboratory.presentation import build_presentation
        run = fixture.AutomaticPresentationTests().run_record()
        data = build_presentation(run)
        self.assertEqual(data['motion_story']['version'], 'dataflow-v1')
        self.assertEqual(data['visual']['layout_version'], LAYOUT_VERSION)

    def test_complete_dark_labels_fit_all_bounded_topology_layouts(self):
        labels = [
            'TEST_ONLY Выбирать кандидата по прошлым оценкам и бонусу разнообразия.',
            'TEST_ONLY Переносить и сочетать идеи объяснений из архива.',
            'TEST_ONLY Обновлять архив через локальные сравнения новизны и качества.',
            'TEST_ONLY Вернуть проверенный результат с границами применимости.']
        nodes = [{'id': 'n' + str(index), 'label': label}
                 for index, label in enumerate(labels)]
        edges = [{'from': 'n0', 'to': 'n1'}, {'from': 'n0', 'to': 'n2'},
                 {'from': 'n1', 'to': 'n3'}, {'from': 'n2', 'to': 'n3'}]
        for hand in (False, True):
            for kind in ('review', 'feedback', 'process', 'inference'):
                with self.subTest(hand=hand, kind=kind):
                    boxes, bottom = _positions(nodes, edges, kind, 100, hand)
                    for node in nodes:
                        x, y, width, height = boxes[node['id']]
                        font = blackboard.font if hand else None
                        lines = _wrap(node['label'], width - 36, 26, True, font)
                        self.assertGreaterEqual(height, len(lines) * 32 + 20)
                        self.assertLessEqual(y + height, bottom)


if __name__ == '__main__':
    unittest.main()
