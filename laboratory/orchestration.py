"""Three paid invocation slots, a durable journal, and no automatic recovery calls."""
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import time

from .trace import canonical, digest, sha, phase_plan, phase_binding, validate_record

TABLES = ("agent_phases",)
MAX_PHASE_BYTES = 5 * 1024 * 1024
PHASE_STATES = {"dispatch_intent", "completed", "failed", "cancelled", "outcome_unknown"}


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def initialize(store):
    with store.connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS agent_phases(run_id TEXT NOT NULL REFERENCES runs(id),phase_index INTEGER NOT NULL CHECK(phase_index BETWEEN 0 AND 2),record TEXT NOT NULL,PRIMARY KEY(run_id,phase_index))")


def call_reservation(plan):
    if plan.get("research_protocol"):
        from .research_protocol import validate_protocol
        validate_protocol(plan["research_protocol"])
        if plan["research_protocol"].get("version") == "editor-resume-v1":
            from .research_continuation import validate_plan
            validate_plan(plan)
            return 1
        return 3
    if plan.get("research_mode") == "reviewed":
        raise ValueError("Для трёх проходов отсутствует одобренный протокол.")
    return 1


def _records(store, run_id):
    with store.connect() as db:
        return [json.loads(row[0]) for row in db.execute("SELECT record FROM agent_phases WHERE run_id=? ORDER BY phase_index", (run_id,))]


def _compact(records):
    keys = ("index", "role", "status", "prompt_sha256", "output_sha256", "dispatched", "elapsed_seconds", "usage", "started_at", "finished_at", "error")
    return [{key: item.get(key) for key in keys} for item in records]


def compact_trace(store, run):
    protocol = run["plan"].get("research_protocol")
    if not protocol:
        return {"status": "legacy_single", "phases": []}
    records = _records(store, run["id"])
    return {"version": protocol["version"], "status": run["status"],
            "reserved_calls": call_reservation(run["plan"]) if run.get("approved_at") else 0,
            "dispatched_calls": sum(item["dispatched"] is True for item in records),
            "uncertain_calls": sum(item["dispatched"] is None for item in records),
            "total_timeout_seconds": protocol["total_timeout_seconds"],
            "elapsed_seconds": sum(item.get("elapsed_seconds") or 0 for item in records),
            "phases": _compact(records),
            **_reuse_view(run["plan"])}


def _reuse_view(plan):
    if (plan.get("research_protocol") or {}).get("version") == "editor-resume-v1":
        from .research_continuation import reused_view
        return {"reused_phases": reused_view(plan)}
    return {}


def agent_trace(store, run_id):
    run = store.run(run_id, include_raw=True)
    result = {"run_id": run_id, **compact_trace(store, run)}
    result["phases"] = [{**item, "prompt": item["context"]["prompt"]} for item in _records(store, run_id)]
    result["review"] = (run["raw"].get("orchestration") or {}).get("review")
    result["notice"] = "Точные запросы фиксируются перед отдельными вызовами. Незавершённый intent не повторяется; скрытые внутренние обращения CLI не наблюдаются."
    return result


def _numeric(value):
    return type(value) in {int, float} and math.isfinite(value) and value >= 0


def normalized_usage(provider, usage):
    observed = {key: value for key, value in usage.items() if _numeric(value)}
    if provider == "claude":
        # Anthropic input excludes its separately reported cache writes/reads.
        if "input_tokens" in observed:
            observed["input_tokens"] += observed.get("cache_creation_input_tokens", 0) + observed.get("cache_read_input_tokens", 0)
        if "cache_read_input_tokens" in observed:
            observed["cached_input_tokens"] = observed["cache_read_input_tokens"]
    # Codex input already includes cached_input_tokens. model_usage is a second
    # view of the same billable work, never another contribution to this sum.
    return observed


def aggregate_usage(provider, records):
    total = {}
    for item in records:
        for key, value in normalized_usage(provider, item.get("usage") or {}).items():
            total[key] = total.get(key, 0) + value
    return total


