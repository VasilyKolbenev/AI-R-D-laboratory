"""Saved-text graph compilation: no model, network, state or measured effects."""
import copy
import json
import unittest

from laboratory.motion_story import build_motion_story, validate_motion_graph
from laboratory.presentation import build_presentation


REVIEW = '''Несколько агентов читают diff и окружающий код.
Проверка отсеивает неподтверждённые находки; оставшиеся объединяются и ранжируются.
Замечания публикуются в PR.
CI и решение по риску остаются у человека.
Для качественного сравнения можно рассматривать ручное ревью плюс CI.
Сервис сам не одобряет PR и не запускает код.
https://primary.example/review'''
FEEDBACK = '''Меняется обвязка агента при фиксированных весах модели.
Propose–Probe–Compose предлагает изменения, проверяет варианты на текущей задаче и составляет улучшенную обвязку.
Второй уровень переносит опыт на следующие задачи.
https://primary.example/method'''
INFERENCE = '''Как обслуживать больше запросов?
Параллелизм распределяет внимание и экспертов между ускорителями; планировщик совмещает подготовку пакетов с вычислениями.
Черновик предлагает черновые токены, затем модель проверяет их.
Авторы приводят условия prefill и decode, а не минимум запуска.
Сопоставимых значений ускорения и стоимости нет.
https://primary.example/inference'''


def presentation(steps=None):
    return {'title': 'Другой проект без известного имени', 'visual_theme': 'reader_infographic',
            'sources': [{'url': 'https://primary.example/review'}],
            'visual': {'kind': 'process_flow', 'steps': [{'text': step} for step in
                       (steps or ['Получить исходный материал.', 'Проверить преобразование.', 'Сохранить результат.'])]}}


def optional_graph():
    return {'version': 'dataflow-v1', 'kind': 'process',
            'nodes': [{'id': 'request', 'label': 'Запрос', 'role': 'input', 'lane': 'technology', 'evidence_ids': ['e1']},
                      {'id': 'check', 'label': 'Проверка', 'role': 'decision', 'lane': 'technology', 'evidence_ids': ['e1']}],
            'edges': [{'id': 'flow', 'from': 'request', 'to': 'check', 'label': 'проверку', 'kind': 'data', 'evidence_ids': ['e1']}],
            'baseline': {'status': 'unknown', 'label': 'Baseline не установлен', 'note': 'Сопоставимого baseline нет.'},
            'notes': []}


