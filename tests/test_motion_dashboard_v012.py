"""Native mechanism motion must carry artifacts, never invented performance."""
from copy import deepcopy
import io
import unittest

from laboratory.motion_dashboard import (
    AMBER, CYAN, MAGENTA, _positions, frame, layout, packet_positions,
    render_png, render_svg,
)
from laboratory.reader_infographic import _width, _wrap


def sample(kind='process', baseline='unknown'):
    nodes=[{'id':key,'label':label,'role':role,'lane':'technology','evidence_ids':[]}
           for key,label,role in [('a','TEST_ONLY вход','input'),
                                  ('b','TEST_ONLY обработка','compute'),
                                  ('c','TEST_ONLY результат','output')]]
    edges=[{'id':'ab','from':'a','to':'b','label':'TEST_ONLY документ','kind':'data','evidence_ids':[]},
           {'id':'bc','from':'b','to':'c','label':'TEST_ONLY проверенный итог','kind':'control','evidence_ids':[]}]
    if kind=='feedback':
        nodes[-1]['role']='memory'
        edges.append({'id':'ca','from':'c','to':'a','label':'TEST_ONLY следующий цикл','kind':'feedback','evidence_ids':[]})
    return {'title':'TEST_ONLY: механизм без вымышленных измерений',
            'problem':'TEST_ONLY: читатель должен понимать путь документа.',
            'comparisons':[],
            'motion_story':{'version':'dataflow-v1','kind':kind,'nodes':nodes,'edges':edges,
                            'baseline':{'status':baseline,'label':'TEST_ONLY baseline неизвестен',
                                        'note':'TEST_ONLY: сопоставимого измеренного процесса нет.'},
                            'notes':['TEST_ONLY: это условная схема, а не замер скорости.'],
                            'sources':[{'url':'https://example.org/TEST_ONLY-source'}]}}


class MotionDashboardTests(unittest.TestCase):
    def test_artifacts_physically_move_and_saved_text_is_stable(self):
        from PIL import ImageChops
        data=sample('feedback');before=deepcopy(data)
        early=packet_positions(data,.01);later=packet_positions(data,.02)
        self.assertTrue(early);self.assertTrue(later)
        self.assertNotEqual(early,later)
        # No easing or speed advantage: the same illustrative arc-length rate.
        edge='ab'
        a=next(p for p in early if p[0]==edge)
        b=next(p for p in later if p[0]==edge)
        self.assertAlmostEqual(b[1]-a[1],11)
        self.assertAlmostEqual(b[2]-a[2],0)
        h,start=layout(data,.01,animation=True)
        _,end=layout(data,.02,animation=True)
        self.assertEqual([p for p in start if p[0]=='text'],[p for p in end if p[0]=='text'])
        self.assertEqual(data,before)
        first,last=frame(data,.01),frame(data,.02)
        self.assertEqual(first.mode,'RGB');self.assertEqual(first.size,(1080,h))
        self.assertIsNotNone(ImageChops.difference(first,last).getbbox())

    def test_unknown_baseline_has_warning_and_no_fictional_lane(self):
        data=sample('inference')
        svg=render_svg(data)
        self.assertIn('baseline неизвестен',svg)
        self.assertIn('сопоставимого измеренного процесса нет',svg)
        self.assertIn(AMBER,svg)
        for number in ('16%','54%','2×','tokens/s','мс'):
            self.assertNotIn(number,svg)
        self.assertIn('собственных замеров нет',svg)
        self.assertIn('https://example.org/TEST_ONLY-source',svg)
        self.assertNotIn('>TEST_ONLY до<',svg)

    def test_each_mechanism_has_different_geometry_and_uses_graph_ids(self):
        shapes=[]
        for kind in ('process','feedback','inference'):
            data=sample(kind);story=data['motion_story']
            for key,previous in (('d','c'),('e','d'),('f','e')):
                story['nodes'].append({'id':key,'label':'TEST_ONLY '+key,'role':'compute','lane':'technology','evidence_ids':[]})
                story['edges'].append({'id':previous+key,'from':previous,'to':key,'label':'TEST_ONLY переход','kind':'data','evidence_ids':[]})
            boxes,_=_positions(story['nodes'],story['edges'],kind,0)
            shapes.append(list(boxes.values()))
            renamed=deepcopy(story)
            for n in renamed['nodes']:
                n['id']='arbitrary_'+n['id']
            for e in renamed['edges']:
                e['from']='arbitrary_'+e['from'];e['to']='arbitrary_'+e['to']
            same,_=_positions(renamed['nodes'],renamed['edges'],kind,0)
            self.assertEqual(list(boxes.values()),list(same.values()))
        self.assertEqual(len(set(map(str,shapes))),3)
        svg=render_svg(sample('feedback'))
        self.assertIn(MAGENTA,svg);self.assertIn('следующий цикл',svg)
        self.assertIn('ВЕСА МОДЕЛИ ФИКСИРОВАНЫ',svg)

    def test_only_current_comparison_supplies_a_numeric_chart(self):
        data=sample()
        data['comparisons']=[{'label':'TEST_ONLY: покрытие замечаниями',
            'unit':'%','baseline_label':'TEST_ONLY до','result_label':'TEST_ONLY после',
            'baseline_value':16,'result_value':54,
            'conditions':'TEST_ONLY: авторское сравнение, собственных замеров нет.',
            'evidence':[{'limitations':'TEST_ONLY: покрытие не измеряет качество.',
                         'source_url':'https://example.org/TEST_ONLY-metric'}]}]
        svg=render_svg(data)
        for text in ('16%','54%','покрытие замечаниями','покрытие не измеряет качество','https://example.org/TEST_ONLY-metric'):
            self.assertIn(text,svg)
        data['comparisons'][0]['result_value']=float('nan')
        svg=render_svg(data)
        self.assertNotIn('16%',svg);self.assertNotIn('54%',svg)

    def test_native_png_labels_sources_and_caveats_stay_on_canvas(self):
        from PIL import Image
        data=sample('feedback')
        label='TEST_ONLY: полное название операции и содержательного результата'
        data['motion_story']['nodes'][1]['label']=label
        h,parts=layout(data)
        self.assertLessEqual(h,1920)
        text_parts=[p for p in parts if p[0]=='text']
        text=''.join(p[3] for p in text_parts)
        self.assertIn(''.join(_wrap(label,242,26,True)),text)
        for _,x,y,value,size,color,bold in text_parts:
            self.assertGreaterEqual(x,0);self.assertGreaterEqual(y,0)
            self.assertLessEqual(x+_width(value,size,bold),1080.1)
            self.assertLessEqual(y+size,h)
        with Image.open(io.BytesIO(render_png(data))) as png:
            self.assertEqual(png.size,(1080,h));self.assertEqual(png.mode,'RGB')
        self.assertIn(CYAN,render_svg(data))


if __name__=='__main__':
    unittest.main()