class DeadlineCancel:
    """The existing runner's cancel interface, bounded by one study deadline."""
    def __init__(self, owner_cancel, deadline):
        self.owner_cancel, self.deadline = owner_cancel, deadline

    def is_set(self):
        return self.owner_cancel.is_set() or time.monotonic() >= self.deadline

    def wait(self, seconds=None):
        remaining = max(0, self.deadline - time.monotonic())
        self.owner_cancel.wait(remaining if seconds is None else min(seconds, remaining))
        return self.is_set()


def _intent(store, run, plan, index):
    context = plan["execution_context"]
    record = {"schema_version": 1, "index": index, "role": run["plan"]["research_protocol"]["roles"][index],
              "status": "dispatch_intent", "parent_plan_hash": run["plan_hash"],
              "protocol_sha256": digest(run["plan"]["research_protocol"]),
              "previous_output_sha256": plan["_phase_binding"]["previous_output_sha256"],
              "context": context, "prompt_sha256": context["prompt_sha256"],
              "output": "", "output_sha256": sha(""), "usage": {}, "raw": {},
              "dispatched": None, "started_at": timestamp(), "finished_at": None,
              "elapsed_seconds": None, "error": ""}
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT status,plan_hash FROM runs WHERE id=?", (run["id"],)).fetchone()
        if not row or row["status"] != "running" or row["plan_hash"] != run["plan_hash"]:
            raise ValueError("Проход больше не связан с одобренным запуском.")
        if run["plan"]["research_protocol"].get("version") == "editor-resume-v1":
            from .research_continuation import validate_bound
            validate_bound(db, run["plan"])
        prior = [json.loads(item[0]) for item in db.execute("SELECT record FROM agent_phases WHERE run_id=? ORDER BY phase_index", (run["id"],))]
        if len(prior) != index or any(item["status"] != "completed" for item in prior) or [item["output_sha256"] for item in prior] != record["previous_output_sha256"]:
            raise ValueError("Проход уже отправлялся либо предыдущий проход не завершён; повтора нет.")
        db.execute("INSERT INTO agent_phases VALUES (?,?,?)", (run["id"], index, canonical(record)))
    return record


def _complete(store, run_id, record, result, elapsed):
    raw = result.get("raw") if isinstance(result.get("raw"), dict) else {}
    record.update(status=result.get("status", "failed"), output=str(result.get("text", "")),
                  usage=result.get("usage") if isinstance(result.get("usage"), dict) else {},
                  raw=raw, dispatched=raw.get("dispatched", True), error=str(result.get("error", "")),
                  elapsed_seconds=max(0, elapsed), finished_at=timestamp())
    if record["status"] not in PHASE_STATES - {"dispatch_intent"}:
        record["status"] = "failed"
    record["output_sha256"] = sha(record["output"])
    encoded = canonical(record)
    if len(encoded.encode("utf-8")) > MAX_PHASE_BYTES:
        # CLI captures and protocol prompt/output bounds normally make this
        # impossible. Preserve the already persisted intent if a runner lies.
        raise ValueError("Диагностика прохода превысила границу журнала; повтор запрещён.")
    with store.connect() as db:
        updated = db.execute("UPDATE agent_phases SET record=? WHERE run_id=? AND phase_index=? AND json_extract(record,'$.status')='dispatch_intent'", (encoded, run_id, record["index"]))
        if updated.rowcount != 1:
            raise ValueError("Исход прохода уже записан; повторная запись запрещена.")


