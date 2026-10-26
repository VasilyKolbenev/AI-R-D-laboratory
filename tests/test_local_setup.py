"""TEST_ONLY installer boundaries. No downloads, models or real FFmpeg execution."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from tools import setup_local as setup


class LocalSetupTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parent / ".tmp"
        base.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="TEST_ONLY-setup-", dir=base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "requirements.txt").write_text("TEST_ONLY pinned requirements", encoding="utf-8")

    def owned_env(self):
        directory = self.root / ".venv"
        (directory / "Scripts").mkdir(parents=True)
        (directory / "Scripts/python.exe").write_bytes(b"TEST_ONLY not executable")
        setup.write_json(directory / setup.MARKER,
                         {"owner": setup.OWNER, "project": str(self.root), "state": "incomplete"})
        return directory

    def test_runtime_rejects_unsupported_host_version_and_architecture(self):
        with patch.object(setup.sys, "platform", "linux"):
            with self.assertRaises(setup.SetupError):
                setup.runtime_check()
        with patch.object(setup.sys, "platform", "win32"), \
                patch.object(setup.platform, "python_implementation", return_value="CPython"), \
                patch.object(setup.sys, "version_info", (3, 14)):
            with self.assertRaises(setup.SetupError):
                setup.runtime_check()
        with patch.object(setup.sys, "platform", "win32"), \
                patch.object(setup.platform, "python_implementation", return_value="CPython"), \
                patch.object(setup.sys, "version_info", (3, 12)), \
                patch.object(setup.struct, "calcsize", return_value=4):
            with self.assertRaises(setup.SetupError):
                setup.runtime_check()

    def test_other_active_environment_and_foreign_marker_are_rejected(self):
        with patch.dict(os.environ, {"VIRTUAL_ENV": str(self.root / "another-env")}):
            with self.assertRaises(setup.SetupError):
                setup.project_env(self.root)
        directory = self.owned_env()
        setup.write_json(directory / setup.MARKER,
                         {"owner": setup.OWNER, "project": str(self.root / "other-project")})
        with self.assertRaises(setup.SetupError):
            setup.marker(self.root)

    def test_install_uses_only_hash_pinned_pypi_and_owned_environment(self):
        calls = []

        def fake_command(args, **kwargs):
            calls.append(args)
            if "venv" in args:
                directory = self.root / ".venv/Scripts"
                directory.mkdir(parents=True)
                (directory / "python.exe").write_bytes(b"TEST_ONLY not executable")

        with patch.dict(os.environ, {"VIRTUAL_ENV": ""}), patch.object(setup, "command", fake_command):
            setup.install(self.root)
            setup.install(self.root)
        self.assertEqual(len(calls), 5)  # one venv creation, two explicit pip/finalize pairs
        pip_calls = [call for call in calls if "pip" in call]
        for call in pip_calls:
            self.assertEqual(Path(call[0]), self.root / ".venv/Scripts/python.exe")
            self.assertIn("--require-hashes", call)
            self.assertIn("--only-binary=:all:", call)
            self.assertIn("--no-deps", call)
            self.assertEqual(call[call.index("--index-url") + 1], "https://pypi.org/simple")
        self.assertFalse((self.root / ".lab-data").exists())
        self.assertEqual(setup.marker(self.root)["state"], "incomplete")

    def test_unmanaged_environment_is_not_modified(self):
        directory = self.root / ".venv"
        directory.mkdir()
        sentinel = directory / "TEST_ONLY-private-file"
        sentinel.write_bytes(b"unchanged")
        with patch.dict(os.environ, {"VIRTUAL_ENV": ""}), patch.object(setup, "command") as command:
            with self.assertRaises(setup.SetupError):
                setup.install(self.root)
        self.assertEqual(sentinel.read_bytes(), b"unchanged")
        command.assert_not_called()

    def test_encoder_manifest_uses_wheel_file_not_environment_override_and_detects_tamper(self):
        directory = self.owned_env()
        relative = Path("imageio_ffmpeg/binaries/TEST_ONLY-ffmpeg.exe")
        source = directory / "Lib/site-packages" / relative
        source.parent.mkdir(parents=True)
        source.write_bytes(b"TEST_ONLY pinned-wheel binary")
        package = SimpleNamespace(files=[relative],
                                  locate_file=lambda item: directory / "Lib/site-packages" / item)
        info = {"-version": "ffmpeg version TEST_ONLY", "-encoders": "libx264", "-L": "TEST_ONLY license"}
        with patch.object(setup.sys, "prefix", str(directory)), \
                patch.object(setup.importlib.metadata, "version", side_effect=lambda name: setup.VERSIONS[name]), \
                patch.object(setup.importlib.metadata, "distribution", return_value=package), \
                patch.object(setup, "verify_encoder", return_value=info) as verify, \
                patch.dict(os.environ, {"IMAGEIO_FFMPEG_EXE": str(self.root / "TEST_ONLY-untrusted.exe")}):
            setup.finalize(self.root)
            verify.assert_called_once_with(source)
            binary = self.root / ".lab-tools/media/ffmpeg.exe"
            receipt = json.loads((binary.parent / "encoder.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["sha256"], setup.sha(source))
            with patch.object(setup.subprocess, "run") as external:
                setup.check(self.root)
                external.assert_not_called()
            binary.write_bytes(b"TEST_ONLY altered")
            with self.assertRaises(setup.SetupError):
                setup.check(self.root)
        self.assertFalse((self.root / ".lab-data").exists())

    @unittest.skipUnless(os.name == "nt", "Windows byte-range locking contract")
    def test_running_server_or_concurrent_setup_blocks_installer(self):
        import msvcrt
        data = self.root / ".lab-data"
        data.mkdir()
        lock = data / ".instance.lock"
        lock.write_bytes(b"0")
        with lock.open("r+b") as handle:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            try:
                with self.assertRaises(setup.SetupError):
                    with setup.inactive_project(self.root):
                        self.fail("must not change active installation")
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        with setup.setup_lock(self.root):
            with self.assertRaises(setup.SetupError):
                with setup.setup_lock(self.root):
                    self.fail("must not run two setups")


if __name__ == "__main__":
    unittest.main()
