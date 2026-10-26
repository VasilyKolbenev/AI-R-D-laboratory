from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import argparse
import json
import os
import secrets
import socket
import threading
import time
import webbrowser
from urllib.request import Request, urlopen

from . import __version__, providers
from .core import LabError, Store, research_prompt
from .telegram import TelegramBridge, TelegramError, import_telegram
from .presentation import build_presentation, render_svg, render_png, render_gif, render_mp4, publication_rules
from .publication import Publisher

ROOT = Path(__file__).resolve().parents[1]
WEB = Path(__file__).resolve().parent / "web"
MAX_REQUEST = 25 * 1024 * 1024
MAX_BACKUP_FILE = 100 * 1024 * 1024
MAX_RESTORE_REQUEST = 128 * 1024 * 1024


class Laboratory:
    def __init__(self, data_dir, runner=None, telegram_factory=TelegramBridge):
        self.store = Store(data_dir)
        self.store.recover_interrupted()
        self.store.memory.repair_completed_reviews()
        self.csrf = secrets.token_urlsafe(32)
        self.runner = runner or providers.run
        self.telegram = telegram_factory(self.store, data_dir)
        self.jobs = {}
        self.experiment_jobs = {}
        self.experiment_errors = {}
        self.lock = threading.Lock()
        self.publisher = Publisher(self.store, self.telegram, self.reviewed_presentation)
        self.telegram.publisher = self.publisher
        if hasattr(self.telegram, "bind_workflow"):
            self.telegram.bind_workflow(self.start_run, self.cancel, self.reviewed_presentation)
        from .operations import Operations
        self.operations = Operations(self.store, ROOT, snapshot_lock=getattr(self.telegram, '_configure_lock', None))

    def bootstrap(self):
        return {"csrf": self.csrf, "settings": self.store.settings(), "providers": providers.discovery(),
                "telegram": self.telegram.status(), "counts": self.store.counts(), "version": __version__,
                "operations": self.operations.status()}

    def start_run(self, run_id, body):
        run = self.store.run(run_id)
        if run["status"] == "planned" and self.runner is providers.run:
            info = next((p for p in providers.discovery() if p["id"] == run["plan"]["provider"]), {})
            if not info.get("installed"):
                raise LabError("Исполнитель не установлен. Выберите установленный CLI или подключите его в настройках.")
        with self.lock:
            if self.experiment_jobs:
                raise LabError("Дождитесь завершения эксперимента.")
            if not self.store.approve(run_id, body.get("plan_hash"), body.get("consent"), body.get("command_id")):
                return self.store.run(run_id)
            cancel = threading.Event()
            worker = threading.Thread(target=self._execute, args=(run_id, cancel), daemon=True)
            self.jobs[run_id] = (cancel, worker)
            try:
                worker.start()
            except Exception:
                self.jobs.pop(run_id, None)
                self.store.finish(run_id, {"status": "failed", "error": "Не удалось создать рабочий процесс; вызов не отправлен."})
                raise
        return self.store.run(run_id)

    def _execute(self, run_id, cancel):
        try:
            run = self.store.run(run_id)
            plan = run["plan"]
            work_dir = self.store.data_dir / "jobs" / run_id
            work_dir.mkdir(parents=True, exist_ok=True)
            if cancel.is_set():
                result = {"status": "cancelled", "error": "Отменено до отправки исполнителю."}
            else:
                if plan.get("research_protocol"):
                    from .orchestration import execute
                    result = execute(self.store, run, self.runner, work_dir, cancel)
                    self.store.finish(run_id, result)
                    return
                try:
                    exact_prompt = self.store.trace.capture(run)
                except ValueError as exc:
                    self.store.finish(run_id, {"status": "failed", "error": "Вызов не отправлен: " + str(exc)})
                    return
                result = self.runner(plan, exact_prompt, work_dir, cancel)
            self.store.finish(run_id, result)
        except Exception:
            self.store.finish(run_id, {"status": "outcome_unknown", "error": "Исполнитель завершился с ошибкой. Вызов мог состояться; автоматического повтора нет."})
        finally:
            with self.lock:
                self.jobs.pop(run_id, None)
            changed = getattr(self.telegram, "_changed", None)
            if changed is not None:
                changed.set()

    def presentation(self, run_id):
        run = self.store.run(run_id)
        if run["status"] != "completed" or not run["output"].strip():
            raise LabError("Краткий результат доступен после завершения исследования.")
        data = self.reviewed_presentation(run)
        # Media is optional; all factual content and SVG work without Pillow.
        try:
            import PIL
            raster_available = True
        except ImportError:
            raster_available = False
        data.setdefault("visual", {}).update(svg_available=True, png_available=raster_available,
                                              animation_available=raster_available)
        from .media_encoder import available
        data['visual']['video_available']=raster_available and (bool(data.get('comparisons')) or data['visual'].get('kind')=='process_flow' or bool(data.get('motion_story'))) and available()
        return data

    def reviewed_presentation(self, run):
        data = build_presentation(run, self.store.review.get(run["id"]))
        from .research_public import attach_public
        data = attach_public(data, run.get('output', ''))
        publisher = getattr(self, 'publisher', None)
        if publisher is not None:
            data = publisher.apply_visual_rotation(run['id'], data)
        lines = [data.get("title", "Прикладной разбор"), "Прикладная подача по сохранённому результату. Оформление не запускает модель."]
        for section in data.get("story", []):
            lines.extend(["", section.get("title", "")])
            if section.get("text"):
                lines.append(section["text"])
            lines.extend("• " + str(item) for item in section.get("items", []))
        if data.get("story") and data.get("next_step"):
            lines.extend(["", "С чего начать", data["next_step"]])
        lines.extend(["", "Источники из сохранённого отчёта:"])
        lines.extend(item["url"] for item in data.get("sources", []))
        data["brief_text"] = "\n".join(lines) if data.get("story") else data.get("post_text", "")
        return data

    def cancel(self, run_id):
        run = self.store.run(run_id)
        with self.lock:
            if run_id in self.jobs:
                self.jobs[run_id][0].set()
            elif run["status"] == "planned":
                self.store.cancel_planned(run_id)
        return self.store.run(run_id)

    def close(self):
        self.operations.stop()
        self.telegram.stop()
        with self.lock:
            jobs = list(self.jobs.values()) + list(self.experiment_jobs.values())
            for cancel, _ in jobs:
                cancel.set()
        for _, thread in jobs:
            thread.join(timeout=12)


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Handler(BaseHTTPRequestHandler):
    server_version = "AI-Laboratory"

    @property
    def app(self):
        return self.server.app

    def log_message(self, *args):
        pass

    def check_host(self):
        port = self.server.server_port
        if self.headers.get("Host") not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
            raise LabError("Доступ разрешён только с локального адреса лаборатории.")

    def send(self, value, status=200, content_type="application/json; charset=utf-8", download=None, csp=None):
        body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", csp or "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'")
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{download}"')
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def reject_post(self, value):
        # Closing a Windows socket with an unread request body can reset it
        # before the client receives our 403. Discard bytes only: rejected
        # requests never reach JSON parsing or any application mutation.
        self.close_connection = True
        lengths = self.headers.get_all("Content-Length", [])
        length = lengths[0] if len(lengths) == 1 else ""
        if (not self.headers.get("Transfer-Encoding") and length.isascii() and length.isdecimal()
                and len(length) <= 10 and 0 < int(length) <= 65536):
            remaining = int(length)
            deadline = time.monotonic() + 0.2
            previous_timeout = self.connection.gettimeout()
            try:
                while remaining:
                    available = deadline - time.monotonic()
                    if available <= 0:
                        break
                    self.connection.settimeout(available)
                    block = self.rfile.read1(min(65536, remaining))
                    if not block:
                        break
                    remaining -= len(block)
            except (OSError, ValueError):
                pass  # Slow, truncated or disconnected bodies still get 403.
            finally:
                try:
                    self.connection.settimeout(previous_timeout)
                except OSError:
                    pass
        return self.send(value, 403)

    def do_GET(self):
        try:
            self.check_host()
            parsed = urlsplit(self.path)
            path = parsed.path
            query = parse_qs(parsed.query).get("q", [""])[0]
            from .research_api import handle_get
            if handle_get(self, path):
                return
            if path == "/api/health":
                return self.send({"project": "AI-R-D-laboratory", "version": __version__, "root": str(ROOT), "data_dir": str(self.app.store.data_dir)})
            if path == "/api/bootstrap":
                return self.send(self.app.bootstrap())
            if path == '/api/operations':
                return self.send(self.app.operations.status())
            fieldwork_files = {
                '/workbench/': ('index.html', 'text/html; charset=utf-8'),
                '/workbench/index.html': ('index.html', 'text/html; charset=utf-8'),
                '/workbench/instrument.js': ('instrument.js', 'text/javascript; charset=utf-8'),
                '/workbench/instrument.css': ('instrument.css', 'text/css; charset=utf-8'),
                '/workbench/library.js': ('library.js', 'text/javascript; charset=utf-8'),
                '/workbench/library.css': ('library.css', 'text/css; charset=utf-8'),
                '/workbench/benchmark.js': ('benchmark.js', 'text/javascript; charset=utf-8'),
                '/workbench/benchmark.css': ('benchmark.css', 'text/css; charset=utf-8'),
                '/workbench/icons.svg': ('icons.svg', 'image/svg+xml'),
                '/workbench/fonts/Manrope.ttf': ('fonts/Manrope.ttf', 'font/ttf'),
            }
            if path == '/workbench':
                self.send_response(302)
                self.send_header('Location', '/workbench/')
                self.end_headers()
                return
            if path in fieldwork_files:
                name, kind = fieldwork_files[path]
                file = ROOT / 'deliverables/ui/frontier-instrument' / name
                if not file.is_file() or file.is_symlink():
                    return self.send({'error': 'Рабочий стол ещё не установлен.'}, 404)
                return self.send(file.read_bytes(), content_type=kind)
            if path in {'/concepts/', '/concepts/lens.html', '/concepts/atlas.html', '/concepts/story.html',
                        '/concepts/v2.html', '/concepts/reactor.html', '/concepts/observatory.html',
                        '/concepts/dispatch.html', '/concepts/workbench.js', '/concepts/workbench.css'}:
                name = 'index.html' if path == '/concepts/' else path.rsplit('/', 1)[-1]
                file = ROOT / 'deliverables/ui/frontier-future' / name
                if not file.is_file():
                    return self.send({'error': 'Концепт ещё не установлен.'}, 404)
                policy = "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src data:; connect-src 'none'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'"
                kind = {'js': 'text/javascript', 'css': 'text/css'}.get(file.suffix.lstrip('.'), 'text/html')
                return self.send(file.read_bytes(), content_type=kind + '; charset=utf-8', csp=policy)
            if path == "/api/sources":
                return self.send({"items": self.app.store.sources(query)})
            if path == "/api/runs":
                return self.send({"items": self.app.store.runs()})
            if path == "/api/review/schema":
                return self.send(self.app.store.review.schema())
            if path == "/api/publication/rules":
                return self.send(publication_rules())
            if path == "/api/publication":
                return self.send(self.app.publisher.status())
            if path.startswith("/api/runs/") and len(path.split("/")) == 4:
                return self.send(self.app.store.run(path.split("/")[-1]))
            if path.startswith("/api/runs/") and len(path.split("/")) == 5 and path.endswith("/context"):
                return self.send(self.app.store.trace.get(path.split("/")[-2]))
            if path.startswith("/api/runs/") and len(path.split("/")) == 5:
                run_id, artifact = path.split("/")[-2:]
                if artifact == "agents":
                    return self.send(self.app.store.agent_trace(run_id))
                if artifact == "review":
                    return self.send(self.app.store.review.get(run_id))
                if artifact == 'quality':
                    run = self.app.store.run(run_id)
                    data = self.app.reviewed_presentation(run) if run['output'] else None
                    return self.send(self.app.operations.quality(run, data, self.app.store.review.get(run_id)))
                if artifact in {"presentation", "card.svg", "card.png", "animation.gif", "animation.mp4", "post.txt", "report.txt", "brief.txt", "review.json"}:
                    data = self.app.presentation(run_id)
                    if artifact == "presentation":
                        return self.send(data)
                    if artifact == "card.svg":
                        return self.send(render_svg(data).encode("utf-8"), content_type="image/svg+xml; charset=utf-8", download="research-" + run_id + ".svg")
                    if artifact == 'animation.mp4':
                        body=render_mp4(data)
                        if body is None:
                            return self.send({'error':'MP4 недоступен; используйте PNG или GIF.'},503)
                        return self.send(body,content_type='video/mp4',download='research-'+run_id+'.mp4')
                    if artifact in {"card.png", "animation.gif"}:
                        body = (render_png if artifact == "card.png" else render_gif)(data)
                        if body is None:
                            return self.send({"error": "Растровый экспорт недоступен в этом Python. Используйте SVG."}, 503)
                        return self.send(body, content_type="image/png" if artifact == "card.png" else "image/gif", download="research-" + run_id + (".png" if artifact == "card.png" else ".gif"))
                    if artifact == "post.txt":
                        return self.send(data["post_text"].encode("utf-8"), content_type="text/plain; charset=utf-8", download="telegram-post-" + run_id + ".txt")
                    if artifact == "brief.txt":
                        return self.send(data["brief_text"].encode("utf-8"), content_type="text/plain; charset=utf-8", download="applied-brief-" + run_id + ".txt")
                    if artifact == "review.json":
                        return self.send(json.dumps(self.app.store.review.get(run_id), ensure_ascii=False, indent=2).encode("utf-8"), download="research-review-" + run_id + ".json")
                    from .presentation import strip_service_blocks
                    return self.send(strip_service_blocks(self.app.store.run(run_id)["output"]).encode("utf-8"), content_type="text/plain; charset=utf-8", download="research-" + run_id + ".txt")
            if path == "/api/lessons/schema":
                return self.send(self.app.store.lessons.schema())
            if path == "/api/lessons":
                return self.send({"items": self.app.store.lessons.list()})
            if path.startswith("/api/lessons/") and len(path.split("/")) == 4:
                return self.send(self.app.store.lessons.get(path.split("/")[-1]))
            if path == "/api/knowledge":
                return self.send({"items": self.app.store.knowledge(query)})
            if path == "/api/study/schema":
                return self.send(self.app.store.study.schema())
            if path == "/api/tasks":
                return self.send({"items": self.app.store.study.tasks()})
            if path.startswith("/api/tasks/") and len(path.split("/")) == 4:
                return self.send(self.app.store.study.task(path.split("/")[-1]))
            if path == "/api/memory":
                return self.send({"profile": self.app.store.memory.profile(), "corrections": self.app.store.memory.corrections()})
            if path == "/api/memory/reviews":
                return self.send({"items": self.app.store.memory.reviews()})
            if path.startswith("/api/memory/") and len(path.split("/")) == 4:
                return self.send(self.app.store.memory.history(path.split("/")[-1]))
            if path == "/api/export":
                exported = json.dumps(self.app.store.export(), ensure_ascii=False).encode("utf-8")
                if len(exported) > MAX_BACKUP_FILE:
                    raise LabError("Копия больше 100 МБ. Остановите приложение и скопируйте папку .lab-data целиком для локального резервирования.")
                return self.send(exported, download="ai-laboratory-backup.json")
            static = {"/assets/research.js": ("research.js", "text/javascript; charset=utf-8"),
                      "/assets/reactor.js": ("reactor.js", "text/javascript; charset=utf-8"),
                      "/assets/reactor.css": ("reactor.css", "text/css; charset=utf-8"),
                      "/assets/observatory.js": ("observatory.js", "text/javascript; charset=utf-8"),
                      "/assets/observatory.css": ("observatory.css", "text/css; charset=utf-8"),
                      "/assets/frontier-live.js": ("frontier-live.js", "text/javascript; charset=utf-8"),
                      "/assets/frontier-shell.css": ("frontier-shell.css", "text/css; charset=utf-8"),
                      "/assets/operations.css": ("operations.css", "text/css; charset=utf-8"),
                      "/assets/research.css": ("research.css", "text/css; charset=utf-8"),
                      "/": ("index.html", "text/html; charset=utf-8"),
                      "/classic": ("index.html", "text/html; charset=utf-8"),
                      "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                      "/style.css": ("style.css", "text/css; charset=utf-8"),
                      "/assets/app.js": ("app.js", "text/javascript; charset=utf-8"),
                      "/assets/style.css": ("style.css", "text/css; charset=utf-8")}
            if path in static:
                name, mime = static[path]
                return self.send((WEB / name).read_bytes(), content_type=mime)
            self.send({"error": "Страница не найдена."}, 404)
        except (LabError, ValueError) as exc:
            self.send({"error": str(exc)}, 400)
        except Exception:
            self.send({"error": "Не удалось прочитать данные. Проверьте локальную базу и повторите действие."}, 500)

    def do_POST(self):
        try:
            self.check_host()
            port = self.server.server_port
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}:
                return self.reject_post({"error": "Запрос с другого сайта отклонён."})
            if not secrets.compare_digest(self.headers.get("X-Lab-Token", ""), self.app.csrf):
                return self.reject_post({"error": "Обновите страницу лаборатории и повторите действие."})
            length = int(self.headers.get("Content-Length", "0"))
            path = urlsplit(self.path).path
            limit = MAX_RESTORE_REQUEST if path == "/api/restore" else MAX_REQUEST
            if not 0 < length <= limit:
                return self.send({"error": "Максимальный размер запроса — 128 МБ для резервной копии и 25 МБ для остальных действий."}, 413)
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise LabError("Нужен JSON-объект.")
            if path == "/api/sources":
                source, created = self.app.store.add_source(body.get("text"), body.get("title", ""), body.get("url", ""), tags=body.get("tags") or [])
                return self.send({**source, "created": created})
            if path == "/api/import/telegram":
                return self.send(import_telegram(body.get("export"), self.app.store))
            if path == "/api/plans":
                return self.send(self.app.store.create_plan(body))
            if path == "/api/tasks":
                return self.send(self.app.store.study.save(body))
            if path == "/api/lessons":
                return self.send(self.app.store.lessons.save(body))
            if path == "/api/memory/profile":
                return self.send(self.app.store.memory.save_profile(body))
            if path == "/api/memory/corrections":
                return self.send(self.app.store.memory.save_correction(body))
            if path == "/api/memory/preview":
                study = self.app.store.study.snapshot(body)
                return self.send(self.app.store.memory.candidates({**body,
                    "study_query": self.app.store.study.query_text(study),
                    "study_context": study}))
            from .research_api import handle_post
            if handle_post(self, path, body):
                return
            if path == '/api/operations/backup':
                if body:
                    raise LabError('Резервная копия не требует дополнительных параметров.')
                return self.send(self.app.operations.create_backup())
            if path == '/api/operations/drill':
                if set(body) != {'backup_id'} or not isinstance(body['backup_id'], str):
                    raise LabError('Укажите существующий backup_id.')
                return self.send(self.app.operations.drill(body['backup_id']))
            if path == "/api/settings":
                return self.send(self.app.store.update_settings(body))
            if path == "/api/publication/settings":
                return self.send(self.app.publisher.configure(body))
            if path == "/api/publication/channel":
                if set(body) != {"channel"}:
                    raise LabError("Укажите только поле channel: @username либо отрицательный числовой ID канала.")
                return self.send(self.app.publisher.connect_channel(body["channel"]))
            if path.startswith("/api/publication/") and path.endswith("/cancel"):
                publication_parts = path.strip("/").split("/")
                if len(publication_parts) == 4:
                    return self.send(self.app.publisher.cancel(publication_parts[2]))
            if path == "/api/telegram/config":
                return self.send(self.app.telegram.configure(body.get("token", "")))
            if path == "/api/telegram/disconnect":
                return self.send(self.app.telegram.disconnect())
            if path == "/api/telegram/plans":
                if not hasattr(self.app.telegram, "present_plan"):
                    raise LabError("Telegram не подключён.")
                return self.send(self.app.telegram.present_plan(body.get("run_id", "")))
            if path == "/api/telegram/results":
                if not hasattr(self.app.telegram, "send_result"):
                    raise LabError("Telegram не подключён.")
                return self.send(self.app.telegram.send_result(body.get("run_id", "")))
            if path == "/api/shutdown":
                from .operations import mark_intentional_stop
                mark_intentional_stop(self.app.store.data_dir)
                self.send({"stopping": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if path == "/api/restore":
                if body.get("confirm") is not True:
                    raise LabError("Подтвердите восстановление в пустую базу.")
                with self.app.lock:
                    if self.app.jobs:
                        raise LabError("Сначала дождитесь завершения исследований.")
                    return self.send(self.app.store.restore(body.get("backup")))
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[:2] == ["api", "plans"] and parts[3] == "memory":
                return self.send(self.app.store.replan_memory(parts[2], body))
            if len(parts) == 4 and parts[:2] == ["api", "plans"] and parts[3] == "context":
                return self.send(self.app.store.replan_context(parts[2], body))
            if len(parts) == 5 and parts[:3] == ["api", "memory", "reviews"] and parts[4] == "resolve":
                return self.send(self.app.store.memory.resolve_review(parts[3], body))
            if len(parts) == 4 and parts[:2] == ["api", "memory"]:
                if parts[3] == "revise":
                    return self.send(self.app.store.memory.revise(parts[2], body))
                if parts[3] == "refresh-plan":
                    return self.send(self.app.store.refresh_memory_plan(parts[2]))
            if len(parts) == 4 and parts[:2] == ["api", "runs"]:
                run_id, action = parts[2:]
                if action == 'continue':
                    return self.send(self.app.store.create_continuation(run_id))
                if action == "start":
                    return self.send(self.app.start_run(run_id, body))
                if action == "cancel":
                    return self.send(self.app.cancel(run_id))
                if action == "save":
                    return self.send(self.app.store.save_finding(run_id, body))
                if action == "review":
                    return self.send(self.app.store.review.save(run_id, body))
            self.send({"error": "Действие не найдено."}, 404)
        except (LabError, ValueError, TypeError, KeyError) as exc:
            memory_path = urlsplit(self.path).path.startswith(("/api/memory", "/api/plans", "/api/tasks", "/api/study", "/api/lessons", "/api/telegram", "/api/publication", "/api/research"))
            review_path = urlsplit(self.path).path.endswith(("/review", "/dossier"))
            message = str(exc) if isinstance(exc, (LabError, TelegramError)) or ((memory_path or review_path) and isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError)) else "Некорректные данные запроса. Проверьте файл или поля формы."
            self.send({"error": message}, 400)
        except Exception:
            self.send({"error": "Не удалось завершить действие. Обновите список материалов перед повторной попыткой."}, 500)


class InstanceLock:
    def __init__(self, data_dir):
        self.path = Path(data_dir) / ".instance.lock"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = None

    def __enter__(self):
        self.file = self.path.open("a+b")
        self.file.seek(0)
        self.file.write(b"0")
        self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            raise LabError("Эта база уже открыта другим процессом лаборатории.") from exc
        return self

    def __exit__(self, *args):
        self.file.close()


def main():
    parser = argparse.ArgumentParser(description="AI Research Laboratory, local single-owner source-analysis increment")
    parser.add_argument("--port", type=int, default=8795)
    parser.add_argument("--data-dir", type=Path, default=ROOT / ".lab-data")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument('--supervised', action='store_true', help='Launch with local crash recovery')
    parser.add_argument("--stop", action="store_true", help="Stop this project's existing local application")
    args = parser.parse_args()
    from .operations import mark_intentional_stop, stop_file
    if args.stop:
        mark_intentional_stop(args.data_dir)
    elif not os.environ.get('LAB_OPERATIONS_STOP_FILE'):
        stop_file(args.data_dir).unlink(missing_ok=True)
    elif stop_file(args.data_dir).exists():
        return
    origin = f"http://127.0.0.1:{args.port}"
    if args.supervised and not args.stop:
        from .operations import start_supervisor
        start_supervisor(ROOT, args.data_dir, args.port)
        if not args.no_browser:
            timer = threading.Timer(2, webbrowser.open, args=(origin,))
            timer.start()
            timer.join()
        print('Supervised laboratory: ' + origin)
        return
    try:
        with urlopen(origin + "/api/health", timeout=0.5) as response:
            health = json.load(response)
        if health.get("root") == str(ROOT) and health.get("data_dir") == str(args.data_dir.resolve()):
            if args.stop:
                with urlopen(origin + "/api/bootstrap", timeout=3) as response:
                    token = json.load(response)["csrf"]
                request = Request(origin + "/api/shutdown", data=b"{}", headers={"X-Lab-Token": token, "Content-Type": "application/json"}, method="POST")
                with urlopen(request, timeout=3) as response:
                    response.read()
                print("Laboratory is stopping.")
                return
            print("Laboratory is already running: " + origin)
            if not args.no_browser:
                webbrowser.open(origin)
            return
    except Exception:
        pass
    if args.stop:
        print("This project's laboratory is not running on that port.")
        return
    server = LocalServer(("127.0.0.1", args.port), Handler)
    with InstanceLock(args.data_dir):
        app = Laboratory(args.data_dir.resolve())
        server.app = app
        app.operations.port = args.port
        app.telegram.start()
        app.operations.start()
        print(f"AI Research Laboratory {__version__}: {origin}")
        print("Data: " + str(app.store.data_dir))
        print("Keep this window open. Ctrl+C stops the application.")
        if not args.no_browser:
            timer = threading.Timer(0.7, webbrowser.open, args=(origin,))
            timer.daemon = True
            timer.start()
        try:
            server.serve_forever(poll_interval=0.3)
        except KeyboardInterrupt:
            print("\nStopping laboratory...")
        finally:
            app.close()
            server.server_close()


if __name__ == "__main__":
    main()
