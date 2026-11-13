"""TEST_ONLY pinned assets and renderer compatibility; no network or render jobs."""
from pathlib import Path
import base64
from copy import deepcopy
import hashlib
import json
import unittest

from tools.vendor_visual_engines import verify
from laboratory.research_readiness import assess
from laboratory.visual_spec import build_run_spec, build_corpus_spec
from test_research_readiness import fixture
from test_visual_spec import motion, corpus, block


ROOT=Path(__file__).resolve().parents[1]


class VisualEngineTests(unittest.TestCase):
    def test_offline_vendored_bytes_and_browser_integrity_match(self):
        self.assertTrue(verify()['verified'])
        pairs=[('laboratory/web/index.html','antv-infographic.min.js'),
               ('deliverables/ui/frontier-instrument/index.html','antv-g2.min.js')]
        for page,name in pairs:
            payload=(ROOT/'laboratory/web/vendor'/name).read_bytes()
            integrity='sha384-'+base64.b64encode(hashlib.sha384(payload).digest()).decode()
            html=(ROOT/page).read_text(encoding='utf-8')
            self.assertIn('src="/assets/vendor/'+name+'" integrity="'+integrity+'"',html)
            self.assertNotIn('https://unpkg.com',html)

    def test_only_compatible_sequence_gets_infographic_renderer(self):
        run,presentation=fixture()
        presentation.pop('source_validation')
        story=motion(run['output'])
        story['kind']='process'
        story['edges']=story['edges'][:1]
        story['edges'][0]['label']='Следующий шаг'
        presentation['motion_story']=story
        before=deepcopy(presentation)
        spec=build_run_spec(run,presentation,assess(run,presentation))
        self.assertEqual(block(spec,'process_flow')['supported_renderer'],'antv_infographic')
        self.assertEqual(block(spec,'process_flow')['renderer_version'],'0.2.20')
        self.assertEqual(block(spec,'process_flow')['fallback_renderer'],'native_dom_svg')
        self.assertEqual(presentation,before)
        story['edges'][0]['label']='TEST_ONLY a meaningful operation label'
        result=build_run_spec(run,presentation,assess(run,presentation))
        self.assertEqual(block(result,'process_flow')['supported_renderer'],'native_dom_svg')

    def test_feedback_retains_native_semantics_and_video_stays_deferred(self):
        run,presentation=fixture()
        presentation.pop('source_validation')
        presentation['motion_story']=motion(run['output'])
        spec=build_run_spec(run,presentation,assess(run,presentation))
        self.assertTrue(block(spec,'process_flow')['selected'])
        self.assertEqual(block(spec,'process_flow')['supported_renderer'],'native_dom_svg')
        self.assertEqual(next(x for x in spec['choices'] if x['kind']=='video')['status'],'deferred')

    def test_corpus_g2_keeps_exact_data_and_source_identity(self):
        value=corpus()
        before=deepcopy(value)
        spec=build_corpus_spec(value)
        trend=block(spec,'trends')
        self.assertEqual(trend['supported_renderer'],'antv_g2')
        self.assertEqual(trend['renderer_version'],'5.4.8')
        self.assertEqual(trend['data']['series'][0]['points'],value['topics'][0]['trajectory'])
        self.assertTrue(trend['data']['overlapping_topics'])
        self.assertEqual(value,before)
        json.dumps(spec,allow_nan=False)


if __name__=='__main__':unittest.main()
