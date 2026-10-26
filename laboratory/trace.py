"""The exact application request, never a claim to observe hidden provider context."""
from datetime import datetime, timezone
from functools import lru_cache
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from . import __version__, providers

TABLES = ("run_contexts",)
TEMPLATE_VERSION = "publish-ready-channel-post-v3"
MAX_CONTEXT_BYTES = 1200 * 1024
LEGACY_CONTEXT_BYTES = 600 * 1024
PIPELINE_CODE = ("core.py", "providers.py", "trace.py", "orchestration.py", "server.py", "research_protocol.py", "applied_analysis.py")
GROUNDING_CODE = (*PIPELINE_CODE, "grounded_protocol.py", "evidence_archive.py", "evidence_validation.py", "research_assets.py", "research_workbench.py", "research_public.py")

def pipeline_code(plan):
    if (plan.get('research_protocol') or {}).get('version') in {'three-pass-v4', 'editor-resume-v1'}:
        return (*GROUNDING_CODE, 'research_continuation.py', 'checkpoint_runtime.py', 'compact_editor.py')
    grounded = (plan.get("research_protocol") or {}).get("version") in {
        "three-pass-v2", "three-pass-v3"}
    return GROUNDING_CODE if grounded else PIPELINE_CODE

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)

def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()

def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

@lru_cache(maxsize=8)
def _binary_hash(path, size, mtime):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()

def executable_identity(executable):
    path = Path(executable)
    stat = path.stat()
    return {"name": path.name, "bytes": stat.st_size,
            "sha256": _binary_hash(str(path), stat.st_size, stat.st_mtime_ns)}

def descriptor(plan):
    executable = providers._executable(plan["provider"])
    cli = {"installed": bool(executable), "version": None, "version_note": "Version text not queried; executable fingerprint recorded."}
    if executable:
        cli.update(executable_identity(executable))
    root = Path(__file__).parent
    code = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in (pipeline_code(plan) if plan.get("research_protocol") else ("core.py", "providers.py", "trace.py"))}
    result = {"application_version": __version__, "template_version": TEMPLATE_VERSION,
            "code_sha256": code, "adapter_version": providers.ADAPTER_VERSION,
            "provider": plan["provider"], "requested_model": plan.get("model") or "CLI default",
            "actual_model": None, "actual_model_note": "Not reported by the adapter; a default is not a pinned model version.",
            "cli": cli, "command": providers._command(plan, "<official-cli>"), "prompt_transport": "stdin",
            "limits": {"timeout_seconds": plan["timeout_seconds"], "web_search": plan["web_search"],
                       "parallel_runs": 1, "application_retry": False,
                       "stdout_bytes": providers.MAX_STDOUT_BYTES, "prompt_bytes": providers.MAX_PROMPT_BYTES},
            "coverage": "Exact application prompt and selected local configuration. Hidden provider/CLI instructions and future web-result contents are not fully observable. Credentials and environment values are not included."}
    if plan.get("research_protocol"):
        result["protocol_sha256"] = digest(plan["research_protocol"])
        result["comparison_context_sha256"] = digest(plan.get("comparison_context"))
        result["phase_binding"] = plan.get("_phase_binding")
        calls = plan['research_protocol']['max_calls']
        result["coverage"] += f" {calls} CLI invocation(s) are approved. Exact prompts follow the frozen recipe and are journaled before dispatch."
    return result

def inputs(plan):
    result = {key: plan.get(key) for key in ("kind", "question", "sources", "study_context", "memory", "memory_options", "provider", "model", "web_search", "timeout_seconds")}
    if plan.get("research_protocol"):
        result.update({key: plan.get(key) for key in ("research_mode", "research_protocol", "comparison_context", "_phase_binding")})
    if (plan.get('research_protocol') or {}).get('version') in {'three-pass-v2', 'three-pass-v3', 'three-pass-v4', 'editor-resume-v1'}:
        result.update({key: plan.get(key) for key in ('evidence_bundle', 'registry_context')})
    if (plan.get('research_protocol') or {}).get('version') in {'three-pass-v4', 'editor-resume-v1'}:
        result.update({key: plan.get(key) for key in ('editor_format', 'continuation')})
    return result

