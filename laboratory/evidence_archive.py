"""Bounded originals and inert text extraction; no model or downloaded execution."""
import base64
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import http.client
import io
import ipaddress
import json
import queue
import re
import socket
import ssl
import threading
import time
from urllib.parse import parse_qsl, urlsplit


MAX_BYTES = 1024 * 1024
FETCH_SECONDS = 6
MAX_FETCHES = 2
MAX_SEGMENTS = 48
MAX_SEGMENT_CHARS = 4000
MAX_TEXT_CHARS = 96_000
MAX_PDF_PAGES = 20
MAX_BUNDLE_CHARS = 48_000
MAX_BUNDLE_DOCUMENT_CHARS = 6000
PARSER_VERSION = 'inert-extract-v1'
STATUSES = {'captured', 'partial', 'unparseable', 'unsupported', 'failed', 'blocked'}
KINDS = {'supplied_text', 'fetched_html', 'fetched_pdf', 'fetched_other'}
NOTICE = ('Хеш фиксирует сохранённые байты, а не подлинность издателя. '
          'Текст извлечён локально; полнота и научная истинность не подтверждены.')
_HASH = re.compile(r'[0-9a-f]{64}\Z')
_SECRET = re.compile(r'-----BEGIN .*PRIVATE KEY|\bsk-[A-Za-z0-9_-]{20,}|'
                     r'\b[0-9]{6,20}:[A-Za-z0-9_-]{20,200}')
_PDF_LOCK = threading.RLock()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False)


def public_url(value):
    """Validate syntax and obvious private names; DNS is separately pinned."""
    if (not isinstance(value, str) or not 1 <= len(value) <= 3000
            or any(ord(c) < 33 or c.isspace() for c in value) or '\\' in value):
        raise ValueError('Источник: нужна ограниченная публичная ссылка.')
    try:
        parts = urlsplit(value)
        host = parts.hostname
        if (parts.scheme not in {'http', 'https'} or not host or parts.username
                or parts.password or parts.port not in {None, 80, 443}):
            raise ValueError()
        if (host.casefold() in {'localhost', 'localhost.localdomain'}
                or host.casefold().endswith(('.local', '.localhost', '.internal', '.lan'))):
            raise ValueError()
        try:
            if not ipaddress.ip_address(host).is_global:
                raise ValueError()
        except ValueError:
            if re.fullmatch(r'[0-9.:]+', host) or '.' not in host:
                raise ValueError()
        host.encode('idna')
        if _SECRET.search(value) or any(re.search(
                r'token|secret|password|signature|credential|api.?key|auth|session', key,
                re.I) for key, _ in parse_qsl(parts.query)):
            raise ValueError()
    except (ValueError, UnicodeError):
        raise ValueError('Источник: закрытый адрес, учётные данные или неверный URL.')
    return value


def _remaining(deadline, clock):
    remaining = deadline - clock()
    if remaining <= 0:
        raise TimeoutError('Срок получения источника истёк.')
    return remaining


def _resolve(host, port, remaining, resolver):
    # Native DNS cannot be cancelled. Its daemon worker can only return data;
    # a late result never opens a connection or continues the request.
    result = queue.Queue(maxsize=1)

    def work():
        try:
            result.put((True, resolver(host, port, type=socket.SOCK_STREAM)))
        except Exception:
            result.put((False, None))

    threading.Thread(target=work, daemon=True).start()
    try:
        success, answers = result.get(timeout=remaining)
    except queue.Empty:
        raise TimeoutError('DNS не завершился в пределах срока.')
    if not success or not answers:
        raise ValueError('DNS источника недоступен.')
    validated = []
    for family, socktype, _, _, address in answers:
        try:
            numeric = ipaddress.ip_address(address[0])
        except (ValueError, TypeError, IndexError):
            raise ValueError('DNS вернул неверный адрес.')
        if family not in {socket.AF_INET, socket.AF_INET6} or not numeric.is_global:
            raise ValueError('DNS содержит закрытый или смешанный набор адресов.')
        validated.append((family, str(numeric)))
    return validated[0]


