import copy
import base64
import hashlib
import io
import json
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


class MemoryAssets:
    def __init__(self):
        self.rows = {}

    def put(self, kind, payload):
        value = {'kind': kind, 'payload': payload}
        raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        identifier = hashlib.sha256(raw.encode()).hexdigest()
        self.rows.setdefault(identifier, {'id': identifier, **copy.deepcopy(value),
                                          'created_at': '2026-10-23T00:00:00+00:00'})
        return copy.deepcopy(self.rows[identifier])

    def get(self, identifier):
        if identifier not in self.rows:
            raise ValueError('Unknown asset')
        return copy.deepcopy(self.rows[identifier])

    def list(self, kind=None, limit=100):
        rows = [row for row in self.rows.values() if kind is None or row['kind'] == kind]
        return copy.deepcopy(rows[-limit:][::-1])


class MemoryStore:
    def __init__(self):
        self.assets = MemoryAssets()


class EvidenceArchiveTests(unittest.TestCase):
    def source(self, **changes):
        row = {'id': 'a' * 32, 'title': 'Source', 'url': 'https://example.org/paper',
               'text': 'Baseline latency 12 ms; candidate latency 8 ms.',
               'content_hash': 'b' * 64}
        row.update(changes)
        return row

    def test_supplied_capture_preserves_actual_bytes_without_network(self):
        from laboratory.evidence_archive import Archive
        store = MemoryStore(); archive = Archive(store); source = self.source()
        original = copy.deepcopy(source)
        captured = archive.capture(source)
        self.assertEqual(captured['kind'], 'source_capture')
        self.assertEqual(captured['payload']['origin'], 'supplied')
        self.assertEqual(captured['payload']['sha256'],
                         hashlib.sha256(source['text'].encode()).hexdigest())
        self.assertEqual(archive.get(captured['id']), captured)
        self.assertEqual(source, original)
        self.assertEqual(archive.capture(source)['id'], captured['id'])

    def test_bundle_uses_immutable_documents_without_raw_bytes(self):
        from laboratory.evidence_archive import Archive
        bundle = Archive(MemoryStore()).prepare([self.source()])
        self.assertEqual(bundle['version'], 'source-bundle-v1')
        row = bundle['documents'][0]
        self.assertEqual(row['asset_id'], row['document_id'])
        self.assertEqual(row['status'], 'captured')
        self.assertTrue(row['segments'][0]['text'])
        self.assertNotIn('raw_b64', json.dumps(bundle))

    def test_html_bytes_tables_and_cache_refresh_are_separate_immutable_captures(self):
        from laboratory.evidence_archive import Archive
        archive = Archive(MemoryStore())
        html = (b'<script>DO_NOT_QUOTE</script><p>Baseline</p>'
                b'<table><tr><th>Method</th><th>Latency</th></tr>'
                b'<tr><td>Candidate</td><td>8 ms</td></tr></table>')
        with patch('laboratory.evidence_archive.pinned_fetch',
                   return_value={'raw': html, 'content_type': 'text/html'}) as fetch:
            first = archive.capture(self.source(), fetch=True)
            cached = archive.capture(self.source(), fetch=True)
            self.assertEqual(first['id'], cached['id'])
            fetch.assert_called_once()
            self.assertEqual(base64.b64decode(first['payload']['raw_b64']), html)
            texts = [row['text'] for row in first['payload']['segments']]
            self.assertTrue(any('Candidate | 8 ms' in text for text in texts))
            self.assertNotIn('DO_NOT_QUOTE', ' '.join(texts))
            fetch.return_value = {'raw': b'<p>Changed 9 ms</p>', 'content_type': 'text/html'}
            refreshed = archive.capture(self.source(), fetch=True, refresh=True)
            self.assertNotEqual(first['id'], refreshed['id'])
            self.assertEqual(refreshed['payload']['previous_asset_id'], first['id'])
            self.assertTrue(archive.list()[0]['source_changed'])
            self.assertEqual(archive.get(first['id']), first)

    def test_prepare_fetches_at_most_two_urls_and_preserves_supplied_text(self):
        from laboratory.evidence_archive import Archive
        archive = Archive(MemoryStore())
        sources = [self.source(id=format(index, '032x'),
                               url='https://example.org/' + str(index)) for index in range(3)]
        with patch('laboratory.evidence_archive.pinned_fetch',
                   return_value={'raw': b'<p>Original 8</p>',
                                 'content_type': 'text/html'}) as fetch:
            bundle = archive.prepare(sources, fetch=True)
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(len(bundle['documents']), 5)
            self.assertEqual({row['origin'] for row in bundle['documents']},
                             {'supplied', 'fetched'})
            self.assertTrue(any('двух загрузок' in text for text in bundle['limitations']))
            archive.prepare(sources[:2], fetch=True)
            self.assertEqual(fetch.call_count, 2)

    def test_failures_never_become_quotes_and_unsafe_urls_never_dispatch(self):
        from laboratory.evidence_archive import Archive
        archive = Archive(MemoryStore())
        with patch('laboratory.evidence_archive.pinned_fetch') as fetch:
            blocked = archive.capture(self.source(url='http://127.0.0.1/'), fetch=True)
            self.assertEqual(blocked['payload']['status'], 'blocked')
            fetch.assert_not_called()
            failed_source = self.source(url='https://example.org/unavailable')
            fetch.side_effect = TimeoutError('fixture')
            failed = archive.capture(failed_source, fetch=True)
            self.assertEqual(failed['payload']['status'], 'failed')
            self.assertEqual(failed['payload']['segments'], [])
            archive.capture(failed_source, fetch=True)
            self.assertEqual(fetch.call_count, 1)

    def test_local_validation_detects_corruption_without_fetch_or_parser(self):
        from laboratory.evidence_archive import Archive, validate_asset
        store = MemoryStore(); archive = Archive(store)
        captured = archive.capture(self.source())
        with patch('laboratory.evidence_archive.pinned_fetch') as fetch, patch(
                'laboratory.evidence_archive._extract') as extract:
            validate_asset('source_capture', captured['payload'])
            fetch.assert_not_called(); extract.assert_not_called()
        store.assets.rows[captured['id']]['payload']['raw_b64'] = 'Zm9yZ2Vk'
        with self.assertRaises(ValueError):
            archive.get(captured['id'])

    def test_bundle_rejects_raw_bytes_and_discloses_projection_bounds(self):
        from laboratory.evidence_archive import Archive, validate_bundle
        text = '\n'.join(['x' * 3000] * 10)
        bundle = Archive(MemoryStore()).prepare([self.source(text=text)])
        row = bundle['documents'][0]
        self.assertEqual(row['status'], 'partial')
        self.assertLessEqual(sum(len(part['text']) for part in row['segments']), 6000)
        row['raw_b64'] = 'private bytes'
        with self.assertRaises(ValueError):
            validate_bundle(bundle)

    def github_html(self):
        navigation = ['TEST_ONLY navigation ' + str(index) + ' ' + 'x' * 160
                      for index in range(60)]
        html = ('<html><nav>' + ''.join('<div>' + text + '</div>' for text in navigation)
                + '</nav><article class="markdown-body entry-content container-lg" '
                'itemprop="text"><h1>TEST_ONLY GEMM README</h1>'
                '<p>TEST_ONLY synthetic author-reported comparison.</p>'
                '<script>TEST_ONLY executable text must be excluded</script>'
                '<table><tr><th>Kernel</th><th>Baseline TFLOPS</th>'
                '<th>Candidate TFLOPS</th></tr><tr><td>TEST_ONLY GEMM</td>'
                '<td>118.39</td><td>157.41</td></tr></table></article>'
                '<footer><p>TEST_ONLY footer must be excluded</p></footer></html>')
        return html.encode(), navigation

    def legacy_github_capture(self, archive, source, raw, navigation):
        # Frozen v1 fixture: expected segments are explicit, never regenerated by v2.
        payload = {'version': 'source-capture-v1', 'source_id': source['id'],
                   'source_content_hash': source['content_hash'], 'url': source['url'],
                   'kind': 'fetched_html', 'status': 'partial', 'origin': 'fetched',
                   'retrieved_at': '2026-10-23T00:00:00+00:00',
                   'content_type': 'text/html', 'parser_version': 'inert-extract-v1',
                   'sha256': hashlib.sha256(raw).hexdigest(),
                   'raw_b64': base64.b64encode(raw).decode(),
                   'segments': [{'id': 's' + str(index + 1),
                                 'locator': 'html:block:' + str(index + 1), 'text': text}
                                for index, text in enumerate(navigation[:48])],
                   'limitations': [
                       'Достигнута граница страниц/сегментов/текста; показана часть.'],
                   'previous_asset_id': None}
        return archive.assets.put('source_capture', payload)

    def test_github_readme_table_survives_navigation_and_bounded_bundle(self):
        from laboratory.evidence_archive import Archive, validate_bundle
        archive = Archive(MemoryStore())
        source = self.source(url='https://github.com/TEST_ONLY/repository')
        raw, _ = self.github_html()
        with patch('laboratory.evidence_archive.pinned_fetch', return_value={
                'raw': raw, 'content_type': 'text/html'}) as fetch:
            bundle = archive.prepare([source], fetch=True)
        fetch.assert_called_once_with(source['url'])
        fetched = next(row for row in bundle['documents'] if row['origin'] == 'fetched')
        capture = archive.get(fetched['asset_id'])['payload']
        self.assertEqual(capture['parser_version'], 'inert-extract-v2')
        self.assertEqual(base64.b64decode(capture['raw_b64']), raw)
        self.assertEqual(fetched['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(fetched['url'], source['url'])
        texts = ' '.join(row['text'] for row in fetched['segments'])
        self.assertIn('TEST_ONLY GEMM | 118.39 | 157.41', texts)
        self.assertNotIn('navigation', texts)
        self.assertNotIn('executable', texts)
        self.assertNotIn('footer', texts)
        self.assertLessEqual(len(texts), 6000)
        self.assertTrue(any(row['locator'].startswith('github:readme:html:table:')
                            for row in fetched['segments']))
        validate_bundle(bundle, [source])

    def test_github_selector_is_scoped_and_missing_readme_discloses_fallback(self):
        from laboratory.evidence_archive import Archive
        raw, _ = self.github_html()
        archive = Archive(MemoryStore())
        for url in ('https://example.org/TEST_ONLY/repository',
                    'https://github.com/TEST_ONLY/repository/issues/1'):
            with self.subTest(url=url), patch('laboratory.evidence_archive.pinned_fetch',
                    return_value={'raw': raw, 'content_type': 'text/html'}):
                captured = archive.capture(self.source(url=url), fetch=True)
            texts = ' '.join(row['text'] for row in captured['payload']['segments'])
            self.assertIn('navigation', texts)
            self.assertNotIn('118.39', texts)
        with patch('laboratory.evidence_archive.pinned_fetch', return_value={
                'raw': b'<p>TEST_ONLY missing README</p>', 'content_type': 'text/html'}):
            captured = archive.capture(self.source(
                url='https://github.com/TEST_ONLY/without-readme'), fetch=True)
        self.assertEqual(captured['payload']['segments'][0]['text'],
                         'TEST_ONLY missing README')
        self.assertTrue(any('не найден' in note for note in captured['payload']['limitations']))

    def test_new_prepare_reprojects_cache_but_v1_plan_and_backup_remain_frozen(self):
        from laboratory.core import Store
        from laboratory.evidence_archive import Archive, _extract_versioned, validate_bundle
        raw, navigation = self.github_html()
        with TemporaryDirectory() as folder:
            store = Store(folder)
            store.update_settings({'research_mode': 'reviewed', 'timeout_seconds': 240,
                                   'source_grounding': True, 'capture_originals': True})
            source, _ = store.add_source('TEST_ONLY supplied context', 'TEST_ONLY GitHub',
                                        'https://github.com/TEST_ONLY/repository')
            archive = Archive(store)
            legacy = self.legacy_github_capture(archive, source, raw, navigation)
            self.assertEqual(_extract_versioned(raw, 'fetched_html', 'text/html',
                             'inert-extract-v1', source['url']),
                             (legacy['payload']['segments'], 'partial',
                              legacy['payload']['limitations']))
            with patch('laboratory.evidence_archive.pinned_fetch') as fetch, patch.object(
                    Archive, '_reproject_cached', side_effect=lambda asset: asset):
                self.assertEqual(archive.capture(source, fetch=True), legacy)
                # Simulate the old prepare behavior to freeze a historical v1 plan.
                run = store.create_plan({'source_ids': [source['id']],
                                         'question': 'TEST_ONLY preserve old evidence'})
                fetch.assert_not_called()
            frozen = copy.deepcopy(run['plan'])
            old_document = next(row for row in frozen['evidence_bundle']['documents']
                                if row['origin'] == 'fetched')
            self.assertEqual(old_document['asset_id'], legacy['id'])
            self.assertEqual(old_document['parser_version'], 'inert-extract-v1')
            self.assertNotIn('118.39', json.dumps(old_document))
            with patch('laboratory.evidence_archive.pinned_fetch') as fetch:
                new_run = store.create_plan({'source_ids': [source['id']],
                                             'question': 'TEST_ONLY new README projection'})
                fetch.assert_not_called()
            new_document = next(row for row in new_run['plan']['evidence_bundle']['documents']
                                if row['origin'] == 'fetched')
            refreshed = archive.get(new_document['asset_id'])
            self.assertNotEqual(refreshed['id'], legacy['id'])
            self.assertEqual(refreshed['payload']['previous_asset_id'], legacy['id'])
            for key in ('raw_b64', 'sha256', 'url', 'origin', 'retrieved_at',
                        'source_id', 'source_content_hash', 'content_type'):
                self.assertEqual(refreshed['payload'][key], legacy['payload'][key], key)
            self.assertEqual(refreshed['payload']['parser_version'], 'inert-extract-v2')
            self.assertIn('118.39 | 157.41', json.dumps(new_document))
            self.assertFalse(new_document['source_changed'])
            self.assertTrue(any('без HTTP' in note for note
                                in refreshed['payload']['limitations']))
            self.assertEqual(archive.get(legacy['id']), legacy)
            self.assertEqual(store.run(run['id'])['plan'], frozen)
            validate_bundle(frozen['evidence_bundle'], frozen['sources'])
            with patch('laboratory.evidence_archive.pinned_fetch') as fetch, patch(
                    'laboratory.evidence_archive._extract_versioned') as versioned:
                reused = archive.prepare([source], fetch=True)
                fetch.assert_not_called(); versioned.assert_not_called()
            self.assertEqual(next(row['asset_id'] for row in reused['documents']
                                  if row['origin'] == 'fetched'), refreshed['id'])
            restored = Store(Path(folder) / 'restored')
            with patch('laboratory.evidence_archive.pinned_fetch') as fetch, patch(
                    'laboratory.evidence_archive._extract') as extract, patch(
                    'laboratory.evidence_archive._extract_versioned') as versioned:
                restored.restore(store.export())
                fetch.assert_not_called(); extract.assert_not_called()
                versioned.assert_not_called()
            self.assertEqual(Archive(restored).get(legacy['id']), legacy)
            self.assertEqual(Archive(restored).get(refreshed['id']), refreshed)
            self.assertEqual(restored.run(run['id'])['plan'], frozen)
            self.assertEqual(restored.run(new_run['id'])['plan'], new_run['plan'])

    def test_prepare_keeps_v1_cache_without_a_scoped_readme_article(self):
        from laboratory.evidence_archive import Archive
        raw, navigation = self.github_html()
        no_article = ''.join('<div>' + text + '</div>' for text in navigation).encode()
        cases = [('https://example.org/TEST_ONLY/repository', raw),
                 ('https://github.com/TEST_ONLY/repository/issues/1', raw),
                 ('https://github.com/TEST_ONLY/without-readme', no_article)]
        for url, cached_raw in cases:
            with self.subTest(url=url):
                archive = Archive(MemoryStore())
                source = self.source(url=url)
                legacy = self.legacy_github_capture(archive, source, cached_raw, navigation)
                with patch('laboratory.evidence_archive.pinned_fetch') as fetch:
                    bundle = archive.prepare([source], fetch=True)
                    fetch.assert_not_called()
                fetched = next(row for row in bundle['documents'] if row['origin'] == 'fetched')
                self.assertEqual(fetched['asset_id'], legacy['id'])
                self.assertEqual(fetched['parser_version'], 'inert-extract-v1')
                self.assertEqual(archive.get(legacy['id']), legacy)
                self.assertEqual(len(archive.list()), 2)

    def pdf(self, compressed=False, bomb=False):
        from pypdf import PdfWriter
        from pypdf.generic import (DecodedStreamObject, DictionaryObject, NameObject)
        writer = PdfWriter(); page = writer.add_blank_page(200, 200)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                 NameObject('/Subtype'): NameObject('/Type1'),
                                 NameObject('/BaseFont'): NameObject('/Helvetica')})
        fonts = DictionaryObject({NameObject('/F1'): writer._add_object(font)})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): fonts})
        stream = DecodedStreamObject()
        padding = b' ' * (2 * 1024 * 1024 + 1) if bomb else b''
        stream.set_data(b'BT /F1 12 Tf 10 10 Td (Candidate 8 ms) Tj ET' + padding)
        page[NameObject('/Contents')] = writer._add_object(
            stream.flate_encode() if compressed else stream)
        output = io.BytesIO(); writer.write(output)
        return output.getvalue()

    def test_installed_pdf_parser_extracts_plain_and_bounded_flate_pages(self):
        from laboratory.evidence_archive import Archive
        archive = Archive(MemoryStore())
        for compressed in (False, True):
            with patch('laboratory.evidence_archive.pinned_fetch', return_value={
                    'raw': self.pdf(compressed), 'content_type': 'application/pdf'}):
                captured = archive.capture(self.source(), fetch=True, refresh=True)
            self.assertEqual(captured['payload']['status'], 'captured')
            self.assertIn('Candidate 8 ms', captured['payload']['segments'][0]['text'])
            self.assertEqual(captured['payload']['segments'][0]['locator'], 'pdf:page:1')

    def test_compressed_pdf_expansion_is_bounded_and_original_is_preserved(self):
        from laboratory.evidence_archive import Archive
        raw = self.pdf(compressed=True, bomb=True)
        with patch('laboratory.evidence_archive.pinned_fetch', return_value={
                'raw': raw, 'content_type': 'application/pdf'}):
            captured = Archive(MemoryStore()).capture(self.source(), fetch=True)
        self.assertEqual(captured['payload']['status'], 'unparseable')
        self.assertEqual(base64.b64decode(captured['payload']['raw_b64']), raw)
        self.assertEqual(captured['payload']['segments'], [])


