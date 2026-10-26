"""Alternating appearance preserves the same source-bound post and graphs."""
from copy import deepcopy
import re
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch

from laboratory.visual_skin import rotation_skin,rotation_position
from laboratory.motion_dashboard import layout,render_png,render_svg
try:
    from .test_compact_dashboard_v0121 import metric_sample
except ImportError:
    from test_compact_dashboard_v0121 import metric_sample


class RotationRenderTests(unittest.TestCase):
    def test_app_uses_queue_skin_for_web_and_bot_presentation_without_rewriting_post(self):
        from laboratory.server import Laboratory
        app=Laboratory.__new__(Laboratory)
        review={'current':None}
        app.store=SimpleNamespace(review=SimpleNamespace(get=lambda _:review))
        app.publisher=SimpleNamespace(apply_visual_rotation=Mock(side_effect=lambda run_id,data:
            {**data,'visual_skin':rotation_skin(2)}))
        run={'id':'TEST_ONLY_completed'}
        data={'title':'TEST_ONLY пост','post_text':'TEST_ONLY полный текст',
              'visual_skin':rotation_skin(1)}
        original=deepcopy(data)
        with patch('laboratory.server.build_presentation',return_value=data):
            actual=app.reviewed_presentation(run)
        app.publisher.apply_visual_rotation.assert_called_once_with(run['id'],data)
        self.assertEqual(actual['visual_skin'],rotation_skin(2))
        self.assertEqual(actual['post_text'],data['post_text'])
        self.assertEqual(data,original)

    def test_release_number_selects_one_repeatable_skin_without_topic_precedence(self):
        self.assertEqual([rotation_skin(n)['id'] for n in range(1,7)],
                         ['dashboard','blackboard']*3)
        for n in range(1,7):
            self.assertEqual(rotation_skin(n),rotation_skin(n))
            self.assertEqual(rotation_position(rotation_skin(n)),n)
        for invalid in (None,True,False,0,-1,'2',1.2,1_000_000_001):
            with self.subTest(value=invalid):
                with self.assertRaises(ValueError):rotation_skin(invalid)
        for invalid in ({},[],None,{'version':'skins-v1','id':'dashboard',
                                   'rotation':{'version':'alternate-v1','position':2}}):
            self.assertIsNone(rotation_position(invalid))

    def test_both_release_skins_keep_numeric_evidence_without_rewriting_the_post(self):
        data=metric_sample();data['post_text']='TEST_ONLY готовый текст с исходными условиями.'
        original=deepcopy(data)
        texts=[];images=[]
        for n in (1,2):
            styled={**data,'visual_skin':rotation_skin(n)}
            height,parts=layout(styled)
            self.assertLess(height,3000)
            text=' '.join(p[3] for p in parts if p[0]=='text')
            texts.append(re.sub(r'\s+','',text))
            images.append(render_png(styled))
            svg=render_svg(styled)
            for expected in ('16%','54%','81 tokens/s','102 tokens/s'):
                self.assertIn(re.sub(r'\s+','',expected),texts[-1])
            self.assertIn('TEST_ONLY-metric-a',svg)
            self.assertEqual(styled['post_text'],data['post_text'])
        self.assertEqual(texts[0],texts[1])
        self.assertNotEqual(images[0],images[1])
        self.assertEqual(data,original)
