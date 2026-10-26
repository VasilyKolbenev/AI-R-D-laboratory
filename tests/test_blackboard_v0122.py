"""The hand-drawn skin changes paint, preserving evidence and artifact motion."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import io
import re
import unittest
import xml.etree.ElementTree as ET

from laboratory import blackboard
from laboratory.motion_dashboard import frame, layout, packet_positions, render_png, render_svg
from laboratory.reader_infographic import _width
try:
    from . import test_motion_dashboard_v012 as fixtures
except ImportError:
    import test_motion_dashboard_v012 as fixtures


def as_board(data):
    board = deepcopy(data)
    board['visual_skin'] = {'version': 'skins-v1', 'id': 'blackboard'}
    return board


def normalized(value):
    return re.sub(r'\s+', '', value)


def visible(data, progress=1, animation=False):
    return ' '.join(part[3] for part in layout(data, progress, animation)[1] if part[0] == 'text')


class BlackboardRenderTests(unittest.TestCase):
    def test_visible_facts_numbers_units_caveats_and_sources_match_dashboard(self):
        data = fixtures.sample('feedback')
        data['comparisons'] = [{
            'label': 'TEST_ONLY покрытие замечаниями', 'unit': '%',
            'baseline_label': 'TEST_ONLY до', 'result_label': 'TEST_ONLY после',
            'baseline_value': 16, 'result_value': 54,
            'conditions': 'TEST_ONLY: авторская выборка; состав не раскрыт, собственных замеров нет.',
            'evidence': [{'limitations': 'TEST_ONLY: покрытие замечаниями не измеряет качество.',
                          'source_url': 'https://example.org/TEST_ONLY-numeric-evidence'}],
        }]
        board = as_board(data)
        self.assertEqual(normalized(visible(data)), normalized(visible(board)))
        for expected in ('16%', '54%', data['comparisons'][0]['label'],
                         data['comparisons'][0]['conditions'],
                         data['comparisons'][0]['evidence'][0]['limitations'],
                         data['comparisons'][0]['evidence'][0]['source_url'],
                         data['motion_story']['sources'][0]['url']):
            self.assertIn(normalized(expected), normalized(visible(board)))
        ns = '{http://www.w3.org/2000/svg}'
        for tag in ('title', 'desc'):
            a = ET.fromstring(render_svg(data)).find(ns + tag)
            b = ET.fromstring(render_svg(board)).find(ns + tag)
            self.assertEqual(''.join(a.itertext()), ''.join(b.itertext()))

    def test_handwriting_wraps_whole_labels_with_bounded_lines_and_deterministic_exports(self):
        from PIL import Image
        data = fixtures.sample('feedback')
        label = 'TEST_ONLY: проверка источников и границ применимости технологии'
        data['motion_story']['nodes'][1]['label'] = label
        board = as_board(data); before = deepcopy(board)
        height, parts = layout(board)
        self.assertIn(normalized(label), normalized(visible(board)))
        for _, x, y, text, size, color, bold in (p for p in parts if p[0] == 'text'):
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x + _width(text, size, bold, blackboard.font), 1080.1, text)
            self.assertLessEqual(y + size, height, text)
        png = render_png(board)
        self.assertEqual(png, render_png(board))
        self.assertNotEqual(png, render_png(data))
        with Image.open(io.BytesIO(png)) as image:
            self.assertEqual(image.size, (1080, height))
            self.assertEqual(image.mode, 'RGB')
            self.assertEqual(image.getpixel((0, 0)), (0, 0, 0))
        svg = render_svg(board)
        self.assertEqual(svg, render_svg(board))
        self.assertNotEqual(svg, render_svg(data))
        self.assertIn('Segoe Print', svg)
        self.assertEqual(board, before)

    def test_packet_rate_and_frame_typography_stay_stable_for_both_skins(self):
        from PIL import ImageChops
        plain = fixtures.sample('feedback')
        identities = None
        for data in (plain, as_board(plain)):
            before = deepcopy(data)
            early, late = packet_positions(data, .01), packet_positions(data, .02)
            current = {p[0] for p in early}
            if identities is None:
                identities = current
            self.assertEqual(current, identities)
            self.assertEqual(current, {p[0] for p in late})
            a = next(p for p in early if p[0] == 'ab')
            b = next(p for p in late if p[0] == 'ab')
            self.assertAlmostEqual(b[1] - a[1], 11)
            self.assertAlmostEqual(b[2] - a[2], 0)
            height, first = layout(data, .01, animation=True)
            _, last = layout(data, .02, animation=True)
            self.assertEqual([p for p in first if p[0] == 'text'],
                             [p for p in last if p[0] == 'text'])
            initial, later = frame(data, .01), frame(data, .02)
            self.assertEqual(initial.size, (1080, height))
            self.assertEqual(initial.size, later.size)
            self.assertIsNotNone(ImageChops.difference(initial, later).getbbox())
            self.assertEqual(data, before)

    def test_concurrent_skins_do_not_leak_paint_or_change_default_rendering(self):
        plain = fixtures.sample('process'); board = as_board(plain)
        originals = deepcopy((plain, board))

        def render(data):
            return render_png(data), render_svg(data)

        expected = [render(plain), render(board)]
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(render, (plain, board, board, plain)))
        self.assertEqual(results, [expected[0], expected[1], expected[1], expected[0]])
        self.assertEqual((plain, board), originals)
        for metadata in ({'version': 'old', 'id': 'blackboard'},
                         {'version': 'skins-v1', 'id': 'unknown'},
                         {'version': 'skins-v1', 'id': 'dashboard'}):
            invalid = deepcopy(plain); invalid['visual_skin'] = metadata
            self.assertEqual(render(invalid), expected[0])


if __name__ == '__main__':
    unittest.main()
