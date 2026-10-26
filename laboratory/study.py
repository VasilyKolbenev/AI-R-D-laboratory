"""Frozen business-task context for source analysis, never a benchmark runner.

All records are owner-entered versioned task descriptions. Expected effects and
external evidence labels are not observations measured by the laboratory.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import re
from urllib.parse import urlsplit
import uuid


TABLES = ("study_task_revisions",)
MAX_CONTEXT_CHARS = 24000
TASK_TYPES = (
    ("exploratory", "Обзор и поиск исследовательского направления"),
    ("classification", "Классификация и маршрутизация"),
    ("extraction", "Извлечение и структурирование данных"),
    ("generation", "Генерация текста, кода или другого результата"),
    ("retrieval", "Поиск, RAG и память"),
    ("reasoning", "Рассуждение, решение и планирование"),
    ("tool_use", "Агенты и использование инструментов"),
    ("multimodal", "Мультимодальная задача"),
    ("other", "Другая прикладная задача в области ИИ"),
)
EVIDENCE_LEVELS = (
    ("unknown", "Данных пока нет"),
    ("hypothesis", "Гипотеза для проверки"),
    ("author_claim", "Заявление автора источника"),
    ("external_measurement", "Измерение внешнего исследования"),
    ("estimate", "Оценка или прогноз"),
)
TOP_LIMITS = {"title": 200, "business_goal": 2000, "beneficiary": 1000,
              "research_question": 3000, "inputs": 2000, "expected_output": 2000,
              "constraints": 2500, "dataset": 2000, "evaluation": 2500,
              "success_criteria": 2000}
BASELINE_LIMITS = {"name": 200, "version": 160, "description": 2500, "limitations": 2000}
CANDIDATE_LIMITS = {"name": 200, "version": 160, "description": 2000, "applicability": 2000,
                    "advantages": 1600, "limitations": 2000}
METRIC_LIMITS = {"name": 160, "definition": 1500, "unit": 120, "target": 1000, "expected": 1500}
SELF_HOSTED_LIMITS = {"model": 300, "license": 1000, "runtime": 1000, "cpu": 600,
                      "ram": 600, "gpu": 1000, "vram": 600, "disk": 600,
                      "context": 600, "concurrency": 600, "dependencies": 1800,
                      "operations": 2000, "cost": 1200, "candidate_profiles": 4000}
DIRECTIONS = {"maximize", "minimize", "descriptive"}
AVAILABILITY = {"unknown", "available", "unavailable", "not_applicable"}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _text(value, name, maximum, required=False):
    if not isinstance(value, str):
        raise ValueError(f"{name}: нужен текст, неизвестное значение можно оставить пустым.")
    value = value.replace("\r\n", "\n").strip()
    if len(value) > maximum or (required and not value):
        raise ValueError(f"{name}: допустимо от {1 if required else 0} до {maximum} символов.")
    return value


def _object(value, allowed, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label}: нужен объект.")
    if set(value) - set(allowed):
        raise ValueError(f"{label}: обнаружены неизвестные поля.")
    return value


def _fields(value, limits, label):
    return {key: _text(value.get(key, ""), label + ": " + key, maximum) for key, maximum in limits.items()}


def _enum(value, allowed, label):
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{label}: неизвестное значение.")
    return value


def _url(value, label):
    value = _text(value, label, 3000)
    if not value:
        return ""
    try:
        parts = urlsplit(value)
        host = parts.hostname
        if (parts.scheme not in {"http", "https"} or not host or parts.username or parts.password
                or parts.port not in {None, 80, 443} or any(character.isspace() for character in value)):
            raise ValueError()
        if host.casefold() in {"localhost", "localhost.localdomain"} or host.casefold().endswith((".local", ".localhost", ".internal")):
            raise ValueError()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if "." not in host or host.endswith("."):
                raise ValueError()
        else:
            if not address.is_global:
                raise ValueError()
    except ValueError:
        raise ValueError(f"{label}: нужна публичная ссылка http:// или https:// без логина и пароля.") from None
    return value


def _evidence(value, label):
    return {"evidence_level": _enum(value.get("evidence_level", "unknown"), {key for key, _ in EVIDENCE_LEVELS}, label + ": уровень доказательств"),
            "evidence_url": _url(value.get("evidence_url", ""), label + ": источник")}


def _template():
    value = {key: "" for key in TOP_LIMITS}
    value.update(title="Обзор источников об ИИ", task_type="exploratory",
                 baseline={key: "" for key in BASELINE_LIMITS}, candidates=[], metrics=[],
                 self_hosted={**{key: "" for key in SELF_HOSTED_LIMITS}, "availability": "unknown",
                              "evidence_level": "unknown", "evidence_url": ""})
    return value


def schema():
    return {"schema_version": 1, "execution_mode": "source_analysis", "template": _template(),
            "task_types": [{"id": key, "label": label} for key, label in TASK_TYPES],
            "evidence_levels": [{"id": key, "label": label} for key, label in EVIDENCE_LEVELS],
            "directions": [{"id": key, "label": label} for key, label in (("maximize", "Больше — лучше"), ("minimize", "Меньше — лучше"), ("descriptive", "Описательная метрика"))],
            "self_hosted_availability": [{"id": key, "label": label} for key, label in (("unknown", "Пока неизвестно"), ("available", "Доступно по имеющимся данным"), ("unavailable", "Недоступно"), ("not_applicable", "Неприменимо"))],
            "limits": {"context_chars": MAX_CONTEXT_CHARS, "candidates": 5, "metrics": 8,
                       "top": dict(TOP_LIMITS), "baseline": dict(BASELINE_LIMITS),
                       "candidate": dict(CANDIDATE_LIMITS), "metric": dict(METRIC_LIMITS),
                       "self_hosted": dict(SELF_HOSTED_LIMITS)},
            "notice": "Это контекст анализа источников. Лаборатория пока не исполняет бенчмарки и не измеряет ожидаемые эффекты."}


def _body(value, require_baseline=False):
    value = _object(value, set(TOP_LIMITS) | {"task_type", "baseline", "candidates", "metrics", "self_hosted"}, "Задача")
    result = _fields(value, TOP_LIMITS, "Задача")
    result["title"] = result["title"] or "Обзор источников об ИИ"
    result["task_type"] = _enum(value.get("task_type", "exploratory"), {key for key, _ in TASK_TYPES}, "Тип задачи")
    baseline = _object(value.get("baseline", {}), BASELINE_LIMITS, "Baseline")
    result["baseline"] = _fields(baseline, BASELINE_LIMITS, "Baseline")
    if require_baseline and result["task_type"] != "exploratory" and not result["baseline"]["name"]:
        raise ValueError("Для прикладной задачи укажите baseline: с каким текущим решением сравнивать. Если он неизвестен, сначала сохраните обзорную задачу.")
    candidates = value.get("candidates", [])
    if not isinstance(candidates, list) or len(candidates) > 5:
        raise ValueError("Допустимо не более 5 кандидатов.")
    result["candidates"] = []
    for index, item in enumerate(candidates):
        label = f"Кандидат {index + 1}"
        item = _object(item, set(CANDIDATE_LIMITS) | {"evidence_level", "evidence_url"}, label)
        candidate = {**_fields(item, CANDIDATE_LIMITS, label), **_evidence(item, label)}
        if not candidate["name"]:
            raise ValueError(label + ": укажите название или удалите пустую строку.")
        result["candidates"].append(candidate)
    metrics = value.get("metrics", [])
    if not isinstance(metrics, list) or len(metrics) > 8:
        raise ValueError("Допустимо не более 8 метрик.")
    result["metrics"] = []
    for index, item in enumerate(metrics):
        label = f"Метрика {index + 1}"
        item = _object(item, set(METRIC_LIMITS) | {"direction", "primary", "evidence_level", "evidence_url"}, label)
        metric = {**_fields(item, METRIC_LIMITS, label), **_evidence(item, label),
                  "direction": _enum(item.get("direction", "descriptive"), DIRECTIONS, label + ": направление")}
        if not metric["name"]:
            raise ValueError(label + ": укажите название или удалите пустую строку.")
        if type(item.get("primary", False)) is not bool:
            raise ValueError(label + ": primary должен быть boolean.")
        metric["primary"] = item.get("primary", False)
        result["metrics"].append(metric)
    if result["metrics"] and sum(item["primary"] for item in result["metrics"]) != 1:
        raise ValueError("Если заданы метрики, выберите ровно одну основную.")
    self_hosted = _object(value.get("self_hosted", {}), set(SELF_HOSTED_LIMITS) | {"availability", "evidence_level", "evidence_url"}, "Self-hosted")
    result["self_hosted"] = {**_fields(self_hosted, SELF_HOSTED_LIMITS, "Self-hosted"), **_evidence(self_hosted, "Self-hosted"),
                             "availability": _enum(self_hosted.get("availability", "unknown"), AVAILABILITY, "Доступность self-hosted")}
    if len(_json(result)) > MAX_CONTEXT_CHARS:
        raise ValueError("Контекст задачи превышает 24 000 символов. Сократите описания; скрытого обрезания не будет.")
    return result


def _notices(body):
    notices = ["Режим: анализ источников. Цели и ожидаемые эффекты не являются измерениями лаборатории."]
    unknowns = [("business_goal", "бизнес-цель"), ("beneficiary", "пользователь результата"),
                ("inputs", "входные данные"), ("expected_output", "ожидаемый результат"),
                ("dataset", "датасет или набор проверочных примеров"), ("evaluation", "методика оценки"),
                ("success_criteria", "критерии успеха")]
    missing = [label for field, label in unknowns if not body[field]]
    if missing:
        notices.append("Пока не определены: " + "; ".join(missing) + ".")
    if not body["baseline"]["name"]:
        notices.append("Baseline пока не определён: количественное сравнение с текущим решением не подготовлено.")
    if not body["metrics"]:
        notices.append("Метрики не заданы: вывод может быть только качественным анализом источников.")
    for candidate in body["candidates"]:
        if not candidate["applicability"]:
            notices.append(f"Для кандидата «{candidate['name']}» не описана применимость к задаче.")
    for label, entry in [("Кандидат «" + item["name"] + "»", item) for item in body["candidates"]] + [("Метрика «" + item["name"] + "»", item) for item in body["metrics"]] + [("Self-hosted", body["self_hosted"])]:
        if entry["evidence_level"] in {"author_claim", "external_measurement"} and not entry["evidence_url"]:
            notices.append(label + ": уровень доказательств указан без ссылки; утверждение требует проверки.")
    for metric in body["metrics"]:
        if not metric["definition"] or not metric["unit"]:
            notices.append(f"Метрика «{metric['name']}»: не заданы определение или единица; сопоставимость не подтверждена.")
        if metric["expected"] and metric["evidence_level"] == "unknown":
            notices.append(f"Ожидаемый эффект для «{metric['name']}» не имеет указанного основания и остаётся непроверенным ожиданием.")
    if body["self_hosted"]["availability"] == "unknown":
        notices.append("Доступность self-hosted и его требования пока неизвестны; аппаратная конфигурация не рассчитана.")
    elif body["self_hosted"]["availability"] == "available" and not body["self_hosted"]["model"]:
        notices.append("Self-hosted отмечен доступным, но модель или вариант не указаны; доступность нужно уточнить.")
    if len(body["candidates"]) > 1 and body["self_hosted"]["availability"] == "available" and not body["self_hosted"]["candidate_profiles"]:
        notices.append("Для разных кандидатов не разделены self-hosted-профили; единые требования нельзя считать подтверждёнными для всех вариантов.")
    return notices


def _snapshot(body, task_id=None, task_version=None):
    notices = _notices(body)
    if task_id is None:
        notices.insert(0, "Сохранённая задача не выбрана. Этот контекст самостоятельный; применимость к конкретному бизнес-процессу не установлена автоматически.")
    value = {"schema_version": 1, "execution_mode": "source_analysis", "task_id": task_id,
             "task_version": task_version, "task": deepcopy(body), "notices": notices}
    value["hash"] = _digest(value)
    if len(_json(value)) > MAX_CONTEXT_CHARS:
        raise ValueError("Полный контекст с пояснениями превышает 24 000 символов. Сократите описания перед сохранением плана.")
    return value


def query_text(snapshot):
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("task"), dict):
        return ""
    body = snapshot["task"]
    pieces = [body.get(key, "") for key in ("title", "business_goal", "beneficiary", "task_type", "research_question", "expected_output")]
    baseline = body.get("baseline") or {}
    pieces.append(str(baseline.get("name", "")))
    pieces.extend(str(item.get("name", "")) + " " + str(item.get("applicability", "")) for item in body.get("candidates", []) if isinstance(item, dict))
    pieces.extend(str(item.get("name", "")) for item in body.get("metrics", []) if isinstance(item, dict))
    return "\n".join(str(piece) for piece in pieces if piece)[:2000]


class Study:
    def __init__(self, store):
        self.store = store

    def initialize(self):
        with self.store.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS study_task_revisions(task_id TEXT NOT NULL,version INTEGER NOT NULL CHECK(version>0),body TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('active','archived')),created_at TEXT NOT NULL,PRIMARY KEY(task_id,version))")

    schema = staticmethod(schema)
    query_text = staticmethod(query_text)

    @staticmethod
    def has_user_data(db):
        return bool(db.execute("SELECT 1 FROM study_task_revisions LIMIT 1").fetchone())

    @staticmethod
    def _item(row):
        value = dict(row)
        value["id"] = value.pop("task_id")
        value["body"] = json.loads(value["body"])
        value["notices"] = _notices(value["body"])
        return value

    def tasks(self):
        with self.store.connect() as db:
            return [self._item(row) for row in db.execute("SELECT r.* FROM study_task_revisions r WHERE r.version=(SELECT max(x.version) FROM study_task_revisions x WHERE x.task_id=r.task_id) ORDER BY r.created_at DESC,r.task_id")]

    def task(self, task_id):
        if not isinstance(task_id, str):
            raise ValueError("Некорректный идентификатор задачи.")
        with self.store.connect() as db:
            rows = db.execute("SELECT * FROM study_task_revisions WHERE task_id=? ORDER BY version DESC", (task_id,)).fetchall()
            if not rows:
                raise ValueError("Задача не найдена.")
            value = self._item(rows[0])
            value["history"] = [self._item(row) for row in rows]
            return value

    def save(self, values):
        values = _object(values, {"id", "expected_version", "status", "body"}, "Сохранение задачи")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task_id = values.get("id")
            if task_id == "":
                task_id = None
            if task_id is not None and (not isinstance(task_id, str) or not re.fullmatch(r"[0-9a-f]{32}", task_id)):
                raise ValueError("Некорректный идентификатор задачи.")
            current = db.execute("SELECT * FROM study_task_revisions WHERE task_id=? ORDER BY version DESC LIMIT 1", (task_id,)).fetchone() if task_id else None
            if task_id and not current:
                raise ValueError("Задача не найдена. Обновите список.")
            expected = values.get("expected_version", 0)
            version = current["version"] if current else 0
            if type(expected) is not int or expected != version:
                raise ValueError("Задача уже изменена. Откройте последнюю версию перед сохранением.")
            status = _enum(values.get("status", current["status"] if current else "active"), {"active", "archived"}, "Статус задачи")
            previous_body = json.loads(current["body"]) if current else _template()
            body = _body(values.get("body", previous_body), require_baseline=status == "active")
            task_id = task_id or uuid.uuid4().hex
            _snapshot(body, task_id, version + 1)
            db.execute("INSERT INTO study_task_revisions VALUES (?,?,?,?,?)", (task_id, version + 1, _json(body), status, _now()))
            row = db.execute("SELECT * FROM study_task_revisions WHERE task_id=? AND version=?", (task_id, version + 1)).fetchone()
            return self._item(row)

    def snapshot(self, values):
        if not isinstance(values, dict):
            raise ValueError("Нужны параметры контекста исследования.")
        task_id = values.get("task_id")
        if task_id == "":
            task_id = None
        if task_id is not None:
            if not isinstance(task_id, str):
                raise ValueError("Некорректный идентификатор задачи.")
            if values.get("study_task") is not None:
                raise ValueError("Выберите сохранённую задачу или самостоятельный контекст, а не оба сразу.")
            with self.store.connect() as db:
                row = db.execute("SELECT * FROM study_task_revisions WHERE task_id=? ORDER BY version DESC LIMIT 1", (task_id,)).fetchone()
                if not row or row["status"] != "active":
                    raise ValueError("Выбранная задача не найдена или архивирована. Выберите активную задачу.")
                if "task_version" in values and (type(values["task_version"]) is not int or values["task_version"] != row["version"]):
                    raise ValueError("Версия выбранной задачи изменилась. Обновите контекст перед созданием плана.")
                return _snapshot(_body(json.loads(row["body"]), require_baseline=True), task_id, row["version"])
        if values.get("task_version") is not None:
            raise ValueError("Версия задачи указана без идентификатора.")
        if "study_task" in values:
            body = _body(values["study_task"], require_baseline=True)
        else:
            body = _template()
            body["research_question"] = _text(values.get("question", ""), "Вопрос исследования", 3000)
        return _snapshot(body)

    def validate(self, db, snapshot):
        if not isinstance(snapshot, dict) or set(snapshot) != {"schema_version", "execution_mode", "task_id", "task_version", "task", "notices", "hash"}:
            raise ValueError("В плане отсутствует корректный контекст задачи. Пересоберите план.")
        if type(snapshot["schema_version"]) is not int or snapshot["schema_version"] != 1 or snapshot["execution_mode"] != "source_analysis":
            raise ValueError("Поддержан только контекст анализа источников, без исполнения эксперимента.")
        body = {key: value for key, value in snapshot.items() if key != "hash"}
        if snapshot["hash"] != _digest(body):
            raise ValueError("Хеш контекста не совпал. Пересоберите план.")
        task = _body(snapshot["task"], require_baseline=True)
        if task != snapshot["task"]:
            raise ValueError("Форма замороженного контекста повреждена.")
        task_id, version = snapshot["task_id"], snapshot["task_version"]
        if task_id is None:
            if version is not None:
                raise ValueError("Версия задачи указана без идентификатора.")
        else:
            if not isinstance(task_id, str) or type(version) is not int:
                raise ValueError("Некорректная ссылка на задачу.")
            current = db.execute("SELECT * FROM study_task_revisions WHERE task_id=? ORDER BY version DESC LIMIT 1", (task_id,)).fetchone()
            if not current or current["status"] != "active" or current["version"] != version or json.loads(current["body"]) != task:
                raise ValueError("Задача изменена или архивирована после предпросмотра. Пересоберите контекст и подтвердите новый план.")
        if _snapshot(task, task_id, version) != snapshot:
            raise ValueError("Пояснения или размер контекста не соответствуют задаче. Пересоберите план.")


def validate_backup_table(table, row, db):
    if table != TABLES[0] or not isinstance(row, dict) or set(row) != {"task_id", "version", "body", "status", "created_at"}:
        raise ValueError("Повреждена структура задач в резервной копии.")
    if not isinstance(row["task_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", row["task_id"]):
        raise ValueError("Повреждён идентификатор задачи.")
    if type(row["version"]) is not int or row["version"] < 1:
        raise ValueError("Повреждена версия задачи.")
    status = _enum(row["status"], {"active", "archived"}, "Статус задачи")
    if not isinstance(row["created_at"], str) or len(row["created_at"]) > 60:
        raise ValueError("Повреждена дата версии задачи.")
    datetime.fromisoformat(row["created_at"])
    if not isinstance(row["body"], str) or len(row["body"]) > MAX_CONTEXT_CHARS:
        raise ValueError("Некорректный размер контекста задачи.")
    original = json.loads(row["body"])
    body = _body(original, require_baseline=status == "active")
    if body != original:
        raise ValueError("Неполная или повреждённая форма задачи.")
    _snapshot(body, row["task_id"], row["version"])


def validate_backup(db):
    for minimum, maximum, count in db.execute("SELECT min(version),max(version),count(*) FROM study_task_revisions GROUP BY task_id"):
        if minimum != 1 or maximum != count:
            raise ValueError("История версий задачи неполна.")
    for row in db.execute("SELECT plan FROM runs"):
        plan = json.loads(row[0])
        frozen = plan.get("study_context")
        if frozen is None:
            continue  # Historical reports from the preceding release keep their hashes.
        if not isinstance(frozen, dict) or set(frozen) != {"schema_version", "execution_mode", "task_id", "task_version", "task", "notices", "hash"}:
            raise ValueError("Повреждён замороженный контекст исследования.")
        task = _body(frozen["task"], require_baseline=True)
        task_id, version = frozen["task_id"], frozen["task_version"]
        if task_id is not None:
            if not isinstance(task_id, str) or type(version) is not int:
                raise ValueError("Повреждена ссылка на историческую задачу.")
            original = db.execute("SELECT body FROM study_task_revisions WHERE task_id=? AND version=?", (task_id, version)).fetchone()
            if not original or json.loads(original[0]) != task:
                raise ValueError("Не найдена исходная версия задачи исследования.")
        elif version is not None:
            raise ValueError("Версия контекста не связана с задачей.")
        if _snapshot(task, task_id, version) != frozen:
            raise ValueError("Контрольная сумма или форма контекста исследования не совпала.")
