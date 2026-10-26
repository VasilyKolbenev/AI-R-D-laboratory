import io
import json
import unittest

from laboratory.presentation import (build_presentation, display_report, render_gif,
                                    render_png, render_svg, utf16_len, PROMPT_INSTRUCTIONS)


class PresentationTests(unittest.TestCase):
    def run_record(self, output):
        return {'id': 'f' * 32, 'output': output, 'links': [], 'plan': {
            'sources': [{'id': 'a' * 32, 'title': 'Технология ИИ', 'url': 'https://example.org/paper'}],
            'memory': {'profile': {'interests': 'PRIVATE OWNER PREFERENCE'}}}}

    def valid_block(self, **changes):
        data = {'title': 'Быстрее с условиями', 'verdict': 'Сначала выбрать baseline.',
                'summary': 'Есть гипотеза, собственных замеров нет.',
                'applicability': ['Длинные ответы при заданной нагрузке.'],
                'pros': ['Может уменьшить задержку.'], 'cons': ['Нужна проверка.'],
                'metrics': ['TPOT: неизвестно.'], 'infrastructure': ['VRAM пока неизвестна.'],
                'setup': 'Не оценено.', 'next_step': 'Выбрать модель.',
                'mechanism': ['Предложение', 'Проверка', 'Продолжение']}
        data.update(changes)
        return '<lab_presentation>' + json.dumps(data, ensure_ascii=False) + '</lab_presentation>'

    def test_valid_structured_block_and_public_post(self):
        data = build_presentation(self.run_record('## Краткий вывод\nНеизвестно.\n' + self.valid_block()))
        self.assertEqual(data['provenance']['mode'], 'model_structured')
        self.assertEqual(data['visual']['steps'][0]['text'], 'Предложение')
        self.assertIn('Плюсы', data['post_text'])
        self.assertNotIn('PRIVATE OWNER', data['post_text'])
        self.assertLessEqual(utf16_len(data['post_text']), 3500)
        self.assertLessEqual(utf16_len(data['short_text']), 900)

    def test_invalid_block_is_labelled_extractive_fallback(self):
        for block in ('<lab_presentation>{invalid}</lab_presentation>',
                      self.valid_block(pros=['x'] * 4), self.valid_block(unknown='untrusted'),
                      self.valid_block(title='<script>alert(1)</script>'),
                      '<lab_presentation>' + 'x' * 21000 + '</lab_presentation>',
                      self.valid_block() + self.valid_block(),
                      '<lab_presentation>{"title":"a","title":"b"}</lab_presentation>'):
            with self.subTest(block=block[:50]):
                data = build_presentation(self.run_record('## Краткий вывод\nУскорение неизвестно.\n' + block))
                self.assertEqual(data['provenance']['mode'], 'legacy_extractive')
                self.assertFalse(data['provenance']['presentation_block_valid'])
                self.assertTrue(data['provenance']['warnings'])
                self.assertNotIn('lab_presentation', data['post_text'])

    def test_no_fake_numeric_ratings_or_private_ids(self):
        data = build_presentation(self.run_record('## Краткий вывод\nМатериал ' + 'f' * 32 + ': эффект неизвестен.'))
        self.assertNotIn('f' * 32, data['post_text'])
        self.assertNotIn('PRIVATE OWNER', data['post_text'])
        self.assertNotIn('2×', data['post_text'])
        self.assertIn('собственных замеров нет', data['post_text'])
        self.assertEqual(data['provenance']['mode'], 'legacy_extractive')

    def test_links_are_filtered_and_not_independently_verified(self):
        run = self.run_record('## Краткий вывод\nСм. https://arxiv.org/abs/1234.12345 .')
        run['links'] = ['http://127.0.0.1:8795/private', 'http://192.168.1.2/report',
                        'https://host.internal/report', 'https://name:pass@example.org',
                        'https://example.org/?api_key=SECRET', 'javascript:alert(1)',
                        'https://api.telegram.org/bot12345678:Abcdefghijklmnopqrstuvwxyz/getMe',
                        'https://docs.example.org/research']
        data = build_presentation(run)
        urls = [item['url'] for item in data['sources']]
        self.assertEqual(urls, ['https://arxiv.org/abs/1234.12345', 'https://docs.example.org/research', 'https://example.org/paper'])
        self.assertTrue(all(item['verification'] == 'link_in_report_not_independent_verification' for item in data['sources']))

    def test_machine_blocks_not_visible_in_report_or_draft(self):
        output = 'Report\n<lab_memory_review>{"comparisons":[]}</lab_memory_review>\n' + self.valid_block()
        self.assertEqual(display_report(output), 'Report')
        self.assertEqual(display_report('Report\n<lab_presentation>{broken'), 'Report')
        self.assertNotIn('comparisons', build_presentation(self.run_record(output))['post_text'])

    def test_utf16_bounds_include_surrogate_pair_emoji(self):
        data = build_presentation(self.run_record('## Краткий вывод\n' + '🧪' * 8000))
        self.assertLessEqual(utf16_len(data['post_text']), 3500)
        self.assertLessEqual(utf16_len(data['short_text']), 900)

    def test_svg_escapes_all_content_and_does_not_add_script(self):
        data = build_presentation(self.run_record('## Краткий вывод\nНичего не измерено.'))
        data['title'] = '<img src=x onerror=alert(1)>'
        data['verdict'] = '<script>secret</script>'
        svg = render_svg(data)
        self.assertNotIn('<script>', svg)
        self.assertNotIn('<img ', svg)
        self.assertIn('&lt;img', svg)
        self.assertNotIn('foreignObject', svg)
        self.assertIn('не является измерением', svg)

    def test_images_can_be_read_and_animation_has_three_frames(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest('Pillow optional')
        data = build_presentation(self.run_record('## Краткий вывод\nСначала проверить.'))
        with Image.open(io.BytesIO(render_png(data))) as image:
            self.assertEqual(image.size, (1200, 1240))
            self.assertEqual(image.format, 'PNG')
        with Image.open(io.BytesIO(render_gif(data))) as image:
            self.assertEqual(image.n_frames, 3)
            self.assertEqual(image.size, (720, 744))

    def test_specific_schematic_only_when_report_contains_mechanism(self):
        run = self.run_record('## Краткий вывод\nSpeculative decoding.\nМалая модель предлагает, target проверяет.')
        data = build_presentation(run)
        self.assertEqual(data['visual']['kind'], 'speculative_decoding')
        self.assertIn('не замер', data['visual']['caption'])
        self.assertEqual(build_presentation(self.run_record('Speculative decoding'))['visual']['kind'], 'research_path')

    def test_prompt_requests_one_existing_call_and_no_private_data(self):
        self.assertIn('без отдельного вызова', PROMPT_INSTRUCTIONS)
        self.assertIn('персональные данные', PROMPT_INSTRUCTIONS)


if __name__ == '__main__':
    unittest.main()
