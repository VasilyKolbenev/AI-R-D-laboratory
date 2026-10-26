"""Automatic presentation validation uses saved output only, never a repair call."""
import copy
from decimal import Decimal
import io
import json
import unittest

from laboratory.presentation import build_presentation,render_svg,render_png,render_gif,utf16_len,_literal_numbers


class AutomaticPresentationTests(unittest.TestCase):
    excerpt='Авторы: baseline 10 мс, метод 8 мс на одной модели и нагрузке.'

    def block(self):
        return {'title':'Метод для задержки ответа','problem':'Высокая задержка интерактивного ответа.',
                'audience':'Команда сервиса ответов.','use_case':'Одна модель и одинаковая нагрузка.',
                'mechanism':['Сформировать кандидатов.','Проверить кандидатов моделью.','Вернуть проверенный ответ.'],
                'findings':['Авторское сравнение относится к одной модели и нагрузке.'],
                'limitations':['Перенос на другие нагрузки не проверен.'],
                'resources':['Нужны модель, память и оценка расходов.'],
                'public_takeaway':'Рассмотреть для одинаковой нагрузки после оценки памяти.',
                'next_step':'Зафиксировать модель и целевую нагрузку.',
                'evidence':[{'id':'e1','claim':'В отчёте указано сравнение задержки.',
                             'source_url':'https://example.org/paper','locator':'Таблица 1',
                             'excerpt':self.excerpt,'limitations':'Замеры авторов, нами не воспроизведены.'}],
                'comparisons':[{'label':'Задержка ответа','unit':'мс','baseline_label':'Обычный ответ',
                                'baseline_value':10,'result_label':'Метод авторов','result_value':8,
                                'conditions':'Одна модель и нагрузка; авторские данные, собственных замеров нет.',
                                'evidence_ids':['e1']}]}

    def run_record(self,block=None,report=None):
        block=self.block() if block is None else block
        report=self.excerpt+'\nИсточник: https://example.org/paper' if report is None else report
        return {'id':'a'*32,'output':report+'\n<lab_presentation>'+json.dumps(block,ensure_ascii=False)+'</lab_presentation>',
                'links':[],'plan':{'sources':[{'url':'https://plan-only.example/paper'}]}}

    def test_same_call_block_produces_evidence_charts_motion_and_checks(self):
        run=self.run_record();original=copy.deepcopy(run)
        data=build_presentation(run)
        self.assertEqual(run,original)
        self.assertEqual(data['provenance']['mode'],'model_structured')
        self.assertTrue(data['provenance']['presentation_block_valid'])
        self.assertEqual(data['evidence'][0]['basis'],'saved_report')
        self.assertEqual(data['comparisons'][0]['baseline_value'],10)
        self.assertEqual(data['comparisons'][0]['evidence'][0]['id'],'e1')
        self.assertEqual(data['visual']['kind'],'process_flow')
        self.assertEqual(data['publication_checks']['status'],'ready')
        self.assertEqual(data['publication_checks']['numeric_data'],'supported')
        self.assertTrue(data['publication_checks']['automatic'])
        self.assertIn('научная достоверность',data['publication_checks']['notice'])
        self.assertIn('Шкалы начинаются с нуля',render_svg(data))
        self.assertLessEqual(utf16_len(data['post_text']),3500)
        self.assertNotIn('comparisons',data['post_text'])

    def test_unknown_zero_or_unreported_values_are_dropped_without_repair(self):
        for value in [0,7,None,-1,True,float('nan'),float('inf'),10**400]:
            with self.subTest(value=value):
                block=self.block();block['comparisons'][0]['result_value']=value
                data=build_presentation(self.run_record(block))
                self.assertEqual(data['provenance']['mode'],'model_structured')
                self.assertEqual(data['comparisons'],[])
                self.assertEqual(data['publication_checks']['numeric_data'],'rejected')
                self.assertEqual(data['publication_checks']['status'],'incomplete')
                self.assertTrue(any('Сравнение 1 отброшено' in issue for issue in data['publication_checks']['issues']))
                self.assertIn('Нет подтверждённых численных сравнений',data['post_text'])

    def test_comma_decimal_literals_and_actual_zero_can_be_supported(self):
        block=self.block();excerpt='Авторы: baseline 10,5 мс; результат 0 мс в искусственном случае.'
        block['evidence'][0]['excerpt']=excerpt
        block['comparisons'][0].update(baseline_value=10.5,result_value=0)
        data=build_presentation(self.run_record(block,excerpt+'\nhttps://example.org/paper'))
        self.assertEqual(data['publication_checks']['status'],'ready')
        self.assertEqual(data['comparisons'][0]['result_value'],0)

    def test_sentence_punctuation_is_not_a_decimal_suffix(self):
        values=_literal_numbers('Calls changed from 10 to 8. Then 4, then 2.5. Version 3.1.2 is not a metric.')
        self.assertTrue({10,8,4,2.5}<=values)
        self.assertNotIn(Decimal('3.1'),values)

    def test_evidence_excerpt_must_exist_in_main_report_not_only_hidden_block(self):
        block=self.block();block['evidence'][0]['excerpt']='Не встречается в отчёте: baseline 10 мс, результат 8 мс.'
        data=build_presentation(self.run_record(block))
        self.assertEqual(data['evidence'],[]);self.assertEqual(data['comparisons'],[])
        self.assertEqual(data['publication_checks']['status'],'incomplete')
        self.assertTrue(any('Доказательство 1 отброшено' in item for item in data['provenance']['warnings']))

    def test_source_must_be_public_and_in_report_or_run_links(self):
        for url in ['https://unreported.example/paper','https://plan-only.example/paper',
                    'http://127.0.0.1/private','https://example.org/paper?token=SECRET']:
            with self.subTest(url=url):
                block=self.block();block['evidence'][0]['source_url']=url
                self.assertFalse(build_presentation(self.run_record(block))['evidence'])
        run=self.run_record(report=self.excerpt);run['links']=[{'url':'https://example.org/paper'}]
        self.assertEqual(build_presentation(run)['publication_checks']['status'],'ready')

    def test_numeric_values_must_occur_in_referenced_evidence_not_unrelated_text(self):
        block=self.block();block['evidence'][0]['excerpt']='Числа для этого утверждения неизвестны.'
        report=self.excerpt+'\nЧисла для этого утверждения неизвестны.\nhttps://example.org/paper'
        data=build_presentation(self.run_record(block,report))
        self.assertEqual(len(data['evidence']),1)
        self.assertEqual(data['comparisons'],[])

    def test_mixed_comparisons_keep_supported_row_and_name_rejected_row(self):
        block=self.block();bad=copy.deepcopy(block['comparisons'][0]);bad['result_value']=7
        block['comparisons'].append(bad)
        data=build_presentation(self.run_record(block))
        self.assertEqual(len(data['comparisons']),1)
        self.assertEqual(data['publication_checks']['numeric_data'],'supported')
        self.assertEqual(data['publication_checks']['status'],'incomplete')
        self.assertTrue(any('Сравнение 2 отброшено' in issue for issue in data['publication_checks']['issues']))

    def test_no_numbers_is_explicit_schematic_and_not_an_invented_chart(self):
        block=self.block();block['comparisons']=[]
        data=build_presentation(self.run_record(block))
        self.assertEqual(data['publication_checks']['status'],'ready')
        self.assertEqual(data['publication_checks']['numeric_data'],'not_provided')
        self.assertEqual(data['visual']['kind'],'process_flow')
        self.assertIn('не график эффективности',data['post_text'])
        self.assertNotIn('Шкалы начинаются с нуля',render_svg(data))
        try:from PIL import Image
        except ImportError:self.skipTest('Pillow optional')
        with Image.open(io.BytesIO(render_png(data))) as picture:self.assertGreater(picture.width,0)
        with Image.open(io.BytesIO(render_gif(data))) as animation:self.assertGreaterEqual(animation.n_frames,20)

    def test_legacy_report_is_readable_with_incomplete_checks(self):
        data=build_presentation({'output':'## Вывод\nДанных недостаточно.','links':[]})
        self.assertEqual(data['provenance']['mode'],'legacy_extractive')
        self.assertEqual(data['publication_checks']['status'],'incomplete')
        self.assertIn('Данных недостаточно',data['post_text'])

    def test_complete_manual_editorial_for_legacy_report_is_not_missing_auto_block(self):
        block=self.block();evidence=block.pop('evidence');block.pop('comparisons')
        run={'output':'Старый сохранённый отчёт. https://example.org/paper','links':[]}
        data=build_presentation(run,{'editorial':block,'evidence':evidence})
        self.assertEqual(data['provenance']['mode'],'editor_reviewed')
        self.assertEqual(data['publication_checks']['status'],'ready')
        self.assertFalse(data['publication_checks']['automatic'])
        self.assertEqual(data['publication_checks']['issues'],[])
        self.assertIn('редакторской версии',data['publication_checks']['notice'])
        self.assertNotIn('извлечение',data['publication_checks']['notice'])


if __name__=='__main__':unittest.main()
