"""Owner-reviewed, versioned lessons with explicit evidence and applicability.

Selection and validation are local and deterministic. Evidence links describe
provenance; this module never verifies a scientific claim or calls a model.
"""
from datetime import date, datetime, timezone
import ipaddress
import json
import re
from urllib.parse import urlsplit
import uuid

from .memory import _tokens


TABLES = ("lesson_revisions",)
MAX_SNAPSHOT_CHARS = 6000
MAX_SELECTED = 3
MAX_BODY_CHARS = 42000
FIELD_LIMITS = {"title": 200, "problem": 1000, "rule": 1800,
                "evidence_note": 1200, "applies_when": 1000,
                "not_applicable_when": 1000, "limitations": 1000}
STATUSES = {"draft", "active", "retired"}
EVIDENCE_LEVELS = {"hypothesis", "source_analysis", "external_measurement"}
ITEM_FIELDS = {"id", "version", "status", "body", "created_at", "stale"}
CONTEXT_OMISSION_NOTICE = "Из-за лимита 6 000 символов часть предложенных уроков не включена. Выберите меньше уроков или сократите их текст."


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _today():
    return datetime.now(timezone.utc).date()


def _object(value, allowed, label):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ValueError(label + ": нужен объект без неизвестных полей.")
    return value


def _text(value, label, maximum, required=False):
    if not isinstance(value, str):
        raise ValueError(label + ": нужен текст.")
    value = value.replace("\r\n", "\n").strip()
    if len(value) > maximum or (required and not value):
        raise ValueError(f"{label}: допустимо от {1 if required else 0} до {maximum} символов.")
    return value


def _id(value, label, optional=False):
    if optional and value in (None, ""):
        return ""
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
        raise ValueError(label + ": некорректный идентификатор.")
    return value


def _ids(value, maximum, label):
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"{label}: допустимо не более {maximum} идентификаторов.")
    return list(dict.fromkeys(_id(item, label) for item in value))


def _enum(value, allowed, label):
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(label + ": неизвестное значение.")
    return value


def _review_date(value, required=False):
    value = _text(value, "Дата пересмотра", 10, required)
    if value:
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError()
            date.fromisoformat(value)
        except ValueError:
            raise ValueError("Дата пересмотра: нужен формат YYYY-MM-DD.") from None
    return value


def _url(value):
    value = _text(value, "Ссылка доказательства", 3000, True)
    try:
        parts = urlsplit(value)
        host = parts.hostname
        if (parts.scheme not in {"http", "https"} or not host or parts.username
                or parts.password or parts.port not in {None, 80, 443}
                or any(character.isspace() or ord(character) < 32 for character in value)
                or "\\" in value or "%" in host):
            raise ValueError()
        if host.casefold() in {"localhost", "localhost.localdomain"} or host.casefold().endswith((".local", ".localhost", ".internal")):
            raise ValueError()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            labels = host.encode("idna").decode("ascii").casefold().split(".")
            if (len(host) > 253 or len(labels) < 2
                    or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels)
                    or all(re.fullmatch(r"(?:0x[0-9a-f]+|[0-9]+)", label) for label in labels)):
                raise ValueError()
        else:
            if not address.is_global:
                raise ValueError()
    except ValueError:
        raise ValueError("Нужна публичная ссылка http:// или https:// без логина и пароля.") from None
    return value


def _template():
    return {**{key: "" for key in FIELD_LIMITS}, "review_at": "", "task_id": "",
            "knowledge_id": "", "evidence_run_id": "", "evidence_source_ids": [],
            "evidence_urls": [], "evidence_level": "hypothesis"}


