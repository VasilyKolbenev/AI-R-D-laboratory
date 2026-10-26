"""TEST_ONLY: extractive adaptive layouts and native, honest local animation."""
from copy import deepcopy
import io
import math
from pathlib import Path
import subprocess
import tempfile
import unittest

from laboratory import adaptive_visual, media_encoder
from laboratory.reader_infographic import layout, render_infographic_png, render_infographic_svg, _width


def sample(mode):
    commit = '1cfe254e8d25b15f37048c3730134686abe60335'
    url = 'https://github.com/example/project/blob/' + commit + '/README.md'
    steps = ['TEST_ONLY: прочитать документ и сохранить ограничения задачи.',
             'TEST_ONLY: проверить основания по доступным источникам и записать противоречия.',
             'TEST_ONLY: передать результат человеку вместе с границами применения.']
    resources = ['TEST_ONLY: нужен доступ к исходным документам и источникам.',
                 'TEST_ONLY: требуется хранилище оснований; полная стоимость неизвестна.']
    limit = 'TEST_ONLY: качество вывода вне описанного набора документов не проверено.'
    return {'title': 'TEST_ONLY: проверка документов и условий применения',
            'problem': 'TEST_ONLY: поток документов требует проверки основания каждого решения.',
            'audience': 'TEST_ONLY: команды, отвечающие за проверку документов.',
            'use_case': 'TEST_ONLY: подготовить проверяемое основание перед решением человека.',
            'public_takeaway': 'TEST_ONLY: ценность зависит от полноты источников и проверки границ человеком.',
            'next_step': 'TEST_ONLY: выбрать небольшой набор ранее проверенных документов.',
            'visual_profile': {'version': 'adaptive-v1', 'mode': mode, 'label': mode,
                               'reason': 'TEST_ONLY: выбран фокус отчёта.', 'emphasis': 'text', 'selection': 'requested'},
            'visual': {'kind': 'process_flow', 'steps': [{'text': step} for step in steps]},
            'story': [{'id': 'resources', 'items': resources}, {'id': 'limitations', 'items': [limit]}],
            'comparisons': [], 'publication_sources': [{'url': url}],
            'post_text': '\n'.join(steps + resources + [limit, 'TEST_ONLY: дополнительная деталь остаётся в посте.', url])}


def all_text(parts):
    return ' '.join(part[3] for part in parts if part[0] == 'text')