def execute(store, run, runner, work_dir, cancel):
    """At most three runner entries; success means all three and a valid review."""
    from .applied_analysis import validate_final, validate_phase
    protocol = run["plan"]["research_protocol"]
    if protocol.get("version") == "editor-resume-v1":
        from .checkpoint_runtime import execute as execute_checkpoint
        return execute_checkpoint(store, run, runner, work_dir, cancel)
    started = time.monotonic()
    hard_deadline = started + protocol["total_timeout_seconds"]
    # Existing bounded Windows process-tree cleanup stays inside the approved
    # total envelope; source generation has only total-minus-reserve seconds.
    dispatch_deadline = hard_deadline - protocol["cleanup_reserve_seconds"]
    bounded_cancel = DeadlineCancel(cancel, dispatch_deadline)
    texts, review = [], None
    state, error = "failed", "Три прохода не завершены."
    try:
        store.trace.capture(run)
        for index in range(3):
            if bounded_cancel.is_set():
                state = "cancelled" if cancel.is_set() else "failed"
                error = "Отменено до следующего прохода." if cancel.is_set() else "Общий бюджет времени исчерпан; следующий вызов не отправлен."
                break
            plan = phase_plan(run["plan"], index, texts)
            if bounded_cancel.is_set():
                state, error = "cancelled", "Общий бюджет времени или отмена остановили исследование до вызова."
                break
            record = _intent(store, run, plan, index)
            phase_started = time.monotonic()
            plan["_runtime_deadline"] = dispatch_deadline
            try:
                result = runner(plan, plan["execution_context"]["prompt"], Path(work_dir) / (str(index + 1) + "-" + record["role"]), bounded_cancel)
                if not isinstance(result, dict):
                    raise ValueError("Исполнитель вернул некорректный результат.")
            except Exception:
                result = {"status": "outcome_unknown", "error": "Исполнитель завершился с ошибкой; вызов мог состояться. Повтора нет.", "raw": {"dispatched": None}}
            if result.get("status") == "completed":
                limit = protocol["limits"][record["role"] + "_output_chars"]
                if not isinstance(result.get("text"), str) or not result["text"].strip() or len(result["text"]) > limit:
                    result = {**result, "status": "failed", "error": "Ответ отсутствует или превышает одобренную границу; следующего вызова нет."}
                else:
                    if protocol.get("version") == "three-pass-v4" and index == 2:
                        from .checkpoint_runtime import capture_received, assemble_result
                        result = capture_received(store, run["id"], record, result)
                        result = assemble_result(run["plan"], result)
                    try:
                        if result.get("status") == "completed":
                            observed_review = validate_phase(
                                run["plan"], index, [*texts, result["text"]])
                        else:
                            observed_review = {"status": "incomplete", "issues": [
                                result.get("error", "Неполная сборка редактора.")]}
                        if not isinstance(observed_review, dict):
                            raise ValueError("Некорректный ответ локальной проверки.")
                    except Exception:
                        observed_review = {"status": "incomplete", "issues": ["Локальная проверка ответа не завершилась; оплаченный ответ сохранён без повторного вызова."]}
                    if observed_review.get("status") != "ready":
                        review = observed_review
                        result = {**result, "status": "failed", "error": "Проверка прохода неполна: " + "; ".join(str(item) for item in observed_review.get("issues", [])[:6])}
            _complete(store, run["id"], record, result, time.monotonic() - phase_started)
            if record["status"] != "completed":
                state, error = record["status"], record["error"]
                break
            texts.append(record["output"])
        if len(texts) == 3:
            review = validate_final(run["plan"], texts)
            if review.get("status") == "ready":
                state, error = "completed", ""
            else:
                state, error = "failed", "Проверка неполна: " + "; ".join(str(item) for item in review.get("issues", [])[:6])
        if state == "completed" and time.monotonic() > hard_deadline:
            state, error = "failed", "Превышен общий бюджет времени; результат не объявлен завершённым."
    except Exception as exc:
        records = _records(store, run["id"])
        state = "outcome_unknown" if any(item["status"] == "dispatch_intent" for item in records) else "failed"
        error = "Исследование остановлено без повтора: " + str(exc)
    records = _records(store, run["id"])
    summary = {"version": protocol["version"], "status": state, "max_calls": 3, "reserved_calls": 3,
               "dispatched_calls": sum(item["dispatched"] is True for item in records),
               "uncertain_calls": sum(item["dispatched"] is None for item in records),
               "total_timeout_seconds": protocol["total_timeout_seconds"],
               "cleanup_reserve_seconds": protocol["cleanup_reserve_seconds"],
               "elapsed_seconds": max(0, time.monotonic() - started), "phases": _compact(records), "review": review,
               "usage_coverage": {key: {"reported_phases": sum(key in normalized_usage(run["plan"]["provider"], item.get("usage") or {}) for item in records), "phase_count": len(records)} for key in ("input_tokens", "output_tokens", "cached_input_tokens")}}
    editor_raw = records[-1]["raw"].get("editor_assembly") if records else None
    return {"status": state, "error": error, "text": texts[2] if len(texts) == 3 else "",
            "usage": aggregate_usage(run["plan"]["provider"], records),
            "raw": {"dispatched": bool(summary["dispatched_calls"]), "orchestration": summary,
                    **({"editor_assembly": editor_raw} if editor_raw is not None else {})}}


