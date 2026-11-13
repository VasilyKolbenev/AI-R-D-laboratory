"""Visual choices are reproducible projections of saved, bounded evidence."""
from copy import deepcopy
import hashlib
import json
import unittest

from laboratory.research_readiness import assess
from laboratory.visual_spec import build_corpus_spec, build_run_spec
from test_research_readiness import fixture


def motion(report):
    return {'version': 'dataflow-v1', 'kind': 'feedback',
        'selection': {'method': 'report_concepts', 'reason': 'TEST_ONLY saved concepts'},
        'baseline': {'status': 'unknown'},
        'evidence': [{'id': 'motion_e1', 'excerpt': report, 'source_url': 'https://example.org/TEST_ONLY'}],
        'nodes': [
            {'id': 'input', 'label': 'TEST_ONLY task', 'role': 'input', 'lane': 'technology', 'evidence_ids': ['motion_e1']},
            {'id': 'memory', 'label': 'TEST_ONLY experience', 'role': 'memory', 'lane': 'technology', 'evidence_ids': ['motion_e1']}],
        'edges': [
            {'id': 'forward', 'from': 'input', 'to': 'memory', 'label': 'TEST_ONLY operation', 'kind': 'data', 'evidence_ids': ['motion_e1']},
            {'id': 'back', 'from': 'memory', 'to': 'input', 'label': 'TEST_ONLY next', 'kind': 'feedback', 'evidence_ids': ['motion_e1']}]}


def corpus():
    # Overlapping topics deliberately sum above 100%; these are paper shares.
    return {'available': True, 'status': 'ready', 'corpus': {
        'id': 'TEST_ONLY_corpus', 'snapshot_id': 'a' * 64, 'title': 'TEST_ONLY corpus',
        'years': [2020, 2021], 'imported_at': '2026-10-01T00:00:00Z',
        'counts': {'papers': 20, 'analytic_papers': 20, 'claims': 30},
        'provenance': {'origin': 'external_extraction', 'license': 'CC-BY-4.0'},
        'reproduction': {'matched': True, 'denominators': [{'year': 2020, 'papers': 10}, {'year': 2021, 'papers': 10}]}},
        'topics': [{'id': number, 'name': 'TEST_ONLY topic ' + str(number), 'is_noise': False,
            'papers': 16, 'claims': 19, 'trajectory': [
                {'year': 2020, 'numerator': 8, 'denominator': 10, 'share': 80},
                {'year': 2021, 'numerator': 8, 'denominator': 10, 'share': 80}]} for number in (1, 2)]}


def block(spec, identifier):
    return next(row for row in spec['blocks'] if row['id'] == identifier)