def schema():
    return {"schema_version": 1, "template": _template(),
            "statuses": [{"id": key, "label": label} for key, label in
                         (("draft", "Черновик"), ("active", "Активен"), ("retired", "Отозван"))],
            "evidence_levels": [{"id": key, "label": label} for key, label in
                                (("hypothesis", "Гипотеза"), ("source_analysis", "Анализ источников"),
                                 ("external_measurement", "Внешнее измерение"))],
            "limits": {"context_chars": MAX_SNAPSHOT_CHARS, "selected": MAX_SELECTED,
                       "evidence_sources": 6, "evidence_urls": 10, "url_chars": 3000,
                       "fields": dict(FIELD_LIMITS)},
            "notice": "Урок — проверяемое правило владельца с областью применимости. Ссылки не подтверждают истинность; лаборатория не выполняет измерения и не запускает проверку автоматически."}


def _body(value, status):
    value = _object(value, _template(), "Урок")
    active = status == "active"
    result = {key: _text(value.get(key, ""), key, limit,
                         active and key in {"rule", "evidence_note", "applies_when"})
              for key, limit in FIELD_LIMITS.items()}
    result["review_at"] = _review_date(value.get("review_at", ""), active)
    for key in ("task_id", "knowledge_id", "evidence_run_id"):
        result[key] = _id(value.get(key, ""), key, optional=True)
    result["evidence_source_ids"] = _ids(value.get("evidence_source_ids", []), 6, "Источники доказательства")
    urls = value.get("evidence_urls", [])
    if not isinstance(urls, list) or len(urls) > 10:
        raise ValueError("Допустимо не более 10 публичных ссылок доказательств.")
    result["evidence_urls"] = list(dict.fromkeys(_url(item) for item in urls))
    result["evidence_level"] = _enum(value.get("evidence_level", "hypothesis"), EVIDENCE_LEVELS, "Уровень доказательств")
    if len(_json(result)) > MAX_BODY_CHARS:
        raise ValueError("Урок превышает допустимый размер. Сократите поля или ссылки.")
    return result


def _crosslinks(db, body, status):
    """Check provenance membership, without interpreting evidence text."""
    task_id, run_id = body["task_id"], body["evidence_run_id"]
    if task_id and not db.execute("SELECT 1 FROM study_task_revisions WHERE task_id=?", (task_id,)).fetchone():
        raise ValueError("Связанная задача урока не найдена.")
    run = db.execute("SELECT status,plan FROM runs WHERE id=?", (run_id,)).fetchone() if run_id else None
    if run_id and (not run or run["status"] != "completed"):
        raise ValueError("Доказательство урока должно ссылаться на завершённое исследование.")
    source_ids = body["evidence_source_ids"]
    for source_id in source_ids:
        if not db.execute("SELECT 1 FROM sources WHERE id=?", (source_id,)).fetchone():
            raise ValueError("Источник доказательства урока не найден.")
    if run:
        plan = json.loads(run["plan"])
        allowed = {item["id"] for item in plan.get("sources", []) if isinstance(item, dict) and isinstance(item.get("id"), str)}
        if any(source_id not in allowed for source_id in source_ids):
            raise ValueError("Источники урока не принадлежат указанному исследованию.")
    if status == "active":
        if source_ids and not run:
            raise ValueError("Для источников активного урока укажите завершённое исследование.")
        if not ((run and source_ids) or body["evidence_urls"]):
            raise ValueError("Для активного урока нужны источники завершённого исследования или публичные ссылки доказательств.")
    knowledge_id = body["knowledge_id"]
    if knowledge_id:
        knowledge = db.execute("SELECT run_id FROM knowledge WHERE id=?", (knowledge_id,)).fetchone()
        if not knowledge or (run_id and knowledge["run_id"] != run_id):
            raise ValueError("Знание урока не найдено или связано с другим исследованием.")
        if status == "active" and not run_id:
            raise ValueError("Для связанного знания активного урока укажите его исследование.")


def _item(row):
    value = dict(row)
    value["body"] = json.loads(value["body"])
    review_at = value["body"]["review_at"]
    value["stale"] = bool(review_at and date.fromisoformat(review_at) <= _today())
    return value


