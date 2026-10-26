"""No-provider tests for reader-oriented structure and actual replay animation."""
import copy
import io
import json
import unittest

from laboratory.presentation import build_presentation, render_svg, render_png, render_gif, utf16_len
from laboratory.replay_visual import replay_visual, _elements
from laboratory.comparison_visual import _axis


class ReaderPresentationTests(unittest.TestCase):
    def run_record(self):
        return {'id':'a'*32,'output':'## Краткий вывод\nВнедрение в лабораторию отложить.\n'
                'https://dream-rsi.com/\nhttps://dream-rsi.com/assets/dream-rsi.pdf\n'
                'https://github.com/google-research/harness2\nhttps://github.com/zhengkid/Dream-RSI',
                'links':[],'plan':{'sources':[{'id':'b'*32,'title':'Dream-RSI','url':'https://dream-rsi.com/'}],
                                  'memory':{'profile':{'interests':'PRIVATE OWNER SECRET'}}}}

    def review(self):
        return {'current':{'version':2,'body':{'editorial':{
            'title':'Dream-RSI: стратегии поиска на истории',
            'problem':'Перепробовать много стратегий поиска дорого: реальные попытки используют агента и оценщик.',
            'audience':'Команды, оптимизирующие код, математические решения и GPU-операции.',
            'use_case':'Есть повторяемая задача, история попыток и автоматическая проверка качества.',
            'mechanism':['Записать дерево выполненных попыток.','Проверить другой маршрут по известным исходам.','Новый онлайн-поиск пополняет историю.'],
            'findings':['Авторы приводят результаты на заданных задачах; независимого воспроизведения нет.'],
            'limitations':['Replay не открывает неизвестные ветви.','Улучшение на истории не гарантирует перенос.'],
            'resources':['Нужны агент, evaluator, история попыток и контроль расходов.'],
            'public_takeaway':'Рассматривать для повторяемого поиска решений с надёжной оценкой; эффект для произвольных задач не установлен.',
            'next_step':'Определить задачу и проверяемый критерий качества.',
            'visual_kind':'replay_tree'},
            'evidence':[{'source_url':'https://dream-rsi.com/'},{'source_url':'https://dream-rsi.com/assets/dream-rsi.pdf'},
                        {'source_url':'https://github.com/zhengkid/Dream-RSI'}]}}}

    def test_public_story_order_excludes_private_rollout_and_profile(self):
        run=self.run_record();before=copy.deepcopy(run)
        data=build_presentation(run,self.review())
        self.assertEqual(run,before)
        self.assertEqual([s['id'] for s in data['story']],['problem','audience','mechanism','findings','limitations','resources','takeaway'])
        self.assertEqual(data['provenance']['mode'],'editor_reviewed')
        self.assertEqual(data['provenance']['editorial_version'],2)
        self.assertNotIn('lab_decision',data)
        self.assertNotIn('PRIVATE OWNER',data['post_text'])
        self.assertNotIn('внедрение в лабораторию',data['post_text'].lower())
        labels=['ПРОБЛЕМА','КОМУ ПОЛЕЗНО','КАК РАБОТАЕТ','ЧТО ПОКАЗАЛИ АВТОРЫ','ГРАНИЦЫ','НАСТРОЙКА И РЕСУРСЫ','ПРАКТИЧЕСКИЙ ВЫВОД']
        positions=[data['post_text'].index(label) for label in labels]
        self.assertEqual(positions,sorted(positions))

    def test_public_sources_are_review_references_already_present_in_report(self):
        review=self.review();review['current']['body']['evidence'].append({'source_url':'https://unread.example/new-evidence'})
        data=build_presentation(self.run_record(),review)
        self.assertNotIn('google-research/harness2',data['post_text'])
        self.assertIn('https://github.com/zhengkid/Dream-RSI',data['post_text'])
        self.assertNotIn('unread.example',data['post_text'])

    def test_long_story_preserves_sources_and_utf16_limit(self):
        review=self.review();editorial=review['current']['body']['editorial']
        for key in ['problem','audience','use_case','public_takeaway','next_step']:editorial[key]='🧪 Условное пояснение. '*100
        for key in ['findings','limitations','resources']:editorial[key]=['Условия и ограничения. '*100]*5
        data=build_presentation(self.run_record(),review)
        self.assertLessEqual(utf16_len(data['post_text']),3500)
        self.assertLessEqual(utf16_len(data['short_text']),900)
        self.assertIn('https://github.com/zhengkid/Dream-RSI',data['post_text'])
        self.assertIn('собственных замеров нет',data['post_text'])
        self.assertIn('С ЧЕГО НАЧАТЬ',data['post_text'])

    def test_short_story_and_next_step_are_preserved_without_section_clipping(self):
        review=self.review();editorial=review['current']['body']['editorial']
        editorial['resources']=['Нужны агент, evaluator, история попыток, контроль расходов и отдельный бюджет проверки на новых задачах.']
        data=build_presentation(self.run_record(),review)
        self.assertLess(utf16_len(data['post_text']),3500)
        self.assertIn(editorial['resources'][0],data['post_text'])
        self.assertIn('С ЧЕГО НАЧАТЬ\n'+editorial['next_step'],data['post_text'])
        self.assertNotIn('…',data['post_text'])

    def comparison_review(self):
        review=self.review();body=review['current']['body']
        body['evidence'][1].update(id='lasso',basis='saved_report',locator='Lasso experiment',limitations='Не воспроизведено.')
        body['editorial']['comparisons']=[
            {'label':'Время работы найденного Lasso-решателя','unit':'мс',
             'baseline_label':'Исходная стратегия','baseline_value':3587.1,
             'result_label':'Dream-RSI','result_value':2931.0,
             'conditions':'Gemini-3.1-Pro, 6 отложенных датасетов; измерения авторов.', 'evidence_ids':['lasso']},
            {'label':'Вызовы discovery-агента','unit':'вызовы',
             'baseline_label':'Исходная стратегия','baseline_value':550,
             'result_label':'Dream-RSI','result_value':317,
             'conditions':'Тот же эксперимент. Вызовы не равны полной стоимости метода.', 'evidence_ids':['lasso']}]
        return review

    def test_comparisons_only_from_review_with_valid_existing_evidence(self):
        review=self.comparison_review();run=self.run_record();before=copy.deepcopy(run)
        data=build_presentation(run,review)
        self.assertEqual(run,before)
        self.assertEqual(len(data['comparisons']),2)
        for actual,wanted in zip(data['comparisons'],review['current']['body']['editorial']['comparisons']):
            self.assertEqual({key:actual[key] for key in wanted},wanted)
        self.assertEqual(data['comparisons'][0]['evidence'][0]['basis'],'saved_report')
        self.assertEqual(data['comparisons'][0]['evidence'][0]['source_url'],'https://dream-rsi.com/assets/dream-rsi.pdf')
        self.assertFalse(build_presentation(run).get('comparisons'))
        for value in [float('nan'),True,-1,1e101]:
            invalid=copy.deepcopy(review);invalid['current']['body']['editorial']['comparisons'][0]['baseline_value']=value
            self.assertEqual(len(build_presentation(run,invalid)['comparisons']),1)
        invalid=copy.deepcopy(review);invalid['current']['body']['editorial']['comparisons'][0]['evidence_ids']=['unverified']
        self.assertEqual(len(build_presentation(run,invalid)['comparisons']),1)

    def test_comparisons_have_separate_axes_conditions_and_keep_mechanism_gif(self):
        data=build_presentation(self.run_record(),self.comparison_review())
        svg=render_svg(data)
        self.assertIn('Шкалы начинаются с нуля',svg)
        self.assertIn('3587,1',svg);self.assertIn('2931,0',svg)
        self.assertIn('550',svg);self.assertIn('317',svg)
        self.assertIn('Gemini-3.1-Pro',svg)
        self.assertIn('авторские данные; собственных замеров нет',svg)
        self.assertIn('Вызовы не равны полной стоимости метода',svg)
        self.assertNotIn('<script',svg)
        self.assertGreater(_axis((3587.1,2931.0))[0],_axis((550,317))[0])
        for values in [(0,0),(5e-324,0),(.00000003,.00000001),(1e100,2e99),(1.7e308,1e308)]:
            maximum,ticks=_axis(values)
            self.assertGreater(maximum,0);self.assertEqual(ticks[0],0)
        extreme=copy.deepcopy(data);extreme['comparisons'][0].update(baseline_value=1.7e308,result_value=1e308)
        self.assertNotIn('width="inf"',render_svg(extreme))
        self.assertNotIn('x="inf"',render_svg(extreme))
        try:from PIL import Image
        except ImportError:self.skipTest('Optional Pillow missing')
        with Image.open(io.BytesIO(render_png(data))) as png:self.assertEqual(png.width,1200)
        with Image.open(io.BytesIO(render_gif(data))) as gif:
            self.assertGreaterEqual(gif.n_frames,20)
            self.assertEqual(gif.size,(960,705))

    def test_comparison_local_record_is_not_labelled_as_author_measurement(self):
        review=self.comparison_review();review['current']['body']['evidence'][1]['basis']='local_record'
        svg=render_svg(build_presentation(self.run_record(),review))
        self.assertIn('Основание: локальная запись',svg)
        self.assertNotIn('авторские данные',svg)

    def test_new_single_response_schema_is_public_story_without_editor_review(self):
        editorial=self.review()['current']['body']['editorial']
        data={key:value for key,value in editorial.items() if key!='visual_kind'}
        run=self.run_record();run['output']+='\n<lab_presentation>'+json.dumps(data,ensure_ascii=False)+'</lab_presentation>'
        result=build_presentation(run)
        self.assertEqual(result['provenance']['mode'],'model_structured')
        self.assertTrue(result['provenance']['presentation_block_valid'])
        self.assertIn('story',result)
        self.assertEqual(result['story'][0]['id'],'problem')

    def test_replay_graph_keeps_unknown_branch_and_online_node_distinct(self):
        visual=replay_visual();graph=visual['graph']
        self.assertEqual(len(visual['scenes']),5)
        self.assertTrue(any(edge['dashed'] for edge in graph['edges']))
        self.assertIn('replay_new',[node['id'] for node in graph['nodes'] if node['kind']=='new'])
        self.assertIn('не гарантирует',visual['scenes'][3]['explanation'])
        data=build_presentation(self.run_record(),self.review())
        first=_elements(data,1,.1);second=_elements(data,1,.8)
        markers=lambda elements:[item for item in elements if item[0]=='circle' and item[3]==9]
        self.assertNotEqual(markers(first),markers(second))
        self.assertFalse(any(item[0] in {'text','center'} and item[3]=='Новый исход' for item in _elements(data,2,.5)))
        self.assertTrue(any(item[0] in {'text','center'} and item[3]=='Новый исход' for item in _elements(data,4,.5)))

    def test_mechanism_svg_and_images_are_safe_and_multiframe(self):
        data=build_presentation(self.run_record(),self.review())
        svg=render_svg(data)
        self.assertIn('stroke-dasharray',svg)
        self.assertIn('не является измерением',svg)
        self.assertNotIn('<script',svg)
        try:from PIL import Image
        except ImportError:self.skipTest('Optional Pillow missing')
        with Image.open(io.BytesIO(render_png(data))) as png:self.assertEqual(png.size,(1280,940))
        with Image.open(io.BytesIO(render_gif(data))) as gif:
            self.assertGreaterEqual(gif.n_frames,20)
            self.assertEqual(gif.size,(960,705))


if __name__=='__main__':unittest.main()