class VisualSpecTests(unittest.TestCase):
    def test_bound_numeric_comparison_is_primary_and_unknown_stays_distinct_from_zero(self):
        run, presentation = fixture()
        presentation['motion_story'] = motion(run['output'])
        result = build_run_spec(run, presentation, assess(run, presentation))
        self.assertEqual(result['version'], 'visual-spec-v1')
        self.assertEqual(result['primary_block_id'], 'comparison_bars')
        self.assertTrue(block(result, 'process_flow')['selected'])
        bars = block(result, 'comparison_bars')
        self.assertEqual(bars['preferred_engine'], 'G2')
        self.assertEqual(bars['supported_renderer'], 'native_dom_svg')
        self.assertEqual(bars['data']['rows'][0]['candidate']['value'], 8)
        self.assertFalse(bars['provenance']['empirical_technology_validation'])
        self.assertNotIn('confidence', json.dumps(result))
        # An explicitly supported zero is valid; missing values have no bar.
        run['output'] = 'TEST_ONLY baseline latency is 10 ms and candidate latency is 0 ms.'
        presentation['evidence'][0]['excerpt'] = run['output']
        presentation['source_validation']['checks'][0]['quote'] = run['output']
        run['plan']['evidence_bundle']['documents'][0]['segments'][0]['text'] = run['output']
        presentation['applied_analysis']['rows'][0]['candidate']['value'] = 0
        zero = build_run_spec(run, presentation, assess(run, presentation))
        self.assertEqual(block(zero, 'comparison_bars')['data']['rows'][0]['candidate']['value'], 0)
        presentation['applied_analysis']['rows'][0]['candidate']['value'] = None
        unknown = build_run_spec(run, presentation, assess(run, presentation))
        self.assertFalse(block(unknown, 'comparison_bars')['selected'])
        self.assertIsNone(block(unknown, 'comparison_table')['data']['rows'][0]['candidate']['value'])

    def test_bad_source_bindings_and_estimates_do_not_become_bars(self):
        for change in ('no_check', 'bad_quote', 'unread_source', 'estimate', 'not_comparable'):
            with self.subTest(change=change):
                run, presentation = fixture()
                if change == 'no_check':
                    presentation.pop('source_validation')
                elif change == 'bad_quote':
                    presentation['source_validation']['checks'][0]['quote'] = 'TEST_ONLY fabricated 8'
                elif change == 'unread_source':
                    run['plan']['evidence_bundle']['documents'][0]['status'] = 'blocked'
                elif change == 'estimate':
                    presentation['applied_analysis']['rows'][0]['candidate']['basis'] = 'estimate'
                else:
                    presentation['applied_analysis']['rows'][0]['comparability'] = 'unknown'
                result = build_run_spec(run, presentation, assess(run, presentation))
                self.assertFalse(block(result, 'comparison_bars')['available'])
                self.assertEqual(result['primary_block_id'], 'task')
                self.assertEqual(block(result, 'comparison_table')['data']['rows'][0]['candidate']['value'], 8)

    def test_readiness_boolean_is_not_sufficient_for_malformed_values(self):
        run, presentation = fixture()
        ready = assess(run, presentation)
        for value in (None, -1, True, '8', float('nan'), float('inf'), 10 ** 400):
            with self.subTest(value=value):
                data = deepcopy(ready)
                data['comparison_dimensions']['latency']['measurements'][0]['candidate']['value'] = value
                result = build_run_spec(run, presentation, data)
                self.assertFalse(block(result, 'comparison_bars')['selected'])
                json.dumps(result, allow_nan=False)
        ready['run_id'] = 'wrong'
        self.assertEqual(build_run_spec(run, presentation, ready)['primary_block_id'], 'task')

    def test_incomplete_chart_labels_or_units_cannot_select_an_unrenderable_pair(self):
        run, presentation = fixture()
        for key in ('metric', 'unit', 'conditions', 'side_label'):
            ready = assess(run, presentation)
            row = ready['comparison_dimensions']['latency']['measurements'][0]
            if key == 'side_label':
                row['candidate']['label'] = ''
            else:
                row[key] = ''
            self.assertFalse(block(build_run_spec(run, presentation, ready), 'comparison_bars')['selected'])

    def test_planned_incomplete_and_unfinished_runs_suppress_finished_content(self):
        for status, stage in [('planned', 'source_review'), ('running', 'externally_evaluated'),
                              ('completed', 'incomplete')]:
            run, presentation = fixture()
            run['status'] = status
            presentation['motion_story'] = motion(run['output'])
            ready = assess(run, presentation)
            ready['stage'] = stage
            result = build_run_spec(run, presentation, ready)
            self.assertEqual(result['primary_block_id'], 'task')
            self.assertEqual([row['id'] for row in result['blocks'] if row['selected']], ['task'])
            self.assertEqual(block(result, 'comparison_table')['data']['rows'], [])
            self.assertIsNone(block(result, 'process_flow')['data']['graph'])

    def test_saved_concept_graph_remains_illustrative_and_not_a_simulation(self):
        run, presentation = fixture()
        presentation.pop('source_validation')
        presentation['motion_story'] = motion(run['output'])
        result = build_run_spec(run, presentation, assess(run, presentation))
        self.assertEqual(result['primary_block_id'], 'process_flow')
        graph = block(result, 'process_flow')
        self.assertTrue(graph['data']['illustrative'])
        self.assertEqual(graph['provenance']['origin'], 'saved_report')
        choices = {row['kind']: row for row in result['choices']}
        self.assertEqual(choices['custom_simulation']['status'], 'deferred')
        self.assertEqual(choices['custom_simulation']['reason_code'], 'missing_formal_model')
        self.assertIsNone(choices['video']['supported_renderer'])
        self.assertEqual(choices['knowledge_graph']['reason_code'], 'missing_typed_source_bound_edges')
        self.assertEqual(result['read_order'], ['task', 'main_figure', 'comparison', 'applicability', 'evidence'])

    def test_invalid_edges_ids_cycles_and_unsupported_reports_fail_closed(self):
        for corruption in ('version', 'id', 'edge_kind', 'missing_endpoint', 'cycle', 'evidence', 'origin', 'bad_type', 'oversize_nodes', 'oversize_edges'):
            with self.subTest(corruption=corruption):
                run, presentation = fixture()
                presentation.pop('source_validation')
                graph = motion(run['output'])
                if corruption == 'version': graph['version'] = 'workflow-v1'
                elif corruption == 'id': graph['nodes'][1]['id'] = 'input'
                elif corruption == 'edge_kind': graph['edges'][0]['kind'] = 'supports'
                elif corruption == 'missing_endpoint': graph['edges'][0]['to'] = 'nonexistent'
                elif corruption == 'cycle': graph['edges'][1]['kind'] = 'data'
                elif corruption == 'evidence': graph['evidence'][0]['excerpt'] = 'TEST_ONLY absent'
                elif corruption == 'origin': graph['selection']['method'] = 'workflow'
                elif corruption == 'bad_type': graph['edges'][0]['from'] = []
                elif corruption == 'oversize_nodes':
                    graph['nodes'].extend({**graph['nodes'][0], 'id': 'node' + str(index)} for index in range(11))
                else:
                    graph['edges'].extend({**graph['edges'][0], 'id': 'edge' + str(index)} for index in range(15))
                presentation['motion_story'] = graph
                result = build_run_spec(run, presentation, assess(run, presentation))
                self.assertFalse(block(result, 'process_flow')['available'])
                self.assertEqual(result['primary_block_id'], 'task')

    def test_steps_and_memory_do_not_generate_a_graph_or_semantic_relations(self):
        run, presentation = fixture()
        presentation.pop('source_validation')
        presentation['mechanism'] = ['step 1', 'step 2', 'step 3']
        presentation['memory_context'] = {'supports': ['e1'], 'related': ['anything']}
        result = build_run_spec(run, presentation, assess(run, presentation))
        self.assertFalse(block(result, 'process_flow')['selected'])
        self.assertFalse(any(row['kind'] == 'knowledge_graph' for row in result['blocks']))

    def test_exact_input_hashes_are_deterministic_and_inputs_are_not_mutated(self):
        run, presentation = fixture()
        ready = assess(run, presentation)
        sources = [{'url': 'https://example.org/TEST_ONLY'}]
        before = deepcopy((run, presentation, ready, sources))
        first = build_run_spec(run, presentation, ready, sources)
        second = build_run_spec(run, presentation, ready, sources)
        self.assertEqual(first, second)
        self.assertEqual(first['input_binding']['report_sha256'], hashlib.sha256(run['output'].encode()).hexdigest())
        self.assertEqual((run, presentation, ready, sources), before)
        run['updated_at'] = 'TEST_ONLY changed walltime'
        self.assertEqual(first['input_digest'], build_run_spec(run, presentation, ready, sources)['input_digest'])
        for item, key in ((run, 'output'), (presentation, 'problem')):
            original = item.get(key)
            item[key] = 'TEST_ONLY changed input'
            self.assertNotEqual(first['input_digest'], build_run_spec(run, presentation, ready, sources)['input_digest'])
            if original is None: item.pop(key)
            else: item[key] = original
        run['plan']['extra'] = 'TEST_ONLY plan change'
        self.assertNotEqual(first['input_digest'], build_run_spec(run, presentation, ready, sources)['input_digest'])
        first['blocks'][0]['data']['task']['business_goal'] = 'TEST_ONLY mutate output'
        self.assertEqual(presentation, before[1])
        self.assertEqual(ready, before[2])
        self.assertEqual(run['plan']['study_context']['task'], before[0]['plan']['study_context']['task'])