def _latest(db):
    return [_item(row) for row in db.execute(
        "SELECT r.* FROM lesson_revisions r WHERE r.version=(SELECT max(x.version) FROM lesson_revisions x WHERE x.id=r.id) ORDER BY r.created_at DESC,r.id")]


def has_user_data(db):
    return bool(db.execute("SELECT 1 FROM lesson_revisions LIMIT 1").fetchone())


class Lessons:
    def __init__(self, store):
        self.store = store

    def initialize(self):
        with self.store.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS lesson_revisions(id TEXT NOT NULL,version INTEGER NOT NULL CHECK(version>0),body TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('draft','active','retired')),created_at TEXT NOT NULL,PRIMARY KEY(id,version))")

    schema = staticmethod(schema)
    has_user_data = staticmethod(has_user_data)

    def list(self):
        with self.store.connect() as db:
            return _latest(db)

    def get(self, lesson_id):
        lesson_id = _id(lesson_id, "Урок")
        with self.store.connect() as db:
            rows = db.execute("SELECT * FROM lesson_revisions WHERE id=? ORDER BY version DESC", (lesson_id,)).fetchall()
            if not rows:
                raise ValueError("Урок не найден.")
            value = _item(rows[0])
            value["history"] = [_item(row) for row in rows]
            return value

    def save(self, values):
        values = _object(values, {"id", "expected_version", "status", "body"}, "Сохранение урока")
        lesson_id = _id(values.get("id"), "Урок", optional=True)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT * FROM lesson_revisions WHERE id=? ORDER BY version DESC LIMIT 1", (lesson_id,)).fetchone() if lesson_id else None
            if lesson_id and not current:
                raise ValueError("Урок не найден. Обновите список.")
            version = current["version"] if current else 0
            if type(values.get("expected_version", 0)) is not int or values.get("expected_version", 0) != version:
                raise ValueError("Урок уже изменён. Откройте последнюю версию перед сохранением.")
            status = _enum(values.get("status", current["status"] if current else "draft"), STATUSES, "Статус урока")
            body = _body(values.get("body", json.loads(current["body"]) if current else _template()), status)
            _crosslinks(db, body, status)
            lesson_id = lesson_id or uuid.uuid4().hex
            db.execute("INSERT INTO lesson_revisions VALUES (?,?,?,?,?)", (lesson_id, version + 1, _json(body), status, _now()))
            return _item(db.execute("SELECT * FROM lesson_revisions WHERE id=? AND version=?", (lesson_id, version + 1)).fetchone())

    def _preview(self, db, values):
        if not isinstance(values, dict):
            raise ValueError("Нужны параметры выбора уроков.")
        options = values.get("memory_options", {})
        if options is None:
            options = {}
        if not isinstance(options, dict):
            raise ValueError("Параметры памяти должны быть объектом.")
        selected = _ids(options["lesson_ids"], MAX_SELECTED, "Выбранные уроки") if "lesson_ids" in options else None
        question = _text(values.get("question", ""), "Вопрос исследования", 3000)
        study_context = values.get("study_context") or {}
        if not isinstance(study_context, dict):
            raise ValueError("Контекст задачи должен быть объектом.")
        task_id = values.get("task_id") or study_context.get("task_id") or ""
        task_id = _id(task_id, "Задача", optional=True)
        query = set(_tokens(question))
        all_items = _latest(db)
        indexed = {item["id"]: item for item in all_items}
        for lesson_id in selected or []:
            if lesson_id not in indexed or indexed[lesson_id]["status"] != "active":
                raise ValueError("Выбранный урок не найден, отозван или остался черновиком. Обновите выбор.")
        candidates = []
        for item in all_items:
            if item["status"] != "active":
                continue
            body = item["body"]
            overlap = sorted(query.intersection(_tokens(" ".join(body[key] for key in FIELD_LIMITS))))
            same_task = bool(task_id and body["task_id"] == task_id)
            different_task = bool(task_id and body["task_id"] and body["task_id"] != task_id)
            item["score"] = len(overlap) + (5 if same_task else 0)
            item["reason"] = ("Та же прикладная задача. " if same_task else "") + ("Совпадение слов: " + ", ".join(overlap[:5]) if overlap else "Тематическое совпадение не найдено")
            if different_task:
                item["score"] = 0
                item["reason"] = "Урок связан с другой прикладной задачей; применимость требует проверки."
            candidates.append(item)
        candidates.sort(key=lambda item: (item["id"] not in (selected or []), -item["score"], item["id"]))
        suggested, suggested_items, suggested_omitted = [], [], False
        for item in candidates:
            if len(suggested) == MAX_SELECTED:
                break
            if item["score"] <= 0 or item["stale"]:
                continue
            frozen = {key: item[key] for key in ITEM_FIELDS}
            proposed = {"items": [*suggested_items, frozen], "notices": [CONTEXT_OMISSION_NOTICE]}
            if len(_json(proposed)) > MAX_SNAPSHOT_CHARS:
                suggested_omitted = True
                continue
            suggested.append(item["id"])
            suggested_items.append(frozen)
        chosen = selected if selected is not None else suggested
        notices = [CONTEXT_OMISSION_NOTICE] if selected is None and suggested_omitted else []
        if any(indexed[lesson_id]["stale"] for lesson_id in chosen):
            notices.append("Срок пересмотра выбранного урока наступил. Его правило требует проверки перед применением.")
        if any(task_id and indexed[lesson_id]["body"]["task_id"] and indexed[lesson_id]["body"]["task_id"] != task_id for lesson_id in chosen):
            notices.append("Выбран урок другой задачи. Проверьте область применимости и ограничения.")
        visible_ids = set((selected or []) + suggested)
        visible = [item for item in candidates if item["id"] in visible_ids]
        visible.extend(item for item in candidates if item["id"] not in visible_ids)
        return {"items": visible[:12], "suggested_ids": suggested,
                "selected_ids": list(chosen), "notices": notices}

    def candidates(self, values):
        with self.store.connect() as db:
            db.execute("BEGIN")
            return self._preview(db, values)

    def snapshot(self, values):
        with self.store.connect() as db:
            db.execute("BEGIN")
            preview = self._preview(db, values)
            by_id = {item["id"]: item for item in preview["items"]}
            result = {"items": [], "notices": list(preview["notices"])}
            explicit = "lesson_ids" in (values.get("memory_options") or {})
            omitted = False
            # Reserve the one omission notice before checking each exact item.
            overflow_notice = CONTEXT_OMISSION_NOTICE
            for lesson_id in preview["selected_ids"]:
                item = {key: by_id[lesson_id][key] for key in ITEM_FIELDS}
                tentative = {"items": [*result["items"], item],
                             "notices": [*result["notices"], *([] if explicit or overflow_notice in result["notices"] else [overflow_notice])]}
                if len(_json(tentative)) > MAX_SNAPSHOT_CHARS:
                    if explicit:
                        raise ValueError("Выбранные уроки превышают лимит 6 000 символов. Уменьшите выбор или сократите текст; уроки не сокращаются автоматически.")
                    omitted = True
                    continue
                result["items"].append(item)
            if omitted and overflow_notice not in result["notices"]:
                result["notices"].append(overflow_notice)
            return result

    def validate(self, db, snapshot):
        """Reject changes between visible preview and approval, including UTC date rollover."""
        items = _snapshot_items(snapshot)
        for item in items:
            _frozen_shape(item)
            current = db.execute("SELECT * FROM lesson_revisions WHERE id=? ORDER BY version DESC LIMIT 1", (item["id"],)).fetchone()
            if not current or current["status"] != "active" or _item(current) != item:
                raise ValueError("Урок изменён, отозван или наступил срок пересмотра. Обновите предпросмотр и подтвердите новый план.")
            _crosslinks(db, item["body"], "active")


