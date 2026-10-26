"""No-provider checks for generic mechanism motion, not scientific measurements."""
import io
import unittest
import xml.etree.ElementTree as ET

from laboratory.process_visual import (process_visual, render_process_svg,
                                      render_process_png, render_process_gif, _elements)


TOPICS = [
    ('TEST_ONLY: поиск документов', ['Превратить запрос в представление для поиска.', 'Выбрать подходящие фрагменты из индекса.', 'Передать фрагменты модели для ответа.']),
    ('TEST_ONLY: генерация изображений', ['Получить исходное шумовое представление.', 'Преобразовать его по условию текстового запроса.', 'Декодировать представление в изображение.'])]


class ProcessVisualTests(unittest.TestCase):
    def data(self, index=0):
        title, steps = TOPICS[index]
        return {'title':title, 'visual':process_visual(steps,title)}

    def test_two_topics_retain_their_steps_without_specialized_invention(self):
        for title, steps in TOPICS:
            visual = process_visual(steps,title)
            self.assertEqual(visual['kind'],'process_flow')
            self.assertEqual([item['text'] for item in visual['steps']],steps)
            self.assertEqual(len(visual['graph']['nodes']),5)
            self.assertEqual(len(visual['graph']['edges']),4)
            self.assertEqual([scene['active_edges'] for scene in visual['scenes']], [[],['path0'],['path1'],['path2'],['path3']])
            self.assertNotIn('replay',str(visual))
            self.assertNotIn('ускорение',str(visual))

    def test_marker_changes_position_along_actual_path(self):
        markers=[]
        for progress in (0,.25,.75,1):
            items=_elements(self.data(),2,progress)
            markers.append(next(item[1:3] for item in items if item[0]=='circle' and item[3]==11))
        self.assertEqual(len(set(markers)),4)
        self.assertTrue(all(markers[i][1]<markers[i+1][1] for i in range(3)))

    def test_svg_is_escaped_and_contains_saved_steps(self):
        data=self.data();data['title']='TEST_ONLY: RAG & индексы'
        svg=render_process_svg(data)
        ET.fromstring(svg)
        self.assertIn('RAG &amp; индексы',svg)
        self.assertIn('Выбрать подходящие фрагменты',svg)
        self.assertNotIn('<script',svg)

    def test_invalid_or_unbounded_steps_are_rejected(self):
        for steps in ([],['a','b'],['a','b',''],['a','b','x'*601],['a','b','<script>'],['a','b','x\x00']):
            with self.assertRaises(ValueError):process_visual(steps)

    def test_png_and_gif_have_real_motion_frames(self):
        from PIL import Image,ImageSequence
        png=render_process_png(self.data())
        self.assertEqual(Image.open(io.BytesIO(png)).size,(1280,1120))
        gif=Image.open(io.BytesIO(render_process_gif(self.data(1))))
        self.assertGreaterEqual(gif.n_frames,26)
        # The strip contains only the route/marker; changing prose cannot satisfy this check.
        strips={frame.convert('RGB').crop((48,150,90,680)).tobytes() for frame in ImageSequence.Iterator(gif)}
        self.assertGreaterEqual(len(strips),24)


if __name__=='__main__':unittest.main()