def freeze(plan, prompt):
    memory = plan.get("memory") or {}
    study = plan.get("study_context") or {}
    manifest = descriptor(plan)
    manifest.update(inputs_sha256=digest(inputs(plan)),
                    sources=[{"id": item["id"], "content_hash": item["content_hash"]} for item in plan["sources"]],
                    task={key: study.get(key) for key in ("task_id", "task_version", "hash")},
                    memory={"hash": memory.get("hash"), "generation": memory.get("generation"),
                            "profile_version": (memory.get("profile") or {}).get("version"),
                            "findings": [{"id": item["id"], "version": item["version"]} for item in memory.get("items", [])],
                            "corrections": [{"id": item["id"], "version": item["version"]} for item in memory.get("corrections", [])],
                            "lessons": [{"id": item["id"], "version": item["version"]} for item in memory.get("lessons", [])]},
                    prompt_chars=len(prompt), prompt_utf8_bytes=len(prompt.encode("utf-8")))
    result = {"schema_version": 2 if plan.get("research_protocol") else 1, "prompt": prompt, "prompt_sha256": sha(prompt), "manifest": manifest}
    result["hash"] = digest(result)
    validate_record(plan, result)
    return result

def validate_record(plan, record, current=False):
    if not isinstance(record, dict) or set(record) != {"schema_version", "prompt", "prompt_sha256", "manifest", "hash"} or type(record["schema_version"]) is not int or record["schema_version"] not in {1, 2}:
        raise ValueError("Точный контекст этого плана не зафиксирован. Обновите план перед апрувом.")
    enhanced = record["schema_version"] == 2
    if enhanced != bool(plan.get("research_protocol")):
        raise ValueError("Версия контекста не соответствует протоколу исследования.")
    prompt, manifest = record["prompt"], record["manifest"]
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode("utf-8")) > providers.MAX_PROMPT_BYTES or len(canonical(record).encode("utf-8")) > (MAX_CONTEXT_BYTES if enhanced else LEGACY_CONTEXT_BYTES) or not isinstance(manifest, dict):
        raise ValueError("Размер или форма контекста исполнителя повреждены.")
    if record["prompt_sha256"] != sha(prompt) or record["hash"] != digest({key: value for key, value in record.items() if key != "hash"}):
        raise ValueError("Контрольная сумма точного запроса не совпала.")
    if manifest.get("inputs_sha256") != digest(inputs(plan)) or manifest.get("prompt_chars") != len(prompt) or manifest.get("prompt_utf8_bytes") != len(prompt.encode("utf-8")):
        raise ValueError("Точный запрос не соответствует замороженному плану.")
    required = {"application_version", "template_version", "code_sha256", "adapter_version", "provider", "requested_model", "actual_model", "actual_model_note", "cli", "command", "prompt_transport", "limits", "coverage", "inputs_sha256", "sources", "task", "memory", "prompt_chars", "prompt_utf8_bytes"}
    if enhanced:
        required.update({"protocol_sha256", "comparison_context_sha256", "phase_binding"})
    if set(manifest) != required or any(not isinstance(manifest[key], str) or not manifest[key] for key in ("application_version", "template_version", "adapter_version", "provider", "requested_model", "actual_model_note", "coverage")):
        raise ValueError("Манифест контекста неполон или повреждён.")
    if manifest["provider"] != plan["provider"] or manifest["requested_model"] != (plan.get("model") or "CLI default") or manifest["prompt_transport"] != "stdin" or (manifest["actual_model"] is not None and not isinstance(manifest["actual_model"], str)):
        raise ValueError("Манифест не соответствует исполнителю плана.")
    if not isinstance(manifest["command"], list) or not manifest["command"] or len(manifest["command"]) > 200 or any(not isinstance(arg, str) or len(arg) > 4000 for arg in manifest["command"]):
        raise ValueError("Повреждена конфигурация запуска.")
    cli, code, limits = manifest["cli"], manifest["code_sha256"], manifest["limits"]
    if not isinstance(cli, dict) or type(cli.get("installed")) is not bool or (cli["installed"] and (not isinstance(cli.get("sha256"), str) or len(cli["sha256"]) != 64 or type(cli.get("bytes")) is not int)):
        raise ValueError("Повреждён отпечаток CLI.")
    if not isinstance(code, dict) or set(code) != (set(pipeline_code(plan)) if enhanced else {"core.py", "providers.py", "trace.py"}) or any(not isinstance(value, str) or len(value) != 64 for value in code.values()):
        raise ValueError("Повреждены версии кода контекста.")
    if not isinstance(limits, dict) or set(limits) != {"timeout_seconds", "web_search", "parallel_runs", "application_retry", "stdout_bytes", "prompt_bytes"} or limits["timeout_seconds"] != plan["timeout_seconds"] or limits["web_search"] is not plan["web_search"] or limits["parallel_runs"] != 1 or limits["application_retry"] is not False:
        raise ValueError("Повреждены ограничения запуска.")
    memory, study = plan.get("memory") or {}, plan.get("study_context") or {}
    references = {"hash": memory.get("hash"), "generation": memory.get("generation"),
                  "profile_version": (memory.get("profile") or {}).get("version"),
                  **{key: [{"id": item["id"], "version": item["version"]} for item in memory.get(source, [])]
                     for key, source in (("findings", "items"), ("corrections", "corrections"), ("lessons", "lessons"))}}
    if manifest["sources"] != [{"id": item["id"], "content_hash": item["content_hash"]} for item in plan["sources"]] or manifest["task"] != {key: study.get(key) for key in ("task_id", "task_version", "hash")} or manifest["memory"] != references:
        raise ValueError("Ссылки контекста не соответствуют источникам и памяти плана.")
    if enhanced:
        from .research_protocol import validate_protocol, phase_prompt
        validate_protocol(plan["research_protocol"])
        if manifest["protocol_sha256"] != digest(plan["research_protocol"]) or manifest["comparison_context_sha256"] != digest(plan.get("comparison_context")) or manifest["phase_binding"] != plan.get("_phase_binding"):
            raise ValueError("Рецепт или исходный контекст проходов изменились.")
        binding = plan.get("_phase_binding")
        if binding is None:
            if plan.get("research_mode") != "reviewed" or plan["timeout_seconds"] != plan["research_protocol"]["total_timeout_seconds"] or prompt != phase_prompt(plan, 0, []):
                raise ValueError("Первый запрос не соответствует одобренному рецепту.")
        else:
            parent, prior = plan.get("_approved_parent"), plan.get("_previous_outputs")
            if not isinstance(parent, dict) or not isinstance(prior, list) or any(not isinstance(item, str) for item in prior):
                raise ValueError("Проход не связан с одобренным родительским планом.")
            validate_record(parent, parent.get("execution_context"), current=current)
            index = binding.get("index") if isinstance(binding, dict) else None
            if type(index) is not int or not 0 <= index < 3 or len(prior) != index:
                raise ValueError("Неверный порядок проходов.")
            expected = phase_binding(parent, index, prior)
            approved_manifest = parent["execution_context"]["manifest"]
            if any(manifest[key] != approved_manifest[key] for key in ("application_version", "adapter_version", "code_sha256", "cli", "provider", "requested_model")):
                raise ValueError("Исполнитель или код прохода отличается от одобренного владельцем.")
            expected_plan = {**parent, "timeout_seconds": parent["research_protocol"]["phase_timeouts"][index], "_phase_binding": expected}
            expected_plan["web_search"] = bool(parent["web_search"] and parent["research_protocol"]["roles"][index] in parent["research_protocol"]["web_search_roles"])
            if binding != expected or inputs(plan) != inputs(expected_plan) or prompt != phase_prompt(parent, index, prior):
                raise ValueError("Точный запрос прохода не соответствует одобренному рецепту.")
    if current:
        actual = descriptor(plan)
        if any(manifest.get(key) != value for key, value in actual.items()):
            raise ValueError("Код или конфигурация исполнителя изменились. Обновите план и подтвердите точный контекст заново.")