def _snapshot_items(snapshot):
    if isinstance(snapshot, list):
        items = snapshot
        bounded = {"items": items, "notices": []}
    else:
        if not isinstance(snapshot, dict) or set(snapshot) != {"items", "notices"}:
            raise ValueError("Повреждён снимок уроков.")
        items = snapshot["items"]
        notices = snapshot["notices"]
        if not isinstance(notices, list) or len(notices) > 10 or any(not isinstance(item, str) or len(item) > 1000 for item in notices):
            raise ValueError("Повреждены пояснения снимка уроков.")
        bounded = snapshot
    if not isinstance(items, list) or len(items) > MAX_SELECTED or len(_json(bounded)) > MAX_SNAPSHOT_CHARS:
        raise ValueError("Снимок уроков превышает лимит.")
    if len({item.get("id") for item in items if isinstance(item, dict) and isinstance(item.get("id"), str)}) != len(items):
        raise ValueError("Снимок уроков содержит повтор или повреждённую запись.")
    return items


def _frozen_shape(item):
    if not isinstance(item, dict) or set(item) != ITEM_FIELDS:
        raise ValueError("Повреждена форма замороженного урока.")
    _id(item["id"], "Урок")
    if type(item["version"]) is not int or item["version"] < 1 or type(item["stale"]) is not bool or item["status"] != "active":
        raise ValueError("Некорректная версия или статус замороженного урока.")
    if _body(item["body"], "active") != item["body"]:
        raise ValueError("Повреждён текст замороженного урока.")
    _timestamp(item["created_at"])


