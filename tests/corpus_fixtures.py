"""TEST_ONLY tiny six-year corpus, deliberately not a measured author result."""
import gzip
import hashlib
from pathlib import Path

from laboratory.corpus_import import REVISION, UPSTREAM_SHA, encoded


def rows():
    papers, claims, assignments = [], [], []
    for year in range(2020, 2026):
        for index in range(1, 5):
            pid = f'{year}.emnlp-main.{index}'
            papers.append({'paper_id': pid, 'year': year, 'title': f'TEST_ONLY paper {year}-{index}',
                           'abstract': 'TEST_ONLY original abstract <script>not executable</script>',
                           'venue': 'EMNLP', 'track': 'main', 'authors': ['TEST_ONLY author']})
        for index, paper, topic in [(1, 1, 54), (2, 1, 54), (3, 2, -1), (4, 3, None)]:
            cid, pid = f'TEST_ONLY_{year}_{index}', f'{year}.emnlp-main.{paper}'
            claims.append({'claim_id': cid, 'paper_id': pid, 'year': year,
                'text': 'TEST_ONLY paraphrased contribution', 'extractor_model': 'TEST_ONLY',
                'prompt_hash': 'TEST_ONLY', 'run_id': 'TEST_ONLY', 'created_at': 'TEST_ONLY'})
            if topic is not None:
                assignments.append({'claim_id': cid, 'paper_id': pid, 'year': year, 'topic_id': topic})
    topics = [{'id': topic, 'name': name, 'full_name': name, 'description': 'TEST_ONLY topic',
               'papers': 6, 'claims': count,
               'published_years': [{'year': year, 'share': 50.0} for year in range(2020, 2026)]}
              for topic, name, count in [(54, 'TEST_ONLY Parsing', 12), (-1, 'TEST_ONLY Noise', 6)]]
    return {'papers': papers, 'claims': claims, 'assignments': assignments, 'topics': topics}


def write_bundle(folder, data=None):
    folder = Path(folder)
    folder.mkdir(exist_ok=True, parents=True)
    manifest = {'format': 'drift-corpus-bundle-v1', 'dataset_id': 'drift-emnlp-2020-2025',
        'revision': REVISION, 'source_hashes': UPSTREAM_SHA, 'title': 'TEST_ONLY external corpus fixture',
        'provenance': {'origin': 'external_extraction', 'license': 'CC-BY-4.0', 'publisher': 'TEST_ONLY',
            'dataset_url': 'https://huggingface.co/datasets/Hamyrappy/emnlp-2020-2025-atomic-claims',
            'paper_url': 'https://aclanthology.org/2026.emnlp-demos.13/'}, 'files': {}}
    for name, values in (data or rows()).items():
        filename = name + '.jsonl.gz'
        payload = gzip.compress(b''.join(encoded(row) + b'\n' for row in values), mtime=0)
        (folder / filename).write_bytes(payload)
        manifest['files'][filename] = {'rows': len(values), 'bytes': len(payload),
                                        'sha256': hashlib.sha256(payload).hexdigest()}
    (folder / 'manifest.json').write_bytes(encoded(manifest))
    return folder