def recover(db):
    for row in db.execute("SELECT run_id,phase_index,record FROM agent_phases"):
        record = json.loads(row["record"])
        if record.get("status") == "dispatch_intent":
            record.update(status="outcome_unknown", finished_at=timestamp(), error="Приложение прервано после intent; исход вызова неизвестен, повтора нет.")
            db.execute("UPDATE agent_phases SET record=? WHERE run_id=? AND phase_index=?", (canonical(record), row["run_id"], row["phase_index"]))
    # A paid phase can be fully committed before Store.finish receives its usage.
    # Sum physical rows only: a resumed run's immutable prefix is another run's cost.
    for row in db.execute("SELECT id,plan FROM runs WHERE status='outcome_unknown'").fetchall():
        run_id = row["id"]
        plan = json.loads(row["plan"])
        if plan.get("research_protocol", {}).get("version") in {
                "editor-resume-v1", "three-pass-v4"}:
            records = [json.loads(item[0]) for item in db.execute(
                "SELECT record FROM agent_phases WHERE run_id=? ORDER BY phase_index",
                (run_id,))]
            db.execute("UPDATE runs SET usage=? WHERE id=? AND status='outcome_unknown'",
                       (canonical(aggregate_usage(plan["provider"], records)), run_id))


def has_user_data(db):
    return bool(db.execute("SELECT 1 FROM agent_phases LIMIT 1").fetchone())