def _timestamp(value):
    if not isinstance(value, str) or len(value) > 60:
        raise ValueError("Повреждена дата версии урока.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("Повреждена дата версии урока.") from None
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("Дата версии урока должна быть в UTC.")


def validate_backup_table(table, row, db):
    if table != TABLES[0] or not isinstance(row, dict) or set(row) != {"id", "version", "body", "status", "created_at"}:
        raise ValueError("Повреждена структура уроков в резервной копии.")
    _id(row["id"], "Урок")
    if type(row["version"]) is not int or row["version"] < 1:
        raise ValueError("Повреждена версия урока.")
    status = _enum(row["status"], STATUSES, "Статус урока")
    _timestamp(row["created_at"])
    if not isinstance(row["body"], str) or len(row["body"]) > MAX_BODY_CHARS:
        raise ValueError("Некорректный размер текста урока.")
    original = json.loads(row["body"])
    body = _body(original, status)
    if body != original:
        raise ValueError("Неполная или повреждённая форма урока.")
    _crosslinks(db, body, status)


def validate_backup(db):
    for minimum, maximum, count in db.execute("SELECT min(version),max(version),count(*) FROM lesson_revisions GROUP BY id"):
        if minimum != 1 or maximum != count:
            raise ValueError("История версий урока неполна.")
    for row in db.execute("SELECT * FROM lesson_revisions"):
        validate_backup_table(TABLES[0], dict(row), db)
    for row in db.execute("SELECT plan FROM runs"):
        plan = json.loads(row[0])
        frozen = (plan.get("memory") or {}).get("lessons")
        if frozen is None:
            continue  # Earlier release plans remain byte-for-byte historical records.
        for item in _snapshot_items(frozen):
            _frozen_shape(item)
            original = db.execute("SELECT * FROM lesson_revisions WHERE id=? AND version=?", (item["id"], item["version"])).fetchone()
            if not original:
                raise ValueError("Не найдена исходная версия замороженного урока.")
            expected = _item(original)
            expected["stale"] = item["stale"]  # Historical staleness belongs to the approval date.
            if expected != item:
                raise ValueError("Снимок урока не совпадает с исходной версией.")