def pinned_fetch(url, *, resolver=None, socket_factory=None, tls_context=None,
                 clock=None):
    """Fetch once through a validated numeric IP; no proxies, redirects or gzip."""
    public_url(url)
    resolver = resolver or socket.getaddrinfo
    socket_factory = socket_factory or socket.socket
    clock = clock or time.monotonic
    deadline = clock() + FETCH_SECONDS
    parts = urlsplit(url)
    host = parts.hostname.encode('idna').decode('ascii')
    port = parts.port or (443 if parts.scheme == 'https' else 80)
    family, numeric = _resolve(host, port, _remaining(deadline, clock), resolver)
    sock, connection, watchdog = None, None, None
    try:
        sock = socket_factory(family, socket.SOCK_STREAM)

        def expire():
            # A socket inactivity timeout alone permits slow-trickle headers.
            # Closing its transport at the absolute deadline bounds those reads.
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except (OSError, AttributeError):
                pass
            try:
                sock.close()
            except OSError:
                pass

        watchdog = threading.Timer(_remaining(deadline, clock), expire)
        watchdog.daemon = True
        watchdog.start()
        sock.settimeout(_remaining(deadline, clock))
        sock.connect((numeric, port))
        if parts.scheme == 'https':
            context = tls_context or ssl.create_default_context()
            sock.settimeout(_remaining(deadline, clock))
            sock = context.wrap_socket(sock, server_hostname=host)
        connection = http.client.HTTPConnection(host, port,
                                                timeout=_remaining(deadline, clock))
        connection.sock = sock
        target = (parts.path or '/') + ('?' + parts.query if parts.query else '')
        display_host = '[' + host + ']' if ':' in host else host
        default = 443 if parts.scheme == 'https' else 80
        host_header = display_host + (':' + str(port) if port != default else '')
        sock.settimeout(_remaining(deadline, clock))
        connection.request('GET', target, headers={
            'Host': host_header, 'Accept-Encoding': 'identity',
            'User-Agent': 'AI-RD-Laboratory-Evidence/1', 'Connection': 'close'})
        sock.settimeout(_remaining(deadline, clock))
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError('Получение не выполнено: HTTP ' + str(response.status) + '.')
        if response.getheader('Content-Encoding', 'identity').lower().strip() not in {
                '', 'identity'}:
            raise ValueError('Сжатые ответы не принимаются; декомпрессии не будет.')
        length = response.getheader('Content-Length')
        if length and (not length.isdigit() or int(length) > MAX_BYTES):
            raise ValueError('Источник превышает ограничение размера.')
        content_type = response.getheader('Content-Type', 'application/octet-stream')
        if len(content_type) > 200:
            raise ValueError('Неверный Content-Type.')
        chunks, size = [], 0
        while True:
            sock.settimeout(_remaining(deadline, clock))
            # read1 returns after at most one underlying read; unlike read(n),
            # slow trickles cannot reset a per-read timeout indefinitely.
            chunk = response.read1(min(16_384, MAX_BYTES + 1 - size))
            _remaining(deadline, clock)
            if not chunk:
                break
            chunks.append(chunk); size += len(chunk)
            if size > MAX_BYTES:
                raise ValueError('Источник превышает ограничение размера.')
        return {'raw': b''.join(chunks), 'content_type': content_type}
    finally:
        if watchdog is not None:
            watchdog.cancel()
        if connection is not None:
            connection.close()
        elif sock is not None:
            sock.close()


class _Segments:
    def __init__(self):
        self.rows, self.total, self.partial = [], 0, False

    def add(self, text, locator):
        text = re.sub(r'\s+', ' ', text).strip()
        if not text:
            return
        if len(self.rows) >= MAX_SEGMENTS or self.total >= MAX_TEXT_CHARS:
            self.partial = True
            return
        allowed = min(MAX_SEGMENT_CHARS, MAX_TEXT_CHARS - self.total)
        if len(text) > allowed:
            self.partial = True
        text = text[:allowed]
        self.rows.append({'id': 's' + str(len(self.rows) + 1), 'locator': locator,
                          'text': text})
        self.total += len(text)


