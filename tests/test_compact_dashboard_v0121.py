"""Compact reader surfaces keep evidence visible and full context accessible."""
from copy import deepcopy
import re
import unittest
import xml.etree.ElementTree as ET

from laboratory.motion_dashboard import (
    MOTION_NOTICE, SURFACE, layout, packet_positions, render_svg,
)


SVG = '{http://www.w3.org/2000/svg}'
PRIMARY = 'https://example.org/TEST_ONLY-primary'
SECONDARY = 'https://example.org/TEST_ONLY-secondary'
METRIC_A = 'https://example.org/TEST_ONLY-metric-a'
METRIC_B = 'https://example.org/TEST_ONLY-metric-b'


def compact_sample(kind='process', status='unknown'):
    """A saved presentation, with deliberately verbose editorial repetition."""
    nodes = [
        {'id': key, 'label': label, 'role': role, 'lane': 'technology', 'evidence_ids': []}
        for key, label, role in (
            ('a', 'TEST_ONLY вход', 'input'),
            ('b', 'TEST_ONLY обработка', 'compute'),
            ('c', 'TEST_ONLY результат', 'output'),
        )
    ]
    edges = [
        {'id': 'ab', 'from': 'a', 'to': 'b', 'label': 'TEST_ONLY длинная подпись документа', 'kind': 'data', 'evidence_ids': []},
        {'id': 'bc', 'from': 'b', 'to': 'c', 'label': 'TEST_ONLY длинная подпись результата', 'kind': 'control', 'evidence_ids': []},
    ]
    if kind == 'feedback':
        nodes[-1]['role'] = 'memory'
        edges.append({'id': 'ca', 'from': 'c', 'to': 'a', 'label': 'TEST_ONLY следующий цикл', 'kind': 'feedback', 'evidence_ids': []})
    if status == 'conceptual':
        nodes += [
            {'id': key, 'label': label, 'role': role, 'lane': 'baseline', 'evidence_ids': []}
            for key, label, role in (
                ('old_a', 'TEST_ONLY ручной вход', 'input'),
                ('old_b', 'TEST_ONLY ручная проверка', 'decision'),
            )
        ]
        edges.append({'id': 'old_ab', 'from': 'old_a', 'to': 'old_b', 'label': 'TEST_ONLY ручной путь', 'kind': 'data', 'evidence_ids': []})
    return {
        'title': 'TEST_ONLY механизм без вымышленных измерений',
        'problem': 'TEST_ONLY повтор проблемы: подробный абзац уже объяснён в сохранённом разборе.',
        'comparisons': [],
        'motion_story': {
            'version': 'dataflow-v1', 'kind': kind, 'nodes': nodes, 'edges': edges,
            'baseline': {
                'status': status,
                'label': 'TEST_ONLY baseline неизвестен' if status == 'unknown' else 'TEST_ONLY исходный процесс',
                'note': 'TEST_ONLY полное объяснение baseline: сопоставимого измеренного процесса нет; это не нулевой результат.',
            },
            'notes': [
                'TEST_ONLY длинная редакционная заметка: детали механизма и объяснение ограничений уже сохранены в полном разборе.',
            ],
            'sources': [{'url': PRIMARY}, {'url': SECONDARY}, {'url': PRIMARY}],
        },
    }


def metric_sample():
    data = compact_sample()
    data['comparisons'] = [
        {
            'label': 'TEST_ONLY покрытие замечаниями', 'unit': '%',
            'baseline_label': 'TEST_ONLY до', 'result_label': 'TEST_ONLY после',
            'baseline_value': 16, 'result_value': 54,
            'conditions': 'TEST_ONLY условия покрытия: авторская выборка, одинаковые задачи; собственных замеров нет.',
            'evidence': [
                {'limitations': 'TEST_ONLY оговорка покрытия: доля замечаний не измеряет качество.', 'source_url': METRIC_A},
                {'limitations': 'TEST_ONLY оговорка покрытия: перенос на другой репозиторий неизвестен.', 'source_url': METRIC_B},
            ],
        },
        {
            'label': 'TEST_ONLY пропускная способность', 'unit': 'tokens/s',
            'baseline_label': 'TEST_ONLY режим один', 'result_label': 'TEST_ONLY режим два',
            'baseline_value': 81, 'result_value': 102,
            'conditions': 'TEST_ONLY условия потока: decode, одна фиксированная конфигурация оборудования.',
            'evidence': [
                {'limitations': 'TEST_ONLY оговорка потока: стоимость и минимум запуска не установлены.', 'source_url': METRIC_A},
            ],
        },
    ]
    return data


def visible_text(data, progress=1, animation=False):
    """Inspect the same text primitives consumed by the native PNG renderer."""
    return ' '.join(part[3] for part in layout(data, progress, animation)[1] if part[0] == 'text')


def squish(value):
    # Wrapping may break a URL or prose at any character without losing content.
    return re.sub(r'\s+', '', value)