class MotionStoryTests(unittest.TestCase):
    def test_review_has_real_finding_flow_and_human_boundary(self):
        story = build_motion_story(presentation(), REVIEW)
        self.assertEqual(story['kind'], 'review')
        nodes = {node['id']: node for node in story['nodes']}
        edges = {(edge['from'], edge['to']) for edge in story['edges']}
        self.assertEqual(nodes['human']['role'], 'decision')
        self.assertEqual(nodes['findings']['role'], 'output')
        self.assertIn(('findings', 'human'), edges)
        self.assertIn(('input', 'inspect_peer'), edges)
        self.assertIn(('inspect_peer', 'verify'), edges)
        self.assertEqual(story['baseline']['status'], 'conceptual')
        self.assertTrue(any('покрытие' in note for note in story['notes']))
        self.assertFalse(any('merge' in node['label'].lower() or 'слияние' in node['label'].lower() for node in story['nodes']))

    def test_review_without_source_baseline_does_not_invent_one(self):
        story = build_motion_story(presentation(), REVIEW.replace('Для качественного сравнения можно рассматривать ручное ревью плюс CI.', ''))
        self.assertEqual(story['baseline']['status'], 'unknown')
        self.assertFalse(any(node['lane'] == 'baseline' for node in story['nodes']))

    def test_feedback_reuses_experience_and_preserves_weights(self):
        story = build_motion_story(presentation(), FEEDBACK)
        self.assertEqual(story['kind'], 'feedback')
        self.assertEqual(story['baseline']['status'], 'conceptual')
        self.assertEqual(next(node for node in story['nodes'] if node['id'] == 'experience')['role'], 'memory')
        self.assertTrue(any(edge['from'] == 'experience' and edge['to'] == 'propose' and edge['kind'] == 'feedback' for edge in story['edges']))
        self.assertTrue(any('Веса модели фиксированы' in note for note in story['notes']))

    def test_feedback_requires_fixed_weights_and_actual_transfer(self):
        for text in [FEEDBACK.replace('Меняется обвязка агента при фиксированных весах модели.', ''),
                     FEEDBACK.replace('Второй уровень переносит опыт на следующие задачи.', '')]:
            self.assertEqual(build_motion_story(presentation(), text)['kind'], 'process')

    def test_inference_stages_and_token_validation_without_fake_topology(self):
        story = build_motion_story(presentation(), INFERENCE)
        self.assertEqual(story['kind'], 'inference')
        self.assertEqual(story['baseline']['status'], 'unknown')
        self.assertEqual([node['id'] for node in story['nodes']], ['input', 'prefill', 'decode', 'draft', 'verify', 'output'])
        self.assertFalse(any(node['lane'] == 'baseline' for node in story['nodes']))
        self.assertFalse(any(node['role'] == 'memory' for node in story['nodes']))
        self.assertFalse(any(edge['kind'] == 'feedback' for edge in story['edges']))
        self.assertFalse(any('vllm' in node['label'].lower() or 'gpu' in node['label'].lower() for node in story['nodes']))

    def test_source_concepts_select_equivalent_unnamed_topics(self):
        for name in ['Продукт Альфа', 'Утилита Бета', 'Неизвестная команда']:
            data = presentation(); data['title'] = name
            self.assertEqual(build_motion_story(data, REVIEW)['kind'], 'review')
            self.assertEqual(build_motion_story(data, FEEDBACK)['kind'], 'feedback')
            self.assertEqual(build_motion_story(data, INFERENCE)['kind'], 'inference')

    def test_equivalent_english_source_concepts_have_same_graph_roles(self):
        texts = {
            'review': ('Multiple agents read diff and surrounding code.\nVerification discards unconfirmed findings and ranks findings.\n'
                       'Findings are published in pull request.\nHuman approval follows verification.\nManual review and CI are a conceptual baseline.'),
            'feedback': ('A fixed weights model changes its harness.\nPropose-Probe-Compose modifies the harness.\nExperience transfers to next tasks.'),
            'inference': ('Requests enter the engine.\nPrefill and decode are named stages.\n'
                          'Draft tokens undergo verification by the model.\nParallel computation distributes attention and expert operations.')}
        for kind, report in texts.items():
            with self.subTest(kind=kind):
                self.assertEqual(build_motion_story(presentation(), report)['kind'], kind)

    def test_generic_fallback_only_uses_actual_three_steps(self):
        steps = ['Получить материал.', 'Проверить преобразование.', 'Сохранить вывод.']
        story = build_motion_story(presentation(steps), '\n'.join(steps))
        self.assertEqual(story['kind'], 'process')
        self.assertEqual([node['label'] for node in story['nodes']], steps)
        self.assertEqual([node['id'] for node in story['nodes']], ['step1', 'step2', 'step3'])
        self.assertFalse(any(node['role'] in {'input', 'output'} for node in story['nodes']))

    def test_generic_long_or_code_steps_keep_existing_renderer(self):
        for step in ['Это длинный подробный шаг механизма, который нельзя без потери смысла обрезать и выдать за название операции.',
                     'print("hello")', 'Сравнить с 100 вариантами.']:
            data = presentation([step, 'Проверить преобразование.', 'Сохранить вывод.'])
            self.assertIsNone(build_motion_story(data, step))

    def test_compilation_is_pure_bounded_and_grounded(self):
        data = presentation(); before = copy.deepcopy(data)
        for report in [REVIEW, FEEDBACK, INFERENCE]:
            story = build_motion_story(data, report)
            self.assertLessEqual(len(story['nodes']), 12)
            self.assertLessEqual(len(story['edges']), 16)
            self.assertTrue(all(len(row['label']) <= 64 and 'http' not in row['label'] and not any(c.isdigit() for c in row['label'])
                                for row in story['nodes'] + story['edges']))
            ids = [row['id'] for row in story['nodes'] + story['edges']]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertTrue(all(row['excerpt'] in report for row in story['evidence']))
            known = {row['id'] for row in story['evidence']}
            self.assertTrue(all(set(row['evidence_ids']) <= known for row in story['nodes'] + story['edges']))
        self.assertEqual(data, before)

    def test_replay_and_raw_legacy_remain_unchanged(self):
        data = presentation(); data['visual']['kind'] = 'replay_tree'
        self.assertIsNone(build_motion_story(data, REVIEW))
        run = {'output': 'Обычный старый отчёт без механизма.', 'plan': {}}
        result = build_presentation(run)
        self.assertNotIn('motion_story', result)


