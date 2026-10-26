"""Versioned local research memory. No embeddings, network or model calls.

Original knowledge/output rows remain immutable. Owner instructions, scientific
claims and model-proposed comparisons are stored and frozen as distinct objects.
"""
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import math
import re
from urllib.parse import urlsplit
import uuid


TABLES = ("memory_meta", "memory_profile_revisions", "memory_correction_revisions",
          "knowledge_revisions", "memory_review_ingestions", "memory_reviews",
          "memory_review_resolutions")
MAX_SNAPSHOT_CHARS = 16000
SCOPE = "Только ИИ и исследования непосредственно связанных передовых технологий."
STOP = set("the and for with from this that are was have has how what about into can not only data source sources study research это как что для при про или все без над под уже ещё еще его она они было быть также материал материалы исследование исследования источники новый новые этой этот этих which when where will than then your their those these our you but using use used of to in on by a an is it as at be we do ai ии".split())
ALIASES = {
    "topic_memory": ("memory", "памят", "retrieval", "rag", "извлеч", "поиск", "search"),
    "topic_agents": ("agent", "агент", "tooluse", "инструмент", "functioncall"),
    "topic_reasoning": ("reasoning", "рассужд", "логическ", "chainofthought"),
    "topic_models": ("llm", "языков", "language", "модел", "transformer", "трансформер"),
    "topic_training": ("training", "обучен", "finetun", "дообуч", "pretrain"),
    "topic_inference": ("inference", "инференс", "quantiz", "квантиз", "декодир", "decoding"),
    "topic_evaluation": ("evaluat", "оценк", "benchmark", "бенчмарк", "метрик"),
    "topic_multimodal": ("multimodal", "мультимодальн", "vision", "зрен", "аудио", "audio"),
}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _text(value, name, maximum, required=False):
    if not isinstance(value, str):
        raise ValueError(f"{name}: нужен текст.")
    value = value.strip()
    if len(value) > maximum or (required and not value):
        raise ValueError(f"{name}: допустимо от {1 if required else 0} до {maximum} символов.")
    return value


def _tags(value):
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, list) or len(value) > 12 or any(not isinstance(item, str) or len(item) > 40 for item in value):
        raise ValueError("Не более 12 текстовых тегов, до 40 символов каждый.")
    return list(dict.fromkeys(item.strip() for item in value if item.strip()))


def _ids(value, maximum=30):
    if not isinstance(value, list) or len(value) > maximum or any(not isinstance(item, str) or not item or len(item) > 100 for item in value):
        raise ValueError("Некорректный список идентификаторов.")
    return list(dict.fromkeys(value))


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Укажите дату следующей проверки в формате YYYY-MM-DD.")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValueError("Дата следующей проверки: YYYY-MM-DD.") from None
    return value


def _public_url(value):
    if not isinstance(value, str) or len(value) > 3000:
        return False
    try:
        parts = urlsplit(value)
        host = parts.hostname
        if parts.scheme not in {"http", "https"} or not host or parts.username or parts.password:
            return False
        if parts.port not in {None, 80, 443} or any(c.isspace() for c in value):
            return False
        if host.casefold() in {"localhost", "localhost.localdomain"} or host.casefold().endswith((".local", ".localhost", ".internal")):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return "." in host and not host.endswith(".")
    except ValueError:
        return False


def _tokens(text):
    words = re.findall(r"[^\W_]{2,}", str(text).casefold(), flags=re.UNICODE)
    result = []
    for word in words:
        if word in STOP:
            continue
        # Light lexical normalization, not a claim of linguistic stemming.
        stem = re.sub(r"(?:иями|ями|ами|ого|его|ому|ему|ение|ения|ений|ость|ости|ы|и|а|я|у|ю|е|ь)$", "", word) if re.search("[а-яё]", word) else re.sub(r"(?:ing|ers|ies|es|s)$", "", word)
        result.append(stem or word)
        for alias, prefixes in ALIASES.items():
            if any(word.startswith(prefix) for prefix in prefixes):
                result.append(alias)
    return result


def _initial_text(finding):
    body = re.sub(r"<lab_memory_review>.*?</lab_memory_review>", "", finding["output"], flags=re.S).strip()
    return {"title": finding["title"].strip()[:200] or "Сохранённое исследование",
            "claim": body[:4000] or finding["decision"].strip()[:4000] or "Требуется ручной пересмотр: текст вывода отсутствует.",
            "notes": finding["decision"][:4000]}


