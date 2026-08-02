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
WaveformFn = Callable[..., dict[str, Any]]
ClockFn = Callable[[], dict[str, Any]]
MonitorFn = Callable[..., tuple[dict[str, Any], bytes]]
WebRtcFn = Callable[[dict[str, Any]], dict[str, Any]]


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
        get_monitor: MonitorFn | None = None,
        run_webrtc: WebRtcFn | None = None,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.password = str(password or "")
        self.get_state = get_state
        self.run_command = run_command
        self.get_waveform = get_waveform
        self.get_clock = get_clock
        self.get_monitor = get_monitor
        self.run_webrtc = run_webrtc
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
                payload: dict[str, Any] = {
                    "ok": True,
                    "service": "cueplayer-web-remote",
                }
                if server.run_webrtc is not None:
                    try:
                        caps = server.run_webrtc({"op": "capabilities"})
                        payload["webrtc"] = bool(caps.get("webrtc") or caps.get("ok"))
                    except Exception:  # noqa: BLE001
                        payload["webrtc"] = False
                else:
                    payload["webrtc"] = False
                self._json(HTTPStatus.OK, payload)
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
                qs = parse_qs(parsed.query)
                def _qfloat(name: str) -> float | None:
                    raw = (qs.get(name) or [None])[0]
                    if raw is None or raw == "":
                        return None
                    try:
                        return float(raw)
                    except ValueError:
                        return None

                def _qint(name: str) -> int | None:
                    raw = (qs.get(name) or [None])[0]
                    if raw is None or raw == "":
                        return None
                    try:
                        return int(float(raw))
                    except ValueError:
                        return None

                try:
                    wave = server.get_waveform(
                        start=_qfloat("start"),
                        end=_qfloat("end"),
                        buckets=_qint("buckets"),
                    )
                except TypeError:
                    # Older callback signature without kwargs.
                    try:
                        wave = server.get_waveform()
                    except Exception as exc:  # noqa: BLE001
                        self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
                        return
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
            if path == "/api/monitor":
                if not self._authorized(parsed.query):
                    self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                    return
                if server.get_monitor is None:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                    return
                qs = parse_qs(parsed.query)

                def _qfloat(name: str) -> float | None:
                    raw = (qs.get(name) or [None])[0]
                    if raw is None or raw == "":
                        return None
                    try:
                        return float(raw)
                    except ValueError:
                        return None

                def _qint(name: str) -> int | None:
                    raw = (qs.get(name) or [None])[0]
                    if raw is None or raw == "":
                        return None
                    try:
                        return int(float(raw))
                    except ValueError:
                        return None

                try:
                    fmt = str((qs.get("format") or ["s16le"])[0] or "s16le").lower()
                    meta, pcm = server.get_monitor(
                        start=_qfloat("start"),
                        seconds=_qfloat("seconds"),
                        rate=_qint("rate"),
                        as_wav=fmt in ("wav", "wave", "audio/wav"),
                    )
                except TypeError:
                    try:
                        meta, pcm = server.get_monitor()
                    except Exception as exc:  # noqa: BLE001
                        self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
                        return
                except Exception as exc:  # noqa: BLE001
                    self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
                    return
                if not isinstance(meta, dict):
                    self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "bad_monitor"})
                    return
                body = pcm if isinstance(pcm, (bytes, bytearray)) else b""
                self._pcm(HTTPStatus.OK, meta, bytes(body))
                return
            self._serve_static(path)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path or "/"
            if path == "/api/webrtc":
                if not self._authorized(parsed.query):
                    self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                    return
                if server.run_webrtc is None:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "webrtc_unavailable"})
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
                try:
                    result = server.run_webrtc(payload)
                except Exception as exc:  # noqa: BLE001
                    self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
                    return
                status = HTTPStatus.OK if result.get("ok", True) else HTTPStatus.BAD_REQUEST
                self._json(status, result)
                return
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
            self.send_header(
                "Access-Control-Expose-Headers",
                "X-CuePlayer-Sample-Rate, X-CuePlayer-Channels, X-CuePlayer-Start, "
                "X-CuePlayer-Seconds, X-CuePlayer-Song-Id, X-CuePlayer-Playing, "
                "X-CuePlayer-Position, X-CuePlayer-Duration, X-CuePlayer-Ready, "
                "X-CuePlayer-Frames, X-CuePlayer-Format",
            )

        def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self._cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _pcm(self, status: HTTPStatus, meta: dict[str, Any], pcm: bytes) -> None:
            fmt = str(meta.get("format") or "s16le").lower()
            is_wav = fmt in ("wav", "wave", "audio/wav")
            self.send_response(status)
            self._cors_headers()
            self.send_header(
                "Content-Type",
                "audio/wav" if is_wav else "application/octet-stream",
            )
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(pcm)))
            self.send_header(
                "X-CuePlayer-Sample-Rate",
                str(int(meta.get("sample_rate") or 24000)),
            )
            self.send_header("X-CuePlayer-Channels", str(int(meta.get("channels") or 1)))
            self.send_header("X-CuePlayer-Start", f"{float(meta.get('start') or 0.0):.6f}")
            self.send_header("X-CuePlayer-Seconds", f"{float(meta.get('seconds') or 0.0):.6f}")
            self.send_header("X-CuePlayer-Song-Id", str(meta.get("song_id") or ""))
            self.send_header(
                "X-CuePlayer-Playing",
                "1" if meta.get("playing") else "0",
            )
            self.send_header(
                "X-CuePlayer-Position",
                f"{float(meta.get('position') or 0.0):.6f}",
            )
            self.send_header(
                "X-CuePlayer-Duration",
                f"{float(meta.get('duration') or 0.0):.6f}",
            )
            self.send_header("X-CuePlayer-Ready", "1" if meta.get("ready") else "0")
            self.send_header("X-CuePlayer-Frames", str(int(meta.get("frames") or 0)))
            self.send_header("X-CuePlayer-Format", "wav" if is_wav else "s16le")
            reason = str(meta.get("reason") or "").strip()
            if reason:
                self.send_header("X-CuePlayer-Reason", reason)
            self.end_headers()
            if pcm:
                self.wfile.write(pcm)

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
