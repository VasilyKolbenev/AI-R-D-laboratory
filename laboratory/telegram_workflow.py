"""Owner-only Telegram approvals and durable result delivery, without model calls.

Sessions are operational settings, deliberately excluded from portable backups.
The immutable approved plan and its execution context remain in the run tables.
Outbound attempts are recorded before sending: an ambiguous network failure is
never a reason to repeat research or silently resend a result. /result is an
explicit owner request to resend the saved report.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re
import secrets
import threading

from .core import canonical, digest
from .memory import _tokens


KEY = "telegram_workflow_v1"
MAX_SESSIONS = 100
MAX_CHUNK = 3300
TERMINAL = {"completed", "failed", "cancelled", "outcome_unknown"}
_UNREAD_ATTACHMENT_NOTICE = re.compile(r"\[Вложение Telegram: .*?\. Содержимое файла не прочитано\.\]", re.S)
_WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
_MOSCOW = timezone(timedelta(hours=3), "Europe/Moscow")
_QUEUE_UNCONFIRMED = "Сохранение в очередь не подтверждено. Проверьте /queue; повтора нет."


def _moscow_slot(value):
    """Format an assigned aware timestamp; never infer a slot or its timezone."""
    if not isinstance(value, str) or len(value) > 100:
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            return None
        local = timestamp.astimezone(_MOSCOW)
    except (ValueError, OverflowError):
        return None
    return _WEEKDAYS[local.weekday()] + local.strftime(", %d.%m.%Y, %H:%M") + " МСК"


def _weekly_slot(value):
    if not isinstance(value, dict):
        return None
    day, clock = value.get("weekday"), value.get("time")
    if (type(day) is not int or not 0 <= day < 7 or not isinstance(clock, str)
            or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", clock)):
        return None
    return _WEEKDAYS[day] + " " + clock + " МСК"


def _publication_answer(entry):
    if not isinstance(entry, dict):
        return _QUEUE_UNCONFIRMED
    state = entry.get("state", entry.get("status"))
    if state == "blocked":
        return "Пакет заблокирован. В очередь не добавлен. /queue — причины."
    if state == "published":
        return "Пакет уже опубликован. /queue — статус."
    if state in {"publishing", "publication_uncertain"}:
        return "Статус публикации требует проверки. /queue; автоматического повтора нет."
    if state != "queued":
        return _QUEUE_UNCONFIRMED
    slot = _moscow_slot(entry.get("due_at"))
    text = "Сохранено в очереди.\n" + ("Слот: " + slot + "." if slot else
                                            "Слот пока не назначен.")
    if entry.get("blockers"):
        return text + "\nОжидает настройки; /queue — причины."
    return text + "\nПубликации ещё нет. /queue — статус."


def chunks(text, limit=MAX_CHUNK):
    """Split by UTF-16 code units, preserving every character including emoji."""
    parts, current, size = [], [], 0
    for character in str(text):
        width = 2 if ord(character) > 0xFFFF else 1
        if size + width > limit and current:
            parts.append("".join(current))
            current, size = [], 0
        current.append(character)
        size += width
    if current:
        parts.append("".join(current))
    return parts or [""]


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _plain_report(text):
    return re.sub(r"<lab_(?:memory_review|presentation)>.*?</lab_(?:memory_review|presentation)>", "", str(text), flags=re.S).strip()


def _has_research_material(source):
    """An unread-attachment placeholder is provenance, not research input.

    Telegram albums arrive as separate updates. A photo-only album member must
    not replace the text member's pending plan with a new empty investigation.
    Strip only the synthetic notice; a real caption, pasted text or URL remains
    valid. A URL occurring inside an attachment filename is not sufficient.
    """
    text = str(source.get("text") or "").strip()
    return bool(_UNREAD_ATTACHMENT_NOTICE.sub("", text).strip()) if text else bool(source.get("url"))


class TelegramWorkflow:
    def __init__(self, bridge, start_run, cancel_run=None, presentation_builder=None):
        self.bridge, self.store = bridge, bridge.store
        self.start_run, self.cancel_run = start_run, cancel_run
        self.presentation_builder = presentation_builder
        self.lock = threading.RLock()

    def _state(self):
        value = self.store.get_setting(KEY, {})
        return value if isinstance(value, dict) else {}

    def _save(self, sessions):
        # Retain active sessions even if many materials arrive. Old terminal
        # metadata is recoverable from the run/knowledge records.
        if len(sessions) > MAX_SESSIONS:
            for key in list(sessions):
                if len(sessions) <= MAX_SESSIONS:
                    break
                if sessions[key].get("state") in {"delivered", "cancelled", "superseded", "delivery_uncertain"}:
                    sessions.pop(key)
        self.store.set_setting(KEY, sessions)

    def _identity(self):
        with self.bridge._lock:
            token, config = self.bridge._token, dict(self.bridge._config)
        owner = config.get("owner_id")
        if not token or type(owner) is not int or owner <= 0:
            raise ValueError("Сначала подключите бота и привяжите владельца в настройках.")
        return token, owner, config.get("token_fingerprint")

    def _matches(self, session, owner, fingerprint):
        return session.get("owner_id") == owner and session.get("fingerprint") == fingerprint

    def _send(self, method, payload, session=None):
        token, owner, fingerprint = self._identity()
        if session is not None and not self._matches(session, owner, fingerprint):
            raise ValueError("Подключение бота изменилось. Подготовьте план заново.")
        payload = {**payload, "chat_id": owner}
        return self.bridge._api(token, method, payload)

    def _text(self, text, session=None, markup=None):
        payload = {"text": text, "link_preview_options": {"is_disabled": True}}
        if markup is not None:
            payload["reply_markup"] = markup
        return self._send("sendMessage", payload, session)

    def _latest(self, sessions=None):
        sessions = self._state() if sessions is None else sessions
        _, owner, fingerprint = self._identity()
        found = [(key, item) for key, item in sessions.items() if self._matches(item, owner, fingerprint)]
        return max(found, key=lambda pair: (pair[1].get("created_at", ""), pair[0])) if found else (None, None)

    def _new_session(self, run, source_id=None, source_message_id=None):
        _, owner, fingerprint = self._identity()
        key = secrets.token_urlsafe(12)
        return key, {"run_id": run["id"], "plan_hash": run["plan_hash"],
                     "owner_id": owner, "fingerprint": fingerprint, "state": "prepared",
                     "source_id": source_id or run["plan"]["sources"][0]["id"],
                     "source_message_id": source_message_id, "created_at": _now(),
                     "approval_message_id": None, "delivery": "pending"}

    def _preview(self, run):
        plan = run["plan"]
        study = plan.get("study_context") or {}
        memory = plan.get("memory") or {}
        protocol = plan.get("research_protocol") or {}
        resume = protocol.get('version') == 'editor-resume-v1'
        reviewed = protocol.get("version") in {"three-pass-v1", "three-pass-v2", "three-pass-v3", "three-pass-v4"}
        execution = ("Три отдельных прохода " + plan["provider"] +
                     ": исследователь и прикладной аналитик → критик → рецензент и редактор. "
                     "Максимум 3 вызова CLI; резерв 3 единицы лимита за 24 часа. Общий предел " +
                     str(protocol.get("total_timeout_seconds", plan["timeout_seconds"]))
                     if reviewed else "Один запуск " + plan["provider"] + "; максимум " + str(plan["timeout_seconds"]))
        if resume:
            checkpoint = plan['continuation']
            usage = checkpoint.get('parent_usage') or {}
            execution = ("ПРОДОЛЖЕНИЕ: только редактор " + plan['provider'] +
                ". Один новый вызов CLI; ответ до " + str(protocol['phase_timeouts'][0]) +
                " сек. +20 сек. завершение; всего " + str(plan['timeout_seconds']))
        header = ("🔬 ПЛАН ИССЛЕДОВАНИЯ\n\n" + plan["question"] +
                  "\n\nМатериал: " + "; ".join(s["title"] for s in plan["sources"]) +
                  "\n\n" + execution +
                  " сек.; веб-проверка " + ("включена" if plan["web_search"] else "отключена") +
                  ". Без бенчмарков, локальных моделей и автоматического повтора.\n"
                  "Расходуется лимит аккаунта исполнителя. Токены/стоимость заранее не гарантированы.\n"
                  "Полный отчёт сохранится в базе знаний; сюда придут прикладной пост, графики по подтверждаемым числам и анимация механизма. "
                  + ("Оформление входит в итоговый ответ третьего прохода; дополнительных вызовов для оформления нет. " if reviewed else
                   "Оформление входит в тот же ответ и не вызывает модель повторно. ") + "Если данных для графика нет, это будет указано.")
        if resume:
            prior = checkpoint.get('prior_editor')
            if prior is None or prior.get('dispatched') is False:
                prior_notice = 'Прежний редактор не был отправлен в CLI. '
            elif prior.get('status') == 'outcome_unknown' or prior.get('dispatched') is None:
                prior_notice = 'Прошлая попытка редактора имеет неизвестный исход; полный расход не подтверждён. '
            else:
                prior_notice = ('Прежний редактор: ' + str(prior.get('status')) +
                                '; известный расход: ' + json.dumps(prior.get('usage'), ensure_ascii=False) +
                                '. Отсутствующие сведения не означают нулевой расход. ')
            header += ("\n\nИсследователь и критик уже завершены: используются их точные сохранённые ответы. "
                "Повторных вызовов этих ролей и нового веб-поиска нет. Исходный запуск: " + checkpoint['parent_run_id'] +
                "\nИсточники, задача, память и уроки остаются в исходной одобренной версии. "
                "Редактор получает компактный пакет; отчёт, пост и визуал собираются локально. "
                "Это новое окно времени на редактора, а не возврат ранее потраченного лимита. "
                + prior_notice + "Известные токены исходного запуска: " +
                json.dumps(usage, ensure_ascii=False) + ". Кеш включён во входные токены, повторно не суммируется.")
        if reviewed:
            role_names = {"researcher": "исследователь и прикладной аналитик", "critic": "критик", "reviewer": "рецензент и редактор"}
            web_roles = protocol.get("web_search_roles") or []
            header += ("\nВеб-поиск разрешён ролям: " + ", ".join(role_names.get(role, role) for role in web_roles) +
                       ". У остальных ролей отключён." if plan["web_search"] and web_roles else
                       "\nВеб-поиск отключён у всех ролей." if not plan["web_search"] else
                       "\nВеб-разрешения ролей не зафиксированы; проверь точный протокол.")
        allowance = self.store.pilot_allowance(run["id"])
        if allowance:
            header += ("\n\nБЮДЖЕТ ЭТОГО ПИЛОТА: " + allowance["notice"] +
                       "\nОдин запуск CLI до " + str(plan['timeout_seconds']) + " секунд, без повтора. Разрешение действительно до " + allowance["expires_at"] + ".")
        # Every selected field is transmitted; there is no invisible truncation.
        context = "ПАСПОРТ ЗАДАЧИ (зафиксирован для этого запуска)\n" + json.dumps(study.get("task", {}), ensure_ascii=False, indent=2)
        exact_memory = {key: memory.get(key) for key in ("enabled", "profile", "corrections", "items", "lessons", "notices")}
        selected = "ПАМЯТЬ И УРОКИ — точный выбранный снимок\n" + json.dumps(exact_memory, ensure_ascii=False, indent=2)
        if not memory.get("items"):
            selected += "\nПодходящих прошлых научных выводов не выбрано. Профиль — предпочтения, а не научное доказательство."
        if not memory.get("lessons"):
            selected += "\nУроки другой задачи автоматически не переносились."
        provenance = ("ВЕРСИЯ ПЛАНА\n" + run["plan_hash"] + "\nВерсия задачи: " + str(study.get("task_version") or "inline") +
                      "\nТочный prompt SHA-256: " + (plan.get("execution_context") or {}).get("prompt_sha256", "не записан") +
                      "\n\nДля изменения вопроса: /research ваш вопрос\nДля отмены: /cancel\n"
                      "Подтверждение ниже относится только к показанному плану, памяти и лимиту.")
        from .presentation import publication_rules
        rules="ПРАВИЛА ГОТОВОГО ПОСТА\n"+json.dumps(publication_rules(),ensure_ascii=False,indent=2)
        # This joins the existing selected-memory preview in the bound owner's
        # private chat; no journal, unselected memory, or channel post is added.
        comparison = plan.get("comparison_context")
        comparison_parts = (chunks("СРАВНЕНИЕ: ТОЧНЫЙ СНИМОК МЕТРИК И ВЫБРАННЫХ АНАЛОГОВ\n"
                                   "Показаны выбранные ID, версии, выводы и условия памяти. "
                                   "Прошлый вывод не становится новым внешним доказательством.\n" +
                                   json.dumps(comparison, ensure_ascii=False, indent=2)) if isinstance(comparison, dict) else [])
        if reviewed:
            phase_labels = ("Исследователь и прикладной аналитик", "Критик", "Рецензент и редактор")
            phase_limits = protocol.get("phase_timeouts") or []
            phase_parts = chunks("ПРОХОДЫ В ОБЩЕМ ЛИМИТЕ\n" + "\n".join(
                str(index + 1) + ". " + label + (" — до " + str(phase_limits[index]) + " сек." if index < len(phase_limits) else "")
                for index, label in enumerate(phase_labels)) +
                ("\nКритик изучает исходники без ответа исследователя; редактор получает оба ответа. "
                 if protocol['version'] != 'three-pass-v1' else
                 "\nСледующий проход получает сохранённый ответ предыдущего. ") +
                ("Редактор использует фактический остаток общего времени; его указанный предел — потолок, а не дополнительное время. "
                 if protocol['version'] == 'three-pass-v4' else '') + "При ошибке цепочка останавливается; "
                "повторов нет. Запас общего времени включает завершение процессов.")
        else:
            phase_parts = []
        source_parts = []
        if plan.get("evidence_bundle") is not None:
            bundle = plan["evidence_bundle"]
            source_parts = chunks("СОХРАНЁННЫЕ ИСТОЧНИКИ И ГРАНИЦЫ ПРОВЕРКИ\n" +
                json.dumps({
                    "version": bundle["version"],
                    "documents": [{
                        **{key: value for key, value in document.items() if key != "segments"},
                        "segment_ids": [segment["id"] for segment in document["segments"]],
                        "selected_text_chars": sum(len(segment["text"])
                                                   for segment in document["segments"])
                    } for document in bundle["documents"]],
                    "limitations": bundle.get("limitations", []),
                    "bundle_sha256": digest(bundle)
                }, ensure_ascii=False, indent=2) +
                "\nТексты сохранены в локальном плане; выше указаны документы, выбранные сегменты и хеш полного снимка. Критик не видит ответ исследователя. Точная цитата проверяется локально; "
                "смысловое подтверждение остаётся оценкой модели, не научной гарантией.")
        validation_parts = []
        contract = protocol.get('validation_contract')
        if isinstance(contract, dict):
            missing_labels = {'task_goal': 'прикладная цель', 'baseline': 'baseline',
                              'measurable_metric': 'измеримая метрика', 'dataset': 'проверочный набор',
                              'evaluation': 'методика оценки'}
            baseline = contract.get('baseline') or {}
            metrics = contract.get('measurable_metrics') or []
            conditions = contract.get('conditions') or {}
            validation_parts = chunks('ПАСПОРТ ПРИКЛАДНОЙ ПРОВЕРКИ\n' +
                'Сейчас разрешён разбор источников; реальный эксперимент не запускался и этим апрувом не разрешается.\n' +
                'Задача: ' + str(contract.get('task') or 'не задана') + '\n' +
                'Baseline: ' + str(baseline.get('name') or 'не выбран') +
                '; версия: ' + str(baseline.get('version') or 'не закреплена') + '\n' +
                'Метрики: ' + ('; '.join(str(m.get('name') or 'метрика') + ' [' +
                    str(m.get('unit') or 'единица не задана') + ']' for m in metrics) or 'не заданы') + '\n' +
                'Данные: ' + str(conditions.get('dataset') or 'не выбраны') + '\n' +
                'Методика: ' + str(conditions.get('evaluation') or 'не выбрана') + '\n' +
                'Недостаёт: ' + (', '.join(missing_labels.get(key, key) for key in
                    contract.get('missing_inputs', [])) or 'основные поля заданы; совпадение условий ещё не проверено') + '\n' +
                'Опровергающая проверка: ' + str(contract.get('minimal_falsifying_check') or 'не определена') + '\n' +
                'Критерий: ' + str(contract.get('acceptance_criteria') or 'не задан') + '\n' +
                'Исполнитель ищет первичное сравнение на похожей задаче. Числа авторов, внешний замер и собственный тест различаются. ' +
                'Иллюстративная симуляция не подтверждает производительность. Бюджет и число проходов выше не увеличиваются.')
        return chunks(header) + phase_parts + validation_parts + chunks(context) + chunks(selected) + comparison_parts + source_parts + chunks(rules) + chunks(provenance)

    def present_plan(self, run_id, source_message_id=None):
        with self.lock:
            run = self.store.run(run_id)
            if run["status"] != "planned":
                raise ValueError("Подтверждение доступно только для незапущенного плана.")
            sessions = self._state()
            # Disable old handles before any new preview begins.
            for item in sessions.values():
                if item.get("run_id") == run_id and item.get("state") in {"ready", "prepared", "preview_sending"}:
                    item["state"] = "superseded"
            key, session = self._new_session(run, source_message_id=source_message_id)
            session["state"] = "preview_sending"
            sessions[key] = session
            self._save(sessions)
            try:
                parts = self._preview(run)
                for index, part in enumerate(parts):
                    self._text(f"План · {index + 1}/{len(parts)}\n\n" + part, session)
                markup = {"inline_keyboard": [[
                    {"text": ("✓ " if run["plan"]["provider"] == "codex" else "") + "Codex", "callback_data": "lab:" + key + ":codex"},
                    {"text": ("✓ " if run["plan"]["provider"] == "claude" else "") + "Claude", "callback_data": "lab:" + key + ":claude"}], [
                    {"text": "✅ Одобрить и исследовать", "callback_data": "lab:" + key + ":approve"}], [
                    {"text": "↻ Обновить план и память", "callback_data": "lab:" + key + ":refresh"},
                    {"text": "Отмена", "callback_data": "lab:" + key + ":cancel"}]]}
                resume = run['plan'].get('continuation') is not None
                if resume:
                    markup['inline_keyboard'].pop(0)
                    markup['inline_keyboard'][0][0]['text'] = '✅ Одобрить только редактора'
                    markup['inline_keyboard'][1][0]['text'] = '↻ Показать checkpoint'
                # The approval button is created only after every context part
                # has returned a successful Telegram response.
                material_titles = "\n".join("• " + str(source.get("title") or "Материал")[:160]
                                            for source in run["plan"]["sources"][:6])
                reviewed = (run["plan"].get("research_protocol") or {}).get("version") in {
                    "three-pass-v1", "three-pass-v2", "three-pass-v3", "three-pass-v4"}
                cost_notice = ("Кнопка «Одобрить и исследовать» резервирует 3 вызова CLI за 24 часа: "
                               "исследователь → критик → рецензент, до " + str(run["plan"]["timeout_seconds"]) + " сек. всего."
                               if reviewed else "Кнопка «Одобрить и исследовать» расходует лимит на один запуск.")
                result = self._text("Материал для этого апрува:\n" + material_titles +
                                    "\n\nПроверь все части плана выше. Версия " + run["plan_hash"][:12] +
                                    (". Источники, память и исполнитель зафиксированы checkpoint.\n" if resume else
                                     ". Выбор исполнителя создаст новый план без запуска.\n")
                                    + cost_notice, session, markup)
                message_id = result.get("message_id") if isinstance(result, dict) else None
                if type(message_id) is not int or message_id <= 0:
                    raise ValueError("Telegram не подтвердил сообщение с кнопкой. Используйте /plan.")
                session.update(state="ready", approval_message_id=message_id)
            except Exception:
                session["state"] = "preview_uncertain"
                self._save(sessions)
                raise
            self._save(sessions)
            return {"run_id": run_id, "status": "ready", "plan_hash": run["plan_hash"], "parts": len(parts) + 1}

    def _study(self, question):
        body = self.store.study.schema()["template"]
        body.update(title="Применимость технологии из Telegram", task_type="exploratory",
                    business_goal="За пять минут помочь читателю понять, какую рабочую задачу решает технология, кому и при каких условиях она полезна, с чем сравнивать и чего потребует применение в его проекте.",
                    beneficiary="Читатель исследовательского Telegram-канала: инженер, исследователь или владелец проекта в области ИИ.",
                    research_question=question,
                    inputs="Один выбранный Telegram-материал и доступные первоисточники.",
                    expected_output="Последовательный прикладной разбор: рабочая проблема и адресат → механизм → результаты авторов и условия → ограничения → ресурсы/сложность → критерии выбора для своего проекта. Объясняющая схема, анимация и готовый пост для чтения за пять минут.",
                    constraints="Только ИИ. Один анализ источников после апрува. Локальные модели, код, бенчмарки, рекурсия и публикация в канал не запускаются.",
                    evaluation="Сверить версии, задачи, baseline, данные, оборудование и нагрузку. Авторские результаты и оценки отделять от собственных измерений; неизвестное не заполнять догадками.",
                    success_criteria="Понятны границы применимости, цена внедрения и следующий дешёвый проверяемый шаг.")
        body["baseline"].update(name="Текущее решение / вариант без этой технологии — уточнить",
                                description="Конкретная модель и реализация baseline пока не выбраны; сравнение качественное.",
                                limitations="Нет собственного замера; ожидаемый эффект и окупаемость неизвестны.")
        body["self_hosted"].update(availability="unknown", model="Уточнить модели/веса, версии и лицензии по источникам.",
                                    operations="Оценить интеграцию, обслуживание, мониторинг и fallback.",
                                    cost="Числа указывать только с источником и предпосылками; закупок и аренды нет.")
        body["metrics"] = [{"name": "Качество / полезность", "definition": "Метрика должна соответствовать прикладной задаче; конкретный набор данных пока не выбран.",
                            "unit": "уточнить", "direction": "descriptive", "primary": True,
                            "target": "не задан", "expected": "неизвестно", "evidence_level": "unknown", "evidence_url": ""},
                           {"name": "Задержка, throughput и стоимость", "definition": "Сравнивать при одинаковой конфигурации и нагрузке; показатели разделить в отчёте.",
                            "unit": "мс; задачи/с; стоимость/задачу", "direction": "descriptive", "primary": False,
                            "target": "не задан", "expected": "неизвестно", "evidence_level": "unknown", "evidence_url": ""}]
        return body

    def _memory_options(self, source, question):
        # Conservative lexical retrieval: general plan boilerplate must not make
        # an unrelated Harness² report look relevant to inference research.
        general = {"ии", "ai", "источник", "анализ", "исслед", "обзор", "модел", "технолог", "результат", "применим", "память", "контекст", "вывод", "лаборатор", "задач"}
        query = set(_tokens(source["title"] + " " + source["text"])) - general
        preview = self.store.memory.candidates({"question": question, "source_ids": [source["id"]],
                                               "memory_options": {"enabled": True, "lesson_ids": []}})
        selected = [item["id"] for item in preview["candidates"] if item.get("effective_status") != "retired"
                    and len((set(_tokens(item.get("title", ""))) - general).intersection(query)) >= 2][:3]
        suggested_lessons = set(preview.get("suggested_lesson_ids", []))
        # An inline task has no right to inherit another saved task's scoped
        # lesson. Fresh, relevant global lessons remain usable and visible.
        lessons = [item["id"] for item in preview.get("lesson_candidates", [])
                   if item["id"] in suggested_lessons and item.get("status") == "active"
                   and not item.get("stale") and not (item.get("body") or {}).get("task_id")]
        return {"enabled": True, "selected_ids": selected, "include_profile": True,
                "include_corrections": True, "lesson_ids": lessons}

    def prepare_source(self, source, message_id=None, question=None, force=False):
        with self.lock:
            if not _has_research_material(source):
                self._unread_attachment_reply()
                return None
            sessions = self._state()
            _, owner, fingerprint = self._identity()
            candidates = [(key, value) for key, value in sessions.items() if self._matches(value, owner, fingerprint)
                          and value.get("source_id") == source["id"]]
            if not force and candidates:
                key, existing = max(candidates, key=lambda pair: (pair[1].get("created_at", ""), pair[0]))
                run = self.store.run(existing["run_id"])
                self._text("Материал уже сохранён. План: " + run["status"] + ".\n/plan — показать план; /status — состояние; /result — сохранённый результат.\nДля нового вопроса: /research ваш вопрос.", existing)
                return run
            question = (question or "Подготовь понятный прикладной разбор материала об ИИ для читателя канала: рабочая задача и кому полезно → механизм → результаты авторов с условиями и baseline → ограничения → сложность, инфраструктура/self-hosted и полная стоимость → критерии выбора для своего проекта. Разделяй проверенные факты, заявления авторов и неизвестное. Дай следующий дешёвый шаг проверки. Не трактуй материал как предложение менять нашу лабораторию и не обещай непроверенный эффект.").strip()
            if not 3 <= len(question) <= 3000:
                raise ValueError("Вопрос должен содержать от 3 до 3000 символов.")
            if force:
                for _, previous in candidates:
                    old = self.store.run(previous["run_id"])
                    if old["status"] == "planned":
                        self.store.cancel_planned(old["id"])
                        previous["state"] = "superseded"
                self._save(sessions)
            settings = self.store.settings()
            run = self.store.create_plan({"source_ids": [source["id"]], "question": question,
                                          "study_task": self._study(question),
                                          "provider": settings["provider"], "model": settings["model"],
                                          "research_mode": settings.get("research_mode", "single"),
                                          "web_search": bool(source.get("url")),
                                          "timeout_seconds": min(settings["timeout_seconds"],
                                                                 360 if settings.get("source_grounding") else 240),
                                          "memory_options": self._memory_options(source, question)})
            self.present_plan(run["id"], source_message_id=message_id)
            return run

    def handle_message(self, token, message):
        from .telegram import _extract, _origin
        with self.lock:
            active_token, owner, _ = self._identity()
            if token != active_token:
                return
            text = str(message.get("text", "")).strip()
            forwarded = any(message.get(key) for key in ("forward_origin", "forward_from", "forward_from_chat", "forward_date"))
            command, _, argument = text.partition(" ")
            command = command.split("@", 1)[0].lower()
            if not forwarded and command.startswith("/"):
                key, session = self._latest()
                if command in {"/start", "/help"}:
                    self._text("Перешли материал об ИИ: я покажу план с памятью и выбором Codex/Claude, затем запущу работу только по кнопке.\n/research ваш вопрос — изменить вопрос последнего материала\n/plan — план\n/status — состояние\n/result — повторить получение результата\n/queue — очередь публикаций\n/cancel — отменить\nОтчёт сохраняется в базу; готовый пакет можно отдельно одобрить для очереди.")
                elif command == "/research":
                    if not session:
                        self._text("Сначала перешли один материал об ИИ.")
                    else:
                        self.prepare_source(self.store.source(session["source_id"]), question=argument or None, force=True)
                elif command == '/continue':
                    source_id = argument.strip() or (session or {}).get('run_id')
                    if not source_id:
                        self._text('Нужен исходный остановленный запуск: /continue ID.')
                    else:
                        selected = self.store.run(source_id)
                        parent_id = (selected['plan'].get('continuation') or {}).get('parent_run_id', source_id)
                        updated = self.store.create_continuation(parent_id)
                        self.present_plan(updated['id'])
                elif command == "/plan":
                    if session:
                        run = self.store.run(session["run_id"])
                        if run["status"] == "planned":
                            self.present_plan(run["id"])
                        else:
                            self._text("Состояние исследования: " + run["status"] + ". /result — получить готовый результат.", session)
                    else:
                        self._text("Пока нет плана. Перешли материал об ИИ.")
                elif command == "/status":
                    if session:
                        run = self.store.run(session["run_id"])
                        self._text("Исследование: " + run["status"] + ". Доставка: " + session.get("delivery", "pending") +
                                   ".\nПовторного модельного запуска нет. /result — получить сохранённый отчёт.", session)
                    else:
                        self._text("Пока нет исследования. Перешли материал об ИИ.")
                elif command == "/result":
                    run_id = argument.strip() or (session or {}).get("run_id")
                    if run_id and re.fullmatch(r"[0-9a-f]{32}", run_id):
                        self._manual_result(run_id, message)
                    else:
                        self._text("Пока нет выбранного результата.")
                elif command == "/queue":
                    self._queue_status()
                elif command == "/cancel":
                    if session:
                        self._cancel(key, session)
                    else:
                        self._text("Нет плана для отмены.")
                else:
                    self._text("Неизвестная команда. /help — доступные действия. Материал можно переслать отдельным сообщением.")
                return
            body, url, _ = _extract(message)
            if not body or len(body) > 50000:
                self._text("Нужен текст до 50 000 символов, ссылка или подпись. Содержимое вложений пока не читается.")
                return
            source, _ = self.store.add_source(text=body, title=body.splitlines()[0][:160], url=url,
                                             origin=_origin(message, "telegram_bot", owner), tags=["telegram"])
            if not _has_research_material(source):
                # Keep the source/origin above, but leave the latest meaningful
                # session and its approval button untouched.
                self._unread_attachment_reply()
                return
            self.prepare_source(source, message_id=message.get("message_id"))

    def _unread_attachment_reply(self):
        self._text("Вложение сохранено, но его содержимое не прочитано. Отдельный план по пустому вложению не создан; модель не запускается.\n"
                   "Если выше есть план по тексту или ссылке, подтверждай его. /plan — показать последний такой план. Иначе пришли подпись или ссылку к материалу.")

    def _manual_result(self, run_id, message):
        """One delivery attempt per Telegram command, including update replays."""
        _, owner, fingerprint = self._identity()
        message_id = message.get("message_id")
        if type(message_id) is not int or message_id <= 0:
            raise ValueError("Telegram не передал идентификатор команды.")
        request_key = digest({"owner": owner, "fingerprint": fingerprint, "message_id": message_id})
        setting_key = KEY + "_result_requests"
        requests = self.store.get_setting(setting_key, {}) or {}
        if request_key in requests:
            return  # A new /result message is required for an explicit resend.
        requests[request_key] = {"run_id": run_id, "created_at": _now(), "state": "attempting"}
        if len(requests) > 200:
            requests = dict(sorted(requests.items(), key=lambda item: item[1].get("created_at", ""))[-200:])
        self.store.set_setting(setting_key, requests)
        try:
            self.send_result(run_id, manual=True)
            requests[request_key]["state"] = "sent"
        except Exception:
            requests[request_key]["state"] = "uncertain"
            self.store.set_setting(setting_key, requests)
            raise
        self.store.set_setting(setting_key, requests)

    def _cancel(self, key, session):
        run = self.store.run(session["run_id"])
        if self.cancel_run:
            self.cancel_run(run["id"])
        elif run["status"] == "planned":
            self.store.cancel_planned(run["id"])
        sessions = self._state()
        # A cancellation request can race completion. Keep watching a started
        # run so a completed report still reaches the knowledge base.
        sessions[key]["state"] = "approved" if run["status"] == "running" else "cancelled"
        sessions[key]["cancel_requested"] = True
        self._save(sessions)
        self._text("Отмена принята. Уже начатый внешний вызов мог использовать лимит; повтор не запускается.", session)

    def _queue_status(self):
        publisher = getattr(self.bridge, "publisher", None)
        if publisher is None:
            self._text("Очередь публикаций не подключена. Канал не подключён; расписание не задано.")
            return
        status = publisher.status()
        counts = status.get("counts") or {}
        queued = counts.get("queued", 0)
        queued = queued if type(queued) is int and queued >= 0 else 0
        slots = status.get("slots")
        schedule = [_weekly_slot(slot) for slot in slots[:7]] if isinstance(slots, list) else []
        channel = (str(status.get("channel_title") or "подключён")[:160]
                   if status.get("channel_connected") else "не подключён")
        lines = ["Очередь публикаций: " + str(queued), "Канал: " + channel,
                 "Расписание: " + (", ".join(slot for slot in schedule if slot) or "не задано"),
                 "Автовыпуск: " + ("включён" if status.get("enabled") is True else "выключен")]
        blockers = status.get("blockers")
        if isinstance(blockers, list) and blockers:
            lines.append("Ожидание: " + " ".join(str(reason)[:180] for reason in blockers[:3]))
        items = status.get("items")
        labels = {"queued": "в очереди", "blocked": "заблокирован",
                  "publishing": "отправляется", "publication_uncertain": "отправка не подтверждена"}
        items = [item for item in items if isinstance(item, dict)
                 and item.get("state", item.get("status")) in labels] if isinstance(items, list) else []
        for item in items[:5]:
            state = item.get("state", item.get("status"))
            title = " ".join(str(item.get("title") or "Пакет").split())[:100]
            slot = _moscow_slot(item.get("due_at")) if state == "queued" else None
            detail = (slot or "слот пока не назначен") if state == "queued" else labels[state]
            lines.append(title + " — " + detail)
            if state == "blocked" and item.get("reason"):
                lines.append("Причина: " + str(item["reason"])[:180])
        if len(items) > 5:
            lines.append("Ещё пакетов: " + str(len(items) - 5))
        self._text("\n".join(lines))

    def _change_provider(self, key, session, run, provider):
        plan = run["plan"]
        values = {"source_ids": [source["id"] for source in plan["sources"]], "question": plan["question"],
                  "provider": provider, "model": "", "web_search": plan["web_search"],
                  "research_mode": "reviewed" if plan.get("research_protocol") else "single",
                  "timeout_seconds": plan["timeout_seconds"], "memory_options": plan.get("memory_options", {})}
        study = plan.get("study_context") or {}
        if study.get("task_id"):
            values["task_id"] = study["task_id"]
        elif study.get("task"):
            values["study_task"] = study["task"]
        replacement = self.store.create_plan(values)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute("UPDATE runs SET status='cancelled',finished_at=? WHERE id=? AND status='planned' AND plan_hash=?",
                                 (_now(), run["id"], session["plan_hash"])).rowcount
        if not changed:
            self.store.cancel_planned(replacement["id"])
            raise ValueError("План уже изменился или запущен. Откройте актуальный план.")
        sessions = self._state()
        sessions[key]["state"] = "superseded"
        self._save(sessions)
        self.present_plan(replacement["id"], source_message_id=session.get("source_message_id"))
        return replacement

    def handle_callback(self, token, query):
        with self.lock:
            active_token, owner, fingerprint = self._identity()
            sender, message = query.get("from", {}), query.get("message", {})
            chat = message.get("chat", {}) if isinstance(message, dict) else {}
            if (token != active_token or not isinstance(sender, dict) or sender.get("is_bot")
                    or type(sender.get("id")) is not int or sender["id"] != owner
                    or not isinstance(chat, dict) or chat.get("type") != "private" or chat.get("id") != owner):
                return
            callback = str(query.get("data", ""))
            publication = re.fullmatch(r"pub:([A-Za-z0-9_-]{1,40}):([A-Za-z0-9_-]{1,40})", callback)
            if publication and len(callback.encode("utf-8")) <= 64:
                publisher = getattr(self.bridge, "publisher", None)
                message_id = message.get("message_id")
                if publisher is None or type(message_id) is not int or message_id <= 0:
                    self._answer(token, query, "Очередь не подключена или кнопка недействительна.")
                    return
                try:
                    entry = publisher.approve(publication[1], publication[2], message_id,
                                              owner, fingerprint)
                except ValueError:
                    self._answer(token, query,
                                 "Пакет или подключение изменились. Получи новый preview через /result.",
                                 show_alert=True)
                    return
                except Exception:
                    self._answer(token, query, _QUEUE_UNCONFIRMED, show_alert=True)
                    return
                self._answer(token, query, _publication_answer(entry), show_alert=True)
                return
            match = re.fullmatch(r"lab:([A-Za-z0-9_-]{16}):(approve|refresh|cancel|codex|claude)", callback)
            sessions = self._state()
            session = sessions.get(match[1]) if match else None
            if (not session or not self._matches(session, owner, fingerprint)
                    or type(message.get("message_id")) is not int
                    or message["message_id"] != session.get("approval_message_id")):
                self._answer(token, query, "Кнопка недействительна. Используйте /plan.")
                return
            key, action = match.groups()
            run = self.store.run(session["run_id"])
            if action == "cancel":
                if session["state"] in {"ready", "approved"}:
                    self._cancel(key, session)
                self._answer(token, query, "Отмена обработана.")
                return
            if session["state"] != "ready" or run["status"] != "planned":
                self._answer(token, query, "Эта кнопка уже обработана. /status — состояние.")
                return
            if run["plan_hash"] != session["plan_hash"]:
                session["state"] = "superseded"
                self._save(sessions)
                self._answer(token, query, "План изменился. Используйте /plan и проверьте новую версию.")
                return
            if action in {"codex", "claude"}:
                if run['plan'].get('continuation') is not None:
                    self._answer(token, query, 'Исполнитель checkpoint зафиксирован. Новый вызов не выполнен.')
                    return
                if action == run["plan"]["provider"]:
                    self._answer(token, query, "Этот исполнитель уже выбран; исследование не запускалось.")
                else:
                    self._answer(token, query, "Меняю исполнителя; новый план потребует нового апрува.")
                    self._change_provider(key, session, run, action)
                return
            if action == "refresh":
                self._answer(token, query, "Обновляю план; потребуется новый апрув.")
                if run['plan'].get('continuation') is not None:
                    updated = self.store.create_continuation(run['plan']['continuation']['parent_run_id'])
                else:
                    updated = self.store.replan_context(run["id"], {"memory_options": run["plan"].get("memory_options", {})})
                self.present_plan(updated["id"])
                return
            # Record the attempt first. A crash after approval is reconciled from
            # the durable run status, never by launching the model again.
            session["state"] = "approving"
            self._save(sessions)
            try:
                # Serialize the final identity check with disconnect/reconfigure.
                # Workflow -> bridge is the only lock order used here.
                with self.bridge._lock:
                    latest_token, latest_owner, latest_fingerprint = self._identity()
                    if latest_token != token or not self._matches(session, latest_owner, latest_fingerprint):
                        raise ValueError("Подключение бота изменилось; требуется новый план.")
                    run = self.start_run(run["id"], {"consent": True, "plan_hash": session["plan_hash"],
                                                    "command_id": "telegram-approve-" + run["id"]})
            except ValueError as exc:
                session["state"] = "ready"
                self._save(sessions)
                self._answer(token, query, "Запуск отклонён. Обновите план через /plan.")
                self._text("Запуск не выполнен: " + str(exc) + "\nНажми «Обновить план и память», затем проверь новый апрув.", session)
                return
            except Exception:
                session["state"] = "approval_uncertain"
                self._save(sessions)
                self._answer(token, query, "Исход запуска уточняется. /status; автоматического повтора нет.")
                return
            session["state"] = "approved"
            self._save(sessions)
            self._answer(token, query, "Апрув принят. Исследование запущено.")
            self._text("▶️ Исследование запущено. После завершения отчёт сохранится в базе, сюда придут выводы. Повторно нажимать не нужно.", session)

    def _answer(self, token, query, text, show_alert=False):
        query_id = query.get("id")
        if isinstance(query_id, str) and 0 < len(query_id) <= 200:
            try:
                payload = {"callback_query_id": query_id, "text": text[:180]}
                if show_alert:
                    payload["show_alert"] = True
                self.bridge._api(token, "answerCallbackQuery", payload)
            except Exception:
                pass  # Answer failure cannot repeat approval.

    def tick(self):
        with self.lock:
            try:
                _, owner, fingerprint = self._identity()
            except ValueError:
                return
            sessions = self._state()
            for key, session in list(sessions.items()):
                if not self._matches(session, owner, fingerprint):
                    continue
                if session.get("state") not in {"ready", "approved", "approving", "approval_uncertain"}:
                    continue
                run = self.store.run(session["run_id"])
                if session.get("state") == "ready" and (not run.get("approved_at") or run["plan_hash"] != session.get("plan_hash")):
                    continue  # Web approval can complete the very same preview.
                if run["status"] in TERMINAL:
                    self.send_result(run["id"], session_key=key)

    def send_result(self, run_id, manual=False, session_key=None):
        with self.lock:
            _, owner, fingerprint = self._identity()
            run = self.store.run(run_id)
            if run["status"] not in TERMINAL:
                self._text("Исследование: " + run["status"] + ". Нового запуска нет.")
                return {"run_id": run_id, "status": run["status"]}
            sessions = self._state()
            if session_key is None:
                candidates = [(key, item) for key, item in sessions.items()
                              if item.get("run_id") == run_id and self._matches(item, owner, fingerprint)]
                session_key = max(candidates, key=lambda pair: pair[1].get("created_at", ""))[0] if candidates else None
            if session_key is None:
                session_key, session = self._new_session(run)
                sessions[session_key] = session
            session = sessions[session_key]
            if not self._matches(session, owner, fingerprint):
                raise ValueError("Подключение изменилось; результат не отправлен.")
            if not manual and session.get("delivery") in {"sent", "attempting", "uncertain"}:
                return {"run_id": run_id, "status": session["delivery"]}
            finding = None
            if run["status"] == "completed" and run.get("output", "").strip():
                finding = self.store.save_finding(run_id, {"title": run["plan"]["sources"][0]["title"][:180],
                    "tags": ["Telegram", "исследование ИИ"],
                    "decision": "Анализ источников сохранён после апрува владельца. Рекомендации отчёта не являются одобрением внедрения или воспроизведёнными измерениями."})
            session.update(state="result_delivering", delivery="attempting", knowledge_id=finding["id"] if finding else None,
                           delivery_attempted_at=_now())
            self._save(sessions)
            try:
                if run["status"] != "completed":
                    from .research_failure import failure_notice
                    self._text(failure_notice(run), session)
                else:
                    if self.presentation_builder:
                        data = self.presentation_builder(run)
                    else:
                        from .presentation import build_presentation
                        data = build_presentation(run)
                    checks = data.get("publication_checks") or {}
                    post = data.get("post_text")
                    post_valid = isinstance(post, str) and bool(post.strip()) and len(post.encode("utf-16-le")) // 2 <= 3500
                    if checks.get("status") != "ready" or not post_valid:
                        issues = checks.get("issues") if isinstance(checks.get("issues"), list) else []
                        detail = "\n".join(str(issue) for issue in issues[:6])
                        if not post_valid:
                            detail += "\nПост отсутствует или превышает 3500 символов UTF-16."
                        notice = ("⚠️ Отчёт сохранён в базе знаний, но публикационный формат не прошёл проверку.\n" + detail.strip() +
                                  "\nПост и медиа не отправлены. Автоматического повторного исследования нет.")
                        self._text(chunks(notice, limit=3500)[0], session)
                    else:
                        publisher = getattr(self.bridge, "publisher", None)
                        entry, assets = None, None
                        if publisher is not None:
                            # Publish approval binds the immutable package that
                            # is actually previewed, including its media bytes.
                            try:
                                entry = publisher.prepare(run_id)
                            except ValueError:
                                self._text("Отчёт сохранён в базе знаний. Пакет для очереди пока не готов: нужны полный пост, PNG и MP4. "
                                           "Публичный пакет и кнопка не отправлены. Автоматического повторного исследования нет.", session)
                                session.update(state="delivered", delivery="sent", delivered_at=_now(),
                                               publication_package_status="not_ready")
                                self._save(sessions)
                                return {"run_id": run_id, "status": "sent", "knowledge_id": session.get("knowledge_id"),
                                        "publication_package_status": "not_ready"}
                            assets = publisher.assets(entry["id"])
                            post = entry["post_text"]
                            callback = "pub:" + str(entry["id"]) + ":" + str(entry["token"])
                            if (not isinstance(post, str) or not post.strip() or len(post.encode("utf-16-le")) // 2 > 3500
                                    or not re.fullmatch(r"pub:[A-Za-z0-9_-]{1,40}:[A-Za-z0-9_-]{1,40}", callback)
                                    or len(callback.encode("utf-8")) > 64
                                    or not isinstance(assets, dict)
                                    or any(not isinstance(assets.get(key), bytes) or not assets[key] for key in ("png", "mp4"))):
                                raise ValueError("Не удалось подготовить точный пакет для очереди.")
                            session.update(publication_entry_id=entry["id"], publication_package_sha256=entry["package_sha256"])
                            self._save(sessions)
                        # This is the complete publication text, not a service
                        # summary or a fragmented copy with a draft wrapper.
                        post_response = self._text(post, session)
                        if entry is not None and (not isinstance(post_response, dict) or type(post_response.get("message_id")) is not int or post_response["message_id"] <= 0):
                            raise ValueError("Telegram не подтвердил текст пакета.")
                        image = assets["png"] if assets is not None else None
                        if assets is None:
                            try:
                                from .presentation import render_png
                                image = render_png(data)
                            except (ImportError, OSError, ValueError):
                                image = None
                        if image:
                            image_response = self._send("sendPhoto", {"photo": "attach://photo",
                                                        "_files": {"photo": ("research.png", image, "image/png")}}, session)
                            if entry is not None and (not isinstance(image_response, dict) or type(image_response.get("message_id")) is not int or image_response["message_id"] <= 0):
                                raise ValueError("Telegram не подтвердил PNG пакета.")
                        animation = assets["mp4"] if assets is not None else None
                        if assets is None:
                            try:
                                from .presentation import render_mp4
                                animation = render_mp4(data)
                            except (ImportError, OSError, ValueError):
                                animation = None
                        filename, mime_type = "research.mp4", "video/mp4"
                        if not animation:
                            try:
                                from .presentation import render_gif
                                animation = render_gif(data)
                            except (ImportError, OSError, ValueError):
                                animation = None
                            filename, mime_type = "research.gif", "image/gif"
                        if animation:
                            response = self._send("sendAnimation", {"animation": "attach://animation",
                                                  "_files": {"animation": (filename, animation, mime_type)}}, session)
                            if entry is not None and (not isinstance(response, dict) or type(response.get("message_id")) is not int or response["message_id"] <= 0):
                                raise ValueError("Telegram не подтвердил MP4 пакета.")
                            media = response.get("animation") if isinstance(response, dict) else None
                            media = media if isinstance(media, dict) else {}
                            record = {"requested_file_name": filename, "requested_mime_type": mime_type,
                                      "width": None, "height": None, "file_name": None, "mime_type": None, "file_size": None}
                            for field in ("width", "height", "file_size"):
                                if type(media.get(field)) is int and media[field] >= 0:
                                    record[field] = media[field]
                            name = media.get("file_name")
                            if isinstance(name, str) and re.fullmatch(r"[\w .()-]{1,200}", name):
                                record["file_name"] = name
                            content_type = media.get("mime_type")
                            if isinstance(content_type, str) and re.fullmatch(r"[A-Za-z0-9.+-]{1,80}/[A-Za-z0-9.+-]{1,80}", content_type):
                                record["mime_type"] = content_type
                            previous_media = session.get("delivery_media")
                            session["delivery_media"] = [*(previous_media if isinstance(previous_media, list) else [])[-9:], record]
                            self._save(sessions)
                        if entry is not None and entry.get("can_enqueue", True) is True:
                            blockers = entry.get("blockers") if isinstance(entry.get("blockers"), list) else []
                            preview = ("Пакет для очереди: пост, PNG и MP4 выше.\nSHA-256: " + str(entry["package_sha256"]) +
                                       "\nКнопка одобряет именно этот пакет. Публикации сейчас нет; выпуск зависит от подключения канала и расписания.")
                            profile = data.get('visual_profile')
                            if isinstance(profile, dict) and isinstance(profile.get('label'), str) and isinstance(profile.get('reason'), str):
                                preview += '\n\nВизуал: ' + profile['label'] + '.\nПочему: ' + profile['reason']
                            motion = data.get('motion_story')
                            if isinstance(motion, dict) and motion.get('version') == 'dataflow-v1':
                                baseline = motion.get('baseline') or {}
                                status = {'reported': 'описан в отчёте', 'conceptual': 'схематический', 'unknown': 'не раскрыт'}.get(baseline.get('status'), 'не раскрыт')
                                preview += '\nАнимация: движение данных и работа компонентов.\nBaseline: ' + status + '.'
                                if isinstance(baseline.get('note'), str):preview += ' ' + baseline['note']
                            if blockers:
                                preview += "\nОжидание: " + "; ".join(str(item) for item in blockers)[:600]
                            result = self._text(preview, session, {"inline_keyboard": [[{"text": "В очередь", "callback_data": callback}]]})
                            message_id = result.get("message_id") if isinstance(result, dict) else None
                            if type(message_id) is not int or message_id <= 0:
                                raise ValueError("Telegram не подтвердил кнопку очереди.")
                            publisher.bind_preview(entry["id"], message_id)
                            session["publication_preview_message_id"] = message_id
                session.update(state="delivered", delivery="sent", delivered_at=_now())
            except Exception:
                session.update(state="delivery_uncertain", delivery="uncertain")
                self._save(sessions)
                raise
            self._save(sessions)
            return {"run_id": run_id, "status": "sent", "knowledge_id": session.get("knowledge_id")}