class _HTML(HTMLParser):
    def __init__(self, segments):
        super().__init__(convert_charrefs=True)
        self.segments = segments
        self.buffer, self.cells = [], []
        self.skip = 0
        self.table, self.row, self.block = 0, 0, 0
        self.in_row = False

    def flush(self):
        if self.buffer and not self.in_row:
            self.block += 1
            self.segments.add(' '.join(self.buffer), 'html:block:' + str(self.block))
            self.buffer = []

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'noscript'}:
            self.skip += 1
        if self.skip:
            return
        if tag == 'table':
            self.flush(); self.table += 1; self.row = 0
        if tag == 'tr':
            self.flush(); self.in_row = True; self.row += 1; self.cells = []
        if tag in {'td', 'th'} and self.in_row and self.buffer:
            self.cells.append(' '.join(self.buffer)); self.buffer = []
        if tag in {'p', 'div', 'section', 'h1', 'h2', 'h3', 'li', 'br'}:
            self.flush()

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'noscript'} and self.skip:
            self.skip -= 1
            return
        if self.skip:
            return
        if tag in {'td', 'th'} and self.in_row:
            self.cells.append(' '.join(self.buffer)); self.buffer = []
        if tag == 'tr' and self.in_row:
            if self.buffer:
                self.cells.append(' '.join(self.buffer)); self.buffer = []
            locator = 'html:table:' + str(self.table) + ':row:' + str(self.row)
            self.segments.add(' | '.join(self.cells), locator)
            self.in_row = False
        if tag in {'p', 'div', 'section', 'h1', 'h2', 'h3', 'li', 'table'}:
            self.flush()

    def handle_data(self, data):
        if not self.skip:
            self.buffer.append(data)


def _pdf_pages(raw, segments):
    from pypdf import PdfReader
    from pypdf import filters
    names = ('ZLIB_MAX_OUTPUT_LENGTH', 'ZLIB_MAX_RECOVERY_INPUT_LENGTH',
             'MAX_DECLARED_STREAM_LENGTH', 'MAX_ARRAY_BASED_STREAM_OUTPUT_LENGTH')
    if not all(hasattr(filters, name) for name in names):
        raise ValueError('PDF-парсер не предоставляет границы декодирования.')
    # The installed parser documents bounded Flate decoding. Other codecs and
    # prediction arrays are rejected, rather than invoking optional helpers.
    with _PDF_LOCK:
        previous = {name: getattr(filters, name) for name in names}
        decode = filters.decode_stream_data

        def bounded_decode(stream):
            methods = stream.get('/Filter', [])
            if not isinstance(methods, list):
                methods = [methods]
            if any(str(method) not in {'/FlateDecode', '/Fl'} for method in methods):
                raise ValueError('PDF использует неподдерживаемый кодек.')
            parameters = stream.get('/DecodeParms') or {}
            if isinstance(parameters, list) or parameters.get('/Predictor', 1) != 1:
                raise ValueError('PDF prediction-массивы не декодировались.')
            return decode(stream)

        try:
            for name in names:
                setattr(filters, name, 2 * MAX_BYTES)
            filters.ZLIB_MAX_RECOVERY_INPUT_LENGTH = 1024
            filters.decode_stream_data = bounded_decode
            reader = PdfReader(io.BytesIO(raw), strict=True)
            if reader.is_encrypted:
                raise ValueError('Зашифрованный PDF не разбирался.')
            if len(reader.pages) > MAX_PDF_PAGES:
                segments.partial = True
            for index in range(min(len(reader.pages), MAX_PDF_PAGES)):
                text = reader.pages[index].extract_text() or ''
                segments.add(text, 'pdf:page:' + str(index + 1))
        finally:
            filters.decode_stream_data = decode
            for name, value in previous.items():
                setattr(filters, name, value)


def _extract(raw, kind, content_type):
    segments = _Segments()
    limitations = []
    try:
        if kind == 'fetched_pdf':
            try:
                _pdf_pages(raw, segments)
            except ImportError:
                return [], 'unparseable', ['Установленный PDF-парсер отсутствует.']
        elif kind in {'supplied_text', 'fetched_html'}:
            charset = 'utf-8'
            match = re.search(r'charset\s*=\s*["\']?([A-Za-z0-9_-]+)', content_type)
            if match:
                charset = match.group(1)
            try:
                text = raw.decode(charset, errors='strict')
            except (LookupError, UnicodeError):
                text = raw.decode('utf-8', errors='replace')
                limitations.append('Неизвестная/ошибочная кодировка: UTF-8 с заменой символов.')
            if kind == 'fetched_html':
                parser = _HTML(segments); parser.feed(text); parser.close(); parser.flush()
            else:
                for index, part in enumerate(text.splitlines() or [text]):
                    segments.add(part, 'text:line:' + str(index + 1))
        else:
            return [], 'unsupported', ['Тип источника не поддерживает извлечение текста.']
    except Exception:
        return [], 'unparseable', ['Не удалось безопасно извлечь текст; байты сохранены.']
    if not segments.rows:
        return [], 'unparseable', limitations + ['Текстовые сегменты не извлечены.']
    if segments.partial:
        limitations.append('Достигнута граница страниц/сегментов/текста; показана часть.')
    return segments.rows, 'partial' if segments.partial else 'captured', limitations