def phase_binding(parent, index, previous_outputs):
    return {"parent_plan_hash": digest(parent), "parent_context_hash": parent["execution_context"]["hash"],
            "protocol_sha256": digest(parent["research_protocol"]), "index": index,
            "previous_output_sha256": [sha(item) for item in previous_outputs]}


def phase_plan(parent, index, previous_outputs):
    """Derive an exact invocation only through the owner-approved frozen recipe."""
    from .research_protocol import phase_prompt
    validate_record(parent, parent.get("execution_context"), current=True)
    plan = deepcopy(parent)
    plan["timeout_seconds"] = parent["research_protocol"]["phase_timeouts"][index]
    plan["web_search"] = bool(parent["web_search"] and parent["research_protocol"]["roles"][index] in parent["research_protocol"]["web_search_roles"])
    plan["_phase_binding"] = phase_binding(parent, index, previous_outputs)
    plan["_approved_parent"] = deepcopy(parent)
    plan["_previous_outputs"] = list(previous_outputs)
    prompt = phase_prompt(parent, index, previous_outputs)
    plan["execution_context"] = freeze(plan, prompt)
    return plan

class Trace:
    def __init__(self, store):
        self.store = store

    def initialize(self):
        with self.store.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS run_contexts(run_id TEXT PRIMARY KEY REFERENCES runs(id),context TEXT NOT NULL,captured_at TEXT NOT NULL)")

    def validate(self, plan, current=True):
        validate_record(plan, plan.get("execution_context"), current=current)

    def capture(self, run):
        plan = run["plan"]
        self.validate(plan)
        context = plan["execution_context"]
        with self.store.connect() as db:
            if not db.execute("SELECT 1 FROM runs WHERE id=? AND status='running'", (run["id"],)).fetchone():
                raise ValueError("Контекст фиксируется только перед одобренным запуском.")
            db.execute("INSERT OR IGNORE INTO run_contexts VALUES (?,?,?)", (run["id"], canonical(context), datetime.now(timezone.utc).isoformat(timespec="seconds")))
            existing = db.execute("SELECT context FROM run_contexts WHERE run_id=?", (run["id"],)).fetchone()
            if json.loads(existing[0]) != context:
                raise ValueError("Для этого запуска уже записан другой контекст.")
        return context["prompt"]

    def get(self, run_id):
        run = self.store.run(run_id)
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM run_contexts WHERE run_id=?", (run_id,)).fetchone()
        record = json.loads(row["context"]) if row else run["plan"].get("execution_context")
        if not record:
            return {"status": "legacy_unavailable", "manifest": {}, "prompt": "", "prompt_sha256": None,
                    "notice": "В старой версии точный отправленный prompt не фиксировался. Исторический план сохранён; реконструкция не выдаётся за оригинал."}
        validate_record(run["plan"], record)
        return {"status": "captured" if row else "prepared", **record,
                "captured_at": row["captured_at"] if row else None,
                "usage": run["usage"], "note": record["manifest"]["coverage"]}

