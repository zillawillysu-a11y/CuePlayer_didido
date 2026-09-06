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


# --- MTC clip-boundary: no previous-clip QF leak -----------------------------


def _tc_in_range(tc: Timecode, lo: Timecode, hi: Timecode) -> bool:
    r = tc.total_frames(FPS)
    return lo.total_frames(FPS) <= r < hi.total_frames(FPS)


def _decode_qf_groups(
    raw: list[tuple[float, int, int]]
) -> list[tuple[Timecode, list[float]]]:
    """Decode complete 8-piece QF groups from the accumulated
    ``(position, piece_type, nibble)`` stream.

    Returns ``(timecode, positions_of_the_8_pieces)`` per group. Groups
    interrupted by a re-anchor (skipped pieces) never complete and are
    ignored — exactly like a receiver that never latched them. A group
    containing even one piece sent after a boundary must still carry the
    correct (new-clip) TC — that is the no-leak assertion.
    """
    out: list[tuple[Timecode, list[float]]] = []
    i = 0
    while i < len(raw) - 7:
        if raw[i][1] != 0 or not all(raw[i + k][1] == k for k in range(8)):
            i += 1
            continue
        v = [raw[i + k][2] for k in range(8)]
        hours = (v[6] | ((v[7] & 0x01) << 4)) & 0x1F
        out.append(
            (
                Timecode(
                    hours,
                    v[4] | (v[5] << 4),
                    v[2] | (v[3] << 4),
                    v[0] | (v[1] << 4),
                ),
                [raw[i + k][0] for k in range(8)],
            )
        )
        i += 8
    return out


def _run_mtc_steps(
    engine, port: _FakePort, start_s: float, end_s: float, step_ms: float = 1.0
) -> tuple[
    list[tuple[float, list[Timecode], list[tuple[int, int]]]],
    list[tuple[float, int, int]],
    ]:
    """Step the playhead by ``step_ms`` ms, run the engine MTC tick each step.

    Returns ``(per_step, raw)`` where ``per_step`` is
    ``(position, full_frames, qf_pieces)`` per step and ``raw`` is the
    accumulated ``(position, piece_type, nibble)`` stream (a QF group spans
    8 consecutive ticks at 1 ms steps, so it must be decoded from ``raw``,
    not from a single step's capture).
    """
    engine._playing = True  # noqa: SLF001
    with engine._lock:
        engine._clear_write_head_stamp_unlocked()  # noqa: SLF001
    engine._mtc._port = port  # noqa: SLF001
    engine._mtc._enabled = True  # noqa: SLF001
    engine._mtc._playing = True  # noqa: SLF001
    per_step: list[tuple[float, list[Timecode], list[tuple[int, int]]]] = []
    raw: list[tuple[float, int, int]] = []
    pos = start_s
    while pos <= end_s + 1e-9:
        engine._position_frame = int(round(pos * SR))  # noqa: SLF001
        port.messages.clear()
        engine._mtc_tick()  # noqa: SLF001
        fulls = [
            _full_frame_tc(m) for m in port.messages if m.bytes()[0] == 0xF0
        ]
        qf = [
            (m.bytes()[1] >> 4, m.bytes()[1] & 0x0F)
            for m in port.messages
            if m.bytes()[0] == 0xF1
        ]
        per_step.append((pos, fulls, qf))
        raw.extend((pos, t, n) for (t, n) in qf)
        pos += step_ms / 1000.0
    engine._playing = False  # noqa: SLF001
    return per_step, raw


