import copy
import hashlib
import json
import unittest

from laboratory.applied_analysis import validate_final, validate_phase
from laboratory.presentation import build_presentation, display_report
from laboratory.research_protocol import build_protocol, comparison_context


URL = 'https://example.org/paper'
EXCERPT = 'Latency is 10 ms for baseline and 8 ms for candidate.'


def block(tag, value):
    return '<' + tag + '>' + json.dumps(value, ensure_ascii=False) + '</' + tag + '>'


class AppliedAnalysisTests(unittest.TestCase):
    def fixture(self):
        plan = {'question': 'Compare source evidence', 'timeout_seconds': 240, 'web_search': False,
                'sources': [{'id': 'a' * 32, 'title': 'Paper', 'url': URL, 'text': EXCERPT}],
                'memory': {'enabled': True, 'items': []}, 'study_context': {'task': {}}}
        plan['comparison_context'] = comparison_context(plan)
        plan['research_protocol'] = build_protocol(plan)
        researcher = {'version': 'research-packet-v1', 'claims': [
            {'id': 'r1', 'claim': EXCERPT, 'source_ids': ['a' * 32], 'source_urls': [URL]}],
            'metric_ids': [], 'analogue_ids': []}
        critic = {'version': 'critic-review-v1', 'issues': []}
        final = {'title': 'Latency under stated conditions', 'problem': 'Slow responses',
                 'audience': 'Builders', 'use_case': 'Source comparison',
                 'mechanism': ['Read inputs', 'Apply method', 'Return result'],
                 'findings': [EXCERPT], 'limitations': ['Single dataset'],
                 'resources': ['Hardware unknown'], 'public_takeaway': 'Check the dataset before choosing',
                 'next_step': 'Choose a workload', 'evidence': [
                     {'id': 'e1', 'claim': 'Reported latency', 'source_url': URL,
                      'locator': 'Table one', 'excerpt': EXCERPT, 'limitations': 'Author data, not reproduced'}],
                 'comparisons': [], 'review_dispositions': [],
                 'applied_analysis': {'version': 'applied-comparison-v1', 'rows': [
                     {'id': 'm1', 'metric': 'Latency', 'definition': 'Time per request', 'unit': 'ms', 'direction': 'minimize',
                      'baseline': {'label': 'Baseline', 'value': 10, 'basis': 'author_claim', 'evidence_ids': ['e1']},
                      'candidate': {'label': 'Candidate', 'value': 8, 'basis': 'author_claim', 'evidence_ids': ['e1']},
                      'conditions': 'Same model version, evaluation dataset and workload; author results',
                      'comparability': 'comparable', 'comparability_reason': 'Same reported task and protocol'}],
                     'analogues': [], 'unknowns': ['Hardware requirements for deployment']}}
        return plan, researcher, critic, final

    def texts(self, researcher, critic, final, prose=None):
        prose = prose or EXCERPT + '\n' + URL
        return [EXCERPT + '\n' + URL + '\n' + block('lab_research', researcher),
                block('lab_critic', critic), prose + '\n' + block('lab_presentation', final)]

    def record(self, plan, texts):
        summary = validate_final(plan, texts)
        return {'id': 'f' * 32, 'plan': plan, 'output': texts[-1], 'links': [],
                'agent_review': summary, 'agent_pipeline': {'status': 'completed', 'dispatched_calls': 3, 'phases': [
                    {'index': index, 'role': role, 'status': 'completed',
                     'dispatched': True,
                     'output_sha256': hashlib.sha256(text.encode()).hexdigest()}
                    for index, (role, text) in enumerate(zip(['researcher', 'critic', 'reviewer'], texts))]}}

    def test_valid_three_packets_derive_only_supported_chart(self):
        plan, researcher, critic, final = self.fixture()
        texts = self.texts(researcher, critic, final)
        result = validate_final(plan, texts)
        self.assertEqual(result['status'], 'ready', result['issues'])
        self.assertEqual(result['comparisons'][0]['baseline_value'], 10)
        self.assertEqual(len(result['phase_output_sha256s']), 3)
        self.assertIn('не независимая', result['notice'])
        data = build_presentation(self.record(plan, texts))
        self.assertEqual(data['publication_checks']['status'], 'ready', data['publication_checks'])
        self.assertEqual(data['comparisons'][0]['result_value'], 8)
        self.assertEqual(data['applied_analysis']['rows'][0]['direction'], 'minimize')

    def test_unknown_incompatible_and_estimated_values_are_table_only(self):
        for kind in ('unknown', 'estimate', 'not_comparable'):
            plan, researcher, critic, final = self.fixture()
            row = final['applied_analysis']['rows'][0]
            if kind == 'unknown':
                row['baseline'].update(value=None, basis='unknown', evidence_ids=[])
                row['comparability'] = 'unknown'
            elif kind == 'estimate':
                row['candidate']['basis'] = 'estimate'
            else:
                row['comparability'] = 'not_comparable'
            result = validate_final(plan, self.texts(researcher, critic, final))
            self.assertEqual(result['status'], 'ready', result['issues'])
            self.assertEqual(result['comparisons'], [])
            self.assertEqual(len(result['applied_analysis']['rows']), 1)

    def test_invented_number_boolean_and_unknown_evidence_are_rejected(self):
        for change in ({'value': 11}, {'value': True}, {'value': float('nan')}, {'evidence_ids': ['missing']}, {'basis': 'unknown'}):
            plan, researcher, critic, final = self.fixture()
            final['applied_analysis']['rows'][0]['baseline'].update(change)
            self.assertEqual(validate_final(plan, self.texts(researcher, critic, final))['status'], 'incomplete')

    def test_incompatible_rows_cannot_smuggle_an_existing_format_chart(self):
        plan, researcher, critic, final = self.fixture()
        final['applied_analysis']['rows'][0]['comparability'] = 'not_comparable'
        final['comparisons'] = [{'label': 'Latency', 'unit': 'ms', 'baseline_label': 'Baseline',
                                'baseline_value': 10, 'result_label': 'Candidate', 'result_value': 8,
                                'conditions': final['applied_analysis']['rows'][0]['conditions'], 'evidence_ids': ['e1']}]
        result = validate_final(plan, self.texts(researcher, critic, final))
        self.assertEqual(result['status'], 'incomplete')
        self.assertIn('График', result['issues'][0])

    def test_source_cannot_first_appear_in_final_editor_pass(self):
        plan, researcher, critic, final = self.fixture()
        final['evidence'][0]['source_url'] = 'https://example.org/new-source'
        result = validate_final(plan, self.texts(researcher, critic, final,
                                EXCERPT + '\nhttps://example.org/new-source'))
        self.assertEqual(result['status'], 'incomplete')
        self.assertIn('добавил источник', result['issues'][0])

    def test_editor_cannot_create_a_new_number_by_repeating_it_in_final_excerpt(self):
        plan, researcher, critic, final = self.fixture()
        invented = 'Latency is 42 ms for baseline and 8 ms for candidate.'
        final['evidence'][0]['excerpt'] = invented
        final['applied_analysis']['rows'][0]['baseline']['value'] = 42
        result = validate_final(plan, self.texts(researcher, critic, final, invented + '\n' + URL))
        self.assertEqual(result['status'], 'incomplete')
        self.assertIn('добавил число', result['issues'][0])

    def test_offline_multiple_source_refs_cannot_transfer_numbers_to_wrong_url(self):
        plan, researcher, critic, final = self.fixture()
        second_url = 'https://example.org/baseline-only'
        plan['sources'].append({'id': 'b' * 32, 'title': 'Baseline only',
                                'url': second_url, 'text': 'Baseline latency is 10 ms; candidate latency is unknown.'})
        researcher['claims'][0]['source_ids'] = ['a' * 32, 'b' * 32]
        researcher['claims'][0]['source_urls'] = [second_url]
        final['evidence'][0]['source_url'] = second_url
        texts = self.texts(researcher, critic, final, EXCERPT + '\n' + second_url)
        texts[0] = texts[0].replace('\n<lab_research>', '\n' + second_url + '\n<lab_research>')
        result = validate_final(plan, texts)
        self.assertEqual(result['status'], 'incomplete')
        self.assertIn('добавил число', result['issues'][0])

    def test_critic_independent_check_is_bounded_and_requires_web_permission(self):
        plan, researcher, critic, final = self.fixture()
        checked_url = 'https://example.org/independent'
        checked = {'id': 'c1', 'source_url': checked_url, 'locator': 'Table two',
                   'excerpt': EXCERPT, 'claim': 'Same latency independently reported', 'limitations': 'One dataset'}
        critic['checked_sources'] = [checked]
        final['evidence'][0]['source_url'] = checked_url
        texts = self.texts(researcher, critic, final, EXCERPT + '\n' + checked_url)
        texts[1] = EXCERPT + '\n' + checked_url + '\n' + texts[1]
        self.assertEqual(validate_phase(plan, 1, texts[:2])['status'], 'incomplete')
        plan['web_search'] = True
        result = validate_final(plan, texts)
        self.assertEqual(result['status'], 'ready', result['issues'])
        critic['checked_sources'] = [dict(checked, id='c' + str(index)) for index in range(3)]
        texts[1] = EXCERPT + '\n' + checked_url + '\n' + block('lab_critic', critic)
        self.assertEqual(validate_phase(plan, 1, texts[:2])['status'], 'incomplete')

    def test_analogue_must_be_exact_selected_revision_and_all_choices_accounted(self):
        plan, researcher, critic, final = self.fixture()
        plan['memory']['items'] = [{'id': 'c' * 32, 'version': 2, 'title': 'Earlier', 'claim': 'Past context'}]
        plan['comparison_context'] = comparison_context(plan)
        researcher['analogue_ids'] = ['c' * 32]
        final['applied_analysis']['analogues'] = [{'memory_id': 'c' * 32, 'memory_version': 2,
            'relation': 'context', 'relevance': 'Similar topic', 'conditions_difference': 'Different dataset'}]
        self.assertEqual(validate_final(plan, self.texts(researcher, critic, final))['status'], 'ready')
        final['applied_analysis']['analogues'][0]['memory_version'] = 3
        self.assertEqual(validate_final(plan, self.texts(researcher, critic, final))['status'], 'incomplete')
        final['applied_analysis']['analogues'] = []
        self.assertEqual(validate_final(plan, self.texts(researcher, critic, final))['status'], 'incomplete')

    def test_invalid_phase_packets_stop_before_a_successor(self):
        plan, researcher, critic, final = self.fixture()
        texts = self.texts(researcher, critic, final)
        self.assertEqual(validate_phase(plan, 0, texts[:1])['status'], 'ready')
        self.assertEqual(validate_phase(plan, 1, texts[:2])['status'], 'ready')
        researcher['claims'][0]['source_ids'] = ['unknown']
        self.assertEqual(validate_phase(plan, 0, self.texts(researcher, critic, final)[:1])['status'], 'incomplete')
        plan, researcher, critic, final = self.fixture()
        critic['issues'] = [self.issue(evidence_ids=['unknown'])]
        self.assertEqual(validate_phase(plan, 1, self.texts(researcher, critic, final)[:2])['status'], 'incomplete')
        self.assertEqual(validate_phase(plan, 0, ['<lab_research>{broken'])['status'], 'incomplete')

    def issue(self, **changes):
        row = {'id': 'i1', 'severity': 'blocker', 'target': 'r1',
               'problem': 'Latency claim lacks comparable conditions', 'evidence_ids': ['r1'],
               'required_change': 'Remove unsupported latency claim and explain conditions'}
        row.update(changes)
        return row

    def test_every_critic_issue_requires_one_disposition(self):
        plan, researcher, critic, final = self.fixture()
        critic['issues'] = [self.issue(severity='minor')]
        self.assertEqual(validate_final(plan, self.texts(researcher, critic, final))['status'], 'incomplete')
        final['review_dispositions'] = [{'issue_id': 'i1', 'status': 'retained_with_limit', 'reason': 'Explicit condition retained'}]
        self.assertEqual(validate_final(plan, self.texts(researcher, critic, final))['status'], 'ready')
        final['review_dispositions'].append(copy.deepcopy(final['review_dispositions'][0]))
        self.assertEqual(validate_final(plan, self.texts(researcher, critic, final))['status'], 'incomplete')

    def test_blocker_cannot_be_waived_or_ticked_fixed_without_change(self):
        for disposition in ({'status': 'unresolved', 'reason': 'Needs verification'},
                            {'status': 'fixed', 'reason': 'Fixed'},
                            {'status': 'fixed', 'reason': 'Latency conditions corrected in the final report',
                             'resolution_excerpt': EXCERPT}):
            plan, researcher, critic, final = self.fixture()
            critic['issues'] = [self.issue()]
            final['review_dispositions'] = [{'issue_id': 'i1', **disposition}]
            result = validate_final(plan, self.texts(researcher, critic, final))
            self.assertEqual(result['status'], 'incomplete', result)

    def test_removed_blocking_claim_requires_a_concrete_visible_resolution(self):
        plan, researcher, critic, final = self.fixture()
        unsupported = 'Universal latency improvement is guaranteed under every workload.'
        researcher['claims'].append({'id': 'r2', 'claim': unsupported, 'source_ids': ['a' * 32], 'source_urls': [URL]})
        critic['issues'] = [self.issue(target='r2', evidence_ids=['r2'])]
        resolution = 'Universal latency improvement remains unknown under other workload conditions.'
        final['review_dispositions'] = [{'issue_id': 'i1', 'status': 'fixed',
            'reason': 'Removed the unsupported universal latency guarantee and stated workload conditions.',
            'resolution_excerpt': resolution}]
        result = validate_final(plan, self.texts(researcher, critic, final, EXCERPT + '\n' + resolution + '\n' + URL))
        self.assertEqual(result['status'], 'ready', result['issues'])

    def test_missing_pipeline_or_hash_mismatch_blocks_publication_after_manual_overlay(self):
        plan, researcher, critic, final = self.fixture()
        texts = self.texts(researcher, critic, final)
        review = {'editorial': {key: final[key] for key in ('title', 'problem', 'audience', 'use_case',
                  'mechanism', 'findings', 'limitations', 'resources', 'public_takeaway', 'next_step')}}
        for mutation in ('no_summary', 'missing_phase', 'hash', 'upstream_hash', 'not_dispatched'):
            run = self.record(plan, texts)
            if mutation == 'no_summary':
                run.pop('agent_review')
            elif mutation == 'missing_phase':
                run['agent_pipeline']['phases'].pop()
            elif mutation == 'hash':
                run['output'] += '\nChanged'
            elif mutation == 'upstream_hash':
                run['agent_pipeline']['phases'][0]['output_sha256'] = '0' * 64
            else:
                run['agent_pipeline']['phases'][0]['dispatched'] = False
            data = build_presentation(run, review)
            self.assertEqual(data['publication_checks']['status'], 'incomplete', mutation)
            self.assertEqual(data['comparisons'], [], mutation)

    def test_machine_blocks_are_never_public_report_text(self):
        self.assertEqual(display_report('Text\n<lab_research>{broken'), 'Text')
        self.assertEqual(display_report('Text\n' + block('lab_critic', {'issues': []})), 'Text')


if __name__ == '__main__':
    unittest.main()
