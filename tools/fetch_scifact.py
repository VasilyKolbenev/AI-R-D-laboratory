"""Download only official plaintext benchmark data; never execute/evaluate it."""
from datetime import datetime, timezone
import csv
import hashlib
import io
import json
import ssl
import subprocess
import os
from urllib.error import URLError
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.lab-data/sources/lexical/scifact'
URL = 'https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/scifact.zip'
MD5 = '5f7d1de60b170fc8027bb7898e2efca1'
MAX = 32 * 1024 * 1024


class SameHost(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        value = urlsplit(newurl)
        if value.scheme != 'https' or value.netloc != urlsplit(URL).netloc:
            raise ValueError('Unexpected dataset redirect')
        return super().redirect_request(request, fp, code, message, headers, newurl)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    archive = OUT / 'scifact.zip'
    if archive.exists():
        data = archive.read_bytes()
    else:
        try:
            with build_opener(ProxyHandler({}), SameHost()).open(URL, timeout=30) as response:
                data = response.read(MAX + 1)
        except URLError as error:
            if os.name != 'nt' or not isinstance(error.reason, ssl.SSLCertVerificationError):
                raise
            # Windows curl uses the system certificate store; TLS verification stays on.
            subprocess.run(['curl.exe','--fail','--silent','--show-error','--max-filesize',str(MAX),
                '--max-time','30','--proto','=https','--max-redirs','0','--output',str(archive),URL],
                check=True,timeout=40,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if archive.stat().st_size > MAX:
                raise ValueError('Dataset exceeds byte limit')
            data=archive.read_bytes()
    assert len(data) <= MAX and hashlib.md5(data).hexdigest() == MD5, 'Dataset differs from the official published checksum'
    archive.write_bytes(data)
    files, content = {}, {}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in ['corpus.jsonl', 'queries.jsonl', 'qrels/test.tsv']:
            entry = z.getinfo('scifact/' + name)
            assert entry.file_size <= MAX and not entry.is_dir()
            value = z.read(entry)
            assert len(value) == entry.file_size
            target = OUT / name
            assert target.resolve().is_relative_to(OUT.resolve()) and not target.is_symlink()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(value)
            content[name] = value.decode('utf-8')
            records = (len([line for line in content[name].splitlines() if line.strip()])
                       if name.endswith('.jsonl') else len(list(csv.DictReader(io.StringIO(content[name]), delimiter='\t'))))
            files[name] = {'sha256': hashlib.sha256(value).hexdigest(), 'bytes': len(value), 'records': records}
    rows = list(csv.DictReader(io.StringIO(content['qrels/test.tsv']), delimiter='\t'))
    assert set(rows[0]) == {'query-id', 'corpus-id', 'score'}
    query_ids = sorted({row['query-id'] for row in rows})
    manifest = {'version': 'lexical-dataset-v1', 'dataset': 'beir-scifact', 'source_url': URL,
                'archive_sha256': hashlib.sha256(data).hexdigest(), 'archive_md5': MD5,
                'files': files, 'query_ids': query_ids,
                'counts': {'documents': files['corpus.jsonl']['records'],
                           'queries': files['queries.jsonl']['records'],
                           'test_queries': len(query_ids), 'qrels': len(rows)}}
    (OUT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2), encoding='utf-8')
    (OUT / 'DATA_LICENSE.md').write_text(
        '# BEIR / SciFact data attribution\n\n'
        'Wadden et al., Fact or Fiction: Verifying Scientific Claims (EMNLP 2020).\n'
        'https://github.com/allenai/scifact\n\n'
        'BEIR conversion: Thakur et al., BEIR (NeurIPS 2021 Datasets and Benchmarks).\n'
        'https://github.com/beir-cellar/beir\n\n'
        'Claims and evidence annotations: CC BY 4.0.\n'
        'Abstracts: Semantic Scholar S2ORC, ODC-By 1.0.\n'
        'https://github.com/allenai/scifact/blob/master/LICENSE.md\n'
        'Dataset kept locally for evaluation; no neural models or third-party code downloaded.\n', encoding='utf-8')
    (OUT / 'SOURCE.json').write_text(json.dumps({'url': URL, 'downloaded_at': datetime.now(timezone.utc).isoformat(),
        'archive_sha256': manifest['archive_sha256'], 'official_md5_match': True,
        'evaluation_executed': False}, indent=2), encoding='utf-8')
    print(json.dumps({'bytes': len(data), 'counts': manifest['counts'],
                      'archive_sha256': manifest['archive_sha256'], 'evaluation_executed': False}))


if __name__ == '__main__':
    main()
