"""Reader visual keeps meaning/unknowns and works for unrelated report topics."""
from copy import deepcopy
import io
import unittest
from laboratory.reader_infographic import layout,render_infographic_svg,render_infographic_png,render_infographic_gif

def sample(percent=True):
    evidence={'id':'e1','source_url':'https://example.org/TEST_ONLY-report','limitations':'TEST_ONLY: покрытие комментариями, качество не измерено.'}
    return {'title':'TEST_ONLY: сравнение и прикладные границы',
      'problem':'TEST_ONLY: растёт очередь задач на проверку.',
      'audience':'TEST_ONLY: команды с очередью задач.','use_case':'TEST_ONLY: дополнительная проверка перед решением человека.',
      'next_step':'TEST_ONLY: задать baseline, бюджет и критерии.',
      'comparisons':[{'label':'TEST_ONLY: доля задач с комментариями' if percent else 'TEST_ONLY: задержка',
        'unit':'%' if percent else 'мс','baseline_label':'TEST_ONLY до','baseline_value':16 if percent else 350,
        'result_label':'TEST_ONLY после','result_value':54 if percent else 290,
        'conditions':'TEST_ONLY: разные периоды; авторские данные, сопоставимость состава не установлена.',
        'evidence':[evidence],'evidence_ids':['e1']}],
      'story':[{'id':'limitations','items':['TEST_ONLY: человек проверяет итог.','TEST_ONLY: результат зависит от условий.']},
               {'id':'resources','items':['TEST_ONLY: нужна инфраструктура.','TEST_ONLY: цена неизвестна.']}],
      'sources':[{'url':'https://example.org/TEST_ONLY-report'}],
      'visual':{'steps':[{'text':'TEST_ONLY вход'},{'text':'TEST_ONLY проверка'},{'text':'TEST_ONLY итог'}]}}

class ReaderInfographicTests(unittest.TestCase):
    def test_percentage_is_a_share_with_scope_benefit_limits_and_source(self):
        data=sample();height,parts=layout(data)
        rings=[p for p in parts if p[0]=='ring']
        self.assertEqual([p[5] for p in rings],[.16,.54])
        svg=render_infographic_svg(data)
        for value in ('16%','54%','доля задач с комментариями','качество не измерено','ГДЕ ПОЛЕЗНО','ГДЕ ГРАНИЦЫ','ЧТО ПОТРЕБУЕТСЯ','https://example.org/TEST_ONLY-report'):
            self.assertIn(value,svg)
        self.assertNotIn('Вызовы агента',svg)
        self.assertLess(height,3000)

    def test_other_units_and_unknown_comparison_do_not_turn_into_percentages(self):
        data=sample(False);_,parts=layout(data)
        self.assertFalse(any(p[0]=='ring' for p in parts))
        svg=render_infographic_svg(data)
        self.assertIn('350',svg);self.assertIn('290',svg);self.assertNotIn('0–100%',svg)
        data['comparisons']=[]
        svg=render_infographic_svg(data)
        self.assertIn('Сопоставимая пара baseline/result не зафиксирована',svg)
        self.assertIn('Механизм по шагам',svg)
        for text in ('TEST_ONLY вход','TEST_ONLY проверка','TEST_ONLY итог'):
            self.assertIn(text,svg)
        self.assertNotIn('Источник чисел',svg)
        self.assertIsNone(render_infographic_gif(data))

    def test_long_bounded_fields_remain_inside_canvas_and_markup_is_text(self):
        data=sample();data['title']='TEST_ONLY: '+('длинное название '*8)
        data['comparisons'][0]['conditions']='TEST_ONLY: '+('условия измерения '*16)
        data['audience']='<script>alert(1)</script>TEST_ONLY адресат'
        height,parts=layout(data)
        from laboratory.reader_infographic import _width
        for part in parts:
            if part[0]=='text':
                _,x,y,text,size,color,bold=part
                self.assertGreaterEqual(x,0);self.assertLessEqual(x+_width(text,size,bold),1080.1)
                self.assertLessEqual(y+size,height)
        self.assertNotIn('<script',render_infographic_svg(data))

    def test_animation_changes_chart_without_changing_report_or_numeric_labels(self):
        from PIL import Image,ImageChops
        data=sample();original=deepcopy(data)
        with Image.open(io.BytesIO(render_infographic_png(data))) as png:self.assertEqual(png.width,1080)
        with Image.open(io.BytesIO(render_infographic_gif(data))) as gif:
            self.assertGreaterEqual(gif.n_frames,10)
            first=gif.convert('RGB');gif.seek(gif.n_frames-1);last=gif.convert('RGB')
            self.assertIsNotNone(ImageChops.difference(first,last).getbbox())
        self.assertEqual(data,original)
        _,start=layout(data,0);_,end=layout(data,1)
        self.assertEqual([p for p in start if p[0]=='text'],[p for p in end if p[0]=='text'])

if __name__=='__main__':unittest.main()
