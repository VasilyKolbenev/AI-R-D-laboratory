"""Durable owner-approved publication packages; never invokes research.

Operational settings and local media are deliberately outside portable research
backups. A single live application instance owns this database. Ambiguous sends
are retained for human inspection rather than automatically repeated.
"""
from datetime import datetime, timedelta, timezone
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import secrets
import threading

from .core import canonical, digest
from .visual_skin import rotation_skin, rotation_position

CONFIG_KEY = 'publication_config_v1'
QUEUE_KEY = 'publication_queue_v1'
MOSCOW = timezone(timedelta(hours=3), 'Europe/Moscow')
DEFAULT_CONFIG = {'enabled': False, 'timezone': 'Europe/Moscow', 'slots': [], 'channel': None}
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()
_ID = re.compile(r'[A-Za-z0-9_-]{16}')
MAX_FILE = 8 * 1024 * 1024


class QueuePersistenceError(RuntimeError):
    """An approval cannot be confirmed from durable storage."""


class QueueConflict(QueuePersistenceError):
    """Another process committed a newer queue snapshot."""


class _Entries(dict):
    def __init__(self, value):
        super().__init__(value)
        self.saved = deepcopy(value)


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError('Время публикации должно содержать часовой пояс.')
    return value.astimezone(timezone.utc)


def _stamp(value):
    return _utc(value).isoformat(timespec='seconds')


def _next_slot(after, slots, occupied=()):
    local = _utc(after).astimezone(MOSCOW)
    occupied = set(occupied)
    for offset in range(740):
        day = local.date() + timedelta(days=offset)
        for slot in slots:
            if day.weekday() != slot['weekday']:
                continue
            hour, minute = map(int, slot['time'].split(':'))
            candidate = datetime(day.year, day.month, day.day, hour, minute, tzinfo=MOSCOW)
            if candidate > local and _stamp(candidate) not in occupied:
                return _stamp(candidate)
    return None


