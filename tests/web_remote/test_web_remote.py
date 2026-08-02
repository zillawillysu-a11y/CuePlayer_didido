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
    build_monitor_pcm,
    build_state,
    build_waveform_overview,
    build_waveform_window,
    format_clock,
    music_mono_samples,
    pcm16_le_to_wav,
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
    assert 'id="dispSetlist"' in html
    assert 'id="dispClock"' in html
    assert 'id="dispCueList"' in html
    assert 'id="cueListBlock"' in html
    assert 'id="renumberCueBtn"' in html
    assert 'id="waveFollowBtn"' in html
    assert 'id="waveSetupBtn"' in html
    assert 'id="listenBtn"' in html
    assert 'id="mutePcBtn"' in html
    assert 'id="previewBtn"' in html
    assert 'id="previewVideo"' in html
    assert 'id="deleteMarkBtn"' in html
    assert 'id="splitSetlist"' in html
    assert 'id="splitWavePreview"' in html
    assert 'id="stageMedia"' in html
    assert 'id="confirmDialog"' in html
    js = (root / "app.js").read_text(encoding="utf-8")
    assert "ignoreCueScroll" in js
    assert "set_display" in js
    assert "scrollCueListTo" in js
    assert "followWavePlayhead" in js
    assert "ensureWaveDetail" in js
    assert "build_waveform_window" not in js  # server-side only
    assert "scheduleWaveDetail" in js
    assert "startScrubEdgeLoop" in js
    assert "panScrubEdge" in js
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
    assert "setListenOn" in js
    assert "/api/monitor" in js
    assert "/api/webrtc" in js
    assert "startWebRtcSession" in js
    assert "setPreviewOn" in js
    assert "fetchMonitorPcm" in js
    assert "scheduleListenBuffer" in js
    assert "unlockListenAudio" in js
    assert "fallbackListenHttp" in js
    assert "tcActive" in js
    assert "set_pc_mute" in js
    assert "move_mark" in js
    assert "delete_marks" in js
    assert "hitTestMark" in js
    assert "waveSetupOn" in js
    assert "updateWaveSetupBtn" in js
    assert "bindWavePreviewSplitter" in js
    assert "applyWavePreviewFlex" in js
    assert "applyLayoutPanelVisibility" in js
    assert "loadPanelPrefs" in js
    assert "setPcMute" in js
    assert "deleteSelectedMark" in js
    assert "setSelectedMark" in js
    assert "openCueActions" in js
    assert "bindCueItemLongPress" in js
    assert "CUE_LONG_PRESS_MS" in js
    assert "showCueActionsForMark" in js
    assert "cue_list_enabled" in js
    assert "mgr-cuelist" in js
    assert "song-badges" in js
    assert "has_video" in js
    assert "ltc_channel" in js
    assert "lastTouchEnd" in js
    assert "gesturestart" in js
    assert "seek_mark" in js
    assert "mark_id: tapId" in js or 'mark_id: tapId' in js
    assert ("Cue ID" in js) or ("mgr-cueid" in js)
    assert (root / "app.js").is_file()
    assert (root / "app.css").is_file()
    html = (root / "index.html").read_text(encoding="utf-8")
    assert 'id="cueActionDialog"' in html
    assert 'id="cueActionList"' in html
    css = (root / "app.css").read_text(encoding="utf-8")
    assert ".now-card.primary .now-body" in css
    assert "position: relative" in css
    assert ".splitter" in css
    assert "#listenBtn.on" in css
    assert "#previewBtn.on" in css
    assert ".preview-wrap" in css
    assert ".wave-setup" in css
    assert ".wave-setup.on" in css
    assert ".transport-row" in css
    assert ".ab-loop" in css
    assert ".ab-btn" in css
    assert ".splitter-h" in css
    assert 'id="loopABtn"' in html
    assert 'id="loopBBtn"' in html
    assert 'id="loopToggleBtn"' in html
    assert 'id="loopClearBtn"' in html
    assert "set_loop_a" in js
    assert "set_loop_b" in js
    assert "clear_loop" in js
    assert "set_loop_enabled" in js
    assert "applyLoopState" in js
    assert ".stage-media.preview-on" in css
    assert ".layout.hide-setlist" in css
    assert ".layout.hide-monitor" in css
    assert "#mutePcBtn.on" in css
    assert ".ghost.tiny.danger" in css
    assert ".cue-item.selected-mark" in css
    assert ".cue-action-btn" in css
    assert ".cue-item.pressing" in css
    assert "touch-action: manipulation" in css
    assert "-webkit-touch-callout: none" in css
    assert "max-height: min(26vh, 220px)" in css
    assert ".song-badges" in css
    assert ".song-badges .b.v.on" in css
    assert "pace_monitor_timeline" in (root / ".." / "webrtc_listen.py").read_text(encoding="utf-8")
    assert "playbackRate = 1" in js


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