def test_mtc_adjacent_clips_no_previous_clip_qf_leak() -> None:
    """Clip A → adjacent Clip B (no gap), very different start TCs, boundary
    NOT on the 2-frame QF grid (4.05s = frame 121.5). After entering B, no
    QF group may carry A's TC — the receiver must not see stale A frames."""
    engine = _make_engine(None, mtc=True)
    song = _clip_song(clips=[
        (2.0, 2.05, "01:00:00:00"),   # A = [2.0, 4.05)
        (4.05, 2.0, "02:00:00:00"),   # B = [4.05, 6.05], 1h offset
    ])
    _attach_clip_song(engine, song)
    port = _FakePort()
    per_step, raw = _run_mtc_steps(engine, port, 3.9, 4.3)

    b_lo = Timecode(2, 0, 0, 0)
    b_hi = Timecode(2, 0, 2, 0)
    a_lo = Timecode(1, 0, 0, 0)
    a_hi = Timecode(1, 0, 2, 1)
    # The boundary crossing must have produced a B full frame + B QFs.
    b_full = any(
        _tc_in_range(tc, b_lo, b_hi) for pos, fulls, _ in per_step
        if pos >= 4.05 for tc in fulls
    )
    groups = _decode_qf_groups(raw)
    b_qf = any(
        all(p >= 4.05 for p in piece_pos) and _tc_in_range(tc, b_lo, b_hi)
        for tc, piece_pos in groups
    )
    assert b_full, "expected a B full frame after entering B"
    assert b_qf, "expected B quarter frames after entering B"
    # No stale A TC may leak: any completed QF group containing even one
    # piece sent at/after the boundary must carry B's TC.
    for tc, piece_pos in groups:
        if any(p >= 4.05 for p in piece_pos):
            assert _tc_in_range(tc, b_lo, b_hi), (
                f"stale A QF group {tc.format()} (A range "
                f"{a_lo.format()}-{a_hi.format()}) has pieces at "
                f"{[round(p, 3) for p in piece_pos]}"
            )


def test_mtc_gap_then_clip_b_only_b_qf() -> None:
    """Gap between clips: silence through the gap, then only B's TC."""
    engine = _make_engine(None, mtc=True)
    song = _clip_song(clips=[
        (2.0, 2.0, "01:00:00:00"),   # A = [2.0, 4.0)
        (5.0, 2.0, "02:00:00:00"),   # B = [5.0, 7.0); gap (4.0, 5.0)
    ])
    _attach_clip_song(engine, song)
    port = _FakePort()
    per_step, raw = _run_mtc_steps(engine, port, 3.9, 5.3)

    # No MTC at all while in the gap.
    for pos, fulls, qf in per_step:
        if 4.0 <= pos < 5.0:
            assert not fulls and not qf, f"MTC in gap at pos {pos}"
    # Entering B: full frame + QFs, all in B's range.
    b_lo, b_hi = Timecode(2, 0, 0, 0), Timecode(2, 0, 2, 0)
    groups = _decode_qf_groups(raw)
    assert any(
        _tc_in_range(tc, b_lo, b_hi) for pos, fulls, _ in per_step
        if pos >= 5.0 for tc in fulls
    )
    assert any(
        all(p >= 5.0 for p in piece_pos) and _tc_in_range(tc, b_lo, b_hi)
        for tc, piece_pos in groups
    )
    # After leaving A: every full frame and completed QF group is B's TC
    # (a group with any piece sent in/after the gap must be B's, since the
    # gap carries no TC at all).
    for pos, fulls, _ in per_step:
        if pos >= 4.0:
            for tc in fulls:
                assert _tc_in_range(tc, b_lo, b_hi), (
                    f"non-B full frame at pos {pos}: {tc.format()}"
                )
    for tc, piece_pos in groups:
        if any(p >= 4.0 for p in piece_pos):
            assert _tc_in_range(tc, b_lo, b_hi), (
                f"non-B QF group {tc.format()} with pieces at "
                f"{[round(p, 3) for p in piece_pos]}"
            )


def test_mtc_backward_tc_clip_no_forward_leak() -> None:
    """Clip B starts at a TC *earlier* than A's range (backward jump).
    No QF from A's forward range may be sent after entering B."""
    engine = _make_engine(None, mtc=True)
    song = _clip_song(clips=[
        (2.0, 2.05, "02:00:00:00"),   # A = [2.0, 4.05) @ 02:00:00:00
        (4.05, 2.0, "01:00:00:00"),   # B = [4.05, 6.05) @ 01:00:00:00
    ])
    _attach_clip_song(engine, song)
    port = _FakePort()
    per_step, raw = _run_mtc_steps(engine, port, 3.9, 4.3)

    b_lo, b_hi = Timecode(1, 0, 0, 0), Timecode(1, 0, 2, 0)
    groups = _decode_qf_groups(raw)
    assert any(
        _tc_in_range(tc, b_lo, b_hi) for pos, fulls, _ in per_step
        if pos >= 4.05 for tc in fulls
    ), "expected a B full frame after entering B"
    assert any(
        all(p >= 4.05 for p in piece_pos) and _tc_in_range(tc, b_lo, b_hi)
        for tc, piece_pos in groups
    ), "expected B quarter frames after entering B"
    for tc, piece_pos in groups:
        if any(p >= 4.05 for p in piece_pos):
            assert _tc_in_range(tc, b_lo, b_hi), (
                f"stale A QF group {tc.format()} with pieces at "
                f"{[round(p, 3) for p in piece_pos]}"
            )


