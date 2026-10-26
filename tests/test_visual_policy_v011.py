"""TEST_ONLY: adaptive composition reuses saved, validated presentation facts."""
from copy import deepcopy
import json
import unittest

from laboratory.presentation import build_presentation, PROMPT_INSTRUCTIONS
from laboratory.visual_policy import select_visual_profile, VISUAL_FOCUS_VALUES


class AdaptiveVisualPolicyTests(unittest.TestCase):
    excerpt = 'TEST_ONLY: авторы сообщают baseline 10 мс и результат 8 мс при одной нагрузке.'
    url = 'https://example.org/TEST_ONLY-paper'

    def block(self, **changes):
        block = {'title': 'TEST_ONLY: новая возможность для рабочих задач',
                 'problem': 'Нужно проверить полезность нового инструмента для своей задачи.',
                 'audience': 'Команда проекта.', 'use_case': 'Разбор результатов перед решением человека.',
                 'mechanism': ['Получить исходный материал.', 'Обработать материал методом авторов.', 'Проверить полученный результат.'],
                 'findings': ['Результат авторов зависит от условий, переноса на нашу задачу не проверяли.'],
                 'limitations': ['Независимого воспроизведения нет.'],
                 'resources': ['Нужны модель, CPU, GPU и контроль расходов.'],
                 'public_takeaway': 'Оценить применимость на ограниченном наборе своих задач.',
                 'next_step': 'Зафиксировать критерий проверки.', 'evidence': [], 'comparisons': []}
        block.update(changes)
        return block

    def numeric_block(self, **changes):
        return self.block(evidence=[{'id': 'e1', 'claim': 'В отчёте приведено сравнение задержки.',
                          'source_url': self.url, 'locator': 'Таблица 1', 'excerpt': self.excerpt,
                          'limitations': 'Авторские данные, перенос не проверен.'}],
                          comparisons=[{'label': 'Задержка', 'unit': 'мс', 'baseline_label': 'Исходный метод',
                                        'baseline_value': 10, 'result_label': 'Метод авторов', 'result_value': 8,
                                        'conditions': 'Одна нагрузка; собственных замеров нет.', 'evidence_ids': ['e1']}],
                          **changes)

    def run_record(self, block):
        return {'id': 'a'*32, 'output': self.excerpt+'\n'+self.url+'\n<lab_presentation>'
                +json.dumps(block, ensure_ascii=False)+'</lab_presentation>', 'links': [],
                'plan': {'sources': [{'title': 'TEST_ONLY сохранённый источник', 'url': self.url}]}}

    def test_supported_comparison_precedes_every_requested_focus_without_mutation(self):
        baseline = build_presentation(self.run_record(self.numeric_block()))
        for requested in VISUAL_FOCUS_VALUES:
            with self.subTest(requested=requested):
                run = self.run_record(self.numeric_block(visual_focus=requested)); original = deepcopy(run)
                data = build_presentation(run)
                self.assertEqual(run, original)
                self.assertEqual(data['post_text'], baseline['post_text'])
                self.assertEqual(data['comparisons'], baseline['comparisons'])
                self.assertEqual(data['visual_profile']['mode'], 'comparison')
                self.assertEqual(data['visual_profile']['selection'], 'evidence')
                self.assertEqual(data['visual_profile']['emphasis'], 'charts')
                self.assertNotIn('visual_focus', data)
                self.assertNotIn('_visual_focus', data)

    def test_focus_is_optional_same_call_metadata_and_keeps_public_post_identical(self):
        base = build_presentation(self.run_record(self.block()))
        for focus in ('auto', 'mechanism', 'infrastructure', 'applicability'):
            with self.subTest(focus=focus):
                data = build_presentation(self.run_record(self.block(visual_focus=focus)))
                self.assertEqual(data['post_text'], base['post_text'])
                self.assertEqual(data['short_text'], base['short_text'])
                self.assertEqual(data['story'], base['story'])
                self.assertEqual(data['publication_checks'], base['publication_checks'])
                self.assertEqual(data['provenance'], base['provenance'])
                profile = data['visual_profile']
                self.assertEqual(set(profile), {'version', 'mode', 'label', 'reason', 'emphasis', 'selection'})
                self.assertEqual(profile['version'], 'adaptive-v1')
                self.assertEqual(profile['selection'], 'heuristic' if focus == 'auto' else 'requested')
                self.assertTrue(any('А' <= char <= 'я' for char in profile['label']))
                self.assertTrue(any('А' <= char <= 'я' for char in profile['reason']))
        self.assertIn('"visual_focus":"auto"', PROMPT_INSTRUCTIONS)
        self.assertIn('без отдельного вызова', PROMPT_INSTRUCTIONS)

    def test_invalid_focus_rejects_block_instead_of_accepting_unbounded_metadata(self):
        for focus in (None, True, 0, [], {}, 'chart', 'AUTO', 'comparison ', '<script>', self.url):
            with self.subTest(focus=focus):
                data = build_presentation(self.run_record(self.block(visual_focus=focus)))
                self.assertEqual(data['provenance']['mode'], 'legacy_extractive')
                self.assertFalse(data['provenance']['presentation_block_valid'])
                self.assertNotIn('visual_profile', data)

    def test_new_focus_does_not_weaken_other_schema_validation(self):
        bad_blocks = [self.block(visual_focus='auto', other_hint='untrusted'),
                      self.block(visual_focus='mechanism', mechanism=['one', 'two']),
                      self.block(visual_focus='applicability', title='<script>bad</script>'),
                      self.block(visual_focus='infrastructure', problem=self.url)]
        for block in bad_blocks:
            with self.subTest(block=block):
                self.assertFalse(build_presentation(self.run_record(block))['provenance']['presentation_block_valid'])

    def test_infrastructure_is_subject_semantics_and_not_incidental_hardware(self):
        for name in ('DeepInfer', 'FictitiousCompute'):
            engine = build_presentation(self.run_record(self.block(
                title='TEST_ONLY: '+name+' inference engine', problem='Движок для инференса моделей.',
                use_case='Обслуживать запросы одной модели при заданной нагрузке.')))
            self.assertEqual(engine['visual_profile']['mode'], 'infrastructure')
        assistant = build_presentation(self.run_record(self.block(
            title='TEST_ONLY: помощник разработчика', problem='Нужно подготовить изменение кода.',
            use_case='Разработчик проверяет предложенный патч.',
            resources=['Нужны CPU, GPU, VRAM и inference engine для вызова модели.'])))
        self.assertEqual(assistant['visual_profile']['mode'], 'applicability')
        self.assertEqual(assistant['comparisons'], [])

    def test_explicit_engine_heading_routes_without_inference_word_or_brand_rules(self):
        for heading in ('FictitiousCompute: открытый движок, неизвестная экономия',
                        'FictitiousCompute: open engine, unknown savings',
                        'FictitiousCompute: runtime для пакетных задач'):
            with self.subTest(heading=heading):
                block = self.block(title='TEST_ONLY: '+heading,
                                   problem='Массовая генерация ответов одной моделью требует контроля расходов.',
                                   use_case='Пакетная обработка однотипных запросов.')
                data = build_presentation(self.run_record(block))
                original = deepcopy(data)
                self.assertEqual(data['visual_profile']['mode'], 'infrastructure')
                block['visual_focus'] = 'applicability'
                alternative = build_presentation(self.run_record(block))
                self.assertEqual(data['post_text'], alternative['post_text'])
                self.assertEqual(data['comparisons'], [])
                self.assertEqual(data, original)
        movement = build_presentation(self.run_record(self.block(
            title='TEST_ONLY: FictitiousMotion: движение задач в команде',
            resources=['CPU, GPU, VRAM и inference engine требуются для вызова модели.'])))
        self.assertEqual(movement['visual_profile']['mode'], 'applicability')

    def test_unknown_topic_keeps_applicability_despite_numbers_in_report_and_three_steps(self):
        data = build_presentation(self.run_record(self.block()))
        self.assertEqual(data['visual_profile']['mode'], 'applicability')
        self.assertEqual(data['visual_profile']['selection'], 'heuristic')
        self.assertEqual(data['comparisons'], [])
        self.assertIn('10 мс', self.run_record(self.block())['output'])

    def test_harness_semantic_selection_and_editorial_priority_for_saved_report(self):
        block = self.block(title='TEST_ONLY: DeepInfer inference engine')
        run = self.run_record(block)
        editorial = self.block(title='TEST_ONLY: Harness² — обвязка для проверки документов',
                               problem='Повторная проверка документов и источников занимает время.',
                               use_case='Сохранить проверяемое основание перед решением человека.')
        review = {'current': {'version': 2, 'body': {'editorial': editorial}}}
        original = deepcopy((run, review))
        data = build_presentation(run, review)
        self.assertEqual((run, review), original)
        self.assertEqual(data['provenance']['mode'], 'editor_reviewed')
        self.assertEqual(data['visual_profile']['mode'], 'mechanism')
        self.assertEqual(data['visual_profile']['emphasis'], 'motion')
        # The same editorial path works when the saved report predates hints.
        run['output'] = self.excerpt+'\n'+self.url
        self.assertEqual(build_presentation(run, review)['visual_profile']['mode'], 'mechanism')

    def test_requested_comparison_without_supported_numbers_has_honest_fallback(self):
        for title, expected in [('TEST_ONLY: Harness² — обвязка агента', 'mechanism'),
                                ('TEST_ONLY: FictitiousFlow — обвязка агента', 'mechanism'),
                                ('TEST_ONLY: DeepInfer inference engine', 'applicability'),
                                ('TEST_ONLY: новая возможность', 'applicability')]:
            with self.subTest(title=title):
                block = self.numeric_block(title=title, visual_focus='comparison')
                block['comparisons'][0]['result_value'] = 0
                data = build_presentation(self.run_record(block))
                profile = data['visual_profile']
                self.assertEqual(profile['mode'], expected)
                self.assertEqual(profile['selection'], 'requested')
                self.assertIn('подтверждённой сопоставимой пары чисел нет', profile['reason'])
                self.assertIn('не заменяются нулями', profile['reason'])
                self.assertEqual(data['comparisons'], [])
                self.assertEqual(data['publication_checks']['numeric_data'], 'rejected')
                self.assertEqual(data['publication_checks']['status'], 'incomplete')

    def test_product_name_alone_cannot_override_unknown_topic_or_choose_a_mechanism(self):
        for title in ('TEST_ONLY: Harness²', 'TEST_ONLY: DeepInfer', 'TEST_ONLY: FictitiousFlow'):
            with self.subTest(title=title):
                data = build_presentation(self.run_record(self.block(title=title)))
                self.assertEqual(data['visual_profile']['mode'], 'applicability')
        for title in ('TEST_ONLY: Harness² — обвязка агента', 'TEST_ONLY: FictitiousFlow — обвязка агента'):
            with self.subTest(title=title):
                data = build_presentation(self.run_record(self.block(title=title)))
                self.assertEqual(data['visual_profile']['mode'], 'mechanism')

    def test_real_evidence_zero_remains_a_supported_comparison(self):
        block = self.numeric_block(visual_focus='mechanism')
        block['evidence'][0]['excerpt'] = 'TEST_ONLY: baseline 10 мс, результат 0 мс в искусственном случае.'
        block['comparisons'][0]['result_value'] = 0
        run = self.run_record(block)
        run['output'] = run['output'].replace(self.excerpt, block['evidence'][0]['excerpt'], 1)
        data = build_presentation(run)
        self.assertEqual(data['comparisons'][0]['result_value'], 0)
        self.assertEqual(data['visual_profile']['mode'], 'comparison')

    def test_replay_special_path_and_raw_legacy_remain_unchanged(self):
        run = self.run_record(self.block(visual_focus='infrastructure'))
        review = {'editorial': self.block(visual_kind='replay_tree')}
        data = build_presentation(run, review)
        self.assertEqual(data['visual']['kind'], 'replay_tree')
        self.assertNotIn('visual_profile', data)
        self.assertNotEqual(data.get('visual_theme'), 'reader_infographic')
        legacy = build_presentation({'output': 'TEST_ONLY: сохранённый отчёт без редакторского блока.', 'links': []})
        self.assertNotIn('visual_profile', legacy)

    def test_policy_does_not_treat_incomplete_pairs_or_booleans_as_evidence(self):
        good = build_presentation(self.run_record(self.numeric_block()))
        before = deepcopy(good)
        for value in (None, True, -1, float('nan'), float('inf'), 10**400):
            data = deepcopy(good); data['comparisons'][0]['baseline_value'] = value
            self.assertNotEqual(select_visual_profile(data)['mode'], 'comparison')
        for field, value in [('conditions', ''), ('unit', ''), ('evidence', []), ('evidence_ids', ['missing'])]:
            data = deepcopy(good); data['comparisons'][0][field] = value
            self.assertNotEqual(select_visual_profile(data)['mode'], 'comparison')
        self.assertEqual(good, before)
        self.assertEqual(select_visual_profile({'title': 'Harness²'}, 'mechanism')['mode'], 'applicability')


if __name__ == '__main__':
    unittest.main()