class CompactDashboardTests(unittest.TestCase):
    def assertVisible(self, expected, actual):
        self.assertIn(squish(expected), squish(actual))

    def assertNotVisible(self, expected, actual):
        self.assertNotIn(squish(expected), squish(actual))

    def test_visible_hierarchy_omits_repeated_prose_and_full_edge_key(self):
        data = compact_sample()
        visible = visible_text(data)
        self.assertNotVisible(data['problem'], visible)
        self.assertNotVisible(data['motion_story']['notes'][0], visible)
        self.assertNotVisible(data['motion_story']['baseline']['note'], visible)
        for edge in data['motion_story']['edges']:
            self.assertNotVisible(edge['label'], visible)
        for node in data['motion_story']['nodes']:
            self.assertVisible(node['label'], visible)
        self.assertVisible(MOTION_NOTICE, visible)

    def test_all_metric_values_units_conditions_caveats_and_sources_remain_visible(self):
        data = metric_sample()
        visible = visible_text(data)
        for expected in ('16%', '54%', '81 tokens/s', '102 tokens/s'):
            self.assertVisible(expected, visible)
        for item in data['comparisons']:
            for key in ('label', 'baseline_label', 'result_label', 'conditions'):
                self.assertVisible(item[key], visible)
            for evidence in item['evidence']:
                self.assertVisible(evidence['limitations'], visible)
                self.assertVisible(evidence['source_url'], visible)
        for url in (PRIMARY, METRIC_A, METRIC_B):
            self.assertEqual(squish(visible).count(url), 1, url)
        self.assertNotVisible(SECONDARY, visible)

    def test_baseline_status_stays_qualified_without_invented_zero_or_nodes(self):
        unknown = compact_sample()
        before = deepcopy(unknown)
        visible = visible_text(unknown)
        self.assertVisible(unknown['motion_story']['baseline']['label'], visible)
        self.assertIn('неизвест', visible.casefold())
        self.assertNotRegex(visible, r'(?<!\d)0\s*(?:%|tokens/s|мс)')
        self.assertEqual(unknown, before)
        self.assertEqual({p[0] for p in packet_positions(unknown, .01)}, {'ab', 'bc'})
        self.assertNotIn('ручной', visible.casefold())
        # Every graph box corresponds to a supplied node, including disconnected
        # ones; no unknown baseline is represented by a fabricated lane.
        boxes = [p for p in layout(unknown)[1] if p[0] == 'rect' and p[5] == SURFACE]
        self.assertEqual(len(boxes), len(unknown['motion_story']['nodes']))
        conceptual = compact_sample(status='conceptual')
        visible = visible_text(conceptual)
        baseline_region = visible.split('С ТЕХНОЛОГИЕЙ')[0]
        self.assertRegex(baseline_region.casefold(), r'концептуальн|условн|схематич')
        for node in conceptual['motion_story']['nodes']:
            self.assertVisible(node['label'], visible)
        self.assertNotVisible(conceptual['motion_story']['baseline']['note'], visible)

    def test_feedback_weights_human_approval_and_unknown_topology_keep_short_scope(self):
        feedback = compact_sample('feedback')
        feedback['motion_story']['notes'].append('TEST_ONLY Веса модели фиксированы; сохранённый опыт переносится на следующие задачи.')
        visible = visible_text(feedback)
        self.assertVisible('TEST_ONLY следующий цикл', visible)
        self.assertVisible('ВЕСА МОДЕЛИ ФИКСИРОВАНЫ', visible)
        self.assertNotVisible(feedback['motion_story']['notes'][-1], visible)
        review = compact_sample('review')
        review['motion_story']['notes'].append('TEST_ONLY Сервис не одобряет PR; окончательное одобрение остаётся у человека и требует его решения.')
        visible = visible_text(review).casefold()
        self.assertRegex(visible, r'человек|ручн')
        self.assertRegex(visible, r'одобр|решени')
        self.assertNotVisible(review['motion_story']['notes'][-1].casefold(), visible)
        inference = compact_sample('inference')
        inference['motion_story']['notes'].append('TEST_ONLY Внимание и эксперты распределяются параллельно; подготовка пакетов совмещена с вычислениями, точная топология не установлена.')
        visible = visible_text(inference).casefold()
        self.assertIn('тополог', visible)
        self.assertRegex(visible, r'не установлен|неизвест|не определ')
        self.assertNotVisible(inference['motion_story']['notes'][-1].casefold(), visible)

    def test_animation_still_moves_packets_at_same_rate_without_input_mutation(self):
        data = compact_sample('feedback')
        before = deepcopy(data)
        early, later = packet_positions(data, .01), packet_positions(data, .02)
        self.assertNotEqual(early, later)
        self.assertEqual({p[0] for p in early}, {'ab', 'bc', 'ca'})
        a = next(p for p in early if p[0] == 'ab')
        b = next(p for p in later if p[0] == 'ab')
        self.assertAlmostEqual(b[1] - a[1], 11)
        self.assertAlmostEqual(b[2] - a[2], 0)
        self.assertEqual(visible_text(data, .01, True), visible_text(data, .02, True))
        render_svg(data)
        self.assertEqual(data, before)

    def test_svg_accessibility_keeps_original_context_out_of_visible_text(self):
        data = compact_sample()
        root = ET.fromstring(render_svg(data))
        self.assertEqual(root.attrib.get('role'), 'img')
        self.assertTrue(root.find(SVG + 'title').text)
        desc = ''.join(root.find(SVG + 'desc').itertext())
        svg_visible = ' '.join(''.join(node.itertext()) for node in root.iter(SVG + 'text'))
        for original in (data['problem'], data['motion_story']['baseline']['note'],
                         *data['motion_story']['notes'], SECONDARY,
                         *(edge['label'] for edge in data['motion_story']['edges'])):
            self.assertVisible(original, desc)
            self.assertNotVisible(original, svg_visible)
        self.assertVisible(PRIMARY, svg_visible)


if __name__ == '__main__':
    unittest.main()
