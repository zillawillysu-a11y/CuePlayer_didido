"""Qt bridge: HTTP worker thread → MainWindow UI thread."""

from __future__ import annotations

import queue
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from cueplayer.web_remote.prefs import WebRemotePrefs
from cueplayer.web_remote.server import WebRemoteServer
from cueplayer.web_remote.state import build_state


class WebRemoteBridge(QObject):
    """Owns the HTTP server and marshals commands onto the UI thread."""

    status_changed = Signal(str)
    started = Signal()
    stopped = Signal()

    def __init__(self, host_window: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._host = host_window
        self._server: WebRemoteServer | None = None
        self._prefs = WebRemotePrefs()
        self._cmd_queue: queue.Queue[tuple[dict[str, Any], queue.Queue[dict[str, Any]]]] = (
            queue.Queue()
        )
        self._pump = QTimer(self)
        self._pump.setInterval(16)
        self._pump.timeout.connect(self._drain_commands)

    @property
    def prefs(self) -> WebRemotePrefs:
        return self._prefs

    @property
    def running(self) -> bool:
        return self._server is not None and self._server.running

    @property
    def listen_url(self) -> str:
        if self._server is None:
            return ""
        return self._server.base_url

    def apply_prefs(self, prefs: WebRemotePrefs, *, restart: bool = True) -> str | None:
        """Apply prefs; start/stop/restart server. Returns error message or None."""
        self._prefs = WebRemotePrefs(
            enabled=bool(prefs.enabled),
            port=prefs.normalized_port(),
            password=str(prefs.password or ""),
            bind_lan=bool(prefs.bind_lan),
        )
        if not self._prefs.enabled:
            self.stop()
            self.status_changed.emit("Web Remote off")
            return None
        if restart or not self.running:
            return self.start()
        return None

    def start(self) -> str | None:
        self.stop()
        host = "0.0.0.0" if self._prefs.bind_lan else "127.0.0.1"
        port = self._prefs.normalized_port()
        server = WebRemoteServer(
            host=host,
            port=port,
            password=self._prefs.password,
            get_state=self._safe_state,
            run_command=self._enqueue_command,
        )
        try:
            server.start()
        except OSError as exc:
            self.status_changed.emit(f"Web Remote failed: {exc}")
            return str(exc)
        self._server = server
        if not self._pump.isActive():
            self._pump.start()
        msg = f"Web Remote on :{port}"
        self.status_changed.emit(msg)
        self.started.emit()
        return None

    def stop(self) -> None:
        server = self._server
        self._server = None
        if server is not None:
            server.stop()
        # Drain pending command waiters so HTTP threads do not hang.
        while True:
            try:
                _cmd, reply_q = self._cmd_queue.get_nowait()
            except queue.Empty:
                break
            try:
                reply_q.put({"ok": False, "error": "server_stopped"})
            except Exception:  # noqa: BLE001
                pass
        self.stopped.emit()

    def _safe_state(self) -> dict[str, Any]:
        # Domain reads are generally safe on the HTTP thread for MVP.
        # Engine position can race slightly — acceptable for 5–10 Hz poll UI.
        host = self._host
        project = host.project
        song = host.current_song
        engine = host.engine
        return build_state(project=project, song=song, engine=engine)

    def _enqueue_command(self, command: dict[str, Any]) -> dict[str, Any]:
        reply: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        self._cmd_queue.put((command, reply))
        try:
            return reply.get(timeout=5.0)
        except queue.Empty:
            return {"ok": False, "error": "timeout"}

    def _drain_commands(self) -> None:
        handled = 0
        while handled < 32:
            try:
                command, reply_q = self._cmd_queue.get_nowait()
            except queue.Empty:
                break
            handled += 1
            try:
                result = self._dispatch(command)
            except Exception as exc:  # noqa: BLE001
                result = {"ok": False, "error": str(exc)}
            try:
                reply_q.put(result)
            except Exception:  # noqa: BLE001
                pass

    def _dispatch(self, command: dict[str, Any]) -> dict[str, Any]:
        op = str(command.get("op") or "").strip().lower()
        host = self._host
        if op in ("play",):
            host.engine.play()
            return {"ok": True, "op": op}
        if op in ("pause",):
            host.engine.pause()
            return {"ok": True, "op": op}
        if op in ("toggle", "play_pause"):
            if host.engine.playing:
                host.engine.pause()
            else:
                host.engine.play()
            return {"ok": True, "op": op, "playing": bool(host.engine.playing)}
        if op in ("stop",):
            host.engine.pause()
            host.engine.seek(0.0)
            return {"ok": True, "op": op}
        if op == "seek":
            seconds = float(command.get("seconds", 0.0))
            host.engine.seek(max(0.0, seconds))
            return {"ok": True, "op": op, "seconds": seconds}
        if op == "seek_mark":
            mark_id = str(command.get("mark_id") or "")
            mark = host.current_song.mark_by_id(mark_id)
            if mark is None:
                return {"ok": False, "error": "mark_not_found"}
            host.engine.seek(float(mark.time_seconds))
            return {"ok": True, "op": op, "mark_id": mark_id}
        if op == "select_song":
            return self._select_song(command)
        if op == "next_song":
            return self._step_song(+1)
        if op == "prev_song":
            return self._step_song(-1)
        if op == "add_mark":
            return self._add_mark(command)
        return {"ok": False, "error": f"unknown_op:{op}"}

    def _select_song(self, command: dict[str, Any]) -> dict[str, Any]:
        host = self._host
        songs = host.project.songs
        if not songs:
            return {"ok": False, "error": "empty_setlist"}
        index: int | None = None
        if "index" in command and command["index"] is not None:
            try:
                index = int(command["index"])
            except (TypeError, ValueError):
                return {"ok": False, "error": "bad_index"}
        song_id = command.get("id")
        if index is None and song_id:
            for i, song in enumerate(songs):
                if song.id == song_id:
                    index = i
                    break
        if index is None or index < 0 or index >= len(songs):
            return {"ok": False, "error": "song_not_found"}
        host._activate_song(index, stop_playback=False)
        host._rebuild_song_list(select_indexes=[index])
        return {"ok": True, "op": "select_song", "index": index}

    def _step_song(self, delta: int) -> dict[str, Any]:
        host = self._host
        songs = host.project.songs
        if not songs:
            return {"ok": False, "error": "empty_setlist"}
        try:
            cur = songs.index(host.current_song)
        except ValueError:
            cur = 0
        nxt = max(0, min(len(songs) - 1, cur + int(delta)))
        if nxt == cur:
            return {"ok": True, "op": "step_song", "index": cur, "unchanged": True}
        host._activate_song(nxt, stop_playback=False)
        host._rebuild_song_list(select_indexes=[nxt])
        return {"ok": True, "op": "step_song", "index": nxt}

    def _add_mark(self, command: dict[str, Any]) -> dict[str, Any]:
        host = self._host
        shortcut = str(command.get("shortcut") or "").strip()
        lane_index = command.get("lane_index")
        song = host.current_song
        if song not in host.project.songs and not host.project.songs:
            return {"ok": False, "error": "no_song"}
        lane = None
        if shortcut:
            lane = song.lane_by_shortcut(shortcut)
        elif lane_index is not None:
            try:
                lane = song.lane_by_index(int(lane_index))
            except (TypeError, ValueError):
                lane = None
        if lane is None:
            return {"ok": False, "error": "lane_not_found"}
        if lane.locked or not lane.visible:
            return {"ok": False, "error": "lane_unavailable"}
        if not getattr(song, "show_mark_tracks", True):
            return {"ok": False, "error": "mark_tracks_hidden"}
        # Remote must never open a blocking Note dialog on the PC.
        saved_prompt = bool(getattr(lane, "prompt_note_on_mark", False))
        try:
            lane.prompt_note_on_mark = False
            host._add_mark(lane.index)
        finally:
            lane.prompt_note_on_mark = saved_prompt
        return {
            "ok": True,
            "op": "add_mark",
            "lane_index": lane.index,
            "shortcut": lane.shortcut or shortcut,
        }


def lan_urls(port: int) -> list[str]:
    """Best-effort LAN URLs for the settings dialog."""
    urls: list[str] = [f"http://127.0.0.1:{port}/"]
    try:
        import socket

        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip.startswith("127."):
                continue
            urls.append(f"http://{ip}:{port}/")
    except Exception:  # noqa: BLE001
        pass
    # Dedupe preserve order.
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out
