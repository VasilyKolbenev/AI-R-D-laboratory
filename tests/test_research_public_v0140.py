"""Public seams: safe projection, exact approval and honest optional English."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from laboratory.research_public import (
    approve, attach_public, parse_public, preview, render_html, validate_asset,
)


def sample():
    return {
        'title': 'TEST_ONLY comparison',
        'summary': 'TEST_ONLY: source analysis without a reproduced experiment.',
        'post_text': 'TEST_ONLY public text.',
        'publication_sources': [{'title': 'Paper', 'url': 'https://example.org/paper'}],
        'story': [{'id': 'takeaway', 'title': 'Result', 'text': 'TEST_ONLY claim'}],
        'memory': {'claim': 'PRIVATE_MEMORY'},
        'agent_review': {'prompt': 'PRIVATE_PROMPT'},
        'raw': {'api_key': 'PRIVATE_KEY'},
        'evidence': [{'id': 'PRIVATE_ID', 'source_url': 'https://example.org/paper'}],
        'publication_checks': {'status': 'ready'},
    }


class PublicProjectionTests(unittest.TestCase):
    def test_separate_exact_approval_and_frozen_version(self):
        from laboratory.core import Store
        temporary_root = Path(__file__).parent / '.tmp'
        temporary_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as directory:
            store = Store(Path(directory) / 'data')
            data = sample()
            result = preview(data)
            for consent, digest in ((False, result['projection_hash']), (True, '0' * 64)):
                with self.assertRaises(ValueError):
                    approve(store, data, digest, consent)
            self.assertEqual(store.assets.list('public_dossier'), [])
            saved = approve(store, data, result['projection_hash'], True)
            self.assertEqual(saved['id'],
                             approve(store, data, result['projection_hash'], True)['id'])
            original_html = render_html(saved['payload'])
            data['summary'] = 'TEST_ONLY changed public conclusion'
            changed = preview(data)
            newer = approve(store, data, changed['projection_hash'], True)
            self.assertNotEqual(newer['id'], saved['id'])
            self.assertEqual(render_html(store.assets.get(saved['id'])['payload']), original_html)

    def test_nested_private_fields_never_enter_payload_or_html(self):
        data = sample()
        data['story'][0]['prompt'] = 'PRIVATE_STORY'
        data['publication_sources'][0]['asset_id'] = 'PRIVATE_ASSET'
        result = preview(data)
        self.assertEqual(result['payload']['version'], 'public-dossier-v1')
        self.assertEqual(len(result['projection_hash']), 64)
        text = str(result['payload']) + render_html(result['payload'])
        for marker in ('PRIVATE_MEMORY', 'PRIVATE_PROMPT', 'PRIVATE_KEY',
                       'PRIVATE_STORY', 'PRIVATE_ASSET', 'PRIVATE_ID'):
            self.assertNotIn(marker, text)
        changed = deepcopy(data)
        changed['memory'] = {'claim': 'different private memory'}
        self.assertEqual(preview(changed)['projection_hash'], result['projection_hash'])

    def test_html_escapes_model_markup_and_rejects_tampered_asset(self):
        data = sample()
        data['title'] = '<img src=x onerror=alert(1)>'
        result = preview(data)
        html = render_html(result['payload'])
        self.assertIn('&lt;img', html)
        self.assertNotIn('<img src=x', html)
        self.assertNotIn('<script', html)
        bad = deepcopy(result['payload'])
        bad['memory'] = {'claim': 'PRIVATE_LEAK'}
        with self.assertRaises(ValueError):
            validate_asset('public_dossier', bad)
        with self.assertRaises(ValueError):
            render_html(bad)

    def test_actual_english_only_and_bound_source_refs(self):
        text = ('<lab_public>{"version":"public-addendum-v1",'
                '"english_abstract":{"language":"en","text":'
                '"This source analysis describes a retrieval method and its limits. '
                'The available evidence does not establish an independent gain."},'
                '"evidence_story":{"focus":"disagreement","summary":'
                '"TEST_ONLY incompatible conditions","limitations":["No reproduction"],'
                '"source_refs":["https://example.org/paper"]}}</lab_public>')
        self.assertEqual(parse_public(text)['english_abstract']['language'], 'en')
        attached = attach_public(sample(), text)
        self.assertIn('english_abstract', preview(attached)['payload'])
        russian = text.replace('This source analysis describes a retrieval method and its limits. '
                               'The available evidence does not establish an independent gain.',
                               'Это русское описание результата, а не перевод на английский язык.')
        self.assertNotIn('english_abstract', parse_public(russian))
        forged = text.replace('https://example.org/paper', 'https://example.org/other')
        self.assertEqual(attach_public(sample(), forged)['evidence_story']['source_refs'], [])
        self.assertEqual(parse_public('<lab_public>{bad}</lab_public>'), {})

    def test_public_addendum_cannot_introduce_numbers_absent_from_ordinary_report(self):
        import json
        addendum = {'version': 'public-addendum-v1', 'english_abstract': {
            'language': 'en', 'text': 'This source analysis describes a retrieval method '
            'and its limits. The new method is 99 percent faster under the same conditions.'},
            'evidence_story': {'focus': 'comparison', 'summary': 'TEST_ONLY 99 percent gain',
                               'limitations': [], 'source_refs': []}}
        output = 'TEST_ONLY ordinary report: no measured speedup.\n<lab_public>'
        output += json.dumps(addendum) + '</lab_public>'
        attached = attach_public(sample(), output)
        self.assertNotIn('english_abstract', attached)
        self.assertNotIn('evidence_story', attached)
        valid = attach_public(sample(), output.replace('no measured speedup',
                                                       'author claim: 99 percent gain'))
        self.assertIn('english_abstract', valid)

    def test_missing_numbers_stay_null_and_private_source_urls_are_omitted(self):
        data = sample()
        data['publication_sources'].append({'title': 'local', 'url': 'http://127.0.0.1/x'})
        data['applied_analysis'] = {'rows': [{
            'metric': 'p95', 'unit': 'ms', 'conditions': 'unknown',
            'comparability': 'unknown', 'baseline': {'label': 'old', 'value': None},
            'candidate': {'label': 'new', 'value': None, 'memory_id': 'PRIVATE_ID'},
        }]}
        result = preview(data)['payload']
        self.assertIsNone(result['applied_analysis']['rows'][0]['candidate']['value'])
        self.assertNotIn('127.0.0.1', str(result))
        self.assertNotIn('PRIVATE_ID', str(result))


if __name__ == '__main__':
    unittest.main()
