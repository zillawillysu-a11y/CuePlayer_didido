"""Web Remote HTTP API + state snapshot tests."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

import pytest

from cueplayer.domain.models import Project, SetlistCategory, Song
from cueplayer.web_remote.prefs import WebRemotePrefs
from cueplayer.web_remote.server import WebRemoteServer, static_dir
from cueplayer.web_remote.state import (
    build_state,
    build_waveform_overview,
    build_waveform_window,
    format_clock,
)
from cueplayer.media.audio_loader import AudioBuffer, PeakLevel
import numpy as np


@dataclass
class _FakeEngine:
    playing: bool = False
    position: float = 1.5
    duration: float = 60.0


def test_static_dir_has_index() -> None:
    root = static_dir()
    assert (root / "index.html").is_file()
    html = (root / "index.html").read_text(encoding="utf-8")
    assert 'id="waveCanvas"' in html
    assert 'id="pauseBtn"' in html
    assert 'id="toggles"' in html
    assert 'id="markMgrBtn"' in html
    assert 'id="dispBtn"' in html
    assert 'id="dispDialog"' in html
    assert 'id="renumberCueBtn"' in html
    assert 'id="waveFollowBtn"' in html
    assert 'id="splitSetlist"' in html
    assert 'id="confirmDialog"' in html
    js = (root / "app.js").read_text(encoding="utf-8")
    assert "ignoreCueScroll" in js
    assert "set_display" in js
    assert "scrollCueListTo" in js
    assert "followWavePlayhead" in js
    assert "ensureWaveDetail" in js
    assert "build_waveform_window" not in js  # server-side only
    assert "scheduleWaveDetail" in js
    assert "renumber_cue_ids" in js
    assert "set_mark_cue_id" in js
    assert "bindSplitter" in js
    assert "pause_on_mark" in js
    assert "prompt_note_on_mark" in js
    assert "show_note_on_wave" in js
    assert "show_cue_id_on_wave" in js
    assert "set_mark_note" in js
    assert "liveTimecode" in js
    assert "scrollCueListTo" in js
    assert ("Cue ID" in js) or ("mgr-cueid" in js)
    assert (root / "app.js").is_file()
    assert (root / "app.css").is_file()
    css = (root / "app.css").read_text(encoding="utf-8")
    assert ".now-card.primary .now-body" in css
    assert "position: relative" in css
    assert ".splitter" in css


def test_format_clock() -> None:
    assert format_clock(0) == "00:00.000"
    assert format_clock(65.25) == "01:05.250"
    assert format_clock(1.89) == "00:01.890"


def test_build_waveform_overview_from_peaks() -> None:
    mins = np.linspace(-0.5, -0.1, 200, dtype=np.float32)
    maxs = np.linspace(0.1, 0.8, 200, dtype=np.float32)
    buf = AudioBuffer(
        path=__import__("pathlib").Path("x.wav"),
        sample_rate=48000,
        samples=np.zeros((48000, 2), dtype=np.float32),
        mono=np.zeros(48000, dtype=np.float32),
        peak_levels=[PeakLevel(samples_per_bucket=240, mins=mins, maxs=maxs)],
    )
    wave = build_waveform_overview(buf, song_id="s1", duration=1.0, buckets=100)
    assert wave["ready"] is True
    assert wave["buckets"] == 100
    assert len(wave["mins"]) == 100
    assert len(wave["maxs"]) == 100
    assert max(abs(v) for v in wave["maxs"]) <= 1.0001
    assert wave["start"] == 0.0
    assert wave["detail"] is False


def test_build_waveform_window_zoomed() -> None:
    # Fine pyramid + mono for raw path.
    n = 4800
    mins = np.linspace(-0.8, -0.1, n, dtype=np.float32)
    maxs = np.linspace(0.1, 0.9, n, dtype=np.float32)
    mono = np.sin(np.linspace(0, 40 * np.pi, 48000)).astype(np.float32) * 0.5
    buf = AudioBuffer(
        path=__import__("pathlib").Path("x.wav"),
        sample_rate=48000,
        samples=mono.reshape(-1, 1),
        mono=mono,
        peak_levels=[
            PeakLevel(samples_per_bucket=10, mins=mins, maxs=maxs),
            PeakLevel(samples_per_bucket=100, mins=mins[::10], maxs=maxs[::10]),
        ],
    )
    window = build_waveform_window(
        buf,
        song_id="s1",
        duration=1.0,
        start=0.2,
        end=0.4,
        buckets=2000,
    )
    assert window["ready"] is True
    assert window["detail"] is True
    assert window["buckets"] == 2000
    assert abs(window["start"] - 0.2) < 1e-6
    assert abs(window["end"] - 0.4) < 1e-6
    assert len(window["mins"]) == 2000
    assert max(abs(v) for v in window["maxs"]) > 0.05
    # Tight zoom should prefer mono when samples/pixel is low enough.
    tight = build_waveform_window(
        buf,
        song_id="s1",
        duration=1.0,
        start=0.25,
        end=0.28,
        buckets=3000,
    )
    assert tight["ready"] is True
    assert tight["source"] == "mono"
    assert max(abs(v) for v in tight["maxs"]) > 0.05


def test_waveform_strips_ltc_channel_energy() -> None:
    """Remote music wave must not be dominated by a striped LTC channel."""
    from cueplayer.media.audio_loader import build_peak_pyramid, waveform_display_buffer

    sr = 48000
    t = np.linspace(0, 1.0, sr, endpoint=False, dtype=np.float32)
    music = (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    # Loud square-ish LTC stand-in on Right.
    ltc = np.where((np.arange(sr) % 48) < 24, 0.95, -0.95).astype(np.float32)
    stereo = np.column_stack([music, ltc])
    mono, levels = build_peak_pyramid(stereo, sr)
    mixed = AudioBuffer(
        path=__import__("pathlib").Path("mix.wav"),
        sample_rate=sr,
        samples=stereo,
        mono=mono,
        peak_levels=levels,
    )
    stripped = waveform_display_buffer(mixed, exclude_channel=1)
    assert stripped is not mixed
    assert not np.allclose(stripped.mono, mixed.mono)
    music_norm = music / float(np.max(np.abs(music)))
    corr_clean = float(np.corrcoef(stripped.mono, music_norm)[0, 1])
    corr_mixed = float(np.corrcoef(mixed.mono, music_norm)[0, 1])
    assert corr_clean > corr_mixed
    assert corr_clean > 0.95
    clean_wave = build_waveform_window(
        stripped, song_id="m", duration=1.0, start=0.1, end=0.3, buckets=800
    )
    assert clean_wave["ready"] is True
    assert max(abs(v) for v in clean_wave["maxs"]) > 0.05


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
    assert state["now"]["primary"][0]["time_display"] == "00:02.000"
    assert state["marks"][0]["time_display"].startswith("00:")
    assert len(state["cue_list"]) == 2
    # At 3.0s the latest cue-list mark is the Button at 3.5? No — 3.5 is after.
    # Primary mark at 2.0 is active; playhead cue is the last at-or-before 3.0.
    assert state["playhead_cue_id"] == song.marks[0].id  # 主歌 @ 2.0
    later = build_state(project=project, song=song, engine=_FakeEngine(position=4.0))
    assert later["playhead_cue_id"] == song.marks[1].id  # Button @ 3.5
    assert "output_toggles" in state
    assert "translate" in state["output_toggles"]
    assert "setlist" in state
    assert state["display"]["primary"] is True
    assert state["display"]["secondary"] is True
    assert state["display"]["timecode"] is True
    assert state["display"]["toggles"] is True
    song.now_primary_visible = False
    project.show_output_timecode_clock = False
    project.show_output_quick_toggles = False
    hidden = build_state(project=project, song=song, engine=_FakeEngine(position=3.0))
    assert hidden["display"]["primary"] is False
    assert hidden["display"]["timecode"] is False
    assert hidden["display"]["toggles"] is False
    lane = song.mark_lanes[0]
    lane.pause_on_mark = True
    lane.prompt_note_on_mark = True
    lane.show_note_on_wave = True
    lane.show_cue_id_on_wave = True
    flagged = build_state(project=project, song=song, engine=_FakeEngine(position=3.0))
    row = next(r for r in flagged["lanes"] if r["index"] == lane.index)
    assert row["pause_on_mark"] is True
    assert row["prompt_note_on_mark"] is True
    assert row["show_note_on_wave"] is True
    assert row["show_cue_id_on_wave"] is True
    mark_row = flagged["marks"][0]
    assert "show_note_on_wave" in mark_row
    assert "show_cue_id_on_wave" in mark_row
    assert "cue_id_enabled" in mark_row


def test_setlist_includes_collapsible_folders() -> None:
    project = Project.create("Folders", with_song=False)
    folder = SetlistCategory.create("Act 1")
    project.setlist_categories.append(folder)
    a = Song.create("Open")
    b = Song.create("Inside")
    b.category_id = folder.id
    project.songs.extend([a, b])
    state = build_state(project=project, song=a, engine=_FakeEngine())
    kinds = [row["kind"] for row in state["setlist"]]
    assert kinds == ["song", "folder", "song"]
    folder.collapsed = True
    state2 = build_state(project=project, song=a, engine=_FakeEngine())
    kinds2 = [row["kind"] for row in state2["setlist"]]
    assert kinds2 == ["song", "folder"]
    assert state2["setlist"][1]["collapsed"] is True


def test_now_secondary_is_single_active_mark() -> None:
    project = Project.create("Now", with_song=True)
    song = project.songs[0]
    song.now_primary_lanes = [1]
    song.now_secondary_lanes = [2, 3]
    song.now_secondary_enabled = True
    song.now_secondary_clear_seconds = 0.5
    song.add_mark(2, 1.0, "A")
    song.add_mark(3, 2.0, "B")
    song.add_mark(2, 3.0, "C")
    state = build_state(project=project, song=song, engine=_FakeEngine(position=2.5))
    assert len(state["now"]["secondary"]) == 1
    assert state["now"]["secondary"][0]["display_name"] == "B"
    assert state["now"]["secondary_clear_seconds"] == 0.5
    later = build_state(project=project, song=song, engine=_FakeEngine(position=3.5))
    assert later["now"]["secondary"][0]["display_name"] == "C"


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
        get_waveform=lambda: {
            "ok": True,
            "song_id": song.id,
            "ready": False,
            "buckets": 0,
            "mins": [],
            "maxs": [],
            "duration": 1.0,
        },
        get_clock=lambda: {
            "ok": True,
            "song_id": song.id,
            "playing": engine.playing,
            "position": engine.position,
            "duration": engine.duration,
            "server_ms": 1,
        },
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

        code, wave = _http_json(
            "http://127.0.0.1:18765/api/waveform",
            headers={"Authorization": "Bearer secret"},
        )
        assert code == 200
        assert wave["ok"] is True

        code, clock = _http_json(
            "http://127.0.0.1:18765/api/clock",
            headers={"Authorization": "Bearer secret"},
        )
        assert code == 200
        assert clock["playing"] is True
        assert "position" in clock

        req = urllib.request.Request("http://127.0.0.1:18765/")
        with urllib.request.urlopen(req, timeout=3) as resp:
            html = resp.read().decode("utf-8")
            assert "CuePlayer" in html
            assert 'id="waveCanvas"' in html
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