# --- Exact clip-end boundary consistency ([start, end)) ---------------------


def test_exact_end_boundary_consistent_across_audio_display_mtc() -> None:
    """Single clip [2.0, 5.0): exact start included, exact end NOT included —
    identically for domain mapping, LTC audio, display, and MTC source key."""
    engine = _make_engine(None, mtc=True)
    song = _clip_song(clips=[(2.0, 3.0, "01:00:00:00")])
    _attach_clip_song(engine, song)
    clip = song.ltc_clips[0]

    # Exact start: inside — TC everywhere.
    from cueplayer.domain.ltc_clips import ltc_timecode_at

    assert ltc_timecode_at(song.ltc_clips, FPS, 2.0) == Timecode(1, 0, 0, 0)
    assert engine.output_timecode_state(2.0).timecode == "01:00:00:00"
    assert np.any(engine._ltc_chunk(2 * SR, 1000) != 0.0)  # noqa: SLF001
    assert engine._mtc_tc_source_key(2.0) == ("clip", clip.id)  # noqa: SLF001

    # One frame before the end (4.9667s = frame 89 of the clip): still inside.
    one_frame_before = 5.0 - 1.0 / FPS
    # 01:00:00:00 + 89 frames @ 30 fps = 01:00:02:29.
    assert ltc_timecode_at(song.ltc_clips, FPS, one_frame_before) == Timecode(1, 0, 2, 29)
    assert (
        engine.output_timecode_state(one_frame_before).timecode == "01:00:02:29"
    )
    assert np.any(
        engine._ltc_chunk(int(round(one_frame_before * SR)), 1000) != 0.0
    )  # noqa: SLF001
    assert engine._mtc_tc_source_key(one_frame_before) == ("clip", clip.id)  # noqa: SLF001

    # Exact end (5.0): outside — silence, No TC, MTC source key = none.
    assert ltc_timecode_at(song.ltc_clips, FPS, 5.0) is None
    assert engine.output_timecode_state(5.0).timecode == "--:--:--:--"
    assert not np.any(engine._ltc_chunk(5 * SR, 1000) != 0.0)  # noqa: SLF001
    assert engine._mtc_tc_source_key(5.0) == ("none",)  # noqa: SLF001

    # MTC sends nothing at/after the exact end.
    port = _FakePort()
    per_step, _ = _run_mtc_steps(engine, port, 4.8, 5.1)
    for pos, fulls, qf in per_step:
        if pos >= 5.0:
            assert not fulls and not qf, f"MTC after clip end at pos {pos}"


def test_adjacent_exact_boundary_belongs_to_b_in_all_layers() -> None:
    """A = [1.0, 3.0), B = [3.0, 5.0): the shared boundary 3.0 is B's in the
    domain mapping, the LTC audio, and the MTC source key."""
    engine = _make_engine(None, mtc=True)
    song = _clip_song(clips=[
        (1.0, 2.0, "01:00:00:00"),
        (3.0, 2.0, "01:10:00:00"),
    ])
    _attach_clip_song(engine, song)
    from cueplayer.domain.ltc_clips import clip_at_position, ltc_timecode_at

    clip_a, clip_b = song.ltc_clips
    assert clip_at_position(song.ltc_clips, 3.0) is clip_b
    assert ltc_timecode_at(song.ltc_clips, FPS, 3.0) == Timecode(1, 10, 0, 0)
    assert _tc_close(
        _decode(engine._ltc_chunk(3 * SR, SR)), Timecode(1, 10, 0, 0)  # noqa: SLF001
    )
    assert engine._mtc_tc_source_key(3.0) == ("clip", clip_b.id)  # noqa: SLF001
    # And the frame before the boundary is still A.
    just_before = 3.0 - 1.0 / FPS
    assert clip_at_position(song.ltc_clips, just_before) is clip_a
    assert engine._mtc_tc_source_key(just_before) == ("clip", clip_a.id)  # noqa: SLF001


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