class Memory:
    def __init__(self, store):
        self.store = store

    def initialize(self):
        statements = (
            "CREATE TABLE IF NOT EXISTS memory_meta(id INTEGER PRIMARY KEY CHECK(id=1),generation INTEGER NOT NULL CHECK(generation>=0))",
            "CREATE TABLE IF NOT EXISTS memory_profile_revisions(version INTEGER PRIMARY KEY CHECK(version>0),interests TEXT NOT NULL,goals TEXT NOT NULL,preferences TEXT NOT NULL,review_days INTEGER NOT NULL CHECK(review_days BETWEEN 1 AND 365),created_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS memory_correction_revisions(id TEXT NOT NULL,version INTEGER NOT NULL CHECK(version>0),text TEXT NOT NULL,knowledge_id TEXT REFERENCES knowledge(id),active INTEGER NOT NULL CHECK(active IN (0,1)),created_at TEXT NOT NULL,PRIMARY KEY(id,version))",
            "CREATE TABLE IF NOT EXISTS knowledge_revisions(knowledge_id TEXT NOT NULL REFERENCES knowledge(id),version INTEGER NOT NULL CHECK(version>0),title TEXT NOT NULL,claim TEXT NOT NULL,notes TEXT NOT NULL,tags TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('active','retired')),review_at TEXT NOT NULL,evidence_run_id TEXT NOT NULL REFERENCES runs(id),source_ids TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(knowledge_id,version))",
            "CREATE TABLE IF NOT EXISTS memory_review_ingestions(run_id TEXT PRIMARY KEY REFERENCES runs(id),metadata TEXT NOT NULL,created_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS memory_reviews(id TEXT PRIMARY KEY,run_id TEXT NOT NULL REFERENCES runs(id),knowledge_id TEXT NOT NULL REFERENCES knowledge(id),memory_version INTEGER NOT NULL,relation TEXT NOT NULL CHECK(relation IN ('contradicts','supersedes','supports')),rationale TEXT NOT NULL,updated_claim TEXT NOT NULL,evidence_source_ids TEXT NOT NULL,evidence_urls TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(run_id,knowledge_id,memory_version,relation),FOREIGN KEY(knowledge_id,memory_version) REFERENCES knowledge_revisions(knowledge_id,version))",
            "CREATE TABLE IF NOT EXISTS memory_review_resolutions(review_id TEXT PRIMARY KEY REFERENCES memory_reviews(id),version INTEGER NOT NULL CHECK(version=2),action TEXT NOT NULL CHECK(action IN ('accept','dismiss')),knowledge_version INTEGER,created_at TEXT NOT NULL)",
        )
        with self.store.connect() as db:
            for statement in statements:
                db.execute(statement)
            db.execute("INSERT OR IGNORE INTO memory_meta VALUES (1,0)")
            db.execute("INSERT OR IGNORE INTO memory_profile_revisions VALUES (1,'','','',30,?)", (_now(),))
            db.execute("BEGIN IMMEDIATE") if not db.in_transaction else None
            self.seed_missing(db)

    def seed_missing(self, db):
        """Seed v1 findings inside the caller's transaction; no connection/commit."""
        rows = db.execute("SELECT * FROM knowledge WHERE id NOT IN (SELECT knowledge_id FROM knowledge_revisions)").fetchall()
        for row in rows:
            self._seed(db, row)
        if rows:
            self._bump(db)
        return len(rows)

    @staticmethod
    def _bump(db):
        db.execute("UPDATE memory_meta SET generation=generation+1 WHERE id=1")

    @staticmethod
    def _generation(db):
        return db.execute("SELECT generation FROM memory_meta WHERE id=1").fetchone()[0]

    @staticmethod
    def has_user_data(db):
        if db.execute("SELECT count(*) FROM memory_profile_revisions").fetchone()[0] > 1:
            return True
        return any(db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() for table in TABLES[2:])

    @staticmethod
    def _profile(db):
        value = dict(db.execute("SELECT * FROM memory_profile_revisions ORDER BY version DESC LIMIT 1").fetchone())
        value["scope"] = SCOPE
        value["trust"] = "owner_preferences_not_scientific_evidence"
        return value

    def profile(self):
        with self.store.connect() as db:
            return self._profile(db)

    def save_profile(self, body):
        if not isinstance(body, dict):
            raise ValueError("Нужен объект профиля.")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = self._profile(db)
            if type(body.get("expected_version")) is not int or body["expected_version"] != current["version"]:
                raise ValueError("Профиль уже изменился. Обновите страницу перед сохранением.")
            values = {key: _text(body.get(key, current[key]), key, 1000) for key in ("interests", "goals", "preferences")}
            days = body.get("review_days", current["review_days"])
            if type(days) is not int or not 1 <= days <= 365:
                raise ValueError("Срок пересмотра: от 1 до 365 дней.")
            db.execute("INSERT INTO memory_profile_revisions VALUES (?,?,?,?,?,?)", (current["version"] + 1, values["interests"], values["goals"], values["preferences"], days, _now()))
            self._bump(db)
            return self._profile(db)

    @staticmethod
    def _corrections(db):
        rows = db.execute("SELECT c.* FROM memory_correction_revisions c WHERE c.version=(SELECT max(x.version) FROM memory_correction_revisions x WHERE x.id=c.id) ORDER BY c.created_at DESC,c.id").fetchall()
        return [{**dict(row), "active": bool(row["active"]), "trust": "owner_correction_not_external_evidence"} for row in rows]

    def corrections(self):
        with self.store.connect() as db:
            return self._corrections(db)

    def save_correction(self, body):
        if not isinstance(body, dict):
            raise ValueError("Нужен объект поправки.")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            correction_id = body.get("id")
            old = db.execute("SELECT * FROM memory_correction_revisions WHERE id=? ORDER BY version DESC LIMIT 1", (correction_id,)).fetchone() if correction_id else None
            if correction_id and not old:
                raise ValueError("Поправка не найдена.")
            current = dict(old) if old else {"version": 0, "text": "", "knowledge_id": None, "active": True}
            if type(body.get("expected_version", 0)) is not int or body.get("expected_version", 0) != current["version"]:
                raise ValueError("Поправка уже изменена. Откройте последнюю версию.")
            text = _text(body.get("text", current["text"]), "Поправка", 1000, True)
            knowledge_id = body.get("knowledge_id", current["knowledge_id"]) or None
            if knowledge_id is not None and (not isinstance(knowledge_id, str) or not db.execute("SELECT 1 FROM knowledge WHERE id=?", (knowledge_id,)).fetchone()):
                raise ValueError("Запись знаний для поправки не найдена.")
            active = body.get("active", bool(current["active"]))
            if type(active) is not bool:
                raise ValueError("active должен быть boolean.")
            correction_id = correction_id or uuid.uuid4().hex
            db.execute("INSERT INTO memory_correction_revisions VALUES (?,?,?,?,?,?)", (correction_id, current["version"] + 1, text, knowledge_id, int(active), _now()))
            self._bump(db)
            return next(item for item in self._corrections(db) if item["id"] == correction_id)

    def _seed(self, db, finding):
        profile = self._profile(db)
        try:
            created = datetime.fromisoformat(finding["created_at"])
        except (ValueError, TypeError):
            created = datetime.now(timezone.utc)
        review_at = (created + timedelta(days=profile["review_days"])).date().isoformat()
        text = _initial_text(finding)
        db.execute("INSERT INTO knowledge_revisions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (finding["id"], 1, text["title"], text["claim"], text["notes"], finding["tags"], "active", review_at, finding["run_id"], finding["source_ids"], finding["created_at"]))

    def register_finding(self, knowledge_id):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM knowledge_revisions WHERE knowledge_id=?", (knowledge_id,)).fetchone():
                finding = db.execute("SELECT * FROM knowledge WHERE id=?", (knowledge_id,)).fetchone()
                if not finding:
                    raise ValueError("Запись базы знаний не найдена.")
                self._seed(db, finding)
                self._bump(db)
            return self._current(db, knowledge_id)

    @staticmethod
    def _revision(row):
        value = dict(row)
        value["id"] = value["knowledge_id"]
        value["tags"] = json.loads(value["tags"])
        value["source_ids"] = json.loads(value["source_ids"])
        try:
            created = datetime.fromisoformat(value["created_at"])
            created = created.replace(tzinfo=timezone.utc) if created.tzinfo is None else created
            value["age_days"] = max(0, (datetime.now(timezone.utc) - created).days)
        except ValueError:
            value["age_days"] = 0
        value["stale"] = date.fromisoformat(value["review_at"]) <= datetime.now(timezone.utc).date()
        value["effective_status"] = "retired" if value["status"] == "retired" else "stale" if value["stale"] else "active"
        value["trust"] = "scientific_claim_requires_evidence"
        return value

    def _current(self, db, knowledge_id):
        row = db.execute("SELECT * FROM knowledge_revisions WHERE knowledge_id=? ORDER BY version DESC LIMIT 1", (knowledge_id,)).fetchone()
        if not row:
            raise ValueError("Версия записи знаний не найдена.")
        value = self._revision(row)
        disputed = db.execute("SELECT 1 FROM memory_reviews r LEFT JOIN memory_review_resolutions d ON d.review_id=r.id WHERE r.knowledge_id=? AND r.memory_version=? AND r.relation='contradicts' AND d.review_id IS NULL LIMIT 1", (knowledge_id, value["version"])).fetchone()
        if disputed and value["status"] != "retired":
            value["effective_status"] = "disputed"
        evidence = db.execute("SELECT plan FROM runs WHERE id=?", (value["evidence_run_id"],)).fetchone()
        study = (json.loads(evidence["plan"]).get("study_context") or {}) if evidence else {}
        if study:
            task = study.get("task") or {}
            value["study_scope"] = {"task_id": study.get("task_id"), "task_version": study.get("task_version"),
                "title": str(task.get("title") or "")[:200], "task_type": task.get("task_type"),
                "business_goal": str(task.get("business_goal") or "")[:500],
                "baseline": str((task.get("baseline") or {}).get("name") or "")[:200],
                "conditions": str(task.get("constraints") or "")[:500],
                "dataset": str(task.get("dataset") or "")[:400],
                "execution_mode": study.get("execution_mode"), "context_hash": study.get("hash")}
        return value

    def decorate(self, findings):
        with self.store.connect() as db:
            result = []
            for finding in findings:
                item = dict(finding)
                try:
                    item["memory"] = self._current(db, item["id"])
                except ValueError:
                    item["memory"] = None
                result.append(item)
            return result

    def _revise(self, db, knowledge_id, body, evidence_run_id=None, source_ids=None):
        current = self._current(db, knowledge_id)
        if type(body.get("expected_version")) is not int or body["expected_version"] != current["version"]:
            raise ValueError("Запись знаний уже изменена. Обновите её перед сохранением.")
        title = _text(body.get("title", current["title"]), "Название", 200, True)
        claim = _text(body.get("claim", current["claim"]), "Вывод", 4000, True)
        notes = _text(body.get("notes", current["notes"]), "Заметки", 4000)
        item_tags = _tags(body.get("tags", current["tags"]))
        status = body.get("status", current["status"])
        if status not in {"active", "retired"}:
            raise ValueError("Статус записи: active или retired.")
        review_at = _date(body.get("review_at", current["review_at"]))
        db.execute("INSERT INTO knowledge_revisions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (knowledge_id, current["version"] + 1, title, claim, notes, _json(item_tags), status,
                    review_at, evidence_run_id or current["evidence_run_id"], _json(source_ids if source_ids is not None else current["source_ids"]), _now()))
        self._bump(db)
        return self._current(db, knowledge_id)

    def revise(self, knowledge_id, body):
        if not isinstance(body, dict):
            raise ValueError("Нужен объект новой версии.")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return self._revise(db, knowledge_id, body)

    def _preview(self, db, values):
        options = values.get("memory_options") or {}
        if not isinstance(options, dict):
            raise ValueError("Параметры памяти должны быть объектом.")
        for key in ("enabled", "include_profile", "include_corrections"):
            if key in options and type(options[key]) is not bool:
                raise ValueError(f"{key} должен быть boolean.")
        selected = _ids(options["selected_ids"], 5) if "selected_ids" in options else None
        refresh = options.get("refresh_id") or None
        if refresh is not None and (not isinstance(refresh, str) or len(refresh) > 100):
            raise ValueError("Некорректный идентификатор обновляемой записи.")
        profile = self._profile(db)
        question = str(values.get("question") or "")[:3000]
        source_ids = _ids(values.get("source_ids") or [], 6)
        source_texts = []
        for source_id in source_ids:
            row = db.execute("SELECT title,text FROM sources WHERE id=?", (source_id,)).fetchone()
            if not row:
                raise ValueError("Материал для поиска памяти не найден.")
            source_texts.append(row["title"] + " " + row["text"][:8000])
        query_tokens = set(_tokens(question + " " + str(values.get("study_query") or "")[:5000] + " " + " ".join(source_texts)))
        rows = db.execute("SELECT r.* FROM knowledge_revisions r WHERE r.version=(SELECT max(x.version) FROM knowledge_revisions x WHERE x.knowledge_id=r.knowledge_id)").fetchall()
        documents = [(self._revision(row), Counter(_tokens(row["title"] + " " + row["claim"] + " " + row["notes"] + " " + row["tags"]))) for row in rows]
        known = {item["id"] for item, _ in documents}
        forced = list(dict.fromkeys(([refresh] if refresh else []) + (selected or [])))
        if any(item not in known for item in forced):
            raise ValueError("Выбранная запись памяти не найдена. Обновите список.")
        if len(forced) > 5:
            raise ValueError("В исследование можно включить не более 5 записей памяти.")
        lengths = [sum(tokens.values()) for _, tokens in documents]
        average = sum(lengths) / len(lengths) if lengths else 1
        frequencies = Counter(token for _, tokens in documents for token in tokens)
        candidates = []
        for (item, tokens), length in zip(documents, lengths):
            if item["status"] == "retired" and item["id"] not in forced:
                continue
            overlap = sorted(query_tokens.intersection(tokens))
            score = 0.0
            for token in overlap:
                frequency = tokens[token]
                idf = math.log(1 + (len(documents) - frequencies[token] + 0.5) / (frequencies[token] + 0.5))
                score += idf * frequency * 2.2 / (frequency + 1.2 * (0.25 + 0.75 * length / max(average, 1)))
            item["score"] = round(score, 4)
            topic_matches = [token[6:] for token in overlap if token.startswith("topic_")]
            item["reason"] = "Явно выбрано для перепроверки" if item["id"] == refresh else "Совпадение темы: " + ", ".join(topic_matches[:3]) if topic_matches else "Совпадение слов: " + ", ".join(overlap[:5]) if overlap else "Последние знания; тематическое совпадение не найдено"
            current = self._current(db, item["id"])
            item["effective_status"] = current["effective_status"]
            if current.get("study_scope"):
                item["study_scope"] = current["study_scope"]
                selected_task = (values.get("study_context") or {}).get("task_id")
                if selected_task and selected_task == current["study_scope"].get("task_id"):
                    item["score"] += 2
                    item["reason"] = "Та же прикладная задача; сопоставимость условий требует проверки. " + item["reason"]
            candidates.append(item)
        candidates.sort(key=lambda item: (item["id"] not in forced, -item["score"], -item["version"], item["id"]))
        candidates = candidates[:12]
        suggested = [item["id"] for item in candidates if item["score"] > 0 and item["status"] == "active"][:5]
        if refresh:
            suggested = [refresh] + [item for item in suggested if item != refresh]
            suggested = suggested[:5]
        chosen = list(selected) if selected is not None else suggested
        if refresh:
            chosen = [refresh] + [item for item in chosen if item != refresh]
        if len(chosen) > 5:
            raise ValueError("В исследование можно включить не более 5 записей памяти.")
        corrections = [item for item in self._corrections(db) if item["active"] and (item["knowledge_id"] is None or item["knowledge_id"] in chosen)]
        notices = []
        if len(corrections) > 6:
            notices.append("В запрос попадут 6 последних применимых поправок владельца; остальные сохранены в истории.")
        corrections = corrections[:6]
        if any(item["stale"] and item["id"] in chosen for item in candidates):
            notices.append("Есть знания, срок пересмотра которых наступил. Они передаются как прежние выводы, требующие проверки.")
        if any(item["effective_status"] == "disputed" and item["id"] in chosen for item in candidates):
            notices.append("Есть неподтверждённое противоречие. Исходный вывод пока не изменён.")
        lesson_values = {**values, "task_id": (values.get("study_context") or {}).get("task_id", values.get("task_id"))}
        if options.get("enabled", True) is False:
            lesson_values["memory_options"] = {**options, "lesson_ids": []}
        lesson_candidates = self.store.lessons.candidates(lesson_values)
        return {"profile": profile, "corrections": corrections, "candidates": candidates,
                "suggested_ids": suggested, "selected_ids": chosen, "notices": notices,
                "generation": self._generation(db), "options": options,
                "lesson_candidates": lesson_candidates["items"],
                "suggested_lesson_ids": lesson_candidates["suggested_ids"],
                "lesson_selected_ids": lesson_candidates["selected_ids"]}

    def candidates(self, values):
        if not isinstance(values, dict):
            raise ValueError("Нужны параметры исследования.")
        with self.store.connect() as db:
            db.execute("BEGIN")
            return self._preview(db, values)

    def snapshot(self, values):
        if not isinstance(values, dict):
            raise ValueError("Нужны параметры исследования.")
        with self.store.connect() as db:
            db.execute("BEGIN")
            preview = self._preview(db, values)
            options = preview["options"]
            enabled = options.get("enabled", True)
            selected = set(preview["selected_ids"])
            result = {"version": 1, "enabled": enabled, "generation": preview["generation"],
                      "profile": preview["profile"] if enabled and options.get("include_profile", True) else None,
                      "corrections": preview["corrections"] if enabled and options.get("include_corrections", True) else [],
                      "items": [item for item in preview["candidates"] if item["id"] in selected] if enabled else [],
                      "lessons": [],
                      "notices": list(preview["notices"]) if enabled else ["Память отключена для этого исследования."]}
            if enabled:
                lesson_values = {**values, "task_id": (values.get("study_context") or {}).get("task_id", values.get("task_id")),
                                 "memory_options": options}
                lesson_context = self.store.lessons.snapshot(lesson_values)
                result["lessons"] = lesson_context["items"]
                result["notices"].extend(lesson_context["notices"])
            # Bounds apply to exact frozen text, never to an undisclosed prompt copy.
            for item in result["items"]:
                if len(item["claim"]) > 1800 or len(item["notes"]) > 700:
                    item["claim"] = item["claim"][:1800]
                    item["notes"] = item["notes"][:700]
                    item["text_truncated"] = True
            while len(_json(result)) > MAX_SNAPSHOT_CHARS - 350:
                longest = max(result["items"], key=lambda item: len(item["claim"]) + len(item["notes"]), default=None)
                if longest and len(longest["claim"]) + len(longest["notes"]) > 250:
                    if len(longest["notes"]) > 100:
                        longest["notes"] = longest["notes"][:max(100, len(longest["notes"]) // 2)]
                    else:
                        longest["claim"] = longest["claim"][:max(150, len(longest["claim"]) // 2)]
                    longest["text_truncated"] = True
                elif result["corrections"]:
                    result["corrections"].pop()
                    notice = "Из-за лимита контекста включена только показанная часть поправок. Остальные остаются в памяти."
                    if notice not in result["notices"]:
                        result["notices"].append(notice)
                else:
                    raise ValueError("Контекст памяти превышает лимит 16 000 символов. Сократите профиль или выбор знаний.")
            if any(item.get("text_truncated") for item in result["items"]):
                result["notices"].append("В план включены показанные сокращённые фрагменты; полные версии сохранены в истории.")
            result["hash"] = _hash(result)
            if len(_json(result)) > MAX_SNAPSHOT_CHARS:
                raise ValueError("Контекст памяти превышает лимит. Уменьшите число выбранных записей.")
            return result

    def validate(self, db, snapshot):
        if not isinstance(snapshot, dict) or snapshot.get("version") != 1:
            raise ValueError("План создан без снимка памяти. Пересоберите память и подтвердите план заново.")
        body = {key: value for key, value in snapshot.items() if key != "hash"}
        if snapshot.get("hash") != _hash(body):
            raise ValueError("Снимок памяти повреждён. Пересоберите план.")
        if snapshot.get("generation") != self._generation(db):
            raise ValueError("Память изменилась после создания плана. Пересоберите память и подтвердите новый план.")
        profile = snapshot.get("profile")
        if profile and profile.get("version") != self._profile(db)["version"]:
            raise ValueError("Версия профиля изменилась.")
        for item in snapshot.get("items", []):
            current = self._current(db, item.get("id"))
            if current["version"] != item.get("version"):
                raise ValueError("Выбранная запись знаний изменилась.")
            if current["stale"] != item.get("stale"):
                raise ValueError("Наступил срок пересмотра выбранных знаний. Обновите предпросмотр памяти и подтвердите план заново.")
        for correction in snapshot.get("corrections", []):
            row = db.execute("SELECT version,active FROM memory_correction_revisions WHERE id=? ORDER BY version DESC LIMIT 1", (correction.get("id"),)).fetchone()
            if not row or row["version"] != correction.get("version") or not row["active"]:
                raise ValueError("Поправка владельца изменилась.")
        self.store.lessons.validate(db, snapshot.get("lessons", []))

    def _reviews(self, db, knowledge_id=None):
        query = "SELECT r.*,d.action,d.created_at AS resolved_at,d.knowledge_version FROM memory_reviews r LEFT JOIN memory_review_resolutions d ON d.review_id=r.id"
        rows = db.execute(query + (" WHERE r.knowledge_id=?" if knowledge_id else "") + " ORDER BY r.created_at DESC,r.id", (knowledge_id,) if knowledge_id else ()).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["version"] = 2 if item["action"] else 1
            item["status"] = {"accept": "accepted", "dismiss": "dismissed"}.get(item["action"], "pending")
            item["evidence_source_ids"] = json.loads(item["evidence_source_ids"])
            item["evidence_urls"] = json.loads(item["evidence_urls"])
            old = db.execute("SELECT title,claim FROM knowledge_revisions WHERE knowledge_id=? AND version=?", (item["knowledge_id"], item["memory_version"])).fetchone()
            item["old_claim"], item["old_title"] = old["claim"], old["title"]
            item["new_claim"] = item["updated_claim"]
            result.append(item)
        return result

    def reviews(self):
        with self.store.connect() as db:
            return self._reviews(db)

    def history(self, knowledge_id):
        with self.store.connect() as db:
            return {"current": self._current(db, knowledge_id),
                    "versions": [self._revision(row) for row in db.execute("SELECT * FROM knowledge_revisions WHERE knowledge_id=? ORDER BY version DESC", (knowledge_id,))],
                    "corrections": [item for item in self._corrections(db) if item["knowledge_id"] == knowledge_id],
                    "reviews": self._reviews(db, knowledge_id)}

    def review_metadata(self, run_id):
        with self.store.connect() as db:
            row = db.execute("SELECT metadata FROM memory_review_ingestions WHERE run_id=?", (run_id,)).fetchone()
            return json.loads(row[0]) if row else {"status": "not_processed", "created_ids": [], "errors": []}

    def repair_completed_reviews(self, limit=100):
        """Replay only local parsing after a crash between report and review commits."""
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Лимит восстановления сравнений: от 1 до 1000.")
        with self.store.connect() as db:
            ids = [row[0] for row in db.execute("SELECT id FROM runs WHERE status='completed' AND id NOT IN (SELECT run_id FROM memory_review_ingestions) ORDER BY created_at DESC,rowid DESC LIMIT ?", (limit,))]
        result = {"processed": 0, "proposals": 0, "errors": []}
        for run_id in ids:
            try:
                with self.store.connect() as db:
                    output = db.execute("SELECT output FROM runs WHERE id=?", (run_id,)).fetchone()[0]
                metadata = self.ingest_review(run_id, output)
                result["processed"] += 1
                result["proposals"] += len(metadata.get("created_ids", []))
            except Exception:
                result["errors"].append({"run_id": run_id, "error": "Не удалось восстановить сопоставление. Сам отчёт сохранён."})
        return result

    def ingest_review(self, run_id, output):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT metadata FROM memory_review_ingestions WHERE run_id=?", (run_id,)).fetchone()
            if previous:
                return json.loads(previous[0])
            row = db.execute("SELECT plan,status FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row or row["status"] != "completed":
                return {"status": "not_completed", "created_ids": [], "errors": ["Сравнение принимается только из завершённого исследования."]}
            plan = json.loads(row["plan"])
            frozen = {item["id"]: item for item in (plan.get("memory") or {}).get("items", [])}
            sources = {item["id"] for item in plan.get("sources", [])}
            metadata = {"status": "not_provided", "created_ids": [], "comparisons": [], "errors": []}
            blocks = re.findall(r"<lab_memory_review>\s*(.*?)\s*</lab_memory_review>", str(output), re.S)
            if "<lab_memory_review>" in str(output) and not blocks:
                metadata["errors"].append("Блок сравнения не закрыт; предложения не добавлены.")
            if len(blocks) > 1:
                metadata["errors"].append("Обнаружено несколько блоков сравнения; предложения не добавлены.")
            elif blocks:
                try:
                    parsed = json.loads(blocks[0])
                    comparisons = parsed.get("comparisons") if isinstance(parsed, dict) else None
                    if not isinstance(comparisons, list) or len(comparisons) > 15:
                        raise ValueError("Нужен список не более 15 сравнений.")
                    metadata["status"] = "processed"
                    for index, proposal in enumerate(comparisons):
                        try:
                            if not isinstance(proposal, dict):
                                raise ValueError("Сравнение должно быть объектом.")
                            knowledge_id = proposal.get("memory_id")
                            item = frozen.get(knowledge_id) if isinstance(knowledge_id, str) else None
                            if not item or type(proposal.get("memory_version")) is not int or proposal["memory_version"] != item["version"]:
                                raise ValueError("ID или версия отсутствуют в замороженной памяти запуска.")
                            relation = proposal.get("relation")
                            if relation not in {"contradicts", "supersedes", "supports"}:
                                raise ValueError("Неизвестный тип сравнения.")
                            rationale = _text(proposal.get("rationale", ""), "Обоснование", 3000, True)
                            claim = _text(proposal.get("updated_claim", ""), "Предлагаемый вывод", 4000)
                            source_ids = _ids(proposal.get("evidence_source_ids", []), 6)
                            urls = proposal.get("evidence_urls", [])
                            if any(source_id not in sources for source_id in source_ids):
                                raise ValueError("Источник доказательства отсутствует в материалах запуска.")
                            if not isinstance(urls, list) or len(urls) > 10 or any(not _public_url(url) for url in urls):
                                raise ValueError("Ссылка доказательства не является обычным публичным URL.")
                            if not source_ids and not urls:
                                raise ValueError("Для предложения нужны ссылки на материалы запуска или публичные URL.")
                            existing = db.execute("SELECT id FROM memory_reviews WHERE run_id=? AND knowledge_id=? AND memory_version=? AND relation=?", (run_id, knowledge_id, item["version"], relation)).fetchone()
                            if existing:
                                continue
                            review_id = uuid.uuid4().hex
                            db.execute("INSERT INTO memory_reviews VALUES (?,?,?,?,?,?,?,?,?,?)", (review_id, run_id, knowledge_id, item["version"], relation, rationale, claim, _json(source_ids), _json(list(dict.fromkeys(urls))), _now()))
                            metadata["created_ids"].append(review_id)
                            metadata["comparisons"].append({"id": review_id, "knowledge_id": knowledge_id, "relation": relation, "status": "pending"})
                        except (ValueError, TypeError, KeyError) as error:
                            metadata["errors"].append(f"Сравнение {index + 1}: {error}")
                except (ValueError, TypeError, RecursionError) as error:
                    metadata["errors"].append("Блок сравнения не разобран: " + str(error)[:300])
            if metadata["errors"] and metadata["status"] == "not_provided":
                metadata["status"] = "invalid"
            db.execute("INSERT INTO memory_review_ingestions VALUES (?,?,?)", (run_id, _json(metadata), _now()))
            if metadata["created_ids"]:
                self._bump(db)
            return metadata

    def resolve_review(self, review_id, body):
        if not isinstance(body, dict) or body.get("action") not in {"accept", "dismiss"}:
            raise ValueError("Выберите принять или отклонить предложение.")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            review = next((item for item in self._reviews(db) if item["id"] == review_id), None)
            if not review:
                raise ValueError("Предложение пересмотра не найдено.")
            if type(body.get("expected_version")) is not int or body["expected_version"] != review["version"]:
                raise ValueError("Предложение уже изменено. Обновите страницу.")
            if review["status"] != "pending":
                raise ValueError("По этому предложению уже принято решение.")
            current = self._current(db, review["knowledge_id"])
            if body["action"] == "accept":
                if current["version"] != review["memory_version"]:
                    raise ValueError("Вывод уже изменился после этого исследования. Перепроверьте новую версию; старое предложение можно отклонить.")
                claim = current["claim"] if review["relation"] == "supports" else _text(body.get("claim", body.get("updated_claim", review["updated_claim"])), "Новая формулировка", 4000, True)
                plan = json.loads(db.execute("SELECT plan FROM runs WHERE id=?", (review["run_id"],)).fetchone()[0])
                sources = review["evidence_source_ids"] or [item["id"] for item in plan["sources"]]
                current = self._revise(db, review["knowledge_id"], {"expected_version": current["version"], "claim": claim,
                                       "notes": (current["notes"] + "\n\nПересмотр владельцем: " + review["rationale"])[-4000:],
                                       "status": "active", "review_at": (datetime.now(timezone.utc) + timedelta(days=self._profile(db)["review_days"])).date().isoformat()},
                                       evidence_run_id=review["run_id"], source_ids=sources)
            db.execute("INSERT INTO memory_review_resolutions VALUES (?,2,?,?,?)", (review_id, body["action"], current["version"] if body["action"] == "accept" else None, _now()))
            self._bump(db)
            resolved = next(item for item in self._reviews(db) if item["id"] == review_id)
            resolved["current"] = self._current(db, review["knowledge_id"])
            return resolved


def validate_backup_table(table, row, db):
    """Validate a memory row before insertion; caller owns one restore transaction."""
    if table not in TABLES or not isinstance(row, dict):
        raise ValueError("Некорректная таблица памяти.")
    columns = {column[1] for column in db.execute(f"PRAGMA table_info({table})")}
    if set(row) != columns:
        raise ValueError("Структура резервной копии памяти повреждена.")
    for key, value in row.items():
        if value is not None and not isinstance(value, (str, int)):
            raise ValueError("Некорректный тип поля памяти.")
    if table == "memory_meta":
        if row["id"] != 1 or type(row["generation"]) is not int or row["generation"] < 0:
            raise ValueError("Некорректный счётчик памяти.")
        return
    if "version" in row and (type(row["version"]) is not int or row["version"] < 1):
        raise ValueError("Некорректная версия памяти.")
    if "created_at" in row:
        datetime.fromisoformat(row["created_at"])
    if table == "memory_profile_revisions":
        for key in ("interests", "goals", "preferences"):
            _text(row[key], key, 1000)
        if type(row["review_days"]) is not int or not 1 <= row["review_days"] <= 365:
            raise ValueError("Некорректный срок пересмотра.")
    elif table == "memory_correction_revisions":
        _text(row["id"], "ID", 100, True)
        _text(row["text"], "Поправка", 1000, True)
        if row["active"] not in {0, 1} or (row["knowledge_id"] is not None and not db.execute("SELECT 1 FROM knowledge WHERE id=?", (row["knowledge_id"],)).fetchone()):
            raise ValueError("Повреждена связь поправки.")
    elif table == "knowledge_revisions":
        _text(row["title"], "Название", 200, True)
        _text(row["claim"], "Вывод", 4000, True)
        _text(row["notes"], "Заметки", 4000)
        _tags(json.loads(row["tags"]))
        _date(row["review_at"])
        if row["status"] not in {"active", "retired"}:
            raise ValueError("Некорректный статус знания.")
        for source_id in _ids(json.loads(row["source_ids"]), 30):
            if not db.execute("SELECT 1 FROM sources WHERE id=?", (source_id,)).fetchone():
                raise ValueError("Нет источника версии знаний.")
        run = db.execute("SELECT status,plan FROM runs WHERE id=?", (row["evidence_run_id"],)).fetchone()
        if not run or run["status"] != "completed":
            raise ValueError("Нет завершённого исследования для версии знаний.")
        allowed_sources = {item["id"] for item in json.loads(run["plan"])["sources"]}
        if any(source_id not in allowed_sources for source_id in json.loads(row["source_ids"])):
            raise ValueError("Источники версии знаний не принадлежат её исследованию.")
        if row["version"] == 1:
            finding = db.execute("SELECT * FROM knowledge WHERE id=?", (row["knowledge_id"],)).fetchone()
            if not finding:
                raise ValueError("Нет первоначальной записи знания.")
            initial = _initial_text(finding)
            if (row["evidence_run_id"] != finding["run_id"] or json.loads(row["source_ids"]) != json.loads(finding["source_ids"])
                    or any(row[key] != initial[key] for key in ("title", "claim", "notes"))
                    or json.loads(row["tags"]) != json.loads(finding["tags"]) or row["created_at"] != finding["created_at"]):
                raise ValueError("Первая версия должна сохранять первоначальный вывод и его происхождение.")
    elif table == "memory_review_ingestions":
        metadata = json.loads(row["metadata"])
        if not isinstance(metadata, dict) or not isinstance(metadata.get("errors"), list) or any(not isinstance(error, str) for error in metadata["errors"]) or not isinstance(metadata.get("created_ids"), list):
            raise ValueError("Повреждены метаданные сравнения.")
        _ids(metadata["created_ids"], 15)
    elif table == "memory_reviews":
        _text(row["rationale"], "Обоснование", 3000, True)
        _text(row["updated_claim"], "Вывод", 4000)
        if row["relation"] not in {"contradicts", "supersedes", "supports"}:
            raise ValueError("Неизвестный тип сравнения.")
        source_ids = _ids(json.loads(row["evidence_source_ids"]), 6)
        urls = json.loads(row["evidence_urls"])
        if not isinstance(urls, list) or len(urls) > 10 or any(not _public_url(url) for url in urls) or (not source_ids and not urls):
            raise ValueError("Повреждены ссылки сравнения.")
        run = db.execute("SELECT plan,status FROM runs WHERE id=?", (row["run_id"],)).fetchone()
        if not run or run["status"] != "completed":
            raise ValueError("Нет завершённого запуска сравнения.")
        plan = json.loads(run["plan"])
        frozen = {item["id"]: item for item in (plan.get("memory") or {}).get("items", [])}
        if row["knowledge_id"] not in frozen or row["memory_version"] != frozen[row["knowledge_id"]]["version"] or any(item not in {source["id"] for source in plan["sources"]} for item in source_ids):
            raise ValueError("Сравнение не связано со снимком запуска.")
    elif table == "memory_review_resolutions":
        if row["version"] != 2 or row["action"] not in {"accept", "dismiss"}:
            raise ValueError("Некорректное решение пересмотра.")


def validate_backup(db):
    if db.execute("SELECT count(*) FROM memory_meta WHERE id=1").fetchone()[0] != 1 or not db.execute("SELECT 1 FROM memory_profile_revisions").fetchone():
        raise ValueError("В копии отсутствует профиль или счётчик памяти.")
    if db.execute("SELECT 1 FROM knowledge k WHERE NOT EXISTS (SELECT 1 FROM knowledge_revisions r WHERE r.knowledge_id=k.id AND r.version=1) LIMIT 1").fetchone():
        raise ValueError("В копии отсутствует первоначальная версия знания.")
    for table, group in (("memory_profile_revisions", None), ("memory_correction_revisions", "id"), ("knowledge_revisions", "knowledge_id")):
        query = f"SELECT min(version),max(version),count(*) FROM {table}" + (f" GROUP BY {group}" if group else "")
        for minimum, maximum, count in db.execute(query):
            if minimum != 1 or maximum != count:
                raise ValueError("История версий памяти неполна.")
    for row in db.execute("SELECT r.knowledge_id,r.memory_version,r.run_id,d.knowledge_version,d.action FROM memory_review_resolutions d JOIN memory_reviews r ON r.id=d.review_id"):
        if row["action"] == "accept":
            revision = db.execute("SELECT evidence_run_id FROM knowledge_revisions WHERE knowledge_id=? AND version=?", (row["knowledge_id"], row["knowledge_version"])).fetchone()
            if not revision or row["knowledge_version"] != row["memory_version"] + 1 or revision["evidence_run_id"] != row["run_id"]:
                raise ValueError("Решение ссылается на отсутствующую или неподходящую версию знания.")
        elif row["knowledge_version"] is not None:
            raise ValueError("Отклонённое предложение не должно создавать версию знания.")
    for row in db.execute("SELECT run_id,metadata FROM memory_review_ingestions"):
        actual = {item[0] for item in db.execute("SELECT id FROM memory_reviews WHERE run_id=?", (row["run_id"],))}
        if set(json.loads(row["metadata"])["created_ids"]) != actual:
            raise ValueError("Метаданные сравнения не совпадают с сохранёнными предложениями.")
    if db.execute("SELECT 1 FROM memory_reviews r WHERE NOT EXISTS (SELECT 1 FROM memory_review_ingestions i WHERE i.run_id=r.run_id) LIMIT 1").fetchone():
        raise ValueError("У предложения нет исходного результата разбора.")
    if db.execute("PRAGMA foreign_key_check").fetchone():
        raise ValueError("Нарушены связи резервной копии памяти.")