class OptionalMotionValidationTests(unittest.TestCase):
    def setUp(self):
        self.report = 'Запрос передаётся на проверку. Проверка возвращает результат.'
        self.evidence = [{'id': 'e1', 'excerpt': self.report, 'source_url': 'https://primary.example/report'}]

    def test_valid_literal_graph_is_copied_without_mutation(self):
        graph = optional_graph(); before = copy.deepcopy(graph)
        actual, issues = validate_motion_graph(graph, self.report, self.evidence)
        self.assertEqual(actual, graph); self.assertFalse(issues)
        self.assertIsNot(actual, graph); self.assertEqual(graph, before)

    def test_malformed_graph_ids_references_and_roles_are_rejected(self):
        changes = [lambda g: g.update(version='wrong'),
                   lambda g: g['nodes'][0].update(id='request/unsafe'),
                   lambda g: g['nodes'][1].update(id='request'),
                   lambda g: g['edges'][0].update(to='absent'),
                   lambda g: g['nodes'][0].update(evidence_ids=['unknown']),
                   lambda g: g['nodes'][0].update(evidence_ids=['e1', 'e1']),
                   lambda g: g['nodes'][0].update(role='gpu'),
                   lambda g: g['nodes'][0].update(role='memory'),
                   lambda g: g['nodes'][0].update(lane='hardware'),
                   lambda g: g['nodes'][0].update(label='Скорость выросла'),
                   lambda g: g['nodes'][0].update(label='Запрос 10x'),
                   lambda g: g['nodes'][0].update(label='https://primary.example'),
                   lambda g: g['edges'][0].update(id='request'),
                   lambda g: g['edges'][0].update(kind='feedback'),
                   lambda g: g['edges'].append({'id': 'cycle', 'from': 'check', 'to': 'request', 'label': 'Запрос', 'kind': 'data', 'evidence_ids': ['e1']}),
                   lambda g: g.update(notes=['Всё работает быстрее.']),
                   lambda g: g.update(nodes=g['nodes'] * 7)]
        for change in changes:
            graph = optional_graph(); change(graph)
            with self.subTest(graph=graph):
                actual, issues = validate_motion_graph(graph, self.report, self.evidence)
                self.assertIsNone(actual); self.assertTrue(issues)

    def test_ungrounded_evidence_or_invented_baseline_rejected(self):
        self.assertIsNone(validate_motion_graph(optional_graph(), self.report,
                                               [{'id': 'e1', 'excerpt': 'Случайный отсутствующий фрагмент.'}])[0])
        graph = optional_graph(); graph['nodes'][0]['lane'] = 'baseline'
        self.assertIsNone(validate_motion_graph(graph, self.report, self.evidence)[0])
        graph = optional_graph(); graph['baseline']['status'] = 'reported'
        self.assertIsNone(validate_motion_graph(graph, self.report, self.evidence)[0])
        graph = optional_graph(); graph['baseline']['status'] = 'conceptual'
        self.assertIsNone(validate_motion_graph(graph, self.report, self.evidence)[0])

    def test_invalid_optional_motion_preserves_valid_post_and_no_second_call(self):
        body = {'title': 'Тема', 'problem': 'Проблема.', 'audience': 'Инженеры.', 'use_case': 'Задача.',
                'mechanism': ['Получить материал.', 'Проверить преобразование.', 'Сохранить вывод.'],
                'findings': ['Сравнений нет.'], 'limitations': ['Перенос неизвестен.'], 'resources': ['Ресурсы неизвестны.'],
                'public_takeaway': 'Проверить применимость.', 'next_step': 'Подготовить примеры.',
                'evidence': [], 'comparisons': [], 'motion': {'bad': 'attachment'}}
        run = {'output': 'Основной сохранённый отчёт.\n<lab_presentation>' + json.dumps(body, ensure_ascii=False) + '</lab_presentation>'}
        before = copy.deepcopy(run)
        actual = build_presentation(run)
        self.assertEqual(actual['provenance']['mode'], 'model_structured')
        self.assertTrue(actual['provenance']['presentation_block_valid'])
        self.assertEqual(actual['motion_story']['kind'], 'process')
        self.assertTrue(any('motion отброшен' in note for note in actual['motion_story']['notes']))
        without = copy.deepcopy(body); without.pop('motion')
        expected = build_presentation({'output': 'Основной сохранённый отчёт.\n<lab_presentation>' + json.dumps(without, ensure_ascii=False) + '</lab_presentation>'})
        self.assertEqual(actual['publication_checks'], expected['publication_checks'])
        self.assertEqual(actual['post_text'], expected['post_text'])
        self.assertEqual(actual['short_text'], expected['short_text'])
        self.assertEqual(actual['comparisons'], expected['comparisons'])
        self.assertEqual(run, before)
        oversized = copy.deepcopy(body); oversized['motion'] = {'payload': 'x' * 20500}
        large = build_presentation({'output': 'Основной сохранённый отчёт.\n<lab_presentation>' + json.dumps(oversized, ensure_ascii=False) + '</lab_presentation>'})
        self.assertTrue(large['provenance']['presentation_block_valid'])
        self.assertEqual(large['post_text'], expected['post_text'])
        duplicate_motion = json.dumps(body, ensure_ascii=False).replace('"bad": "attachment"', '"kind":"process","kind":"review"')
        duplicate = build_presentation({'output': 'Основной сохранённый отчёт.\n<lab_presentation>' + duplicate_motion + '</lab_presentation>'})
        self.assertTrue(duplicate['provenance']['presentation_block_valid'])
        self.assertEqual(duplicate['post_text'], expected['post_text'])


if __name__ == '__main__':
    unittest.main()