def validate_asset(kind, payload):
    """Pure validation: restore never fetches, imports a parser or reparses bytes."""
    if kind != 'source_capture':
        raise ValueError('Архив не поддерживает этот вид актива.')
    fields = {'version', 'source_id', 'source_content_hash', 'url', 'kind', 'status',
              'origin', 'retrieved_at', 'content_type', 'parser_version', 'sha256',
              'raw_b64', 'segments', 'limitations', 'previous_asset_id'}
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ValueError('Повреждена форма захвата источника.')
    if (payload['version'] != 'source-capture-v1' or payload['kind'] not in KINDS
            or payload['status'] not in STATUSES
            or payload['origin'] not in {'supplied', 'fetched'}
            or payload['parser_version'] != PARSER_VERSION):
        raise ValueError('Неверные версия, происхождение или статус захвата.')
    for key, limit in [('source_id', 100), ('content_type', 200),
                       ('retrieved_at', 50), ('raw_b64', (MAX_BYTES + 2) // 3 * 4)]:
        if not isinstance(payload[key], str) or len(payload[key]) > limit:
            raise ValueError('Неверное поле захвата: ' + key)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', payload['source_id']):
        raise ValueError('Неверный ID исходника.')
    for key in ('sha256', 'source_content_hash'):
        if not isinstance(payload[key], str) or not _HASH.fullmatch(payload[key]):
            raise ValueError('Неверный хеш источника.')
    previous = payload['previous_asset_id']
    if previous is not None and (not isinstance(previous, str) or not _HASH.fullmatch(previous)):
        raise ValueError('Неверная ссылка на предыдущий захват.')
    if payload['url']:
        public_url(payload['url'])
    elif payload['origin'] == 'fetched' and payload['status'] not in {'failed', 'blocked'}:
        raise ValueError('Полученный оригинал не связан с URL.')
    try:
        stamp = datetime.fromisoformat(payload['retrieved_at'])
        if stamp.tzinfo is None:
            raise ValueError()
        raw = base64.b64decode(payload['raw_b64'], validate=True)
    except (ValueError, TypeError):
        raise ValueError('Неверные время или байты захвата.')
    if len(raw) > MAX_BYTES or _sha(raw) != payload['sha256']:
        raise ValueError('Контрольная сумма оригинала не совпала.')
    rows, notes = payload['segments'], payload['limitations']
    if not isinstance(rows, list) or len(rows) > MAX_SEGMENTS:
        raise ValueError('Неверное число сегментов.')
    seen, total = set(), 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'id', 'locator', 'text'}:
            raise ValueError('Повреждён сегмент источника.')
        if (not isinstance(row['id'], str) or not re.fullmatch(r's[1-9][0-9]*', row['id'])
                or row['id'] in seen or not isinstance(row['locator'], str)
                or not 1 <= len(row['locator']) <= 120 or not isinstance(row['text'], str)
                or not 1 <= len(row['text']) <= MAX_SEGMENT_CHARS):
            raise ValueError('Неверные ID, locator или текст сегмента.')
        seen.add(row['id']); total += len(row['text'])
    if total > MAX_TEXT_CHARS or not isinstance(notes, list) or len(notes) > 12:
        raise ValueError('Нарушена граница извлечённого текста.')
    if any(not isinstance(note, str) or len(note) > 500 for note in notes):
        raise ValueError('Неверное пояснение захвата.')
    if (payload['status'] in {'captured', 'partial'}) != bool(rows):
        raise ValueError('Статус не соответствует наличию извлечённых сегментов.')


def document(asset, previous=None):
    payload = asset['payload']
    return {'asset_id': asset['id'], 'document_id': asset['id'],
            **{key: deepcopy(payload[key]) for key in
               ('source_id', 'url', 'kind', 'status', 'sha256', 'segments', 'limitations',
                'origin', 'retrieved_at', 'parser_version', 'previous_asset_id')},
            'source_changed': bool(previous and previous['payload']['sha256']
                                   != payload['sha256'])}


class Archive:
    def __init__(self, store):
        self.store = store

    @property
    def assets(self):
        return self.store.assets

    def get(self, identifier):
        asset = self.assets.get(identifier)
        validate_asset(asset['kind'], asset['payload'])
        expected = _sha(_canonical({'kind': asset['kind'],
                                    'payload': asset['payload']}).encode('utf-8'))
        if asset['id'] != expected:
            raise ValueError('Хеш актива источника повреждён.')
        return asset

    def _all(self):
        return self.assets.list(kind='source_capture', limit=100)

    def list(self, source_id=None, url=None, limit=100):
        rows = [self.get(row['id']) for row in self._all()
                if (source_id is None or row['payload']['source_id'] == source_id)
                and (url is None or row['payload']['url'] == url)]
        by_id = {row['id']: row for row in self._all()}
        return [document(row, by_id.get(row['payload']['previous_asset_id']))
                for row in rows[:max(1, min(int(limit), 100))]]

    def capture(self, source, fetch=False, refresh=False):
        if not isinstance(source, dict) or not isinstance(source.get('text', ''), str):
            raise ValueError('Нужен исходник с текстом и ID.')
        identifier = source.get('id')
        if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',
                                                              identifier):
            raise ValueError('Неверный ID исходника.')
        supplied = source.get('text', '').encode('utf-8')
        if len(supplied) > MAX_BYTES:
            raise ValueError('Предоставленный текст превышает 1 MiB.')
        source_hash = source.get('content_hash') or _sha(supplied)
        if not isinstance(source_hash, str) or not _HASH.fullmatch(source_hash):
            raise ValueError('Неверный хеш исходника.')
        origin = 'fetched' if fetch else 'supplied'
        url, denied = source.get('url') or '', False
        if url:
            try:
                public_url(url)
            except ValueError:
                url, denied = '', True
        existing = [row for row in self._all()
                    if row['payload']['origin'] == origin and row['payload']['url'] == url
                    and (fetch or (row['payload']['source_content_hash'] == source_hash
                                   and row['payload']['sha256'] == _sha(supplied)))]
        previous = existing[0] if existing else None
        if previous and not refresh and not denied:
            if previous['payload']['source_id'] == identifier:
                return self.get(previous['id'])
            copied = deepcopy(previous['payload'])
            copied.update(source_id=identifier, source_content_hash=source_hash)
            validate_asset('source_capture', copied)
            return self.assets.put('source_capture', copied)
        payload = {'version': 'source-capture-v1', 'source_id': identifier,
                   'source_content_hash': source_hash, 'url': url, 'origin': origin,
                   'retrieved_at': _now(), 'content_type': 'text/plain; charset=utf-8',
                   'parser_version': PARSER_VERSION, 'kind': 'supplied_text',
                   'status': 'captured', 'raw_b64': '', 'sha256': _sha(b''),
                   'segments': [], 'limitations': [],
                   'previous_asset_id': previous['id'] if previous else None}
        raw = supplied
        if fetch:
            payload['kind'] = 'fetched_other'
            if denied or not url:
                raw = b''; payload['status'] = 'blocked'
                payload['limitations'] = ['Публичный URL не разрешён; загрузки не было.']
            else:
                try:
                    fetched = pinned_fetch(url)
                    raw, content_type = fetched['raw'], fetched['content_type']
                    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
                        raise ValueError('Неверные или избыточные байты ответа.')
                    payload['content_type'] = content_type
                    media = content_type.split(';', 1)[0].lower().strip()
                    payload['kind'] = ('fetched_pdf' if media == 'application/pdf' else
                                       'fetched_html' if media in {'text/html',
                                       'application/xhtml+xml'} else 'fetched_other')
                except (ValueError, OSError, TimeoutError, http.client.HTTPException):
                    raw = b''; payload['status'] = 'failed'
                    payload['limitations'] = [
                        'Получение источника не выполнено; повтор только явно.']
        if payload['status'] not in {'failed', 'blocked'}:
            if _SECRET.search(raw.decode('utf-8', errors='ignore')):
                raw = b''; payload['status'] = 'blocked'
                payload['limitations'] = ['Возможные учётные данные: байты не сохранялись.']
            else:
                segments, status, notes = _extract(raw, payload['kind'], payload['content_type'])
                payload.update(segments=segments, status=status, limitations=notes)
        if denied and not fetch:
            payload['limitations'].append('Закрытый/секретный URL исключён из архива.')
        if fetch and url.startswith('http:'):
            payload['limitations'].append('HTTP без TLS: подлинность сервера не подтверждена.')
        payload.update(raw_b64=base64.b64encode(raw).decode('ascii'), sha256=_sha(raw))
        validate_asset('source_capture', payload)
        return self.assets.put('source_capture', payload)

    def prepare(self, sources, fetch=False):
        if not isinstance(sources, list) or not 1 <= len(sources) <= 6:
            raise ValueError('Нужно от 1 до 6 исходников.')
        documents, attempts, notes = [], 0, []
        for source in sources:
            supplied = self.capture(source)
            documents.append(document(supplied))
            if fetch and source.get('url'):
                cached = any(row['payload']['origin'] == 'fetched'
                             and row['payload']['url'] == source['url'] for row in self._all())
                if not cached and attempts >= MAX_FETCHES:
                    notes.append('Граница двух загрузок: дополнительные URL не получались.')
                    continue
                if not cached:
                    attempts += 1
                captured = self.capture(source, fetch=True)
                previous_id = captured['payload']['previous_asset_id']
                previous = self.get(previous_id) if previous_id else None
                documents.append(document(captured, previous))
        bundle = {'version': 'source-bundle-v1', 'documents': documents,
                  'limitations': list(dict.fromkeys(notes)) + [NOTICE]}
        for row in documents:
            selected, shown = [], 0
            for segment in row['segments']:
                if shown + len(segment['text']) > MAX_BUNDLE_DOCUMENT_CHARS:
                    break
                selected.append(segment); shown += len(segment['text'])
            if len(selected) < len(row['segments']):
                row['segments'] = selected
                row['status'] = 'partial'
                row['limitations'].append(
                    'Пакет содержит часть сегментов; полный оригинал сохранён в архиве.')
        validate_bundle(bundle, sources)
        return bundle


