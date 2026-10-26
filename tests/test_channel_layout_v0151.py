"""Local channel layout preserves full mandatory paragraphs and source data."""
from copy import deepcopy
import unittest

from laboratory.channel_layout import fit
from laboratory.presentation import _story_post, utf16_len


def sample(findings):
    return {'title': 'TEST_ONLY title', 'numeric_note': 'Measurements are author claims.',
            'next_step': 'Check the original experiment.', 'report': 'UNCHANGED report',
            'sources': [{'url': 'https://example.org/primary'}], 'publication_sources': [],
            'provenance': {}, 'story': [
                {'id': 'problem', 'text': 'Problem and baseline conditions.'},
                {'id': 'audience', 'text': 'Audience.', 'items': ['Use case.']},
                {'id': 'mechanism', 'text': '', 'items': ['One.', 'Two.', 'Three.']},
                {'id': 'findings', 'text': 'Original attribution.', 'items': findings},
                {'id': 'limitations', 'text': '', 'items': ['Caveat remains whole.']},
                {'id': 'resources', 'text': '', 'items': ['Unknown full cost.']},
                {'id': 'takeaway', 'text': 'Practical conclusion under stated conditions.'}]}


def plain_render(data):
    data['post_compacted'] = False
    parts = [data['title'], data['numeric_note']]
    for section in data['story']:
        parts.extend([section['text'], *section.get('items', [])])
    parts.extend([data['next_step'], *(item['url'] for item in data['sources'])])
    return '\n'.join(parts)


