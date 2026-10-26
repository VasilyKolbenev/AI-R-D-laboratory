"""Read-only, loopback-only preview of the Frontier research instrument.

This server cannot approve, dispatch, save or publish anything. Its only upstream
is the owner's existing local laboratory, and only explicit GET routes are read.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.client import HTTPException
from pathlib import Path
import re
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


ROOT = Path(__file__).resolve().parent
UPSTREAM = "http://127.0.0.1:8795"
PORT = 8797
MAX_BODY = 12 * 1024 * 1024
TIMEOUT = 12
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; "
    "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
    "object-src 'none'; base-uri 'none'; form-action 'none'"
)
API_PATH = re.compile(
    r"/api/(?:health|runs|knowledge|research|publication|benchmarks/lexical(?:/[a-f0-9]{64}(?:/export)?)?|runs/[a-f0-9]{32}(?:/(?:presentation|quality|research))?)\Z"
)
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/instrument.css": ("instrument.css", "text/css; charset=utf-8"),
    "/instrument.js": ("instrument.js", "text/javascript; charset=utf-8"),
    "/library.js": ("library.js", "text/javascript; charset=utf-8"),
    "/library.css": ("library.css", "text/css; charset=utf-8"),
    "/benchmark.js": ("benchmark.js", "text/javascript; charset=utf-8"),
    "/benchmark.css": ("benchmark.css", "text/css; charset=utf-8"),
    "/icons.svg": ("icons.svg", "image/svg+xml"),
}
FONT_PATH = re.compile(r"/fonts/[a-zA-Z0-9_-]+\.(?:ttf|woff2|txt)\Z")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


def upstream_json(path: str) -> bytes:
    """The caller must supply an allowlisted path; no remote input is accepted."""
    if not API_PATH.fullmatch(path):
        raise ValueError("The preview only reads explicitly allowed API routes")
    opener = build_opener(ProxyHandler({}), NoRedirect())
    request = Request(UPSTREAM + path, headers={
        "Accept": "application/json", "User-Agent": "VV-Frontier-ReadOnly-Preview/1"
    }, method="GET")
    with opener.open(request, timeout=TIMEOUT) as response:
        if response.status != 200 or response.headers.get_content_type() != "application/json":
            raise ValueError("The local laboratory did not return a JSON record")
        body = response.read(MAX_BODY + 1)
    if len(body) > MAX_BODY:
        raise ValueError("The saved record exceeds the preview size limit")
    # Validate JSON before exposing it to the page; do not forward upstream headers.
    json.loads(body)
    return body


class PreviewHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "FrontierReadOnlyPreview/1"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(TIMEOUT)

    def log_message(self, *_args):
        # No paths, query text, report contents, tokens, or request bodies in logs.
        pass

    def send_bytes(self, status: int, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_json(self, status: int, message: str):
        body = json.dumps({"error": message, "preview_read_only": True}, ensure_ascii=False).encode("utf-8")
        self.send_bytes(status, body, "application/json; charset=utf-8")

    def local_request(self) -> bool:
        port = self.server.server_address[1]
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        host_values = self.headers.get_all("Host", [])
        if self.client_address[0] != "127.0.0.1" or len(host_values) != 1 or host_values[0] not in hosts:
            self.send_json(403, "Предпросмотр доступен только с этого компьютера.")
            return False
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + host_values[0]:
            self.send_json(403, "Межсайтовый доступ к локальным данным запрещён.")
            return False
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            self.send_json(403, "Межсайтовый доступ к локальным данным запрещён.")
            return False
        return True

    def do_GET(self):
        if not self.local_request():
            return
        try:
            parsed = urlsplit(self.path)
        except ValueError:
            self.send_json(400, "Этот адрес не разрешён в предпросмотре.")
            return
        if (parsed.scheme or parsed.netloc or "?" in self.path or "#" in self.path
                or "%" in self.path or "\\" in self.path
                or any(ord(char) < 32 for char in self.path)):
            self.send_json(400, "Этот адрес не разрешён в предпросмотре.")
            return
        path = parsed.path
        if API_PATH.fullmatch(path):
            try:
                self.send_bytes(200, upstream_json(path), "application/json; charset=utf-8")
            except HTTPError as error:
                if error.code in (404, 410):
                    self.send_json(404, "Сохранённая запись в лаборатории не найдена.")
                else:
                    self.send_json(502, "Лаборатория не вернула сохранённую запись. Повторите чтение позже.")
            except (URLError, TimeoutError, socket.timeout, ConnectionError, OSError, HTTPException):
                self.send_json(503, "Локальная лаборатория недоступна. Проверьте, открывается ли порт 8795.")
            except (ValueError, UnicodeError):
                self.send_json(502, "Сохранённая запись недоступна в формате предпросмотра.")
            return
        item = STATIC.get(path)
        if item is None and FONT_PATH.fullmatch(path):
            content_type = "text/plain; charset=utf-8" if path.endswith(".txt") else (
                "font/woff2" if path.endswith(".woff2") else "font/ttf")
            item = (path.lstrip("/"), content_type)
        if item is None:
            self.send_json(404, "Такого экрана нет. Откройте главную страницу предпросмотра.")
            return
        target = ROOT / item[0]
        if target.is_symlink() or not target.resolve().is_relative_to(ROOT.resolve()) or not target.is_file():
            self.send_json(404, "Файл интерфейса пока недоступен.")
            return
        try:
            with target.open("rb") as handle:
                body = handle.read(MAX_BODY + 1)
            if len(body) > MAX_BODY:
                self.send_json(413, "Файл интерфейса превышает предел предпросмотра.")
                return
            self.send_bytes(200, body, item[1])
        except OSError:
            self.send_json(404, "Файл интерфейса пока недоступен.")

    def reject_mutation(self):
        self.send_json(405, "Предпросмотр только читает сохранённые данные. Изменения и запуски доступны в основной лаборатории.")

    do_POST = reject_mutation
    do_PUT = reject_mutation
    do_PATCH = reject_mutation
    do_DELETE = reject_mutation
    do_OPTIONS = reject_mutation
    do_HEAD = reject_mutation
    do_CONNECT = reject_mutation
    do_TRACE = reject_mutation


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), PreviewHandler)
    server.daemon_threads = True
    print(f"VV Frontier read-only preview: http://127.0.0.1:{PORT}/", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
