"""Unknown/incompatible metrics remain legible facts without fabricated bars."""
from copy import deepcopy
import re
import unittest
from laboratory.motion_dashboard import layout,render_png,_visual_metrics
from laboratory.visual_skin import rotation_skin
try:
    from .test_compact_dashboard_v0121 import compact_sample
except ImportError:
    from test_compact_dashboard_v0121 import compact_sample

def sample():
    data=compact_sample()
    data['evidence']=[{'id':'TEST_ONLY-a','source_url':'https://example.org/TEST_ONLY-a'},
                      {'id':'TEST_ONLY-b','source_url':'https://example.org/TEST_ONLY-b'}]
    data['applied_analysis']={'version':'applied-comparison-v1','rows':[
        {'id':'TEST_ONLY-r1','metric':'TEST_ONLY p95 задержки','unit':'мс',
         'baseline':{'label':'TEST_ONLY baseline','value':20,'basis':'author_claim','evidence_ids':['TEST_ONLY-a']},
         'candidate':{'label':'TEST_ONLY технология','value':15,'basis':'author_claim','evidence_ids':['TEST_ONLY-b']},
         'conditions':'TEST_ONLY разные устройства и нагрузки.',
         'comparability':'not_comparable','comparability_reason':'TEST_ONLY условия не совпадают.'},
        {'id':'TEST_ONLY-r2','metric':'TEST_ONLY стоимость задачи','unit':'USD',
         'baseline':{'label':'TEST_ONLY baseline','value':None,'basis':'unknown','evidence_ids':[]},
         'candidate':{'label':'TEST_ONLY технология','value':None,'basis':'unknown','evidence_ids':[]},
         'conditions':'TEST_ONLY расчёта расходов нет.','comparability':'unknown',
         'comparability_reason':'TEST_ONLY измерение ещё требуется.'}]}
    return data

class AppliedVisualTests(unittest.TestCase):
    def test_unknown_and_incompatible_rows_never_create_numeric_bars_or_fake_zero(self):
        data=sample();charts,tables,total=_visual_metrics(data)
        self.assertEqual(charts,[]);self.assertEqual(len(tables),2);self.assertEqual(total,2)
        text=' '.join(p[3] for p in layout(data)[1] if p[0]=='text')
        for value in ('20 мс','15 мс','н/д','прямого сравнения нет','Сопоставимость не установлена',
                      'https://example.org/TEST_ONLY-a','https://example.org/TEST_ONLY-b'):
            self.assertIn(value,text)
        self.assertNotRegex(text,r'(?<!\d)0\s*USD')

    def test_grounded_chart_is_not_repeated_as_a_table_and_three_rows_are_bounded(self):
        data=sample();row=data['applied_analysis']['rows'][0]
        row['comparability']='comparable'
        data['comparisons']=[{'label':row['metric'],'unit':'мс','baseline_label':'TEST_ONLY baseline',
                             'baseline_value':20,'result_label':'TEST_ONLY технология','result_value':15,
                             'conditions':'TEST_ONLY одинаковая нагрузка','evidence':[]}]
        data['applied_analysis']['rows'].append({**deepcopy(row),'id':'TEST_ONLY-r3','metric':'TEST_ONLY третий'})
        charts,tables,total=_visual_metrics(data)
        self.assertEqual((len(charts),len(tables),total),(1,1,3))
        self.assertEqual(tables[0]['id'],'TEST_ONLY-r2')
        text=' '.join(p[3] for p in layout(data)[1] if p[0]=='text')
        self.assertEqual(text.count(row['metric']),1)
        self.assertIn('2 из 3',text)

    def test_both_skins_keep_values_conditions_and_motion_without_mutation(self):
        data=sample();original=deepcopy(data);texts=[]
        for position in (1,2):
            styled={**data,'visual_skin':rotation_skin(position)}
            height,parts=layout(styled,progress=.3,animation=True)
            self.assertLessEqual(height,3000)
            texts.append(re.sub(r'\s+','',' '.join(p[3] for p in parts if p[0]=='text')))
            self.assertTrue(render_png(styled))
        self.assertEqual(texts[0],texts[1]);self.assertEqual(data,original)