def has_user_data(db):
    return bool(db.execute("SELECT 1 FROM run_contexts LIMIT 1").fetchone())

def validate_backup_table(table, row, db):
    if table != TABLES[0] or not isinstance(row, dict) or set(row) != {"run_id", "context", "captured_at"}:
        raise ValueError("Повреждена таблица контекста запусков.")
    if not isinstance(row["captured_at"], str):
        raise ValueError("Повреждена дата фиксации контекста.")
    datetime.fromisoformat(row["captured_at"])
    parent = db.execute("SELECT plan,status FROM runs WHERE id=?", (row["run_id"],)).fetchone()
    if not parent or parent["status"] == "planned" or not isinstance(row["context"], str) or len(row["context"].encode("utf-8")) > MAX_CONTEXT_BYTES:
        raise ValueError("Контекст не связан с отправленным запуском.")
    plan, context = json.loads(parent["plan"]), json.loads(row["context"])
    validate_record(plan, context)
    if plan.get("execution_context") != context:
        raise ValueError("Записанный контекст отличается от одобренного плана.")

def validate_backup(db):
    for row in db.execute("SELECT plan FROM runs"):
        plan = json.loads(row[0])
        if "execution_context" in plan:
            validate_record(plan, plan["execution_context"])
    if db.execute("PRAGMA foreign_key_check").fetchone():
        raise ValueError("Нарушены связи контекста запусков.")