class AdaptiveRenderTests(unittest.TestCase):
    def test_three_profiles_have_different_composition_and_no_unfounded_charts(self):
        signatures = []
        expected = {'mechanism': 'Механизм по шагам', 'infrastructure': 'Стек требований из отчёта',
                    'applicability': 'ЦЕННОСТЬ ДЛЯ РАБОЧЕЙ ЗАДАЧИ'}
        for mode in expected:
            data = sample(mode); original = deepcopy(data)
            height, parts = layout(data)
            self.assertIn(expected[mode], all_text(parts))
            self.assertFalse(any(part[0] == 'ring' for part in parts))
            signatures.append([(p[0], p[1:5]) for p in parts if p[0] in {'rect', 'line', 'circle'}])
            with io.BytesIO(render_infographic_png(data)) as stream:
                from PIL import Image
                with Image.open(stream) as image:
                    self.assertEqual(image.size, (1080, height))
            self.assertEqual(data, original)
        self.assertEqual(len({repr(value) for value in signatures}), 3)

    def test_full_selected_wording_provenance_and_unknowns_are_kept_without_post_rewrite(self):
        for mode in ('mechanism', 'infrastructure', 'applicability'):
            data = sample(mode); original = deepcopy(data)
            _, parts = layout(data); text = all_text(parts)
            selected = [data['title'], data['problem'], data['publication_sources'][0]['url']]
            if mode == 'mechanism':
                selected += [step['text'] for step in data['visual']['steps']] + [data['use_case']]
            elif mode == 'infrastructure':
                selected += data['story'][0]['items'] + data['story'][1]['items'] + [data['next_step']]
                self.assertIn('полная стоимость неизвестна', text)
            else:
                selected += [data['audience'], data['use_case'], data['public_takeaway'], data['next_step']]
                selected += data['story'][1]['items']
            for value in selected:
                self.assertIn(value, text)
            self.assertIn('собственных замеров нет', text)
            self.assertNotIn('[ID скрыт]', text)
            self.assertNotIn('TEST_ONLY: дополнительная деталь', text)
            self.assertIn('TEST_ONLY: дополнительная деталь', data['post_text'])
            self.assertEqual(data, original)
            svg = render_infographic_svg(data)
            self.assertIn('Собственных замеров нет', svg)
            self.assertNotIn('Источник чисел', svg)

    def test_frames_change_focus_at_fixed_native_size_while_all_selected_text_stays(self):
        for mode in ('mechanism', 'infrastructure', 'applicability'):
            data = sample(mode)
            phases = list(adaptive_visual.phases(data))
            layouts = [adaptive_visual.layout(data, active, animation=True) for active in phases]
            frames = [adaptive_visual.frame(data, active) for active in phases]
            self.assertEqual(len({frame.size for frame in frames}), 1)
            self.assertEqual(frames[0].width, 1080)
            self.assertLessEqual(frames[0].height, 1920)
            self.assertEqual(frames[0].height % 2, 0)
            self.assertNotEqual(frames[0].tobytes(), frames[-1].tobytes())
            for height, parts in layouts:
                text = all_text(parts)
                self.assertIn(data['publication_sources'][0]['url'], text)
                self.assertIn('собственных замеров нет', text)
                for part in parts:
                    if part[0] == 'text':
                        _, x, y, value, size, _, bold = part
                        self.assertLessEqual(x + _width(value, size, bold), 1080.1)
                        self.assertLessEqual(y + size, height)
                self.assertFalse(any(p[0] == 'ring' for p in parts))

    def test_oversize_selection_is_rejected_instead_of_truncating_or_resizing(self):
        for mode in ('mechanism', 'infrastructure', 'applicability'):
            data = sample(mode)
            value = 'TEST_ONLY: полное утверждение с условиями и ограничениями. ' * 100
            if mode == 'mechanism':
                data['visual']['steps'][0]['text'] = value
            elif mode == 'infrastructure':
                data['story'][0]['items'][0] = value
            else:
                data['problem'] = value
            with self.assertRaisesRegex(ValueError, 'не помещаются'):
                adaptive_visual.frame(data, 0)
            self.assertIsNone(media_encoder.render_mp4(data))

    def test_absent_profile_preserves_legacy_and_supported_comparison_keeps_conditions(self):
        data = sample('comparison')
        item = {'label': 'TEST_ONLY: задержка', 'unit': 'мс', 'baseline_label': 'TEST_ONLY: baseline',
                'baseline_value': 350, 'result_label': 'TEST_ONLY: метод', 'result_value': 290,
                'conditions': 'TEST_ONLY: один набор документов, одинаковая модель; данные авторов.',
                'evidence': [{'source_url': data['publication_sources'][0]['url'],
                              'limitations': 'TEST_ONLY: перенос на другие нагрузки не проверен.'}]}
        data['comparisons'] = [item]
        legacy = deepcopy(data); legacy.pop('visual_profile')
        self.assertEqual(layout(data), layout(legacy))
        self.assertEqual(media_encoder._comparison_frame(data, item, 1).tobytes(),
                         media_encoder._comparison_frame(legacy, item, 1).tobytes())
        text = all_text(layout(data)[1])
        self.assertIn(item['conditions'], text)
        self.assertIn(item['evidence'][0]['limitations'], text)
        self.assertIn(data['publication_sources'][0]['url'], text)

    def test_each_profile_h264_decodes_at_native_size_with_changed_reading_focus(self):
        binary = media_encoder.encoder_path()
        if binary is None:
            self.skipTest('Optional verified local H.264 encoder missing')
        from PIL import Image, ImageChops, ImageStat
        for mode in ('mechanism', 'infrastructure', 'applicability'):
            data = sample(mode)
            content = media_encoder.render_mp4(data)
            self.assertIsNotNone(content)
            self.assertLess(len(content), 8 * 1024 * 1024)
            self.assertIn(b'avc1', content)
            expected = adaptive_visual.frame(data, list(adaptive_visual.phases(data))[-1])
            with tempfile.TemporaryDirectory(prefix='TEST_ONLY-adaptive-') as directory:
                video = Path(directory) / 'animation.mp4'; video.write_bytes(content)
                first = Path(directory) / 'first.png'; last = Path(directory) / 'last.png'
                for target, seek in ((first, ['-ss', '0']), (last, ['-sseof', '-0.1'])):
                    result = subprocess.run([str(binary), '-hide_banner', '-loglevel', 'error', '-y',
                                             *seek, '-i', str(video), '-frames:v', '1', str(target)],
                                            capture_output=True, timeout=20,
                                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
                with Image.open(first) as start, Image.open(last) as finish:
                    self.assertEqual(finish.size, expected.size)
                    self.assertEqual(finish.width, 1080)
                    self.assertLessEqual(finish.height, 1920)
                    self.assertIsNotNone(ImageChops.difference(start.convert('RGB'), finish.convert('RGB')).getbbox())
                    difference = ImageChops.difference(expected, finish.convert('RGB'))
                    mse = sum(ImageStat.Stat(difference).sum2) / (expected.width * expected.height * 3)
                    self.assertGreater(10 * math.log10(255 ** 2 / max(mse, 1e-9)), 35)


if __name__ == '__main__':
    unittest.main()
