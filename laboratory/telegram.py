"""Telegram intake with optional owner-only approval workflow.

Receiving a material never starts research. A wired workflow can start only the
exact previewed plan after its owner's explicit inline-button confirmation.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import threading
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


MAX_MESSAGES = 10_000
MAX_TEXT = 50_000
MAX_EXPORT_BYTES = 20 * 1024 * 1024
_SAVED_NAMES = {"saved messages", "избранное"}
_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_TOKEN = re.compile(r"[0-9]{6,20}:[A-Za-z0-9_-]{20,200}\Z")


class TelegramError(ValueError):
    """User-visible error which must never contain a bot token."""


def _safe_url(value):
    if not isinstance(value, str):
        return ""
    value = value.strip().rstrip(".,;!?)]}")
    try:
        parts = urlsplit(value)
        return value if parts.scheme.lower() in {"http", "https"} and parts.hostname and not parts.username and not parts.password and len(value) <= 3000 else ""
    except ValueError:
        return ""


def _flatten(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_flatten(item) for item in value)
    if isinstance(value, dict):
        text = _flatten(value.get("text", ""))
        link = _safe_url(value.get("href", value.get("url", "")))
        return f"{text} ({link})" if link and link not in text else text
    return ""


def _extract(message):
    text = _flatten(message.get("text", message.get("caption", "")))
    links = []
    entities = message.get("entities") or []
    caption_entities = message.get("caption_entities") or []
    for entity in (entities if isinstance(entities, list) else []) + (caption_entities if isinstance(caption_entities, list) else []):
        if isinstance(entity, dict):
            link = _safe_url(entity.get("url", ""))
            if link and link not in text and link not in links:
                links.append(link)
    if links:
        text += "\n\nСсылки: " + "\n".join(links)
    attachment = any(message.get(key) for key in ("document", "photo", "video", "audio", "voice", "sticker", "file", "media_type"))
    if attachment:
        item = message.get("document", {})
        filename = item.get("file_name", "") if isinstance(item, dict) else ""
        filename = filename or message.get("file_name", "") or message.get("media_type", "вложение")
        warning = f"[Вложение Telegram: {filename}. Содержимое файла не прочитано.]"
        text = text.rstrip() + ("\n\n" if text.strip() else "") + warning
    text = text.strip()
    found = next((_safe_url(match.group()) for match in _URL.finditer(text) if _safe_url(match.group())), "")
    return text, found, attachment


def _origin(message, kind, chat_id):
    raw = json.loads(json.dumps(message, ensure_ascii=False))
    _, _, attachment = _extract(message)
    return {
        "kind": kind,
        "chat_id": chat_id,
        "message_id": message.get("message_id", message.get("id")),
        "date": message.get("date"),
        "forward_from": message.get("forward_origin", message.get("forwarded_from", message.get("forward_from"))),
        "attachment_unread": attachment,
        "raw_sha256": hashlib.sha256(json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "raw": raw,
    }


def _add_message(message, chat_id, kind, store):
    if not isinstance(message, dict) or message.get("type", "message") != "message":
        return "skipped"
    text, url, _ = _extract(message)
    if not text or len(text) > MAX_TEXT:
        return "skipped"
    title = next((line.strip() for line in text.splitlines() if line.strip()), "Материал Telegram")[:160]
    _, created = store.add_source(text=text, title=title, url=url, origin=_origin(message, kind, chat_id), tags=["telegram"])
    return "imported" if created else "duplicates"


def import_telegram(export, store):
    """Import a selected Saved Messages JSON or its entry in a full export."""
    if not isinstance(export, dict):
        raise TelegramError("Нужен JSON-экспорт «Избранного» из Telegram Desktop.")
    if len(json.dumps(export, ensure_ascii=False).encode("utf-8")) > MAX_EXPORT_BYTES:
        raise TelegramError("Экспорт больше 20 МБ. Экспортируйте меньший диапазон сообщений без файлов.")
    chats = export.get("chats")
    if isinstance(chats, dict) and isinstance(chats.get("list"), list):
        selected = [chat for chat in chats["list"] if isinstance(chat, dict) and chat.get("type") == "saved_messages"]
        if not selected:
            raise TelegramError("В полном экспорте не найдено «Избранное» (saved_messages). Другие переписки не импортированы.")
    elif isinstance(export.get("messages"), list):
        chat_type = export.get("type")
        name = str(export.get("name", "")).casefold()
        if chat_type and chat_type != "saved_messages" and name not in _SAVED_NAMES:
            raise TelegramError("Выберите экспорт чата «Избранное». Другие личные переписки не импортированы.")
        selected = [export]
    else:
        raise TelegramError("Не найдены сообщения. Выберите result.json из экспорта Telegram Desktop.")
    if any(not isinstance(chat.get("messages"), list) for chat in selected):
        raise TelegramError("В JSON-экспорте неверный список сообщений.")
    if sum(len(chat["messages"]) for chat in selected) > MAX_MESSAGES:
        raise TelegramError("За один импорт можно принять до 10 000 сообщений. Выберите меньший диапазон дат.")
    result = {"imported": 0, "duplicates": 0, "skipped": 0}
    for chat in selected:
        for message in chat["messages"]:
            result[_add_message(message, chat.get("id"), "telegram_export", store)] += 1
    return result


def _dpapi(data: bytes, decrypt=False) -> bytes:
    if os.name != "nt":
        raise TelegramError("Постоянное хранение токена доступно только через Windows DPAPI.")
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_byte))]

    buffer = ctypes.create_string_buffer(data)
    incoming = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    outgoing = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    method = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    method.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    method.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not method(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing)):
        raise TelegramError("Windows не смог защитить или прочитать токен. Введите токен заново в настройках.")
    try:
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        kernel.LocalFree(ctypes.cast(outgoing.data, ctypes.c_void_p))


class TelegramBridge:
    def __init__(self, store, data_dir, transport=None):
        self.store = store
        self.data_dir = Path(data_dir)
        self._secret_path = self.data_dir / ".telegram-token.dpapi"
        self._transport = transport or self._request
        self._lock = threading.RLock()
        self._configure_lock = threading.Lock()
        self._stop = threading.Event()
        self._changed = threading.Event()
        self._thread = None
        self.workflow = None
        self._config = store.get_setting("telegram_config", {}) or {}
        self._token = ""
        self._last_error = ""
        if self._secret_path.is_file() and os.name == "nt":
            try:
                token = _dpapi(self._secret_path.read_bytes(), decrypt=True).decode("utf-8")
                if _TOKEN.fullmatch(token) and self._fingerprint(token) == self._config.get("token_fingerprint"):
                    self._token = token
            except Exception:
                self._last_error = "Введите токен заново: сохранённое подключение недоступно."

    @staticmethod
    def _fingerprint(token):
        return hashlib.sha256(token.encode()).hexdigest()[:24]

    @staticmethod
    def _request(token, method, payload):
        payload = dict(payload)
        files = payload.pop("_files", None)
        if files:
            boundary = "lab-" + secrets.token_hex(18)
            fields = []
            for name, value in payload.items():
                encoded = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
                fields.append(("--" + boundary + '\r\nContent-Disposition: form-data; name="' + name + '"\r\n\r\n' + encoded + "\r\n").encode("utf-8"))
            for name, (filename, content, mime) in files.items():
                if not isinstance(content, bytes) or len(content) > 8 * 1024 * 1024:
                    raise TelegramError("Файл для Telegram больше допустимого локального лимита.")
                fields.append(("--" + boundary + '\r\nContent-Disposition: form-data; name="' + name + '"; filename="' + filename + '"\r\nContent-Type: ' + mime + "\r\n\r\n").encode("utf-8") + content + b"\r\n")
            fields.append(("--" + boundary + "--\r\n").encode())
            body, content_type = b"".join(fields), "multipart/form-data; boundary=" + boundary
        else:
            body, content_type = json.dumps(payload).encode(), "application/json"
        request = Request("https://api.telegram.org/bot" + token + "/" + method,
                          data=body,
                          headers={"Content-Type": content_type, "Accept": "application/json"}, method="POST")
        with urlopen(request, timeout=30) as response:
            body = response.read(2 * 1024 * 1024 + 1)
        if len(body) > 2 * 1024 * 1024:
            raise TelegramError("Ответ Telegram слишком большой.")
        decoded = json.loads(body)
        if not decoded.get("ok"):
            raise TelegramError("Telegram отклонил запрос. Проверьте токен и доступ к сети.")
        return decoded.get("result")

    def _api(self, token, method, payload):
        try:
            return self._transport(token, method, payload)
        except Exception:
            # urllib errors contain the URL, and the URL contains the credential.
            raise TelegramError("Нет ответа Telegram. Проверьте сеть, токен и отсутствие другого запущенного приёмника этого бота.") from None

    def status(self):
        with self._lock:
            owner = self._config.get("owner_id") if self._token else None
            return {
                "configured": bool(self._token),
                "owner_id": owner,
                "username": self._config.get("username", "") if self._token else "",
                "pairing_code": self._config.get("pairing_code", "") if self._token and not owner else "",
                "workflow_enabled": self.workflow is not None,
                "status": self._last_error or ("Готов к приёму материалов" if owner else "Ожидает привязки владельца" if self._token else "Не подключён"),
            }

    def bind_workflow(self, start_run, cancel_run=None, presentation_builder=None):
        from .telegram_workflow import TelegramWorkflow
        self.workflow = TelegramWorkflow(self, start_run, cancel_run, presentation_builder)
        return self.workflow

    def present_plan(self, run_id):
        if self.workflow is None:
            raise TelegramError("Telegram-подтверждение пока не подключено.")
        return self.workflow.present_plan(run_id)

    def send_result(self, run_id):
        if self.workflow is None:
            raise TelegramError("Получение результатов в Telegram пока не подключено.")
        return self.workflow.send_result(run_id, manual=True)

    def tick_workflow(self):
        if self.workflow is not None:
            self.workflow.tick()
        publisher = getattr(self, "publisher", None)
        if publisher is not None:
            publisher.tick()

    def notify_run(self, run_id=None):
        # Worker completion only wakes the polling thread; all Telegram network
        # operations and durable delivery state remain in the workflow.
        self._changed.set()

    def configure(self, token):
        if not isinstance(token, str) or not _TOKEN.fullmatch(token.strip()):
            raise TelegramError("Введите корректный токен бота, полученный у @BotFather.")
        token = token.strip()
        with self._configure_lock:
            bot = self._api(token, "getMe", {})
            webhook = self._api(token, "getWebhookInfo", {})
            if not isinstance(bot, dict) or not bot.get("is_bot"):
                raise TelegramError("Telegram не подтвердил подключение бота.")
            if not isinstance(webhook, dict):
                raise TelegramError("Не удалось проверить режим подключения бота.")
            if webhook.get("url"):
                raise TelegramError("У этого бота уже настроен webhook. Используйте отдельного бота; существующее подключение не изменено.")
            fingerprint = self._fingerprint(token)
            with self._lock:
                previous = self._config if self._config.get("token_fingerprint") == fingerprint else {}
                config = {"bot_id": bot.get("id"), "username": str(bot.get("username", "")),
                          "owner_id": previous.get("owner_id"),
                          "pairing_code": previous.get("pairing_code") or secrets.token_urlsafe(12),
                          "token_fingerprint": fingerprint}
                self.data_dir.mkdir(parents=True, exist_ok=True)
                if os.name == "nt":
                    encrypted = _dpapi(token.encode("utf-8"))
                    temporary = self._secret_path.with_suffix(".tmp")
                    temporary.write_bytes(encrypted)
                    os.replace(temporary, self._secret_path)
                self.store.set_setting("telegram_config", config)
                self._config, self._token, self._last_error = config, token, ""
                self._changed.set()
            return self.status()

    def disconnect(self):
        with self._configure_lock, self._lock:
            self._token, self._config, self._last_error = "", {}, ""
            self.store.set_setting("telegram_config", {})
            self._secret_path.unlink(missing_ok=True)
            self._changed.set()
            return self.status()

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="telegram-intake", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        self._changed.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1)

    def _handle_update(self, token, update):
        callback = update.get("callback_query")
        if isinstance(callback, dict) and self.workflow is not None:
            self.workflow.handle_callback(token, callback)
            return None
        message = update.get("message")
        if not isinstance(message, dict):
            return None
        chat, sender = message.get("chat", {}), message.get("from", {})
        if not isinstance(chat, dict) or not isinstance(sender, dict):
            return None
        sender_id = sender.get("id")
        if chat.get("type") != "private" or not isinstance(sender_id, int) or isinstance(sender_id, bool) or sender_id <= 0 or sender_id != chat.get("id") or sender.get("is_bot"):
            return None
        with self._lock:
            if token != self._token:
                return None
            owner = self._config.get("owner_id")
            text = _flatten(message.get("text", "")).strip()
            if not owner:
                expected = "/start " + self._config.get("pairing_code", "")
                if not self._config.get("pairing_code") or not secrets.compare_digest(text.encode("utf-8"), expected.encode("utf-8")):
                    return None
                config = {**self._config, "owner_id": sender_id}
                self.store.set_setting("telegram_config", config)
                self._config = config
                return sender_id, ("Лаборатория подключена. Пересылайте выбранные материалы. " +
                                   ("Бот покажет план с памятью; исследование запустится только после вашего подтверждения кнопкой."
                                    if self.workflow is not None else "Исследование запускается только после вашего одобрения в локальном приложении."))
            if sender_id != owner:
                return None
            workflow = self.workflow
        # Never acquire the workflow lock while holding the bridge lock: HTTP
        # delivery can hold the workflow lock and recheck bridge identity.
        if workflow is not None:
            workflow.handle_message(token, message)
            return None
        with self._lock:
            if token != self._token or sender_id != self._config.get("owner_id"):
                return None
            if text in {"/start", "/help", "/research"} or text.startswith("/start "):
                return sender_id, "Перешлите материал, затем откройте лабораторию на компьютере и нажмите «Одобрить и исследовать». Получение сообщения не запускает модель."
            result = _add_message(message, chat.get("id"), "telegram_bot", self.store)
        if result == "skipped":
            return sender_id, "Материал не сохранён: нужен текст до 50 000 символов, ссылка или подпись к вложению."
        return sender_id, ("Материал сохранён во «Входящие»." if result == "imported" else "Этот материал уже есть во «Входящих».") + " Откройте лабораторию и одобрите исследование."

    def _poll_once(self, token, config):
        offset_key = "telegram_offset_" + config["token_fingerprint"]
        offset = self.store.get_setting(offset_key, 0)
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            offset = 0
        updates = self._api(token, "getUpdates", {"offset": offset, "timeout": 20, "limit": 50, "allowed_updates": ["message", "callback_query"]})
        if not isinstance(updates, list):
            raise TelegramError("Не удалось прочитать сообщения Telegram.")
        for update in updates:
            if not isinstance(update, dict) or not isinstance(update.get("update_id"), int) or isinstance(update.get("update_id"), bool) or update["update_id"] < offset:
                continue
            with self._lock:
                if self._stop.is_set() or token != self._token:
                    return
            reply = self._handle_update(token, update)
            with self._lock:
                # Intake is durable before acknowledging the update. A crash between
                # these commits merely replays an idempotent source insertion.
                self.store.set_setting(offset_key, update["update_id"] + 1)
                offset = update["update_id"] + 1
            if reply:
                self._api(token, "sendMessage", {"chat_id": reply[0], "text": reply[1]})
        with self._lock:
            if token == self._token:
                self._last_error = ""

    def _loop(self):
        while not self._stop.is_set():
            with self._lock:
                token, config = self._token, dict(self._config)
            if not token:
                self._changed.wait(5)
                self._changed.clear()
                continue
            try:
                self.tick_workflow()
                self._poll_once(token, config)
                self.tick_workflow()
            except Exception:
                with self._lock:
                    if token == self._token:
                        self._last_error = "Telegram временно недоступен. Приём повторится; исследования не запускаются автоматически."
                self._stop.wait(5)