class FakeSocket:
    def __init__(self, response):
        self.response, self.connected, self.sent = response, None, b''

    def settimeout(self, value):
        self.timeout = value

    def connect(self, address):
        self.connected = address

    def sendall(self, data):
        self.sent += data

    def makefile(self, mode):
        return io.BytesIO(self.response)

    def close(self):
        pass


class PinnedFetchTests(unittest.TestCase):
    def response(self, status='200 OK', headers=b'', body=b'<p>8 ms</p>'):
        return b'HTTP/1.1 ' + status.encode() + b'\r\n' + headers + b'\r\n' + body

    def resolver(self, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]

    def test_numeric_connection_preserves_tls_hostname_and_ignores_proxy_environment(self):
        from laboratory.evidence_archive import pinned_fetch
        sock = FakeSocket(self.response(headers=b'Content-Type: text/html\r\n'))
        class TLS:
            def wrap_socket(self, value, server_hostname):
                self.hostname = server_hostname
                return value
        context = TLS()
        with patch.dict('os.environ', {'HTTPS_PROXY': 'http://127.0.0.1:1234'}):
            result = pinned_fetch('https://example.org/paper', resolver=self.resolver,
                                  socket_factory=lambda *args: sock, tls_context=context)
        self.assertEqual(sock.connected, ('8.8.8.8', 443))
        self.assertEqual(context.hostname, 'example.org')
        self.assertIn(b'Host: example.org', sock.sent)
        self.assertIn(b'Accept-Encoding: identity', sock.sent)
        self.assertEqual(result['raw'], b'<p>8 ms</p>')

    def test_mixed_dns_redirect_encoding_and_oversize_fail_closed(self):
        from laboratory.evidence_archive import pinned_fetch
        addresses = self.resolver() + [
            (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]
        with self.assertRaises(ValueError):
            pinned_fetch('https://example.org', resolver=lambda *a, **k: addresses,
                         socket_factory=lambda *args: self.fail('must not connect'))
        for response in (self.response('302 Found', b'Location: https://example.org/new\r\n'),
                         self.response(headers=b'Content-Encoding: gzip\r\n'),
                         self.response(headers=b'Content-Length: 1048577\r\n')):
            with self.subTest(response=response[:50]), self.assertRaises(ValueError):
                pinned_fetch('http://example.org', resolver=self.resolver,
                             socket_factory=lambda *args: FakeSocket(response))

    def test_private_and_credential_urls_are_rejected_before_dns(self):
        from laboratory.evidence_archive import pinned_fetch
        for url in ('http://127.0.0.1/', 'http://[::1]/', 'http://localhost/',
                    'https://user:password@example.org/',
                    'https://example.org/?api_key=private', 'file:///C:/private'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                pinned_fetch(url, resolver=lambda *a, **k: self.fail('must not resolve'))


if __name__ == '__main__':
    unittest.main()
