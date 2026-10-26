"""Bounded adapters for the user's existing cloud CLI logins.

No credential files are read or copied. A run is one CLI invocation; this module
never retries it. CLI tool restrictions are defence in depth, not an OS sandbox.
Reference flags: learn.chatgpt.com/docs/config-file/config-reference and
code.claude.com/docs/en/cli-reference (checked 2026-10-20).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time

MAX_STDOUT_BYTES = 2 * 1024 * 1024
MAX_STDERR_BYTES = 128 * 1024
MAX_PROMPT_BYTES = 512 * 1024
ADAPTER_VERSION = "cli-source-analysis-v1"


def _executable(provider: str) -> str | None:
    names = (provider + ".exe", provider) if os.name == "nt" else (provider,)
    for name in names:
        found = shutil.which(name)
        if found and (os.name != "nt" or Path(found).suffix.lower() == ".exe"):
            return str(Path(found).resolve())
    # Native installs only: batch shims introduce an implicit command shell.
    candidates = [Path.home() / ".local" / "bin" / (provider + ".exe")]
    if provider == "codex" and os.environ.get("LOCALAPPDATA"):
        folder = Path(os.environ["LOCALAPPDATA"]) / "OpenAI" / "Codex" / "bin"
        if folder.is_dir():
            candidates += sorted(folder.glob("*/codex.exe"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in candidates:
        if path.is_file():
            return str(path.resolve())
    return None


def discovery() -> list[dict]:
    """Discover installed native CLIs without invoking models or reading auth."""
    result = []
    for provider, name in (("codex", "Codex / ChatGPT"), ("claude", "Claude Code")):
        path = _executable(provider)
        result.append({"id": provider, "name": name, "installed": bool(path), "path": path})
    return result


def _validate(plan: dict) -> tuple[str, str, bool, int]:
    if not isinstance(plan, dict):
        raise ValueError("План должен быть объектом.")
    provider = plan.get("provider")
    if provider not in {"codex", "claude"}:
        raise ValueError("Выберите Codex или Claude Code.")
    model = plan.get("model", "")
    if not isinstance(model, str) or (model and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", model)):
        raise ValueError("Некорректный идентификатор модели.")
    web_search = plan.get("web_search", False)
    if type(web_search) is not bool:
        raise ValueError("web_search должен быть boolean.")
    timeout = plan.get("timeout_seconds", 180)
    if type(timeout) is not int or not 60 <= timeout <= 600:
        raise ValueError("Лимит времени должен быть от 60 до 600 секунд.")
    return provider, model, web_search, timeout


def _command(plan: dict, executable: str) -> list[str]:
    provider, model, web_search, _ = _validate(plan)
    if provider == "codex":
        command = [executable, "--no-daemon", "exec", "--ignore-user-config", "--ignore-rules",
                   "--ephemeral", "--skip-git-repo-check", "--sandbox", "read-only", "--json",
                   "--color", "never", "--strict-config"]
        config = {
            "approval_policy": '"never"',
            "forced_login_method": '"chatgpt"',
            "web_search": '"live"' if web_search else '"disabled"',
            "mcp_servers": "{}",
            "apps._default.enabled": "false",
            "features.shell_tool": "false",
            "features.hooks": "false",
            "features.apps": "false",
            "features.plugins": "false",
            "features.remote_plugin": "false",
            "features.multi_agent": "false",
            "features.goals": "false",
            "features.memories": "false",
            "features.skill_mcp_dependency_install": "false",
            "features.skip_host_skill_discovery": "true",
            "features.skill_search": "false",
            "features.tool_suggest": "false",
            "features.browser_use": "false",
            "features.browser_use_external": "false",
            "features.computer_use": "false",
            "features.code_mode": "false",
            "features.artifact": "false",
            "features.image_generation": "false",
            "features.sleep_tool": "false",
            "features.unbounded_connection_retries": "false",
            "history.persistence": '"none"',
        }
        for key, value in config.items():
            command += ["-c", f"{key}={value}"]
        if model:
            command += ["--model", model]
        return command + ["-"]  # Prompt is sent on stdin, never in process argv.
    tools = "WebSearch,WebFetch" if web_search else ""
    command = [executable, "--safe-mode", "--no-chrome", "--disable-slash-commands",
               "--tools", tools, "--disallowedTools", "mcp__*", "--strict-mcp-config",
               "--mcp-config", '{"mcpServers":{}}', "--permission-mode", "dontAsk",
               "--no-session-persistence", "-p", "--output-format", "json", "--max-turns", "4"]
    if tools:
        command += ["--allowedTools", tools]
    if model:
        command += ["--model", model]
    return command


def _parse_codex(stdout: str) -> tuple[str, dict, str | None]:
    text = ""
    usage = {}
    completed = False
    error = None
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "item.completed":
            item = event.get("item", {})
            if isinstance(item, dict) and item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                text = item["text"]
            elif isinstance(item, dict) and item.get("type") in {"command_execution", "file_change", "mcp_tool_call"}:
                error = "CLI сообщил об инструменте, запрещённом профилем исследования."
        if event.get("type") == "turn.completed":
            completed = True
            observed = event.get("usage", {})
            if isinstance(observed, dict):
                for key, value in observed.items():
                    if type(value) in {int, float}:
                        usage[key] = usage.get(key, 0) + value
        if event.get("type") in {"turn.failed", "error"}:
            detail = event.get("error", event.get("message", "Ошибка CLI"))
            error = detail.get("message", str(detail)) if isinstance(detail, dict) else str(detail)
    if not completed and not error:
        error = "CLI завершился без подтверждённого окончания исследования."
    if not text and not error:
        error = "CLI не вернул текст отчёта."
    return text, usage, error


def _parse_claude(stdout: str) -> tuple[str, dict, str | None]:
    try:
        value = json.loads(stdout)
    except ValueError:
        return "", {}, "Claude Code не вернул ожидаемый JSON-результат."
    if isinstance(value, list):
        value = next((item for item in reversed(value) if isinstance(item, dict) and item.get("type") == "result"), {})
    if not isinstance(value, dict):
        return "", {}, "Некорректный результат Claude Code."
    text = value.get("result", "")
    text = text if isinstance(text, str) else ""
    usage = value.get("usage", {})
    usage = dict(usage) if isinstance(usage, dict) else {}
    if isinstance(value.get("modelUsage"), dict):
        usage["model_usage"] = value["modelUsage"]
    if type(value.get("total_cost_usd")) in {int, float}:
        usage["cli_estimated_cost_usd"] = value["total_cost_usd"]
    error = None
    if value.get("is_error") or value.get("subtype") not in {None, "success"}:
        error = str(value.get("subtype") or "Claude Code сообщил об ошибке.")
    if not text and not error:
        error = "Claude Code не вернул текст отчёта."
    return text, usage, error


def _redact_forbidden_tool_output(stdout: str) -> str:
    """Do not archive local-file/command output if a CLI violates its profile."""
    lines = []
    for line in stdout.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            lines.append(line)
            continue
        item = value.get("item") if isinstance(value, dict) else None
        if isinstance(item, dict) and item.get("type") in {"command_execution", "file_change", "mcp_tool_call"}:
            value["item"] = {"type": item["type"], "redacted": True}
            line = json.dumps(value, ensure_ascii=False)
        lines.append(line)
    return "\n".join(lines)


class _Capture:
    def __init__(self, limit: int, overflow: threading.Event):
        self.limit = limit
        self.overflow = overflow
        self.data = bytearray()

    def drain(self, pipe):
        try:
            while chunk := pipe.read(8192):
                remaining = max(0, self.limit - len(self.data))
                self.data.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    self.overflow.set()
        finally:
            pipe.close()


def _stop(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        taskkill = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe")
        try:
            subprocess.run([taskkill, "/PID", str(process.pid), "/T", "/F"],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=5, shell=False, creationflags=subprocess.CREATE_NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
    else:
        process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def run(plan: dict, prompt: str, work_dir, cancel_event: threading.Event) -> dict:
    """Return {text, raw, usage, status, error?}; status is completed/failed/
    cancelled/outcome_unknown. raw is a JSON-serializable diagnostic dictionary.
    cancel/timeout after spawn is conservatively outcome_unknown, without retry.
    The caller must persist its dispatch intent before calling this function.
    """
    started = time.monotonic() if plan.get("_phase_binding") else None
    raw = {"adapter_version": ADAPTER_VERSION, "stdout": "", "stderr": "", "exit_code": None,
           "truncated": False, "dispatched": False,
           "retry_policy": "one CLI invocation; bounded internal CLI retries may still occur"}

    def result(status, text="", usage=None, error=None):
        value = {"text": text, "raw": raw, "usage": usage or {}, "status": status}
        if error:
            value["error"] = error
        return value

    try:
        provider, _, _, timeout = _validate(plan)
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
            raise ValueError("Текст запроса пуст или превышает лимит 512 KiB.")
        directory = Path(work_dir).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        if any(directory.iterdir()):
            raise ValueError("Рабочий каталог запуска должен быть новым и пустым.")
        executable = _executable(provider)
        if not executable:
            raise ValueError(f"{provider} не установлен как native CLI. Установите его и войдите в аккаунт локально.")
        if plan.get("execution_context"):
            from .trace import validate_record, executable_identity
            context = plan["execution_context"]
            validate_record(plan, context)
            identity = executable_identity(executable)
            if prompt != context["prompt"] or identity.get("sha256") != context["manifest"]["cli"].get("sha256"):
                raise ValueError("Запрос или исполняемый CLI изменились после апрува. Вызов не отправлен; обновите план.")
            raw["cli_fingerprint_sha256"] = identity["sha256"]
        command = _command(plan, executable)
        external_deadline = plan.get("_runtime_deadline")
        if external_deadline is not None and (not plan.get("_phase_binding") or type(external_deadline) not in {int, float}):
            raise ValueError("Неверная граница общего времени исследования.")
        if cancel_event.is_set():
            return result("cancelled", error="Отменено до запуска CLI.")
        if external_deadline is not None and time.monotonic() >= external_deadline:
            return result("cancelled", error="Общий бюджет времени исчерпан до вызова CLI.")
        process = subprocess.Popen(command, cwd=str(directory), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, shell=False,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except (OSError, ValueError) as error:
        return result("failed", error=str(error))

    raw["dispatched"] = True
    overflow = threading.Event()
    out = _Capture(MAX_STDOUT_BYTES, overflow)
    err = _Capture(MAX_STDERR_BYTES, overflow)
    readers = [threading.Thread(target=capture.drain, args=(pipe,), daemon=True)
               for capture, pipe in ((out, process.stdout), (err, process.stderr))]
    for reader in readers:
        reader.start()

    def feed():
        try:
            process.stdin.write(prompt.encode("utf-8"))
            process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        finally:
            process.stdin.close()

    writer = threading.Thread(target=feed, daemon=True)
    writer.start()
    deadline = (started if started is not None else time.monotonic()) + timeout
    if external_deadline is not None:
        deadline = min(deadline, external_deadline)
        raw["global_deadline_applied"] = True
    stop_reason = None
    while process.poll() is None:
        if cancel_event.is_set():
            stop_reason = "Запуск отменён. Внешний запрос мог продолжиться; автоматического повтора нет."
            break
        if overflow.is_set():
            stop_reason = "CLI превысил лимит вывода. Сохранён доступный фрагмент; исход внешнего запроса неизвестен."
            break
        if time.monotonic() >= deadline:
            stop_reason = "Истёк лимит времени. Исход внешнего запроса неизвестен; автоматического повтора нет."
            break
        cancel_event.wait(0.1)
    if stop_reason:
        _stop(process)
    for thread in [writer, *readers]:
        thread.join(timeout=2)
    raw.update(stdout=bytes(out.data).decode("utf-8", errors="replace"),
               stderr=bytes(err.data).decode("utf-8", errors="replace"),
               exit_code=process.poll(), truncated=overflow.is_set())
    if provider == "codex":
        raw["stdout"] = _redact_forbidden_tool_output(raw["stdout"])
    text, usage, parse_error = (_parse_codex if provider == "codex" else _parse_claude)(raw["stdout"])
    if stop_reason or overflow.is_set():
        return result("outcome_unknown", text, usage, stop_reason or "Лимит вывода превышен; результат неполон.")
    if process.returncode != 0:
        return result("failed", text, usage, parse_error or f"CLI завершился с кодом {process.returncode}.")
    if parse_error:
        return result("failed", text, usage, parse_error)
    return result("completed", text, usage)