class ChannelLayoutTests(unittest.TestCase):
    def test_compact_surface_keeps_required_prose_and_numeric_conditions_whole(self):
        def paragraph(label, size):
            return ('TEST_ONLY ' + label + ' ').ljust(size, 'x')

        first = paragraph('claimed 7 same conditions', 300)
        data = sample([first, paragraph('optional', 300), paragraph('optional', 300)])
        data['title'] = paragraph('technology', 80)
        data['next_step'] = paragraph('next step', 250)
        data['numeric_note'] = ('Нет сопоставимой пары подтверждённых чисел; '
                                'известные данные и пробелы показаны в таблице.')
        story = data['story']
        story[0]['text'] = paragraph('problem', 250)
        story[1].update(text=paragraph('audience', 200), items=[paragraph('baseline', 250)])
        story[2]['items'] = [paragraph('mechanism', 60)] * 3
        story[4]['items'] = [paragraph('caveat', 300)] * 3
        story[5]['items'] = [paragraph('resource', 300)] * 2
        story[6]['text'] = paragraph('conclusion', 300)
        original = deepcopy(data)
        self.assertIsNone(fit(data, _story_post, 3500))
        result = fit(data, lambda item: _story_post(item, compact=True), 3500)
        self.assertIsNotNone(result)
        self.assertLessEqual(utf16_len(result['text']), 3500)
        self.assertNotIn('…', result['text'])
        self.assertIn('У АВТОРОВ\n', result['text'])
        self.assertIn('Пара чисел не подтверждена.', result['text'])
        self.assertIn(first, result['text'])
        for section in data['story']:
            if section['id'] == 'findings':
                continue
            if section['text']:
                self.assertIn(section['text'], result['text'])
            for item in section.get('items', []):
                self.assertIn(item, result['text'])
        self.assertIn('https://example.org/primary', result['text'])
        self.assertEqual(data, original)
        data['story'][0]['text'] += 'Cannot drop this condition. ' * 20
        self.assertIsNone(fit(data, lambda item: _story_post(item, compact=True), 3500))

    def test_whole_optional_findings_removed_without_mutating_original(self):
        first, optional, numeric = 'First full result.', 'Optional detail. ' * 30, 'Value is 7.'
        data = sample([first, optional, numeric])
        original = deepcopy(data)
        minimum = deepcopy(data)
        minimum['story'][3]['items'] = [first, numeric]
        expected = plain_render(minimum)
        result = fit(data, plain_render, utf16_len(expected))
        self.assertIsNotNone(result)
        self.assertEqual(result['text'], expected)
        self.assertEqual(result['metadata']['selected_findings'], [0, 2])
        self.assertEqual(result['metadata']['omitted_findings'], [1])
        self.assertEqual(result['metadata']['mandatory_findings'], [0, 2])
        self.assertEqual(data, original)

    def test_greedy_addback_uses_original_order_and_whole_paragraphs(self):
        data = sample(['First.', 'A' * 30, 'B' * 30, 'C' * 5, 'Value 2 conditions.'])
        chosen = deepcopy(data)
        chosen['story'][3]['items'] = [data['story'][3]['items'][i] for i in [0, 1, 3, 4]]
        limit = utf16_len(plain_render(chosen))
        result = fit(data, plain_render, limit)
        self.assertEqual(result['metadata']['selected_findings'], [0, 1, 3, 4])
        self.assertEqual(result['metadata']['omitted_findings'], [2])
        self.assertEqual(result['text'], plain_render(chosen))

    def test_all_digit_findings_are_mandatory_including_unicode_digits(self):
        findings = ['First.', 'Optional.' * 30, 'Result ٤ conditions.', 'Value ² caveat.']
        data = sample(findings)
        minimum = deepcopy(data)
        minimum['story'][3]['items'] = [findings[i] for i in [0, 2, 3]]
        limit = utf16_len(plain_render(minimum))
        result = fit(data, plain_render, limit)
        self.assertEqual(result['metadata']['mandatory_findings'], [0, 2, 3])
        self.assertEqual(result['text'], plain_render(minimum))
        self.assertIsNone(fit(data, plain_render, limit - 1))

    def test_clipped_minimum_stays_blocked_even_when_returned_text_is_short(self):
        data = sample(['First.', 'Optional.' * 30])
        original = deepcopy(data)

        def clipped(projection):
            projection['post_compacted'] = True
            return 'short but clipped'

        self.assertIsNone(fit(data, clipped, 3500))
        self.assertEqual(data, original)

    def test_utf16_limit_counts_astral_characters_and_full_fit_keeps_everything(self):
        data = sample(['First 😀 paragraph.', 'Another full paragraph.'])
        complete = plain_render(deepcopy(data))
        result = fit(data, plain_render, utf16_len(complete))
        self.assertEqual(result['text'], complete)
        self.assertEqual(result['metadata']['omitted_findings'], [])
        self.assertEqual(result['metadata']['utf16_units'], utf16_len(complete))
        self.assertEqual(result['metadata']['limit'], utf16_len(complete))
        first = sample(['First 😀 paragraph.'])
        self.assertIsNone(fit(first, plain_render, len(plain_render(deepcopy(first)))))

    def test_existing_story_renderer_keeps_complete_sections_and_source_footer(self):
        data = sample(['First complete finding. ' * 8, 'Optional whole finding. ' * 100])
        for section in data['story']:
            if section['id'] == 'findings':
                continue
            section['text'] *= 5
            section['items'] = [item * 15 for item in section.get('items', [])]
        original = deepcopy(data)
        old = deepcopy(data)
        _story_post(old)
        self.assertTrue(old['post_compacted'])
        result = fit(data, _story_post, 3500)
        self.assertIsNotNone(result)
        self.assertLessEqual(utf16_len(result['text']), 3500)
        self.assertNotIn('…', result['text'])
        self.assertIn(data['story'][3]['items'][0], result['text'])
        for section in data['story']:
            if section['id'] != 'findings':
                if section['text']:
                    self.assertIn(section['text'], result['text'])
                for item in section.get('items', []):
                    self.assertIn(item, result['text'])
        self.assertTrue(result['text'].endswith('Источники\nhttps://example.org/primary'))
        self.assertEqual(data, original)


if __name__ == '__main__':
    unittest.main()
