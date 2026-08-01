"""Web Remote HTTP API + state snapshot tests."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

import pytest

from cueplayer.domain.models import Project, Song
from cueplayer.web_remote.prefs import WebRemotePrefs
from cueplayer.web_remote.server import WebRemoteServer, static_dir
from cueplayer.web_remote.state import build_state, format_clock


@dataclass
class _FakeEngine:
    playing: bool = False
    position: float = 1.5
    duration: float = 60.0


def test_static_dir_has_index() -> None:
    root = static_dir()
    assert (root / "index.html").is_file()
    assert (root / "app.js").is_file()
    assert (root / "app.css").is_file()


def test_format_clock() -> None:
    assert format_clock(0).startswith("00:00")
    assert "01:05" in format_clock(65.25)


def test_build_state_includes_unicode_song_and_marks() -> None:
    project = Project.create("現場", with_song=False)
    song = Song.create("彼个字")
    project.songs.append(song)
    song.add_mark(1, 2.0, "主歌")
    song.add_mark(2, 3.5, "Button")
    state = build_state(project=project, song=song, engine=_FakeEngine(position=3.0))
    assert state["project_name"] == "現場"
    assert state["song"]["name"] == "彼个字"
    assert state["playing"] is False
    assert abs(state["position"] - 3.0) < 1e-6
    assert len(state["marks"]) == 2
    assert state["now"]["primary"]
    assert state["now"]["primary"][0]["display_name"] == "主歌"


def test_prefs_port_clamp() -> None:
    assert WebRemotePrefs(port=80).normalized_port() == 8765
    assert WebRemotePrefs(port=9000).normalized_port() == 9000


def _http_json(
    url: str,
    *,
    data: dict | None = None,
    headers: dict | None = None,
) -> tuple[int, dict]:
    body = None if data is None else json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="GET" if data is None else "POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"error": raw}
        return int(exc.code), payload


def test_web_remote_server_auth_and_command() -> None:
    project = Project.create("Show", with_song=False)
    song = Song.create("A")
    project.songs.append(song)
    engine = _FakeEngine()
    commands: list[dict] = []

    def get_state() -> dict:
        return build_state(project=project, song=song, engine=engine)

    def run_command(cmd: dict) -> dict:
        commands.append(cmd)
        if cmd.get("op") == "play":
            engine.playing = True
        return {"ok": True, "op": cmd.get("op")}

    server = WebRemoteServer(
        host="127.0.0.1",
        port=18765,
        password="secret",
        get_state=get_state,
        run_command=run_command,
    )
    try:
        server.start()
        deadline = time.time() + 2.0
        while time.time() < deadline:
            try:
                code, health = _http_json("http://127.0.0.1:18765/api/health")
                if code == 200 and health.get("ok"):
                    break
            except Exception:  # noqa: BLE001
                time.sleep(0.05)
        else:
            pytest.fail("server did not start")

        code, _ = _http_json("http://127.0.0.1:18765/api/state")
        assert code == 401

        code, state = _http_json(
            "http://127.0.0.1:18765/api/state",
            headers={"Authorization": "Bearer secret"},
        )
        assert code == 200
        assert state["song"]["name"] == "A"

        code, result = _http_json(
            "http://127.0.0.1:18765/api/command",
            data={"op": "play"},
            headers={"X-CuePlayer-Token": "secret"},
        )
        assert code == 200
        assert result["ok"] is True
        assert commands and commands[0]["op"] == "play"

        req = urllib.request.Request("http://127.0.0.1:18765/")
        with urllib.request.urlopen(req, timeout=3) as resp:
            html = resp.read().decode("utf-8")
            assert "CuePlayer" in html
            assert resp.status == 200
    finally:
        server.stop()


def test_web_remote_bridge_dispatch_marks() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from cueplayer.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow(Project.create("Remote", with_song=True))
    app.processEvents()
    bridge = window._web_remote
    out = bridge._dispatch({"op": "add_mark", "shortcut": "1"})
    assert out["ok"] is True
    assert len(window.current_song.marks) == 1
    out = bridge._dispatch({"op": "seek", "seconds": 4.0})
    assert out["ok"] is True
    assert abs(window.engine.position - 4.0) < 0.05
    out = bridge._dispatch({"op": "stop"})
    assert out["ok"] is True
    window._web_remote.stop()
    # Do not call window.close() — closeEvent quits the QApplication.
