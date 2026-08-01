"""HTTP server for Web Remote (stdlib ThreadingHTTPServer)."""

from __future__ import annotations

import json
import mimetypes
import secrets
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from cueplayer.util.runtime import package_root

CommandFn = Callable[[dict[str, Any]], dict[str, Any]]
StateFn = Callable[[], dict[str, Any]]
WaveformFn = Callable[[], dict[str, Any]]
ClockFn = Callable[[], dict[str, Any]]


def static_dir() -> Path:
    return package_root() / "web_remote" / "static"


class WebRemoteServer:
    """Background HTTP server; command/state callbacks must be thread-safe."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        password: str,
        get_state: StateFn,
        run_command: CommandFn,
        get_waveform: WaveformFn | None = None,
        get_clock: ClockFn | None = None,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.password = str(password or "")
        self.get_state = get_state
        self.run_command = run_command
        self.get_waveform = get_waveform
        self.get_clock = get_clock
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._httpd is not None and self._thread is not None and self._thread.is_alive()

    @property
    def base_url(self) -> str:
        display_host = "127.0.0.1" if self.host in ("0.0.0.0", "::") else self.host
        return f"http://{display_host}:{self.port}/"

    def start(self) -> None:
        with self._lock:
            if self.running:
                return
            handler = _make_handler(self)
            httpd = ThreadingHTTPServer((self.host, self.port), handler)
            httpd.daemon_threads = True
            thread = threading.Thread(
                target=httpd.serve_forever,
                name="cueplayer-web-remote",
                daemon=True,
            )
            self._httpd = httpd
            self._thread = thread
            thread.start()

    def stop(self) -> None:
        with self._lock:
            httpd = self._httpd
            thread = self._thread
            self._httpd = None
            self._thread = None
        if httpd is not None:
            try:
                httpd.shutdown()
            except Exception:  # noqa: BLE001
                pass
            try:
                httpd.server_close()
            except Exception:  # noqa: BLE001
                pass
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)


def _make_handler(server: WebRemoteServer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            # Quiet by default — show-floor noise otherwise.
            return

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(HTTPStatus.NO_CONTENT)
            self._cors_headers()
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path or "/"
            if path == "/api/health":
                self._json(
                    HTTPStatus.OK,
                    {"ok": True, "service": "cueplayer-web-remote"},
                )
                return
            if path == "/api/state":
                if not self._authorized(parsed.query):
                    self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                    return
                try:
                    state = server.get_state()
                except Exception as exc:  # noqa: BLE001
                    self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
                    return
                self._json(HTTPStatus.OK, state)
                return
            if path == "/api/waveform":
                if not self._authorized(parsed.query):
                    self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                    return
                if server.get_waveform is None:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                    return
                try:
                    wave = server.get_waveform()
                except Exception as exc:  # noqa: BLE001
                    self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
                    return
                self._json(HTTPStatus.OK, wave)
                return
            if path == "/api/clock":
                if not self._authorized(parsed.query):
                    self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                    return
                getter = server.get_clock or (lambda: {})
                try:
                    clock = getter()
                except Exception as exc:  # noqa: BLE001
                    self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
                    return
                self._json(HTTPStatus.OK, clock)
                return
            self._serve_static(path)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path or "/"
            if path not in ("/api/command", "/api/transport", "/api/song", "/api/mark", "/api/seek"):
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            if not self._authorized(parsed.query):
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
                return
            if not isinstance(payload, dict):
                self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
                return
            command = dict(payload)
            if path == "/api/transport" and "op" not in command:
                action = str(command.get("action") or "toggle").strip().lower()
                command = {"op": action, **{k: v for k, v in command.items() if k != "action"}}
            elif path == "/api/song" and "op" not in command:
                command = {"op": "select_song", **command}
            elif path == "/api/mark" and "op" not in command:
                command = {"op": "add_mark", **command}
            elif path == "/api/seek" and "op" not in command:
                if "mark_id" in command:
                    command = {"op": "seek_mark", **command}
                else:
                    command = {"op": "seek", **command}
            try:
                result = server.run_command(command)
            except Exception as exc:  # noqa: BLE001
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
                return
            status = HTTPStatus.OK if result.get("ok", True) else HTTPStatus.BAD_REQUEST
            self._json(status, result)

        def _authorized(self, query: str) -> bool:
            expected = server.password
            if not expected:
                return True
            auth = self.headers.get("Authorization") or ""
            token = self.headers.get("X-CuePlayer-Token") or ""
            if auth.lower().startswith("bearer "):
                token = auth[7:].strip()
            if not token:
                qs = parse_qs(query)
                vals = qs.get("token") or qs.get("password") or []
                token = vals[0] if vals else ""
            return secrets.compare_digest(str(token), str(expected))

        def _cors_headers(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-CuePlayer-Token")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

        def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self._cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _serve_static(self, path: str) -> None:
            root = static_dir().resolve()
            if path in ("/", "/index.html"):
                rel = "index.html"
            else:
                rel = path.lstrip("/")
            target = (root / rel).resolve()
            try:
                target.relative_to(root)
            except ValueError:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            if not target.is_file():
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            data = target.read_bytes()
            ctype, _ = mimetypes.guess_type(str(target))
            if ctype is None:
                ctype = "application/octet-stream"
            if ctype.startswith("text/") or ctype in (
                "application/javascript",
                "application/json",
            ):
                ctype = f"{ctype}; charset=utf-8"
            self.send_response(HTTPStatus.OK)
            self._cors_headers()
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler
