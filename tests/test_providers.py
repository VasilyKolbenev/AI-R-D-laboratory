import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from laboratory import providers


class FakeProcess:
    def __init__(self, command, output, returncode=0, **kwargs):
        self.command = command
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO(output.encode())
        self.stderr = io.BytesIO()
        self.returncode = returncode
        self.pid = 999999
        self.kwargs = kwargs

    def poll(self):
        return self.returncode


class ProviderTests(unittest.TestCase):
    def plan(self, provider="codex", **overrides):
        return {"provider": provider, "model": "", "web_search": False, "timeout_seconds": 60, **overrides}

    def test_codex_command_has_no_prompt_or_local_execution(self):
        command = providers._command(self.plan(web_search=True), "codex.exe")
        joined = " ".join(command)
        for setting in ["features.shell_tool=false", "features.hooks=false", "features.apps=false",
                        "features.plugins=false", "features.multi_agent=false", "features.skip_host_skill_discovery=true",
                        "mcp_servers={}", 'forced_login_method="chatgpt"', 'web_search="live"']:
            self.assertIn(setting, command)
        self.assertIn("--ignore-user-config", command)
        self.assertIn("--ignore-rules", command)
        self.assertIn("read-only", command)
        self.assertNotIn("dangerously", joined)
        self.assertEqual(command[-1], "-")

    def test_claude_tools_are_explicit_and_mcp_disabled(self):
        for enabled in [False, True]:
            command = providers._command(self.plan("claude", web_search=enabled), "claude.exe")
            self.assertIn("--safe-mode", command)
            self.assertNotIn("--bare", command)
            self.assertEqual(command[command.index("--tools") + 1], "WebSearch,WebFetch" if enabled else "")
            self.assertIn("--strict-mcp-config", command)
            self.assertIn("mcp__*", command)
            self.assertEqual(command[command.index("--max-turns") + 1], "4")

    def test_invalid_model_or_timeout_is_rejected(self):
        for plan in [self.plan(model="--config=bad"), self.plan(timeout_seconds=1), self.plan(web_search="yes")]:
            with self.assertRaises(ValueError):
                providers._command(plan, "codex.exe")

    def test_parse_codex_final_and_usage(self):
        output = '\n'.join(json.dumps(event) for event in [
            {"type": "item.completed", "item": {"type": "agent_message", "text": "готовый отчёт"}},
            {"type": "turn.completed", "usage": {"input_tokens": 120, "output_tokens": 60}},
        ])
        text, usage, error = providers._parse_codex(output)
        self.assertEqual(text, "готовый отчёт")
        self.assertEqual(usage["input_tokens"], 120)
        self.assertIsNone(error)
        self.assertIsNotNone(providers._parse_codex(output.splitlines()[0])[2])

    def test_forbidden_codex_tool_is_not_a_valid_report(self):
        output = '\n'.join([json.dumps({"type": "item.completed", "item": {"type": "command_execution"}}),
                            json.dumps({"type": "turn.completed"})])
        self.assertIsNotNone(providers._parse_codex(output)[2])

    def test_forbidden_tool_output_is_not_archived(self):
        event = {"type": "item.completed", "item": {"type": "command_execution", "output": "private host file"}}
        output = providers._redact_forbidden_tool_output(json.dumps(event))
        self.assertNotIn("private host file", output)
        self.assertTrue(json.loads(output)["item"]["redacted"])

    def test_claude_max_turns_is_failure_with_partial_text(self):
        text, usage, error = providers._parse_claude(json.dumps({"type": "result", "subtype": "error_max_turns",
                                                               "result": "partial", "usage": {"input_tokens": 100}}))
        self.assertEqual(text, "partial")
        self.assertEqual(usage["input_tokens"], 100)
        self.assertEqual(error, "error_max_turns")

    def test_successful_invocation_uses_stdin_and_hidden_no_shell(self):
        output = '\n'.join([json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "report"}}),
                            json.dumps({"type": "turn.completed", "usage": {"output_tokens": 2}})])
        calls = []

        def popen(command, **kwargs):
            calls.append((command, kwargs))
            return FakeProcess(command, output, **kwargs)

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory, patch.object(providers, "_executable", return_value="codex.exe"), patch.object(providers.subprocess, "Popen", side_effect=popen):
            result = providers.run(self.plan(), "private material", directory, threading.Event())
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["text"], "report")
        self.assertNotIn("private material", calls[0][0])
        self.assertIs(calls[0][1]["shell"], False)
        self.assertTrue(result["raw"]["dispatched"])

    def test_cancel_before_dispatch_does_not_spawn(self):
        cancel = threading.Event()
        cancel.set()
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory, patch.object(providers, "_executable", return_value="codex.exe"), patch.object(providers.subprocess, "Popen") as popen:
            result = providers.run(self.plan(), "material", directory, cancel)
        self.assertEqual(result["status"], "cancelled")
        popen.assert_not_called()

    def test_nonempty_workdir_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            Path(directory, "host-file.txt").write_text("not a fresh workspace")
            with patch.object(providers.subprocess, "Popen") as popen:
                result = providers.run(self.plan(), "material", directory, threading.Event())
        self.assertEqual(result["status"], "failed")
        popen.assert_not_called()

    def test_output_is_bounded(self):
        overflow = threading.Event()
        capture = providers._Capture(10, overflow)
        capture.drain(io.BytesIO(b"a" * 100))
        self.assertEqual(bytes(capture.data), b"a" * 10)
        self.assertTrue(overflow.is_set())

    def test_cancel_after_spawn_is_unknown_and_never_retried(self):
        cancel = threading.Event()

        def popen(command, **kwargs):
            process = FakeProcess(command, "partial output", returncode=None, **kwargs)
            cancel.set()
            return process

        def stop(process):
            process.returncode = -9

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory, patch.object(providers, "_executable", return_value="codex.exe"), patch.object(providers.subprocess, "Popen", side_effect=popen) as spawn, patch.object(providers, "_stop", side_effect=stop) as stopped:
            result = providers.run(self.plan(), "material", directory, cancel)
        self.assertEqual(result["status"], "outcome_unknown")
        self.assertEqual(result["raw"]["stdout"], "partial output")
        self.assertEqual(spawn.call_count, 1)
        stopped.assert_called_once()

    def test_timeout_is_unknown_without_retry(self):
        process = FakeProcess([], "partial", returncode=None)

        def stop(value):
            value.returncode = -9

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory, patch.object(providers, "_executable", return_value="codex.exe"), patch.object(providers.subprocess, "Popen", return_value=process) as spawn, patch.object(providers, "_stop", side_effect=stop), patch.object(providers.time, "monotonic", side_effect=[0, 61]):
            result = providers.run(self.plan(), "material", directory, threading.Event())
        self.assertEqual(result["status"], "outcome_unknown")
        self.assertEqual(result["raw"]["stdout"], "partial")
        self.assertEqual(spawn.call_count, 1)


if __name__ == "__main__":
    unittest.main()