def test_monitor_pcm_music_only_strips_ltc() -> None:
    """Listen stream must use music channels only (no striped LTC energy)."""
    sr = 48000
    t = np.linspace(0, 1.0, sr, endpoint=False, dtype=np.float32)
    music = (0.35 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    ltc = np.where((np.arange(sr) % 48) < 24, 0.95, -0.95).astype(np.float32)
    stereo = np.column_stack([music, ltc])
    buf = AudioBuffer(
        path=__import__("pathlib").Path("mon.wav"),
        sample_rate=sr,
        samples=stereo,
        mono=stereo.mean(axis=1),
        peak_levels=[],
    )
    mono = music_mono_samples(buf, exclude_channel=1)
    assert float(np.corrcoef(mono, music)[0, 1]) > 0.99
    meta, pcm = build_monitor_pcm(
        buf,
        song_id="s",
        position=0.1,
        playing=True,
        duration=1.0,
        start=0.1,
        seconds=0.25,
        out_rate=24000,
        exclude_channel=1,
    )
    assert meta["ready"] is True
    assert meta["sample_rate"] == 24000
    assert meta["format"] == "s16le"
    assert meta["channels"] == 1
    assert meta["frames"] > 1000
    assert len(pcm) == meta["frames"] * 2
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    # Resampled music still has energy; LTC-dominated mix would be much louder.
    assert float(np.max(np.abs(samples))) > 0.05
    assert float(np.max(np.abs(samples))) < 0.6
    meta_wav, wav = build_monitor_pcm(
        buf,
        song_id="s",
        position=0.1,
        playing=True,
        duration=1.0,
        start=0.1,
        seconds=0.25,
        out_rate=24000,
        exclude_channel=1,
        as_wav=True,
    )
    assert meta_wav["format"] == "wav"
    assert wav[:4] == b"RIFF"
    assert wav[8:12] == b"WAVE"
    assert len(wav) == 44 + meta_wav["frames"] * 2
    wrapped = pcm16_le_to_wav(pcm, sample_rate=24000, channels=1)
    assert wrapped[:4] == b"RIFF"
    assert len(wrapped) == 44 + len(pcm)


def test_tc_off_shows_em_dash_not_running_clock() -> None:
    """Web Remote must not invent a running SMPTE clock when MTC/LTC are off."""
    project = Project.create("TC", with_song=False)
    song = Song.create("A")
    song.start_timecode = "01:00:00:00"
    project.songs.append(song)
    project.audio_output.ltc_enabled = False
    project.audio_output.mtc_enabled = False
    project.audio_output.midi_enabled = False
    state = build_state(project=project, song=song, engine=_FakeEngine(position=12.0))
    assert state["tc_status"] == "TC off"
    assert state["tc_active"] is False
    assert state["timecode"] == "—"


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
    assert "cue_list_enabled" in row
    mark_row = flagged["marks"][0]
    assert "show_note_on_wave" in mark_row
    assert "show_cue_id_on_wave" in mark_row
    assert "cue_id_enabled" in mark_row
    assert "cue_list_enabled" in mark_row
    song.mark_lanes[1].cue_list_enabled = False
    filtered = build_state(project=project, song=song, engine=_FakeEngine(position=4.0))
    assert len(filtered["marks"]) == 2
    assert len(filtered["cue_list"]) == 1
    assert filtered["cue_list"][0]["lane_index"] == song.mark_lanes[0].index


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


def test_setlist_includes_video_and_ltc_badges() -> None:
    from pathlib import Path

    from cueplayer.domain.models import VideoClip

    project = Project.create("Badges", with_song=False)
    song = Song.create("ClipSong")
    song.file_ltc_side = "left"
    song.add_video_clip(VideoClip.create("v", Path("clip.mp4"), duration_seconds=2.0))
    project.songs.append(song)

    def _ltc(_song: Song) -> int:
        return 0

    state = build_state(
        project=project,
        song=song,
        engine=_FakeEngine(),
        ltc_channel_for_song=_ltc,
    )
    row = state["setlist"][0]
    assert row["has_video"] is True
    assert row["ltc_channel"] == 0

    project.setlist_show_video_badge = False
    project.setlist_show_ltc_badge = False
    hidden = build_state(
        project=project,
        song=song,
        engine=_FakeEngine(),
        ltc_channel_for_song=_ltc,
    )
    assert hidden["setlist"][0]["has_video"] is False
    assert hidden["setlist"][0]["ltc_channel"] is None


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
        get_monitor=lambda start=None, seconds=None, rate=None, as_wav=False: (
            {
                "ok": True,
                "song_id": song.id,
                "playing": engine.playing,
                "position": engine.position,
                "duration": engine.duration,
                "start": float(start or 0.0),
                "seconds": 0.01,
                "sample_rate": int(rate or 24000),
                "channels": 1,
                "format": "wav" if as_wav else "s16le",
                "ready": True,
                "frames": 240,
            },
            (
                pcm16_le_to_wav(
                    (np.linspace(-0.2, 0.2, 240, dtype=np.float32) * 32767)
                    .astype(np.int16)
                    .tobytes(),
                    sample_rate=int(rate or 24000),
                    channels=1,
                )
                if as_wav
                else (np.linspace(-0.2, 0.2, 240, dtype=np.float32) * 32767)
                .astype(np.int16)
                .tobytes()
            ),
        ),
        run_webrtc=lambda payload: (
            {"ok": True, "webrtc": True, "op": "capabilities"}
            if str(payload.get("op") or "") == "capabilities"
            else {"ok": True, "op": str(payload.get("op") or ""), "type": "answer", "sdp": "v=0"}
        ),
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

        assert health.get("webrtc") is True

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

        mon_req = urllib.request.Request(
            "http://127.0.0.1:18765/api/monitor?start=0&seconds=0.01&rate=24000",
            headers={"Authorization": "Bearer secret"},
        )
        with urllib.request.urlopen(mon_req, timeout=3) as resp:
            assert resp.status == 200
            assert resp.headers.get("X-CuePlayer-Ready") == "1"
            assert resp.headers.get("X-CuePlayer-Sample-Rate") == "24000"
            assert resp.headers.get("X-CuePlayer-Format") == "s16le"
            body = resp.read()
            assert len(body) == 480  # 240 int16 frames

        wav_req = urllib.request.Request(
            "http://127.0.0.1:18765/api/monitor?start=0&seconds=0.01&rate=24000&format=wav",
            headers={"Authorization": "Bearer secret"},
        )
        with urllib.request.urlopen(wav_req, timeout=3) as resp:
            assert resp.status == 200
            assert resp.headers.get("Content-Type", "").startswith("audio/wav")
            assert resp.headers.get("X-CuePlayer-Format") == "wav"
            wav_body = resp.read()
            assert wav_body[:4] == b"RIFF"
            assert len(wav_body) == 44 + 480

        code, caps = _http_json(
            "http://127.0.0.1:18765/api/webrtc",
            data={"op": "capabilities"},
            headers={"Authorization": "Bearer secret"},
        )
        assert code == 200
        assert caps.get("webrtc") is True

        req = urllib.request.Request("http://127.0.0.1:18765/")
        with urllib.request.urlopen(req, timeout=3) as resp:
            html = resp.read().decode("utf-8")
            assert "CuePlayer" in html
            assert 'id="waveCanvas"' in html
            assert 'id="listenBtn"' in html
            assert resp.status == 200
    finally:
        server.stop()


def test_pace_monitor_timeline_skips_instead_of_burst() -> None:
    from cueplayer.web_remote.webrtc_listen import (
        LAG_SKIP_SECONDS,
        SAMPLE_RATE,
        SAMPLES_PER_FRAME,
        pace_monitor_timeline,
    )

    start = 1000.0
    # On time: ask to sleep ~20ms.
    _s, ts, sleep, skipped = pace_monitor_timeline(
        start=start,
        timestamp=0,
        now=start,
    )
    assert skipped is False
    assert ts == SAMPLES_PER_FRAME
    assert abs(sleep - (SAMPLES_PER_FRAME / SAMPLE_RATE)) < 1e-6

    # Slightly late: emit immediately, do not jump.
    _s, ts, sleep, skipped = pace_monitor_timeline(
        start=start,
        timestamp=0,
        now=start + 0.03,
    )
    assert skipped is False
    assert sleep == 0.0

    # Far behind: jump timeline (no burst catch-up).
    _s, ts, sleep, skipped = pace_monitor_timeline(
        start=start,
        timestamp=0,
        now=start + 0.25,
    )
    assert skipped is True
    assert sleep == 0.0
    assert ts >= int(0.25 * SAMPLE_RATE) - SAMPLES_PER_FRAME
    assert LAG_SKIP_SECONDS > 0


def test_downscale_rgb24_and_video_pace() -> None:
    from cueplayer.web_remote.webrtc_listen import (
        VIDEO_CLOCK_RATE,
        VIDEO_PTS_STEP,
        downscale_rgb24,
        pace_video_timeline,
    )

    big = np.zeros((1080, 1920, 3), dtype=np.uint8)
    big[:, :, 0] = 255
    small = downscale_rgb24(big, max_width=960)
    assert small.shape == (540, 960, 3)
    assert small.dtype == np.uint8

    start = 50.0
    _s, ts, sleep, skipped = pace_video_timeline(
        start=start,
        timestamp=0,
        now=start,
    )
    assert skipped is False
    assert ts == VIDEO_PTS_STEP
    assert abs(sleep - (VIDEO_PTS_STEP / VIDEO_CLOCK_RATE)) < 1e-6
    _s, ts, sleep, skipped = pace_video_timeline(
        start=start,
        timestamp=0,
        now=start + 0.5,
    )
    assert skipped is True
    assert sleep == 0.0


def test_webrtc_listen_hub_offer_answer() -> None:
    pytest.importorskip("aiortc")
    from aiortc import RTCPeerConnection

    from cueplayer.web_remote.webrtc_listen import WEBRTC_AVAILABLE, WebRTCListenHub

    assert WEBRTC_AVAILABLE is True
    hub = WebRTCListenHub(lambda n, _sr: np.zeros(int(n), dtype=np.int16))
    try:
        caps = hub.handle({"op": "capabilities"})
        assert caps["ok"] is True
        assert caps["webrtc"] is True

        async def _client_offer() -> tuple[str, str]:
            pc = RTCPeerConnection()
            pc.addTransceiver("audio", direction="recvonly")
            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)
            # Give ICE a moment; hub also waits.
            for _ in range(40):
                if pc.iceGatheringState == "complete":
                    break
                await __import__("asyncio").sleep(0.05)
            local = pc.localDescription
            assert local is not None
            sdp, typ = local.sdp, local.type
            await pc.close()
            return sdp, typ

        import asyncio

        sdp, typ = asyncio.run(_client_offer())
        answer = hub.handle({"op": "offer", "sdp": sdp, "type": typ})
        assert answer.get("ok") is True, answer
        assert answer.get("type") == "answer"
        assert "m=audio" in str(answer.get("sdp") or "")

        hang = hub.handle({"op": "hangup"})
        assert hang.get("ok") is True
    finally:
        hub.stop()


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
    mark_id = window.current_song.marks[0].id
    out = bridge._dispatch({"op": "move_mark", "mark_id": mark_id, "seconds": 3.25})
    assert out["ok"] is True
    assert abs(window.current_song.marks[0].time_seconds - 3.25) < 1e-6
    out = bridge._dispatch({"op": "add_mark", "shortcut": "1"})
    assert out["ok"] is True
    assert len(window.current_song.marks) == 2
    delete_id = window.current_song.marks[0].id
    out = bridge._dispatch({"op": "delete_marks", "mark_ids": [delete_id]})
    assert out["ok"] is True
    assert out["removed"] == 1
    assert all(m.id != delete_id for m in window.current_song.marks)
    lane2 = next(l for l in window.current_song.mark_lanes if l.index == 2)
    assert lane2.cue_list_enabled is True
    out = bridge._dispatch({
        "op": "update_lane",
        "lane_index": 2,
        "cue_list_enabled": False,
    })
    assert out["ok"] is True
    assert lane2.cue_list_enabled is False
    out = bridge._dispatch({"op": "set_pc_mute", "muted": True})
    assert out["ok"] is True
    assert out["muted"] is True
    assert window.engine.music_muted is True
    out = bridge._dispatch({"op": "set_pc_mute", "muted": False})
    assert out["ok"] is True
    assert window.engine.music_muted is False
    out = bridge._dispatch({"op": "seek", "seconds": 4.0})
    assert out["ok"] is True
    assert abs(window.engine.position - 4.0) < 0.05
    out = bridge._dispatch({"op": "stop"})
    assert out["ok"] is True
    out = bridge._dispatch({"op": "seek", "seconds": 1.0})
    assert out["ok"] is True
    out = bridge._dispatch({"op": "set_loop_a"})
    assert out["ok"] is True
    assert out["loop"]["a"] is not None
    out = bridge._dispatch({"op": "seek", "seconds": 3.0})
    assert out["ok"] is True
    out = bridge._dispatch({"op": "set_loop_b"})
    assert out["ok"] is True
    assert out["loop"]["b"] is not None
    assert out["loop"]["enabled"] is True
    out = bridge._dispatch({"op": "set_loop_enabled", "enabled": False})
    assert out["ok"] is True
    assert out["loop"]["enabled"] is False
    out = bridge._dispatch({"op": "clear_loop"})
    assert out["ok"] is True
    assert out["loop"]["a"] is None
    assert out["loop"]["b"] is None
    assert out["loop"]["enabled"] is False
    window._web_remote.stop()
    # Do not call window.close() — closeEvent quits the QApplication.
