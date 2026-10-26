"""TEST_ONLY release fixtures. No private data, network, models or real corpus."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

from tools.build_local_release import REQUIRED, ReleaseError, build, collect, validate_content


class LocalReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='TEST_ONLY-release-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'source'
        self.root.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.email', 'TEST_ONLY@example.invalid')
        self.git('config', 'user.name', 'TEST_ONLY')
        for name in REQUIRED:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('TEST_ONLY\n', encoding='utf-8')
        (self.root / 'laboratory/__init__.py').write_text(
            '__version__ = "0.20.0-alpha.1"\n', encoding='utf-8')
        self.commit()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.PIPE)

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'TEST_ONLY fixture')

    def test_deterministic_archive_and_complete_manifest(self):
        first = build(self.root, Path(self.tmp.name) / 'one')
        second = build(self.root, Path(self.tmp.name) / 'two')
        self.assertEqual(first['sha256'], second['sha256'])
        self.assertEqual(Path(first['archive']).read_bytes(), Path(second['archive']).read_bytes())
        with zipfile.ZipFile(first['archive']) as bundle:
            prefix = 'ai-rd-laboratory-v0.20.0-alpha.1/'
            manifest = json.loads(bundle.read(prefix + 'RELEASE-MANIFEST.json'))
            self.assertEqual(set(manifest['files']), REQUIRED)
            for name, digest in manifest['files'].items():
                self.assertEqual(hashlib.sha256(bundle.read(prefix + name)).hexdigest(), digest)
            self.assertEqual(len(bundle.namelist()), len(REQUIRED) + 1)
        self.assertEqual(Path(first['checksums']).read_text(encoding='ascii'),
                         first['sha256'] + '  ' + Path(first['archive']).name + '\n')

    def test_untracked_runtime_and_internal_tasks_are_never_packaged(self):
        runtime = self.root / '.lab-data/private.sqlite3'
        runtime.parent.mkdir()
        runtime.write_bytes(b'TEST_ONLY private runtime')
        internal = self.root / 'docs/tasks/private-context.md'
        internal.parent.mkdir(parents=True)
        internal.write_text('TEST_ONLY private context', encoding='utf-8')
        self.git('add', 'docs/tasks/private-context.md')
        self.git('commit', '-qm', 'TEST_ONLY task excluded')
        _, files = collect(self.root)
        self.assertNotIn('.lab-data/private.sqlite3', files)
        self.assertNotIn('docs/tasks/private-context.md', files)

    def test_git_clean_crlf_checkout_uses_canonical_blob_bytes(self):
        readme = self.root / 'README.md'
        readme.write_bytes(b'TEST_ONLY\n')
        (self.root / '.gitattributes').write_bytes(b'*.md text\n')
        self.git('add', '--renormalize', '.')
        self.commit()
        first = build(self.root, Path(self.tmp.name) / 'lf')
        readme.write_bytes(b'TEST_ONLY\r\n')
        self.assertEqual(self.git('diff', '--cached', '--name-only', 'HEAD', '--').strip(), b'')
        self.assertEqual(self.git('diff', '--name-only', '--').strip(), b'')
        second = build(self.root, Path(self.tmp.name) / 'crlf')
        self.assertEqual(first['sha256'], second['sha256'])
        with zipfile.ZipFile(second['archive']) as bundle:
            self.assertEqual(bundle.read('ai-rd-laboratory-v0.20.0-alpha.1/README.md'), b'TEST_ONLY\n')

    def test_tracked_runtime_is_rejected_even_outside_allowlist(self):
        path = self.root / '.lab-data/private.sqlite3'
        path.parent.mkdir()
        path.write_bytes(b'TEST_ONLY')
        self.commit()
        with self.assertRaisesRegex(ReleaseError, 'Runtime or credential path'):
            collect(self.root)

    def test_modified_source_and_missing_required_files_refuse_release(self):
        (self.root / 'README.md').write_text('Changed TEST_ONLY', encoding='utf-8')
        with self.assertRaisesRegex(ReleaseError, 'Commit reviewed'):
            collect(self.root)
        self.git('checkout', '--', 'README.md')
        self.git('rm', 'README.md')
        self.git('commit', '-qm', 'TEST_ONLY missing readme')
        with self.assertRaisesRegex(ReleaseError, 'Required release files'):
            collect(self.root)

    def test_owner_paths_and_credentials_are_rejected_without_echoing_value(self):
        fixtures = [b'C:\\Users\\TEST_ONLY_OWNER\\Desktop',
                    b'ghp_' + b'A' * 36, b'sk-proj-' + b'B' * 40,
                    b'123456789:' + b'C' * 35]
        for fixture in fixtures:
            with self.subTest(kind=fixture[:4]):
                with self.assertRaises(ReleaseError) as error:
                    validate_content('laboratory/TEST_ONLY.py', fixture)
                self.assertNotIn(fixture.decode(), str(error.exception))
        validate_content('tests/TEST_ONLY.py', b'sk-TEST_ONLY-key-never-sent-0123456789')
        with self.assertRaises(ReleaseError):
            validate_content('laboratory/not-test.py', b'sk-TEST_ONLY-key-never-sent-0123456789')

    def test_symlink_mode_is_rejected_from_index(self):
        blob = self.git('rev-parse', 'HEAD:README.md')
        self.git('update-index', '--add', '--cacheinfo', '120000,' + blob.decode().strip() + ',tools/linked.py')
        self.git('commit', '-qm', 'TEST_ONLY symbolic link entry')
        # Git status sees a missing symlink; regardless, no linked bytes can reach a bundle.
        with self.assertRaises(ReleaseError):
            collect(self.root)


if __name__ == '__main__':
    unittest.main()
