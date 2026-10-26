"""TEST_ONLY public seams: compact output, unchanged semantic gates, hash rederive."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from laboratory import compact_editor
from laboratory.applied_analysis import validate_final
from laboratory.presentation import display_report
import test_applied_analysis_v0130 as fixtures


def sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def block(tag, value):
    return '<' + tag + '>' + json.dumps(value, ensure_ascii=False) + '</' + tag + '>'


class CompactEditorTests(unittest.TestCase):
    def fixture(self):
        plan, research, critic, final = fixtures.AppliedAnalysisTests().fixture()
        final['evidence_checks'] = []
        outputs = fixtures.AppliedAnalysisTests().texts(research, critic, final)[:2]
        return plan, outputs, final

    def test_only_packet_becomes_readable_report_and_original_block(self):
        plan, outputs, final = self.fixture()
        raw = block('lab_presentation', final)
        result = compact_editor.assemble(plan, raw)
        self.assertIn('Slow responses', display_report(result))
        self.assertIn(fixtures.EXCERPT, display_report(result))
        self.assertTrue(result.endswith(raw))
        self.assertEqual(validate_final(plan, [*outputs, result])['status'], 'ready')

    def test_raw_packet_is_bounded_strict_and_has_no_duplicate_outputs(self):
        plan, _, final = self.fixture()
        raw = block('lab_presentation', final)
        for bad in ('Prose before\n' + raw, raw + '\nExtra report', raw + raw,
                    raw.replace('"title":', '"title":"duplicate","title":'),
                    raw.replace('"value": 10', '"value": NaN'),
                    ' ' * 16001 + raw):
            with self.subTest(bad=bad[:60]), self.assertRaises(ValueError):
                compact_editor.assemble(plan, bad)
        for field in ('motion', 'post_text', 'english_abstract'):
            bad = deepcopy(final)
            bad[field] = 'not a compact public field'
            with self.subTest(field=field), self.assertRaises(ValueError):
                compact_editor.assemble(plan, block('lab_presentation', bad))

    def test_resolution_excerpt_must_preexist_in_public_narrative(self):
        plan, _, final = self.fixture()
        excerpt = 'TEST_ONLY latency guarantee remains unsupported for other workloads.'
        final['review_dispositions'] = [{'issue_id': 'i1', 'status': 'fixed',
            'reason': 'Removed the unsupported latency guarantee in the public conclusion.',
            'resolution_excerpt': excerpt, 'resolution_evidence_ids': []}]
        with self.assertRaises(ValueError):
            compact_editor.assemble(plan, block('lab_presentation', final))
        final['limitations'].append(excerpt)
        result = compact_editor.assemble(plan, block('lab_presentation', final))
        self.assertEqual(display_report(result).count(excerpt), 1)

    def test_input_keeps_all_structured_issues_and_selected_analogues(self):
        plan, outputs, _ = self.fixture()
        plan['comparison_context']['analogues'] = [
            {'memory_id': 'a' * 32, 'memory_version': 3, 'claim': 'TEST_ONLY prior claim'}]
        critic = {'version': 'critic-review-v1', 'issues': [
            {'id': 'i' + str(index), 'problem': 'TEST_ONLY issue ' + str(index)}
            for index in range(8)]}
        outputs[0] = 'x' * 9000 + outputs[0]
        outputs[1] = block('lab_critic', critic)
        before = deepcopy(plan), list(outputs)
        value = compact_editor.payload(plan, outputs)
        self.assertIn('critic_packet', value)
        self.assertEqual(value['critic_packet'], critic)
        self.assertEqual(value['comparison_context'], plan['comparison_context'])
        self.assertTrue(value['research_prose_excerpt']['truncated'])
        self.assertLessEqual(len(value['research_prose_excerpt']['text']), 6000)
        self.assertEqual((plan, outputs), before)

    def test_assembly_hashes_rederive_and_reject_tampering(self):
        plan, _, final = self.fixture()
        raw = block('lab_presentation', final)
        result = compact_editor.assemble(plan, raw)
        record = compact_editor.assembly_record(raw, result)
        self.assertIn('raw_text', record)
        self.assertEqual(record['raw_text'], raw)
        self.assertEqual(record['raw_sha256'], sha(raw))
        self.assertEqual(record['assembled_sha256'], sha(result))
        self.assertTrue(record['local_assembly'])
        self.assertIsNone(compact_editor.validate_assembly(plan, record))
        for key in ('raw_sha256', 'assembled_sha256'):
            corrupted = {**record, key: '0' * 64}
            with self.subTest(key=key), self.assertRaises(ValueError):
                compact_editor.validate_assembly(plan, corrupted)
        failed = {'version': compact_editor.VERSION, 'status': 'failed',
                  'raw_text': '<lab_presentation>{broken}</lab_presentation>',
                  'raw_sha256': sha('<lab_presentation>{broken}</lab_presentation>'),
                  'error': 'TEST_ONLY malformed packet', 'local_assembly': True}
        self.assertIsNone(compact_editor.validate_assembly(plan, failed))
        failed.update(raw_text=raw, raw_sha256=sha(raw))
        with self.assertRaises(ValueError):
            compact_editor.validate_assembly(plan, failed)

    def test_normal_gate_still_rejects_unbound_number_and_unresolved_blocker(self):
        plan, outputs, final = self.fixture()
        final['applied_analysis']['rows'][0]['baseline']['value'] = 42
        final['findings'] = [fixtures.EXCERPT.replace('10', '42')]
        final['evidence'][0]['excerpt'] = final['findings'][0]
        result = compact_editor.assemble(plan, block('lab_presentation', final))
        gate = validate_final(plan, [*outputs, result])
        self.assertEqual(gate['status'], 'incomplete')
        self.assertIn('число', ' '.join(gate['issues']))
        plan, outputs, final = self.fixture()
        critic = {'version': 'critic-review-v1', 'issues': [{
            'id': 'i1', 'severity': 'blocker', 'target': 'r1',
            'problem': 'Latency guarantee is unsupported', 'evidence_ids': ['r1'],
            'required_change': 'Remove the unsupported latency guarantee'}]}
        outputs[1] = block('lab_critic', critic)
        final['review_dispositions'] = [{'issue_id': 'i1', 'status': 'unresolved',
            'reason': 'TEST_ONLY unresolved latency objection',
            'resolution_excerpt': '', 'resolution_evidence_ids': []}]
        result = compact_editor.assemble(plan, block('lab_presentation', final))
        gate = validate_final(plan, [*outputs, result])
        self.assertEqual(gate['status'], 'incomplete')
        self.assertIn('Блокирующее', ' '.join(gate['issues']))
        final['review_dispositions'] = []
        result = compact_editor.assemble(plan, block('lab_presentation', final))
        self.assertEqual(validate_final(plan, [*outputs, result])['status'], 'incomplete')

    def test_all_selected_analogues_are_required_without_fabricated_public_ids(self):
        from laboratory.research_protocol import comparison_context
        plan, _, final = self.fixture()
        plan['memory']['items'] = [{'id': 'b' * 32, 'version': 2,
                                   'claim': 'TEST_ONLY previous contextual finding'}]
        plan['comparison_context'] = comparison_context(plan)
        with self.assertRaises(ValueError):
            compact_editor.assemble(plan, block('lab_presentation', final))
        final['applied_analysis']['analogues'] = [{
            'memory_id': 'b' * 32, 'memory_version': 2, 'relation': 'context',
            'relevance': 'TEST_ONLY previous method uses source comparison',
            'conditions_difference': 'TEST_ONLY data and hardware differ'}]
        result = compact_editor.assemble(plan, block('lab_presentation', final))
        self.assertNotIn('b' * 32, display_report(result))

    def test_source_binding_gate_still_rejects_forged_original_after_assembly(self):
        from laboratory.core import Store
        from test_grounded_flow_v0140 import grounded, packets
        temporary_root = Path(__file__).parent / '.tmp'
        temporary_root.mkdir(exist_ok=True)
        with TemporaryDirectory(dir=temporary_root) as directory:
            run = grounded(Store(Path(directory) / 'data'))
            outputs = packets(run)
            final = json.loads(outputs[2].split('<lab_presentation>')[1].split('</')[0])
            final['evidence_checks'][0]['quote'] = 'TEST_ONLY forged original quotation'
            assembled = compact_editor.assemble(run['plan'], block('lab_presentation', final))
            gate = validate_final(run['plan'], [*outputs[:2], assembled])
            self.assertEqual(gate['status'], 'incomplete')
            self.assertIn('цитата', ' '.join(gate['issues']).lower())

    def test_sentinel_mutants_are_killed_at_public_seams(self):
        mutations = [
            ('_resolution_narrative', lambda packet, parsed: None,
             'test_resolution_excerpt_must_preexist_in_public_narrative'),
            ('validate_assembly', lambda plan, record: None,
             'test_assembly_hashes_rederive_and_reject_tampering'),
        ]
        for member, mutant, target in mutations:
            result = unittest.TestResult()
            with self.subTest(mutant=member), patch.object(compact_editor, member, mutant):
                CompactEditorTests(target).run(result)
                self.assertFalse(result.wasSuccessful(), 'Mutant survived: ' + member)


if __name__ == '__main__':
    unittest.main()