class CorpusVisualSpecTests(unittest.TestCase):
    def test_matched_overlapping_shares_select_lines_without_pie_or_stack(self):
        overview = corpus()
        before = deepcopy(overview)
        result = build_corpus_spec(overview)
        self.assertEqual(result['primary_block_id'], 'trends')
        trends = block(result, 'trends')
        self.assertEqual(trends['data']['unit'], 'percent')
        self.assertEqual(trends['data']['quantity'], 'distinct_paper_share')
        self.assertTrue(trends['data']['overlapping_topics'])
        self.assertEqual(trends['data']['series'][0]['points'][0]['share'], 80)
        for kind in ('pie', 'stacked_share'):
            choice = next(row for row in result['choices'] if row['kind'] == kind)
            self.assertFalse(choice['selected'])
            self.assertEqual(choice['reason_code'], 'overlapping_topics_not_partition')
        self.assertEqual(result, build_corpus_spec(overview))
        self.assertEqual(result, build_corpus_spec({**overview, 'visual_spec': result}))
        self.assertEqual(overview, before)
        overview['corpus']['imported_at'] = 'TEST_ONLY different import walltime'
        self.assertEqual(result['input_digest'], build_corpus_spec(overview)['input_digest'])
        overview['topics'][0]['trajectory'][0]['numerator'] = 7
        self.assertNotEqual(result['input_digest'], build_corpus_spec(overview)['input_digest'])

    def test_absent_unmatched_or_invalid_corpus_never_gets_trends(self):
        cases = [{}, {'available': False, 'status': 'not_imported', 'corpus': None}]
        for corruption in ('available', 'snapshot', 'matched', 'years', 'duplicate', 'denominator',
                           'numerator', 'share', 'negative', 'nonfinite', 'count_bool'):
            overview = corpus()
            if corruption == 'available': overview['available'] = False
            elif corruption == 'snapshot': overview['corpus']['snapshot_id'] = 'invalid'
            elif corruption == 'matched': overview['corpus']['reproduction']['matched'] = False
            elif corruption == 'years': overview['corpus']['years'] = [2021, 2020]
            elif corruption == 'duplicate': overview['topics'][1]['id'] = 1
            elif corruption == 'denominator': overview['topics'][0]['trajectory'][0]['denominator'] = 0
            elif corruption == 'numerator': overview['topics'][0]['trajectory'][0]['numerator'] = 11
            elif corruption == 'share': overview['topics'][0]['trajectory'][0]['share'] = 30
            elif corruption == 'negative': overview['topics'][0]['trajectory'][0]['share'] = -1
            elif corruption == 'nonfinite': overview['topics'][0]['trajectory'][0]['share'] = float('nan')
            else: overview['topics'][0]['trajectory'][0]['numerator'] = True
            cases.append(overview)
        for overview in cases:
            with self.subTest(overview=overview):
                result = build_corpus_spec(overview)
                self.assertFalse(block(result, 'trends')['selected'])
                self.assertEqual(result['primary_block_id'], 'corpus')
                json.dumps(result, allow_nan=False)

    def test_zero_is_a_known_paper_share_and_nonfinite_identity_differs_from_missing(self):
        overview = corpus()
        point = overview['topics'][0]['trajectory'][0]
        point.update(numerator=0, share=0)
        result = build_corpus_spec(overview)
        self.assertTrue(block(result, 'trends')['selected'])
        self.assertEqual(block(result, 'trends')['data']['series'][0]['points'][0]['share'], 0)
        point['share'] = None
        missing = build_corpus_spec(overview)
        point['share'] = float('nan')
        invalid = build_corpus_spec(overview)
        self.assertFalse(block(invalid, 'trends')['selected'])
        self.assertNotEqual(missing['input_digest'], invalid['input_digest'])


if __name__ == '__main__':
    unittest.main()