class Publisher:
    def __init__(self, store, bridge, presentation_builder, clock=None):
        self.store, self.bridge = store, bridge
        self.presentation_builder = presentation_builder
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        with _LOCKS_GUARD:
            self.lock = _LOCKS.setdefault(str(Path(store.path).resolve()), threading.RLock())
        with self.lock:
            entries = self._entries()
            changed = False
            for entry in entries.values():
                if entry['state'] == 'publishing':
                    entry.update(state='publication_uncertain', reason='Отправка была прервана; автоматического повтора нет.')
                    changed = True
            if changed:
                self._save(entries)

    def _entries(self):
        value = self.store.get_setting(QUEUE_KEY, {})
        return _Entries(value if isinstance(value, dict) else {})

    def _save(self, entries):
        if not isinstance(entries, _Entries):
            raise QueuePersistenceError('Не подтверждена исходная версия очереди.')
        if entries == entries.saved:
            return
        if not self.store.compare_and_set_setting(QUEUE_KEY, entries.saved, dict(entries)):
            raise QueueConflict('Очередь изменилась одновременно; устаревшая запись отклонена.')
        if self.store.get_setting(QUEUE_KEY, {}) != entries:
            raise QueuePersistenceError('Сохранение очереди не подтверждено. Проверьте /queue.')
        entries.saved = deepcopy(dict(entries))

    def _config(self):
        return {**DEFAULT_CONFIG, **self.store.get_setting(CONFIG_KEY, {})}

    def _identity(self):
        if not hasattr(self.bridge, '_lock'):
            raise ValueError('Сначала подключите Telegram-бота и владельца.')
        with self.bridge._lock:
            config = dict(getattr(self.bridge, '_config', {}))
            token = getattr(self.bridge, '_token', '')
        owner, fingerprint = config.get('owner_id'), config.get('token_fingerprint')
        if not token or type(owner) is not int or owner <= 0 or not isinstance(fingerprint, str) or not fingerprint:
            raise ValueError('Сначала подключите Telegram-бота и владельца.')
        return token, owner, fingerprint

    @staticmethod
    def _blockers(config):
        reasons = []
        if not config.get('channel'):
            reasons.append('Канал не подключён.')
        if not config['slots']:
            reasons.append('Расписание не задано.')
        if not config['enabled']:
            reasons.append('Публикация по расписанию выключена.')
        return reasons

    def _safe(self, entry, include_token=False):
        config = self._config()
        value = {key: entry.get(key) for key in ('id', 'run_id', 'title', 'package_sha256', 'post_text',
                 'approved_at', 'created_at', 'published_at', 'receipts', 'reason')}
        value.update(status=entry['state'], state=entry['state'], due_at=entry.get('due_at'),
                     scheduled_for=entry.get('due_at'), blockers=self._blockers(config),
                     can_enqueue=entry['state'] in {'awaiting_owner', 'queued'})
        if isinstance(entry.get('visual_skin'), dict):
            value['visual_skin'] = deepcopy(entry['visual_skin'])
        if include_token:
            value['token'] = entry['token']
        return value

    def status(self):
        with self.lock:
            config, entries = self._config(), self._entries()
            items = [self._safe(entry) for entry in sorted(entries.values(), key=lambda row: row['created_at'], reverse=True)]
            counts = {}
            for item in items:
                counts[item['status']] = counts.get(item['status'], 0) + 1
            blockers = self._blockers(config)
            return {'enabled': config['enabled'], 'timezone': config['timezone'], 'slots': config['slots'],
                    'channel_configured': bool(config['channel']), 'channel_connected': bool(config['channel']),
                    'channel_title': (config['channel'] or {}).get('title'), 'items': items, 'counts': counts,
                    'blockers': blockers, 'blocked_reason': ' '.join(blockers),
                    'next_slot': _next_slot(self.clock(), config['slots']) if config['slots'] else None}

    def configure(self, body):
        if not isinstance(body, dict) or set(body) - {'enabled', 'timezone', 'slots'}:
            raise ValueError('Настраиваются только включение, часовой пояс и слоты. Канал подключается отдельно.')
        with self.lock:
            config = self._config()
            updated = {**config, **body}
            if type(updated['enabled']) is not bool or updated['timezone'] != 'Europe/Moscow':
                raise ValueError('Укажите включение и часовой пояс Europe/Moscow.')
            slots = updated['slots']
            if not isinstance(slots, list) or len(slots) > 7:
                raise ValueError('Укажите до 7 слотов расписания.')
            cleaned = []
            for slot in slots:
                if (not isinstance(slot, dict) or set(slot) != {'weekday', 'time'}
                        or type(slot['weekday']) is not int or not 0 <= slot['weekday'] <= 6
                        or not isinstance(slot['time'], str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', slot['time'])):
                    raise ValueError('Слот: weekday от 0 до 6 и time в формате ЧЧ:ММ.')
                if slot not in cleaned:
                    cleaned.append(dict(slot))
            updated['slots'] = sorted(cleaned, key=lambda slot: (slot['weekday'], slot['time']))
            if updated != config:
                self.store.set_setting(CONFIG_KEY, updated)
                entries = self._entries()
                for entry in entries.values():
                    if entry['state'] == 'queued':
                        entry['due_at'] = None
                self._schedule(entries, updated, _utc(self.clock()))
                self._save(entries)
            return self.status()

    def connect_channel(self, channel):
        """Resolve and verify an explicitly selected public handle or channel ID.

        A target must be a verified channel with posting rights for this bot.
        Changing target never grants an old queue approval to the new channel.
        """
        by_id = type(channel) is int and channel < 0
        by_name = isinstance(channel, str) and re.fullmatch(r'@[A-Za-z0-9_]{5,32}', channel)
        if not by_id and not by_name:
            raise ValueError('Укажите @username канала (5–32 латинских символа, цифры или _) либо его отрицательный числовой ID.')
        if not hasattr(self.bridge, '_lock'):
            raise ValueError('Сначала подключите Telegram-бота и владельца.')
        with self.lock, self.bridge._lock:
            token, owner, fingerprint = self._identity()
            bot_id = self.bridge._config.get('bot_id')
            if type(bot_id) is not int or bot_id <= 0:
                raise ValueError('Не удалось определить подключённого бота.')
            chat = self.bridge._api(token, 'getChat', {'chat_id': channel})
            channel_id = chat.get('id') if isinstance(chat, dict) else None
            if (not isinstance(chat, dict) or chat.get('type') != 'channel'
                    or type(channel_id) is not int or channel_id >= 0 or (by_id and channel_id != channel)):
                raise ValueError('Telegram не подтвердил выбранный канал; личные чаты и группы не подключаются.')
            if by_name:
                names = [chat.get('username')]
                aliases = chat.get('active_usernames')
                if isinstance(aliases, list):
                    names.extend(aliases[:100])
                if channel[1:].casefold() not in {name.casefold() for name in names if isinstance(name, str)}:
                    raise ValueError('Telegram вернул другой публичный адрес канала; подключение не изменено.')
            member = self.bridge._api(token, 'getChatMember', {'chat_id': channel_id, 'user_id': bot_id})
            member_user = member.get('user') if isinstance(member, dict) else None
            if (not isinstance(member, dict) or member.get('status') != 'administrator' or member.get('can_post_messages') is not True
                    or not isinstance(member_user, dict) or type(member_user.get('id')) is not int or member_user['id'] != bot_id):
                raise ValueError('Бот должен иметь право публиковать в выбранном канале.')
            config = self._config()
            target = {'id': channel_id, 'title': str(chat.get('title', 'Канал'))[:200],
                      'owner_id': owner, 'fingerprint': fingerprint}
            if target != config.get('channel'):
                original_config = deepcopy(config)
                previous = config.get('channel') or {}
                identity_changed = any(previous.get(key) != target[key] for key in ('id', 'owner_id', 'fingerprint'))
                config['channel'] = target
                entries = self._entries()
                if identity_changed:
                    for entry in entries.values():
                        if entry['state'] == 'queued':
                            entry.update(state='blocked', due_at=None, reason='Канал назначения изменился; покажите пакет и подтвердите выпуск заново.')
                # Target and invalidation commit together; failed verification
                # or a failed transaction cannot partially rebind the queue.
                with self.store.connect() as db:
                    db.execute('PRAGMA synchronous=FULL')
                    db.execute('BEGIN IMMEDIATE')
                    for key, expected in ((CONFIG_KEY, original_config), (QUEUE_KEY, entries.saved)):
                        row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
                        current = json.loads(row[0]) if row else (DEFAULT_CONFIG if key == CONFIG_KEY else {})
                        if key == CONFIG_KEY:
                            current = {**DEFAULT_CONFIG, **current}
                        if current != expected:
                            raise QueueConflict('Подключение или очередь изменились одновременно; подключение не сохранено.')
                    for key, value in ((CONFIG_KEY, config), (QUEUE_KEY, entries)):
                        db.execute('INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                                   (key, canonical(value)))
            return self.status()

    def _directory(self, entry_id):
        if not isinstance(entry_id, str) or not _ID.fullmatch(entry_id):
            raise ValueError('Некорректный выпуск.')
        base = Path(self.store.data_dir).resolve()
        path = base / 'publications' / entry_id
        if not path.resolve().is_relative_to(base) or path.is_symlink():
            raise ValueError('Повреждён путь публикационного пакета.')
        return path

    @staticmethod
    def _motion(data):
        story = data.get('motion_story') if isinstance(data, dict) else None
        return isinstance(story, dict) and story.get('version') == 'dataflow-v1'

    @staticmethod
    def _rotation_anchor(entries, channel):
        return max((rotation_position(entry.get('visual_skin')) or 0
                    for entry in entries.values()
                    if entry['state'] in {'published', 'publishing', 'publication_uncertain'}
                    and entry.get('binding', {}).get('channel_id') == channel), default=0)

    @classmethod
    def _next_rotation(cls, entries, channel):
        position = cls._rotation_anchor(entries, channel) + 1
        queued = sorted((rotation_position(entry.get('visual_skin'))
                         for entry in entries.values() if entry['state'] == 'queued'
                         and entry.get('binding', {}).get('channel_id') == channel
                         and rotation_position(entry.get('visual_skin')) is not None))
        for claimed in queued:
            if claimed != position:
                break
            position += 1
        return position

    @classmethod
    def _reconcile_rotation(cls, entries, channel):
        """Revoke a broken queued suffix; its approved files remain untouched."""
        expected = cls._rotation_anchor(entries, channel) + 1
        changed = False
        queued = sorted((entry for entry in entries.values() if entry['state'] == 'queued'
                         and entry.get('binding', {}).get('channel_id') == channel
                         and rotation_position(entry.get('visual_skin')) is not None),
                        key=lambda entry: (rotation_position(entry['visual_skin']), entry['id']))
        for entry in queued:
            if rotation_position(entry['visual_skin']) != expected:
                entry.update(state='blocked', due_at=None,
                             reason='Порядок выпусков изменился. Откройте /result, проверьте новый стиль и нажмите «В очередь» заново.')
                changed = True
            else:
                expected += 1
        return changed

    def apply_visual_rotation(self, run_id, data):
        """Pure preview selection: GETs/retries never consume a publication."""
        if not self._motion(data):
            return data
        with self.lock:
            entries = self._entries()
            channel = (self._config().get('channel') or {}).get('id')
            candidates = [entry for entry in entries.values()
                          if entry['run_id'] == run_id and entry['state'] in
                          {'awaiting_owner', 'queued', 'publishing', 'published', 'publication_uncertain'}
                          and entry.get('binding', {}).get('channel_id') == channel
                          and rotation_position(entry.get('visual_skin')) is not None]
            if candidates:
                # A fresh preview takes precedence over an older published
                # edition of the same research. Existing assets are immutable.
                entry = max(candidates, key=lambda row: (row['state'] in {'awaiting_owner', 'queued'},
                                                         row['created_at'], row['id']))
                skin = deepcopy(entry['visual_skin'])
            else:
                skin = rotation_skin(self._next_rotation(entries, channel))
            return {**data, 'visual_skin': skin}

    def _content(self, run_id, pinned_skin=None):
        run = self.store.run(run_id)
        if run['status'] != 'completed' or not run.get('output', '').strip():
            raise ValueError('Публикация доступна только для готового исследования.')
        data = self.presentation_builder(run)
        if self._motion(data) and rotation_position(pinned_skin) is not None:
            data = {**data, 'visual_skin': deepcopy(pinned_skin)}
        post = data.get('post_text')
        if ((data.get('publication_checks') or {}).get('status') != 'ready' or data.get('post_compacted')
                or not isinstance(post, str) or not post.strip() or len(post.encode('utf-16-le')) // 2 > 3500):
            raise ValueError('Пост не прошёл проверку полноты и формата; платного исправления не будет.')
        review = self.store.review.get(run_id).get('current')
        signature = digest({'run_id': run_id, 'plan_hash': run['plan_hash'], 'output_sha256': _sha(run['output'].encode('utf-8')),
                            'review_version': review.get('version') if review else None, 'presentation': data})
        return data, signature

    def prepare(self, run_id):
        with self.lock:
            _, owner, fingerprint = self._identity()
            data, _ = self._content(run_id)
            data = self.apply_visual_rotation(run_id, data)
            data, signature = self._content(run_id, data.get('visual_skin'))
            config, entries = self._config(), self._entries()
            channel = (config.get('channel') or {}).get('id')
            binding = {'owner_id': owner, 'fingerprint': fingerprint, 'channel_id': channel, 'content_signature': signature}
            for entry in entries.values():
                if entry['binding'] == binding and entry['state'] in {'awaiting_owner', 'queued', 'publishing', 'published', 'publication_uncertain'}:
                    self._assets(entry)
                    return self._safe(entry, True)
            # A changed report replaces its old preview/approval. Reconcile
            # before assigning the replacement so it fills the released place.
            for previous in entries.values():
                if previous['run_id'] == run_id and previous['state'] in {'awaiting_owner', 'queued'}:
                    previous.update(state='blocked', due_at=None, reason='Пакет или канал изменился; требуется новый апрув.')
            self._reconcile_rotation(entries, channel)
            if self._motion(data):
                data, signature = self._content(run_id, rotation_skin(self._next_rotation(entries, channel)))
                binding['content_signature'] = signature
            from . import presentation
            png, mp4 = presentation.render_png(data), presentation.render_mp4(data)
            if any(not isinstance(content, bytes) or not content or len(content) > MAX_FILE for content in (png, mp4)):
                raise ValueError('Для апрува нужны готовые PNG и MP4; повторное исследование не запускается.')
            if sum(entry['state'] in {'awaiting_owner', 'queued'} for entry in entries.values()) >= 100:
                raise ValueError('В очереди уже 100 пакетов; сначала обработайте их.')
            entry_id = secrets.token_urlsafe(12)
            directory = self._directory(entry_id)
            directory.mkdir(parents=True, exist_ok=False)
            payloads = {'post.txt': data['post_text'].encode('utf-8'), 'card.png': png, 'animation.mp4': mp4}
            files = {name: {'sha256': _sha(content), 'bytes': len(content)} for name, content in payloads.items()}
            package = {'binding': binding, 'files': files, 'run_id': run_id, 'rules_version': (data.get('publication_rules') or {}).get('version')}
            package_sha = digest(package)
            for name, content in payloads.items():
                (directory / name).write_bytes(content)
            (directory / 'manifest.json').write_text(canonical(package), encoding='utf-8')
            entry = {'id': entry_id, 'token': secrets.token_urlsafe(12), 'run_id': run_id,
                     'title': str(data.get('title') or 'Готовый разбор')[:200], 'post_text': data['post_text'],
                     'binding': binding, 'files': files, 'package_sha256': package_sha,
                     'state': 'awaiting_owner', 'preview_message_id': None, 'approved_at': None,
                     'due_at': None, 'created_at': _stamp(self.clock()), 'receipts': [], 'reason': None}
            if self._motion(data):
                entry['visual_skin'] = deepcopy(data['visual_skin'])
            entries[entry_id] = entry
            self._save(entries)
            return self._safe(entry, True)

    def _assets(self, entry):
        directory = self._directory(entry['id'])
        manifest_path = directory / 'manifest.json'
        if manifest_path.is_symlink() or manifest_path.stat().st_size > 65536:
            raise ValueError('Манифест публикационного пакета повреждён.')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if digest(manifest) != entry['package_sha256'] or manifest['files'] != entry['files'] or manifest['binding'] != entry['binding']:
            raise ValueError('Контрольная сумма пакета изменилась; требуется новый просмотр.')
        contents = {}
        for name in ('post.txt', 'card.png', 'animation.mp4'):
            path = directory / name
            expected = entry['files'][name]
            if path.is_symlink() or path.stat().st_size != expected['bytes'] or expected['bytes'] > MAX_FILE:
                raise ValueError('Публикационный файл повреждён.')
            value = path.read_bytes()
            if _sha(value) != expected['sha256']:
                raise ValueError('Публикационный файл изменился.')
            contents[name] = value
        if contents['post.txt'] != entry['post_text'].encode('utf-8'):
            raise ValueError('Текст публикационного пакета изменился.')
        return {'png': contents['card.png'], 'mp4': contents['animation.mp4']}

    def assets(self, entry_id):
        with self.lock:
            entry = self._entries().get(entry_id)
            if not entry:
                raise ValueError('Выпуск не найден.')
            return self._assets(entry)

    def bind_preview(self, entry_id, message_id):
        if type(message_id) is not int or message_id <= 0:
            raise ValueError('Telegram не подтвердил сообщение с кнопкой.')
        with self.lock:
            entries = self._entries()
            entry = entries.get(entry_id)
            if not entry or entry['state'] not in {'awaiting_owner', 'queued'}:
                raise ValueError('Этот выпуск больше не принимает апрув.')
            entry['preview_message_id'] = message_id
            self._save(entries)
            return self._safe(entry)

    def _validate(self, entry, owner, fingerprint):
        _, active_owner, active_fingerprint = self._identity()
        if (type(owner) is not int or not isinstance(fingerprint, str) or owner != active_owner or fingerprint != active_fingerprint
                or entry['binding']['owner_id'] != owner or entry['binding']['fingerprint'] != fingerprint):
            raise ValueError('Подключение владельца изменилось; покажите пакет заново.')
        config = self._config()
        if entry['binding']['channel_id'] != (config.get('channel') or {}).get('id'):
            raise ValueError('Канал изменился; требуется новый апрув.')
        target = config.get('channel')
        if target and (target.get('owner_id') != owner or target.get('fingerprint') != fingerprint):
            raise ValueError('Права нового подключения в канале ещё не проверены.')
        if 'visual_skin' in entry and rotation_position(entry['visual_skin']) is None:
            raise ValueError('Оформление выпуска повреждено; требуется новый просмотр и апрув.')
        _, signature = self._content(entry['run_id'], entry.get('visual_skin'))
        if signature != entry['binding']['content_signature']:
            raise ValueError('Отчёт, редакционная версия или правила изменились; требуется новый апрув.')
        self._assets(entry)

    def approve(self, entry_id, token, message_id, owner, fingerprint):
        # Retrying only a local CAS conflict cannot publish or dispatch a study.
        for _ in range(3):
            try:
                return self._approve_once(entry_id, token, message_id, owner, fingerprint)
            except QueueConflict:
                continue
        raise QueuePersistenceError('Очередь меняется одновременно. Сохранение апрува не подтверждено; проверьте /queue.')

    def _approve_once(self, entry_id, token, message_id, owner, fingerprint):
        with self.lock:
            entries = self._entries()
            entry = entries.get(entry_id)
            if (not entry or not isinstance(token, str) or not secrets.compare_digest(token, entry['token'])
                    or type(message_id) is not int or entry['preview_message_id'] != message_id
                    or entry['state'] not in {'awaiting_owner', 'queued'}):
                raise ValueError('Кнопка недействительна; откройте актуальный готовый пост.')
            self._validate(entry, owner, fingerprint)
            channel = (self._config().get('channel') or {}).get('id')
            self._reconcile_rotation(entries, channel)
            if entry['state'] == 'blocked':
                self._save(entries)
                raise ValueError(entry['reason'])
            if entry['state'] != 'queued':
                position = rotation_position(entry.get('visual_skin'))
                if position is not None and position != self._next_rotation(entries, channel):
                    entry.update(state='blocked', due_at=None,
                                 reason='Другой выпуск уже занял этот стиль. Откройте /result, проверьте новый пакет и нажмите «В очередь» заново.')
                    self._save(entries)
                    raise ValueError(entry['reason'])
                entry.update(state='queued', approved_at=_stamp(self.clock()), approved_message_id=message_id)
            if not entry.get('due_at'):
                self._schedule(entries, self._config(), _utc(self.clock()))
            self._save(entries)
            persisted = self._entries().get(entry_id)
            if persisted != entry or persisted.get('state') != 'queued' or not persisted.get('approved_at'):
                raise QueuePersistenceError('Сохранение апрува не подтверждено; проверьте /queue.')
            return self._safe(persisted)

    def _record_uncertain(self, attempted):
        """Keep confirmed receipts without overwriting another entry's approval."""
        for _ in range(3):
            entries = self._entries()
            current = entries.get(attempted['id'])
            if (not current or current['binding'] != attempted['binding']
                    or current['state'] not in {'publishing', 'publication_uncertain'}):
                raise QueuePersistenceError('Не удалось подтвердить состояние отправки. Автоматического повтора нет.')
            receipts = list(current.get('receipts', []))
            for receipt in attempted.get('receipts', []):
                if receipt not in receipts:
                    receipts.append(deepcopy(receipt))
            current.update(state='publication_uncertain', receipts=receipts,
                           reason='Исход отправки неизвестен; проверьте канал. Автоматического повтора нет.')
            try:
                self._save(entries)
                return
            except QueueConflict:
                continue
        raise QueuePersistenceError('Не удалось сохранить состояние отправки. Автоматического повтора нет.')

    def cancel(self, entry_id):
        with self.lock:
            _, owner, fingerprint = self._identity()
            entries = self._entries()
            entry = entries.get(entry_id)
            if (not entry or entry['state'] not in {'awaiting_owner', 'queued', 'blocked'}
                    or entry['binding']['owner_id'] != owner or entry['binding']['fingerprint'] != fingerprint):
                raise ValueError('Этот выпуск нельзя убрать из очереди: отправка могла начаться либо подключение изменилось.')
            entry.update(state='cancelled', due_at=None, reason='Владелец отозвал апрув публикации.')
            self._reconcile_rotation(entries, (self._config().get('channel') or {}).get('id'))
            self._save(entries)
            return self._safe(entry)

    @staticmethod
    def _schedule(entries, config, current):
        if Publisher._blockers(config):
            return
        channel_id = config['channel']['id']
        rotated = sorted((entry for entry in entries.values() if entry['state'] == 'queued'
                          and entry['binding']['channel_id'] == channel_id
                          and rotation_position(entry.get('visual_skin')) is not None),
                         key=lambda row: (rotation_position(row['visual_skin']), row['id']))
        # A missed/cancelled slot must not put the first style behind the next
        # one. Reassign only the affected suffix, preserving on-time due slots.
        reset, previous = False, None
        for entry in rotated:
            due = datetime.fromisoformat(entry['due_at']) if entry.get('due_at') else None
            if reset or due is None or due < current - timedelta(minutes=2) or (previous and due <= previous):
                entry['due_at'] = None
                reset = True
            else:
                previous = due
        occupied = {entry['due_at'] for entry in entries.values() if entry.get('due_at')
                    and entry['state'] in {'queued', 'publishing', 'published', 'publication_uncertain'}}
        def order(row):
            position = rotation_position(row.get('visual_skin'))
            return (1, position, row['id']) if position is not None else (0, row.get('approved_at') or row['created_at'], row['id'])
        previous = None
        for entry in sorted(entries.values(), key=order):
            if entry['state'] == 'queued' and not entry.get('due_at') and entry['binding']['channel_id'] == channel_id:
                after = max(current, previous) if rotation_position(entry.get('visual_skin')) is not None and previous else current
                entry['due_at'] = _next_slot(after, config['slots'], occupied)
                if entry['due_at']:
                    occupied.add(entry['due_at'])
            if (entry['state'] == 'queued' and entry['binding']['channel_id'] == channel_id
                    and rotation_position(entry.get('visual_skin')) is not None and entry.get('due_at')):
                previous = datetime.fromisoformat(entry['due_at'])

    def tick(self, now=None):
        with self.lock:
            current = _utc(now or self.clock())
            config, entries = self._config(), self._entries()
            if self._blockers(config):
                return self.status()
            try:
                token, owner, fingerprint = self._identity()
            except ValueError:
                return self.status()
            for entry in entries.values():
                if entry['state'] != 'queued':
                    continue
                if (entry['binding']['channel_id'] != config['channel']['id'] or entry['binding']['owner_id'] != owner
                        or entry['binding']['fingerprint'] != fingerprint or config['channel'].get('owner_id') != owner
                        or config['channel'].get('fingerprint') != fingerprint):
                    entry.update(state='blocked', due_at=None, reason='Владелец, бот или канал изменился; требуется новый апрув.')
                elif entry.get('due_at') and current > datetime.fromisoformat(entry['due_at']) + timedelta(minutes=2):
                    entry['due_at'] = None
            self._reconcile_rotation(entries, config['channel']['id'])
            self._schedule(entries, config, current)
            self._save(entries)
            due = [entry for entry in entries.values() if entry['state'] == 'queued' and entry.get('due_at')
                   and datetime.fromisoformat(entry['due_at']) <= current]
            if not due:
                return self.status()
            entry = min(due, key=lambda row: (row['due_at'], row['id']))
            try:
                self._validate(entry, owner, fingerprint)
                media = self._assets(entry)
            except (ValueError, OSError, KeyError):
                entry.update(state='blocked', due_at=None, reason='Пакет или контекст изменился; требуется новый просмотр и апрув.')
                self._reconcile_rotation(entries, config['channel']['id'])
                self._save(entries)
                return self.status()
            entry.update(state='publishing', attempted_at=_stamp(current))
            self._save(entries)  # Durable intent before the first network request.
            actions = [
                ('sendMessage', {'text': entry['post_text'], 'link_preview_options': {'is_disabled': True}}),
                ('sendPhoto', {'photo': 'attach://photo', 'disable_notification': True,
                               '_files': {'photo': ('research.png', media['png'], 'image/png')}}),
                ('sendAnimation', {'animation': 'attach://animation', 'disable_notification': True,
                                   '_files': {'animation': ('research.mp4', media['mp4'], 'video/mp4')}})]
            try:
                for method, payload in actions:
                    with self.bridge._lock:
                        active_token, active_owner, active_fingerprint = self._identity()
                        if (active_token, active_owner, active_fingerprint) != (token, owner, fingerprint):
                            raise ValueError('Подключение изменилось во время отправки.')
                        response = self.bridge._api(token, method, {**payload, 'chat_id': config['channel']['id']})
                    message_id = response.get('message_id') if isinstance(response, dict) else None
                    if type(message_id) is not int or message_id <= 0:
                        raise ValueError('Telegram не подтвердил публикацию.')
                    entry['receipts'].append({'method': method, 'message_id': message_id, 'confirmed_at': _stamp(self.clock())})
                    self._save(entries)
                entry.update(state='published', published_at=_stamp(self.clock()), reason=None)
            except Exception:
                self._record_uncertain(entry)
                return self.status()
            try:
                self._save(entries)
            except QueueConflict:
                self._record_uncertain(entry)
            return self.status()