def validate_bundle(bundle, sources=None):
    """Pure frozen projection validation; no live source lookup or network."""
    if (not isinstance(bundle, dict) or set(bundle) != {'version', 'documents', 'limitations'}
            or bundle['version'] != 'source-bundle-v1'
            or not isinstance(bundle['documents'], list) or len(bundle['documents']) > 12
            or not isinstance(bundle['limitations'], list)):
        raise ValueError('Неверная форма замороженного пакета источников.')
    allowed = {source['id'] for source in sources} if sources is not None else None
    seen, total = set(), 0
    allowed_fields = {'asset_id', 'document_id', 'source_id', 'url', 'kind', 'status',
                      'sha256', 'segments', 'limitations', 'origin', 'retrieved_at',
                      'parser_version', 'previous_asset_id', 'source_changed'}
    required = {'asset_id', 'document_id', 'source_id', 'url', 'kind', 'status',
                'sha256', 'segments', 'limitations'}
    for row in bundle['documents']:
        if (not isinstance(row, dict) or set(row) - allowed_fields
                or not required <= set(row)):
            raise ValueError('Неверный документ пакета.')
        identifier = row.get('asset_id')
        if (not isinstance(identifier, str) or not _HASH.fullmatch(identifier)
                or row.get('document_id') != identifier or identifier in seen
                or row.get('kind') not in KINDS or row.get('status') not in STATUSES
                or not _HASH.fullmatch(str(row.get('sha256', '')))
                or (allowed is not None and row.get('source_id') not in allowed)):
            raise ValueError('Неверные ID, версия или происхождение документа.')
        if row.get('url'):
            public_url(row['url'])
        segments = row.get('segments')
        if not isinstance(segments, list) or len(segments) > MAX_SEGMENTS:
            raise ValueError('Неверные сегменты пакета.')
        ids = set()
        for segment in segments:
            if (not isinstance(segment, dict) or set(segment) != {'id', 'locator', 'text'}
                    or not isinstance(segment['id'], str) or segment['id'] in ids
                    or not isinstance(segment['text'], str)
                    or not 1 <= len(segment['text']) <= MAX_SEGMENT_CHARS
                    or not isinstance(segment['locator'], str)
                    or not 1 <= len(segment['locator']) <= 120):
                raise ValueError('Повреждён сегмент пакета.')
            ids.add(segment['id'])
            total += len(segment['text'])
        if (row['status'] in {'captured', 'partial'}) != bool(segments):
            raise ValueError('Статус документа не соответствует его сегментам.')
        seen.add(identifier)
    if total > MAX_BUNDLE_CHARS:
        raise ValueError('Пакет превышает общую границу текста для модели.')