def validate_backup_table(table, row, db):
    if table != TABLES[0] or not isinstance(row, dict) or set(row) != {"run_id", "phase_index", "record"} or not isinstance(row["run_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", row["run_id"]) or type(row["phase_index"]) is not int or not 0 <= row["phase_index"] < 3:
        raise ValueError("Повреждён журнал отдельных проходов.")
    if not isinstance(row["record"], str) or len(row["record"].encode("utf-8")) > MAX_PHASE_BYTES:
        raise ValueError("Превышен размер журнала прохода.")
    record = json.loads(row["record"])
    required = {"schema_version", "index", "role", "status", "parent_plan_hash", "protocol_sha256", "previous_output_sha256", "context", "prompt_sha256", "output", "output_sha256", "usage", "raw", "dispatched", "started_at", "finished_at", "elapsed_seconds", "error"}
    parent_row = db.execute("SELECT plan,plan_hash,status FROM runs WHERE id=?", (row["run_id"],)).fetchone()
    if not isinstance(record, dict) or set(record) != required or not parent_row or parent_row["status"] == "planned":
        raise ValueError("Журнал не связан с одобренным исследованием.")
    parent = json.loads(parent_row["plan"])
    protocol = parent.get("research_protocol")
    if protocol and protocol.get("version") == "editor-resume-v1":
        from .checkpoint_runtime import validate_phase_record
        return validate_phase_record(row, record, parent_row, db)
    if not protocol or type(record["index"]) is not int or record["index"] != row["phase_index"] or record["role"] != protocol["roles"][record["index"]] or type(record["schema_version"]) is not int or record["schema_version"] != 1 or record["status"] not in PHASE_STATES:
        raise ValueError("Повреждена роль или состояние прохода.")
    captured = db.execute("SELECT context FROM run_contexts WHERE run_id=?", (row["run_id"],)).fetchone()
    if not captured or json.loads(captured[0]) != parent.get("execution_context"):
        raise ValueError("У прохода отсутствует зафиксированное одобренное основание.")
    previous = [json.loads(item[0]) for item in db.execute("SELECT record FROM agent_phases WHERE run_id=? AND phase_index<? ORDER BY phase_index", (row["run_id"], row["phase_index"]))]
    if len(previous) != row["phase_index"] or any(item["status"] != "completed" for item in previous):
        raise ValueError("Нарушена последовательность проходов.")
    texts = [item["output"] for item in previous]
    expected_binding = phase_binding(parent, row["phase_index"], texts)
    if record["parent_plan_hash"] != parent_row["plan_hash"] or record["protocol_sha256"] != digest(protocol) or record["previous_output_sha256"] != [sha(item) for item in texts]:
        raise ValueError("Происхождение прохода не соответствует одобренному плану.")
    phase = {**parent, "timeout_seconds": protocol["phase_timeouts"][row["phase_index"]],
             "web_search": bool(parent["web_search"] and record["role"] in protocol["web_search_roles"]),
             "_phase_binding": expected_binding, "_approved_parent": parent, "_previous_outputs": texts}
    validate_record(phase, record["context"])
    if not isinstance(record["output"], str) or record["output_sha256"] != sha(record["output"]) or record["prompt_sha256"] != record["context"]["prompt_sha256"] or not isinstance(record["usage"], dict) or not isinstance(record["raw"], dict) or (record["dispatched"] is not None and type(record["dispatched"]) is not bool) or not isinstance(record["error"], str):
        raise ValueError("Повреждён результат или расход прохода.")
    for key in ("started_at", "finished_at"):
        if record[key] is not None:
            datetime.fromisoformat(record[key])
    if record["elapsed_seconds"] is not None and not _numeric(record["elapsed_seconds"]):
        raise ValueError("Повреждено время прохода.")
    if protocol.get("version") == "three-pass-v4" and record["index"] == 2:
        from .checkpoint_runtime import validate_assembled_record
        validate_assembled_record(parent, record)


def validate_backup(db):
    for row in db.execute("SELECT id,plan,status,output,raw,usage FROM runs"):
        plan = json.loads(row["plan"])
        if not plan.get("research_protocol"):
            continue
        records = [json.loads(item[0]) for item in db.execute("SELECT record FROM agent_phases WHERE run_id=? ORDER BY phase_index", (row["id"],))]
        if plan["research_protocol"].get("version") == "editor-resume-v1":
            from .checkpoint_runtime import validate_completed_run
            validate_completed_run(db, row, plan, records)
            continue
        if (plan["research_protocol"].get("version") == "three-pass-v4" and
                json.loads(row["usage"]) != aggregate_usage(plan["provider"], records)):
            raise ValueError("Расход компактного исследования отличается от журнала вызовов.")
        if row["status"] == "completed":
            from .applied_analysis import validate_final
            if len(records) != 3 or any(item["status"] != "completed" for item in records) or records[-1]["output"] != row["output"]:
                raise ValueError("Завершённый отчёт требует три завершённых прохода.")
            expected = validate_final(plan, [item["output"] for item in records])
            review = (json.loads(row["raw"]).get("orchestration") or {}).get("review")
            if expected.get("status") != "ready" or expected != review or aggregate_usage(plan["provider"], records) != json.loads(row["usage"]):
                raise ValueError("Проверка или суммарный расход отчёта не соответствуют журналу.")
            if plan["research_protocol"].get("version") == "three-pass-v4":
                assembly = records[2]["raw"].get("editor_assembly")
                if json.loads(row["raw"]).get("editor_assembly") != assembly:
                    raise ValueError("Сборка общего результата отличается от журнала редактора.")
    if db.execute("PRAGMA foreign_key_check").fetchone():
        raise ValueError("Нарушены связи журнала проходов.")
