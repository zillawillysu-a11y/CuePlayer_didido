"""Phase 2: LTC generator clips wired into playback (LTC audio / MTC / display).

Covers: in-clip/out-of-clip LTC audio, TC restart per clip, multiple clips,
backward TC, adjacent-clip boundary, seek, MTC shared mapping + re-anchor,
timecode display No-TC, and legacy full-track / striped / explicit-off
regression.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.ltc_clips import add_ltc_clip
from cueplayer.domain.models import AudioOutputSettings, Song
from cueplayer.media.audio_loader import AudioBuffer
from cueplayer.playback import audio_engine as eng_mod
from cueplayer.timecode.ltc import generate_ltc_pcm
from cueplayer.timecode.ltc_decode import decode_ltc_timecode
from cueplayer.timecode.smpte import Timecode, add_frames

SR = 48000
FPS = 30.0


class _FakePort:
    def __init__(self) -> None:
        self.messages: list = []

    def send(self, message) -> None:  # noqa: ANN001
        self.messages.append(message)

    def close(self) -> None:
        pass


def _full_frame_tc(message) -> Timecode:
    b = message.bytes()
    assert b[0] == 0xF0 and b[-1] == 0xF7
    data = list(b[1:-1])
    return Timecode(
        data[4] & 0x1F, data[5] & 0x7F, data[6] & 0x7F, data[7] & 0x7F
    )


@pytest.fixture(autouse=True)
def _fake_devices(monkeypatch):
    from cueplayer.playback.devices import OutputDeviceInfo

    device = OutputDeviceInfo(
        index=0,
        name="Test",
        max_output_channels=8,
        default_samplerate=48000.0,
        hostapi_name="Test",
    )
    monkeypatch.setattr(eng_mod, "probe_supported_output_channels",
                        lambda index, *, min_channels, samplerate: min_channels)
    monkeypatch.setattr(eng_mod, "list_output_devices",
                        lambda dedupe=True: [device])
    monkeypatch.setattr(eng_mod.sd, "check_output_settings",
                        lambda **kwargs: None)
    QApplication.instance() or QApplication([])


def _make_engine(
    monkeypatch,
    *,
    ltc_source: str = "generator",
    ltc_enabled: bool = True,
    ltc_gain: float = 1.0,
    mtc: bool = False,
) -> eng_mod.AudioEngine:
    engine = eng_mod.AudioEngine()
    engine.apply_audio_settings(
        AudioOutputSettings(
            output_device_name="Test",
            ltc_enabled=ltc_enabled,
            ltc_source=ltc_source,
            ltc_gain=ltc_gain,
            ltc_channels=[2],
            midi_enabled=mtc,
            mtc_enabled=mtc,
            midi_port_name="",
        )
    )
    return engine


def _clip_song(*, duration: float = 10.0, start_tc: str = "01:00:00:00",
               clips: tuple = ()) -> Song:
    song = Song(id="song1", name="Clip Song", duration_seconds=duration,
                start_timecode=start_tc)
    for (start, dur, tc) in clips:
        add_ltc_clip(song, timeline_start_seconds=start, duration_seconds=dur,
                     start_timecode=tc)
    return song


def _attach_clip_song(engine, song: Song) -> None:
    engine.set_song_timebase(song.start_timecode, song.fps)
    engine.set_song(song)
    engine.refresh_song_ltc_routing()
    _wait_clip_cache(engine)


def _wait_clip_cache(engine, timeout: float = 30.0) -> None:
    fut = engine._ltc_clip_cache_future  # noqa: SLF001
    if fut is not None:
        fut.result(timeout=timeout)
    deadline = time.monotonic() + 5.0
    while engine._ltc_clip_table is None and time.monotonic() < deadline:  # noqa: SLF001
        time.sleep(0.01)


def _decode(chunk: np.ndarray) -> Timecode | None:
    return decode_ltc_timecode(chunk, SR, FPS)


def _tc_close(tc: Timecode | None, expected: Timecode, tol_frames: int = 2) -> bool:
    if tc is None:
        return False
    return abs(tc.total_frames(FPS) - expected.total_frames(FPS)) <= tol_frames


# --- LTC audio -------------------------------------------------------------


def test_clip_chunk_inside_and_outside_is_correct() -> None:
    engine = _make_engine(None)
    song = _clip_song(clips=[(2.0, 3.0, "01:00:00:00")])
    _attach_clip_song(engine, song)
    assert engine._uses_clip_ltc()  # noqa: SLF001
    assert not engine._uses_generated_ltc()  # noqa: SLF001

    ref = generate_ltc_pcm(3.0, SR, "01:00:00:00", FPS, amplitude=1.0)

    # Before the clip: silence (no fallback to song start TC).
    assert not np.any(engine._ltc_chunk(0, SR) != 0.0)  # noqa: SLF001
    # After the clip: silence.
    assert not np.any(engine._ltc_chunk(5 * SR, 1000) != 0.0)  # noqa: SLF001
    # Inside: exactly the per-clip generated LTC.
    chunk = engine._ltc_chunk(2 * SR, 1000)  # noqa: SLF001
    assert np.allclose(chunk, ref[:1000])
    # Straddling the clip start: silence up to the clip, then generated LTC.
    chunk = engine._ltc_chunk(2 * SR - 800, 2000)  # noqa: SLF001
    assert not np.any(chunk[:800] != 0.0)
    assert np.allclose(chunk[800:1800], ref[:1000])


def test_clip_chunk_decodes_mapped_timecode() -> None:
    engine = _make_engine(None)
    song = _clip_song(clips=[(2.0, 3.0, "01:00:00:00")])
    _attach_clip_song(engine, song)

    chunk = engine._ltc_chunk(2 * SR, 2 * SR)  # noqa: SLF001
    assert _tc_close(_decode(chunk), Timecode(1, 0, 0, 0))
    chunk = engine._ltc_chunk(int(3.5 * SR), 2 * SR)  # noqa: SLF001
    # 3.5s - 2.0s = 1.5s into the clip → 01:00:01:15 at 30 fps.
    assert _tc_close(_decode(chunk), Timecode(1, 0, 1, 15))
    # Outside: decode fails (pure silence).
    assert _decode(engine._ltc_chunk(0, SR)) is None  # noqa: SLF001


def test_multiple_clips_restart_timecode() -> None:
    engine = _make_engine(None)
    song = _clip_song(clips=[
        (1.0, 2.0, "01:00:00:00"),
        (5.0, 2.0, "02:00:00:00"),
    ])
    _attach_clip_song(engine, song)

    assert _tc_close(
        _decode(engine._ltc_chunk(int(1.2 * SR), SR)),  # noqa: SLF001
        Timecode(1, 0, 0, 6),
    )
    assert not np.any(engine._ltc_chunk(4 * SR, 1000) != 0.0)  # noqa: SLF001
    # Second clip restarts at its own start TC (no continuation of clip A).
    assert _tc_close(
        _decode(engine._ltc_chunk(int(5.2 * SR), SR)),  # noqa: SLF001
        Timecode(2, 0, 0, 6),
    )


def test_backward_tc_range_allowed_in_playback() -> None:
    engine = _make_engine(None)
    song = _clip_song(clips=[
        (1.0, 2.0, "01:00:00:00"),
        (5.0, 2.0, "00:59:50:00"),  # regresses behind clip A's TC range
    ])
    _attach_clip_song(engine, song)

    assert _tc_close(
        _decode(engine._ltc_chunk(int(5.5 * SR), SR)),  # noqa: SLF001
        Timecode(0, 59, 50, 15),
    )


def test_adjacent_clips_boundary_later_wins() -> None:
    engine = _make_engine(None)
    song = _clip_song(clips=[
        (1.0, 2.0, "01:00:00:00"),
        (3.0, 2.0, "01:10:00:00"),
    ])
    _attach_clip_song(engine, song)

    assert _tc_close(
        _decode(engine._ltc_chunk(int(2.5 * SR), SR)),  # noqa: SLF001
        Timecode(1, 0, 1, 15),
    )
    # Exact shared boundary: the later clip owns the boundary position.
    assert _tc_close(
        _decode(engine._ltc_chunk(3 * SR, SR)),  # noqa: SLF001
        Timecode(1, 10, 0, 0),
    )


def test_clip_chunk_fallback_matches_cache() -> None:
    """Before the async table is ready, the realtime fallback renders the
    same mapping."""
    engine = _make_engine(None)
    song = _clip_song(clips=[(2.0, 3.0, "01:00:00:00")])
    engine.set_song_timebase(song.start_timecode, song.fps)
    engine.set_song(song)
    # Do NOT wait for the cache — force the fallback path.
    fallback = engine._clip_ltc_chunk(2 * SR, 2000)  # noqa: SLF001
    assert np.any(fallback != 0.0)
    assert _tc_close(_decode(fallback), Timecode(1, 0, 0, 0))


# --- Timecode display -------------------------------------------------------


def test_display_mapped_tc_inside_and_no_tc_outside() -> None:
    engine = _make_engine(None)
    song = _clip_song(clips=[(2.0, 3.0, "01:00:00:00")])
    _attach_clip_song(engine, song)

    state = engine.output_timecode_state(2.5)
    # 2.5 - 2.0 = 0.5s into the clip → 15 frames → 01:00:00:15.
    assert state.timecode == "01:00:00:15"
    assert "LTC" in state.outputs
    for pos in (0.5, 5.5, 8.0):  # 4.0 is inside the [2,5] clip
        assert engine.output_timecode_state(pos).timecode == "--:--:--:--"


def test_display_outside_clip_is_not_song_start_fallback() -> None:
    engine = _make_engine(None)
    song = _clip_song(start_tc="01:00:00:00", clips=[(5.0, 2.0, "01:00:00:00")])
    _attach_clip_song(engine, song)
    # Legacy math would show 01:00:00:15 at 1.5s; clip mode must not.
    state = engine.output_timecode_state(1.5)
    assert state.timecode == "--:--:--:--"
    assert state.timecode != "01:00:00:15"


def test_display_after_seek() -> None:
    engine = _make_engine(None)
    song = _clip_song(clips=[(2.0, 3.0, "01:00:00:00")])
    _attach_clip_song(engine, song)

    engine.seek(6.5)
    assert engine.output_timecode_state().timecode == "--:--:--:--"
    engine.seek(3.5)
    assert engine.output_timecode_state().timecode == "01:00:01:15"


# --- MTC shared mapping ------------------------------------------------------


def _mtc_events(engine, positions: list[float]) -> list[list]:
    port = _FakePort()
    engine._mtc._port = port  # noqa: SLF001
    engine._mtc._enabled = True  # noqa: SLF001
    engine._playing = True  # noqa: SLF001
    events = []
    for pos in positions:
        engine._position_frame = int(round(pos * SR))  # noqa: SLF001
        port.messages.clear()
        engine._mtc_tick()
        events.append(list(port.messages))
    engine._playing = False  # noqa: SLF001
    engine._mtc._port = None  # noqa: SLF001
    return events


def test_mtc_silent_outside_clips() -> None:
    engine = _make_engine(None, mtc=True)
    song = _clip_song(clips=[(2.0, 3.0, "01:00:00:00")])
    _attach_clip_song(engine, song)

    engine._mtc.on_play(0.5)  # noqa: SLF001 — start outside every clip
    port = engine._mtc._port  # noqa: SLF001
    assert port is None  # no port was requested (empty port name)
    # Drive ticks with a fake port while outside the clip: nothing is sent.
    port = _FakePort()
    engine._mtc._port = port  # noqa: SLF001
    engine._position_frame = int(round(0.5 * SR))  # noqa: SLF001
    port.messages.clear()
    engine._mtc_tick()
    assert port.messages == []


def test_mtc_reanchors_and_shares_clip_mapping() -> None:
    engine = _make_engine(None, mtc=True)
    song = _clip_song(clips=[
        (2.0, 2.0, "01:00:00:00"),  # [2,4]
        (5.0, 3.0, "02:00:00:00"),  # [5,8] — gap (4,5) has no TC
    ])
    _attach_clip_song(engine, song)

    port = _FakePort()
    engine._mtc._port = port  # noqa: SLF001
    engine._mtc._enabled = True  # noqa: SLF001
    engine._playing = True  # noqa: SLF001
    engine._mtc.on_play(0.5)  # noqa: SLF001 — outside: no full frame, no QF
    assert port.messages == []

    # Enter clip A: re-anchor full frame + quarter frames at the mapped TC.
    engine._position_frame = int(round(2.5 * SR))  # noqa: SLF001
    port.messages.clear()
    engine._mtc_tick()
    full = [m for m in port.messages if m.bytes()[0] == 0xF0]
    qf = [m for m in port.messages if m.bytes()[0] == 0xF1]
    assert full and _tc_close(_full_frame_tc(full[0]), Timecode(1, 0, 0, 15))
    assert qf

    # In the gap between clips: no MTC at all until the next clip.
    engine._position_frame = int(round(4.5 * SR))  # noqa: SLF001
    port.messages.clear()
    engine._mtc_tick()
    assert port.messages == []

    # Enter clip B: re-anchor to B's start TC, not a continuation of A.
    engine._position_frame = int(round(5.5 * SR))  # noqa: SLF001
    port.messages.clear()
    engine._mtc_tick()
    full = [m for m in port.messages if m.bytes()[0] == 0xF0]
    assert full and _tc_close(_full_frame_tc(full[0]), Timecode(2, 0, 0, 15))
    engine._playing = False  # noqa: SLF001


def test_mtc_legacy_timebase_unchanged_without_provider() -> None:
    from cueplayer.playback.mtc_output import MtcOutput
    from cueplayer.timecode.mtc import absolute_timecode

    mtc = MtcOutput()
    mtc.set_timebase("01:00:00:00", FPS)
    port = _FakePort()
    mtc._port = port  # noqa: SLF001
    mtc._enabled = True  # noqa: SLF001
    mtc.on_play(0.0)
    port.messages.clear()
    mtc.tick(1.5)
    assert port.messages
    # Legacy single timebase: 01:00:01:15 at 1.5s.
    assert absolute_timecode(Timecode(1, 0, 0, 0), 1.5, FPS) == Timecode(1, 0, 1, 15)


# --- Legacy / regression ------------------------------------------------------


def test_legacy_auto_generator_full_track_unchanged() -> None:
    engine = _make_engine(None, ltc_source="generator")
    engine.set_song_timebase("01:00:00:00", FPS)
    engine.set_song(Song(id="s", name="Legacy", duration_seconds=10.0))
    engine._ensure_ltc_cache()  # noqa: SLF001
    fut = engine._ltc_cache_future  # noqa: SLF001
    if fut is not None:
        fut.result(timeout=30.0)
    deadline = time.monotonic() + 5.0
    while engine._ltc_pcm is None and time.monotonic() < deadline:  # noqa: SLF001
        time.sleep(0.01)
    assert engine._uses_generated_ltc()  # noqa: SLF001
    assert not engine._uses_clip_ltc()  # noqa: SLF001
    ref = generate_ltc_pcm(10.0, SR, "01:00:00:00", FPS, amplitude=1.0)
    assert np.allclose(engine._ltc_chunk(0, 1000), ref[:1000])  # noqa: SLF001
    # Display uses the single-offset math (no clip mapping).
    assert engine.output_timecode_state(1.5).timecode == "01:00:01:15"


def test_explicit_full_track_mode_behaves_like_legacy_generator() -> None:
    engine = _make_engine(None, ltc_source="generator")
    song = Song(id="s", name="Explicit", duration_seconds=10.0)
    song.ltc_source_mode = "full_track_generator"
    engine.set_song_timebase(song.start_timecode, song.fps)
    engine.set_song(song)
    assert engine._uses_generated_ltc()  # noqa: SLF001
    assert not engine._uses_clip_ltc()  # noqa: SLF001


def test_explicit_off_stops_generated_ltc() -> None:
    engine = _make_engine(None, ltc_source="generator")
    song = Song(id="s", name="Off", duration_seconds=10.0)
    song.ltc_source_mode = "off"
    engine.set_song_timebase(song.start_timecode, song.fps)
    engine.set_song(song)
    assert not engine._uses_generated_ltc()  # noqa: SLF001
    assert not engine._uses_clip_ltc()  # noqa: SLF001
    assert not np.any(engine._ltc_chunk(0, 1000) != 0.0)  # noqa: SLF001


def test_clip_mode_with_generator_project_settings() -> None:
    """Explicit clip_generator wins over a generator project setting
    (mutual exclusion: clips stop the full-track generator)."""
    engine = _make_engine(None, ltc_source="generator")
    song = _clip_song(clips=[(2.0, 3.0, "01:00:00:00")])
    _attach_clip_song(engine, song)
    assert engine._uses_clip_ltc()  # noqa: SLF001
    assert not engine._uses_generated_ltc()  # noqa: SLF001
    assert engine._ltc_pcm is None  # noqa: SLF001 — no full-track pcm


def test_clip_mode_ignores_file_stripe() -> None:
    """A striped file must not feed the LTC bus or be stripped from music in
    clip mode — the file channels are plain music."""
    engine = _make_engine(None, ltc_source="auto")
    ltc = generate_ltc_pcm(10.0, SR, "03:00:00:00", FPS, amplitude=1.0)
    music = np.ones_like(ltc) * 0.1
    stereo = np.stack([music, ltc], axis=1)
    buf = AudioBuffer(path=None, sample_rate=SR, samples=stereo,
                      mono=music, peak_levels=[])
    song = _clip_song(clips=[(2.0, 3.0, "01:00:00:00")])
    engine.set_buffer(buf)
    engine.set_song_timebase(song.start_timecode, song.fps)
    engine.set_song(song)
    engine.flush_deferred_buffer_setup()

    assert engine._effective_ltc_source_channel() is None
    assert engine._resolved_file_ltc_channel() is None
    assert engine._decode_source_channel() is None
    # Music bed keeps both channels (no stripe stripping).
    music_ch = engine._music_source_indices()
    assert music_ch == (0, 1)
    # The LTC bus carries the generated clip TC, not the file stripe.
    chunk = engine._ltc_chunk(2 * SR, SR)  # noqa: SLF001
    assert _tc_close(_decode(chunk), Timecode(1, 0, 0, 0))
    assert _decode(chunk) != Timecode(3, 0, 0, 0)


def test_clip_mode_display_independent_of_project_source() -> None:
    engine = _make_engine(None, ltc_source="auto")
    song = _clip_song(clips=[(2.0, 3.0, "01:00:00:00")])
    _attach_clip_song(engine, song)
    assert engine.output_timecode_state(2.5).timecode == "01:00:00:15"
    assert engine.output_timecode_state(0.5).timecode == "--:--:--:--"


def test_ltc_gain_applies_to_clip_ltc() -> None:
    engine = _make_engine(None, ltc_gain=0.5)
    song = _clip_song(clips=[(2.0, 3.0, "01:00:00:00")])
    _attach_clip_song(engine, song)
    # Use a full LTC frame so the decoder can lock (1000 samples is too short).
    full = engine._ltc_chunk(2 * SR, 2 * SR)  # noqa: SLF001
    ref = generate_ltc_pcm(3.0, SR, "01:00:00:00", FPS, amplitude=1.0)
    assert np.allclose(full, ref[: 2 * SR] * 0.5)
    assert _tc_close(_decode(full), Timecode(1, 0, 0, 0))


def test_no_song_keeps_legacy_resolution() -> None:
    engine = _make_engine(None, ltc_source="generator")
    assert engine._resolved_ltc_mode() == "full_track_generator"  # noqa: SLF001
    assert engine._uses_generated_ltc()  # noqa: SLF001

    engine2 = _make_engine(None, ltc_source="auto")
    assert engine2._resolved_ltc_mode() == "striped_file"  # noqa: SLF001

    engine3 = _make_engine(None, ltc_source="generator", ltc_enabled=False)
    assert engine3._resolved_ltc_mode() == "off"  # noqa: SLF001
    assert not engine3._uses_generated_ltc()  # noqa: SLF001
