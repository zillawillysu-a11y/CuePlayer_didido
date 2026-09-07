"""LTC clip PCM builder lifecycle: cancellation, dedup, incremental publish.

These tests prove the structural guarantees that keep the PortAudio callback
starved-free while a song has LTC clips:

- at most one in-flight builder job (no stacked duplicates);
- identical in-flight requests are suppressed;
- stale builds (edit / song switch) stop at the next clip boundary;
- stale results are never published;
- the gap/active callback path is identically cheap whether the builder is
  idle or actively generating (A/B diagnostic for the playback-stall root
  cause): the callback never waits on, or is gated by, the builder.

No wall-clock assertions: builder work is gated with threading.Event so the
tests are deterministic regardless of machine speed.
"""

from __future__ import annotations

import threading
import time

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.diagnostics import perf as perf_diag
from cueplayer.domain.ltc_clips import add_ltc_clip
from cueplayer.domain.models import AudioOutputSettings, Song
from cueplayer.playback import audio_engine as eng_mod
from cueplayer.timecode.ltc import generate_ltc_pcm
from cueplayer.timecode.ltc_decode import decode_ltc_timecode
from cueplayer.timecode.smpte import Timecode

SR = 48000
FPS = 30.0


@pytest.fixture(autouse=True)
def _fake_devices_and_perf(monkeypatch):
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
    perf_diag.clear()
    perf_diag.set_enabled(True)
    yield
    perf_diag.set_enabled(False)
    perf_diag.clear()


def _counters() -> dict:
    return perf_diag.snapshot()["counters"]


def _perf_attr(name: str):
    return perf_diag.snapshot()["attrs"].get(name)


def _make_engine() -> eng_mod.AudioEngine:
    engine = eng_mod.AudioEngine()
    engine.apply_audio_settings(
        AudioOutputSettings(
            output_device_name="Test",
            ltc_enabled=True,
            ltc_source="generator",
            ltc_gain=1.0,
            ltc_channels=[2],
        )
    )
    return engine


def _clip_song(*, duration: float = 12.0, clips: tuple = ()) -> Song:
    song = Song(id="song1", name="Clip Song", duration_seconds=duration,
                start_timecode="01:00:00:00")
    for (start, dur, tc) in clips:
        add_ltc_clip(song, timeline_start_seconds=start, duration_seconds=dur,
                     start_timecode=tc)
    return song


def _install_gated_generator(monkeypatch, gate: threading.Event,
                             calls: list, *, gate_clips: int = 1) -> None:
    """Replace generate_ltc_pcm with a spy that blocks on ``gate`` while the
    first ``gate_clips`` clips are being generated (0 = never block)."""
    monkeypatch.setattr(
        eng_mod,
        "generate_ltc_pcm",
        lambda dur, sr, tc, fps, *, amplitude=0.9, drop_frame=False: (
            calls.append(str(tc)),
            (gate.wait(10) if len(calls) <= gate_clips else None),
            generate_ltc_pcm(dur, sr, tc, fps, amplitude=amplitude,
                             drop_frame=drop_frame),
        )[2],
    )


def _wait_for_call_count(calls: list, count: int, timeout_s: float = 5.0) -> bool:
    """Bounded state wait: the gated builder MUST reach this call count
    (the gate keeps it parked there). This awaits an inevitable state, not a
    wall-clock instant."""
    import time as _time
    deadline = _time.monotonic() + timeout_s
    while len(calls) < count:
        if _time.monotonic() > deadline:
            return False
        _time.sleep(0.001)
    return len(calls) >= count


def _install_generator_raise_spy(monkeypatch, calls: list) -> None:
    """Generator that explodes if called (use only when no builder is active)."""
    monkeypatch.setattr(
        eng_mod,
        "generate_ltc_pcm",
        lambda *a, **k: calls.append(("called", a, k))
        or (_ for _ in ()).throw(AssertionError("callback must not generate LTC")),
    )


def _install_generator_record_delegate(monkeypatch, calls: list) -> None:
    """Generator spy that records and delegates (safe while a builder runs)."""
    monkeypatch.setattr(
        eng_mod,
        "generate_ltc_pcm",
        lambda dur, sr, tc, fps, *, amplitude=0.9, drop_frame=False: (
            calls.append(str(tc)),
            generate_ltc_pcm(dur, sr, tc, fps, amplitude=amplitude,
                             drop_frame=drop_frame),
        )[1],
    )


def _install_cursor_raise_spy(monkeypatch, calls: list) -> None:
    monkeypatch.setattr(
        eng_mod,
        "LtcPlaybackCursor",
        lambda *a, **k: (calls.append(1),)[0]
        or (_ for _ in ()).throw(AssertionError("gap must not build a cursor")),
    )


def _wait_clip_cache(engine, timeout: float = 10.0) -> None:
    fut = engine._ltc_clip_cache_future  # noqa: SLF001
    if fut is not None:
        fut.result(timeout=timeout)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if (
            engine._ltc_clip_cache_key is not None
            and len(engine._ltc_clip_pcm) >= len(engine._ltc_clip_intervals)
        ):
            return
        time.sleep(0.01)
    raise TimeoutError("clip PCM cache did not complete")


def _wait_all_jobs(engine, timeout: float = 15.0) -> None:
    """Wait until the builder slot is clear (every submitted job finished)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if engine._ltc_clip_inflight is None:  # noqa: SLF001
            return
        time.sleep(0.01)
    raise TimeoutError("builder jobs did not finish")


def _tc_close(tc: Timecode | None, expected: Timecode, tol_frames: int = 2) -> bool:
    if tc is None:
        return False
    return abs(tc.total_frames(FPS) - expected.total_frames(FPS)) <= tol_frames


# --- Job lifecycle ----------------------------------------------------------


def test_first_ensure_submits_one_job() -> None:
    engine = _make_engine()
    song = _clip_song(clips=[(2.0, 3.0, "01:00:00:00")])
    engine.set_song_timebase(song.start_timecode, song.fps)
    engine.set_song(song)

    engine._ensure_clip_ltc_cache()  # noqa: SLF001
    c = _counters()
    assert c["audio.ltc_clip.builder_job_started"] == 1
    assert _perf_attr("audio.ltc_clip.builder_active_jobs") == 1

    _wait_clip_cache(engine)
    c = _counters()
    assert c["audio.ltc_clip.builder_job_completed"] == 1
    assert c.get("audio.ltc_clip.builder_job_cancelled", 0) == 0
    assert _perf_attr("audio.ltc_clip.builder_active_jobs") == 0
    assert engine._ltc_clip_cache_key == engine._clip_ltc_cache_key()
    assert len(engine._ltc_clip_pcm) == len(engine._ltc_clip_intervals)
    engine.publish_audio_continuity_to_perf()
    events = _perf_attr("audio.ltc_clip.builder_event_ring")
    builder_events = [event for event in events if event["kind"].startswith("builder_")]
    assert [event["kind"] for event in builder_events] == [
        "builder_job_started",
        "builder_clip_generated",
        "builder_job_completed",
    ]
    assert builder_events[0]["monotonic_s"] <= builder_events[-1]["monotonic_s"]
    assert builder_events[-1]["published"] == 1
    # Report surface: builder metrics must appear in the PERF report text.
    report = perf_diag.report_text()
    assert "audio.ltc_clip.builder_job_started" in report
    assert "audio.ltc_clip.builder_total_ms" in report


def test_duplicate_builder_request_suppressed() -> None:
    engine = _make_engine()
    song = _clip_song(clips=[(2.0, 3.0, "01:00:00:00")])
    engine.set_song_timebase(song.start_timecode, song.fps)
    engine.set_song(song)

    engine._ensure_clip_ltc_cache()  # noqa: SLF001 — first build
    engine._ensure_clip_ltc_cache()  # noqa: SLF001 — identical in-flight: suppressed
    engine._ensure_clip_ltc_cache()  # noqa: SLF001 — still in-flight: suppressed
    c = _counters()
    assert c["audio.ltc_clip.builder_job_started"] == 1
    assert c["audio.ltc_clip.builder_duplicate_suppressed"] == 2
    assert _perf_attr("audio.ltc_clip.builder_active_jobs") == 1

    _wait_clip_cache(engine)
    engine._ensure_clip_ltc_cache()  # noqa: SLF001 — ready: no new job at all
    c = _counters()
    assert c["audio.ltc_clip.builder_job_started"] == 1
    assert c["audio.ltc_clip.builder_job_completed"] == 1


def test_only_one_builder_active_no_stacked_duplicate(monkeypatch) -> None:
    gate = threading.Event()
    calls: list = []
    _install_gated_generator(monkeypatch, gate, calls)

    engine = _make_engine()
    song = _clip_song(clips=[
        (1.0, 2.0, "01:00:00:00"),
        (5.0, 2.0, "02:00:00:00"),
    ])
    engine.set_song_timebase(song.start_timecode, song.fps)
    engine.set_song(song)
    engine._ensure_clip_ltc_cache()  # noqa: SLF001 — build #1 (blocks on clip 1)

    # Edit a clip while build #1 is in flight (UI edit flow): invalidation +
    # a new build must queue exactly ONE successor, never a stacked copy of
    # the in-flight job.
    song.ltc_clips[0].duration_seconds = 3.0
    song.ltc_clips = sorted(song.ltc_clips, key=lambda c: c.timeline_start_seconds)
    engine.refresh_song_ltc_routing()
    c = _counters()
    assert c["audio.ltc_clip.builder_job_started"] == 2
    assert c["audio.ltc_clip.builder_duplicate_suppressed"] >= 1
    assert _perf_attr("audio.ltc_clip.builder_active_jobs") == 1
    assert engine._ltc_clip_inflight is not None  # noqa: SLF001

    gate.set()
    _wait_all_jobs(engine)
    c = _counters()
    assert c["audio.ltc_clip.builder_job_completed"] == 1
    assert c["audio.ltc_clip.builder_job_cancelled"] == 1
    assert _perf_attr("audio.ltc_clip.builder_active_jobs") == 0
    assert engine._ltc_clip_inflight is None  # noqa: SLF001
    # The published cache is the NEW key's data, fully present.
    assert engine._ltc_clip_cache_key == engine._clip_ltc_cache_key()
    assert len(engine._ltc_clip_pcm) == len(engine._ltc_clip_intervals)
    # The stale build generated at most its first clip before bailing.
    assert len(calls) == 3  # 1 (stale, bailed) + 2 (current build)


def test_stale_builder_result_ignored(monkeypatch) -> None:
    gate = threading.Event()
    calls: list = []
    _install_gated_generator(monkeypatch, gate, calls)

    engine = _make_engine()
    song = _clip_song(clips=[(1.0, 2.0, "01:00:00:00"), (5.0, 2.0, "02:00:00:00")])
    engine.set_song_timebase(song.start_timecode, song.fps)
    engine.set_song(song)
    engine._ensure_clip_ltc_cache()  # noqa: SLF001 — build for the OLD key
    old_key = engine._clip_ltc_cache_key()

    song.ltc_clips[0].duration_seconds = 3.0
    song.ltc_clips = sorted(song.ltc_clips, key=lambda c: c.timeline_start_seconds)
    engine.refresh_song_ltc_routing()
    new_key = engine._clip_ltc_cache_key()
    assert new_key != old_key

    gate.set()
    _wait_all_jobs(engine)
    assert engine._ltc_clip_cache_key == new_key
    assert engine._ltc_clip_cache_key != old_key
    # The stale build's first clip (2.0 s) must NOT be at index 0 — the
    # published PCM is the new clip's 3.0 s rendering.
    assert len(engine._ltc_clip_pcm) == len(engine._ltc_clip_intervals)
    assert engine._ltc_clip_pcm[0].size == int(round(3.0 * SR))


# --- Callback / builder independence (A/B diagnostic) ------------------------


def test_gap_callback_never_waits_builder(monkeypatch) -> None:
    """Case B: builder actively generating; a gap buffer must stay silence
    without touching the builder (no wait, no cursor, no generation)."""
    gate = threading.Event()
    calls: list = []
    # gate_clips=2 parks the builder deterministically at the clip-1 gate.
    _install_gated_generator(monkeypatch, gate, calls, gate_clips=2)

    engine = _make_engine()
    song = _clip_song(clips=[
        (1.0, 2.0, "01:00:00:00"),
        (5.0, 2.0, "02:00:00:00"),
    ])
    engine.set_song_timebase(song.start_timecode, song.fps)
    engine.set_song(song)
    engine._ensure_clip_ltc_cache()  # noqa: SLF001 — in-flight (blocked)
    assert engine._ltc_clip_inflight is not None  # noqa: SLF001

    # Park the builder at the clip-1 gate (bounded state wait). From here
    # on, the callback is the only possible source of a generation.
    assert _wait_for_call_count(calls, 1)

    # Recording spy (safe: the worker is already parked); the callback
    # itself must add zero generations and zero cursors.
    _install_generator_record_delegate(monkeypatch, calls)
    cursor_spy: list = []
    _install_cursor_raise_spy(monkeypatch, cursor_spy)

    before = len(calls)
    chunk = engine._ltc_chunk(3 * SR, 512)  # noqa: SLF001 — inside the gap
    assert not np.any(chunk != 0.0)
    diag = engine.ltc_clip_callback_diagnostics()
    assert diag["gap_fast_path_count"] >= 1
    assert diag["active_path_count"] == 0
    assert len(calls) == before  # callback generated nothing
    assert cursor_spy == []
    # The builder is still in flight — the callback neither waited for it
    # nor finished it.
    assert engine._ltc_clip_inflight is not None  # noqa: SLF001
    gate.set()
    _wait_all_jobs(engine)


def test_cache_pending_gap_remains_silence() -> None:
    engine = _make_engine()
    song = _clip_song(clips=[(2.0, 3.0, "01:00:00:00")])
    engine.set_song_timebase(song.start_timecode, song.fps)
    engine.set_song(song)
    # No ensure yet: cache pending, pcm empty — gap must stay silent.
    assert engine._ltc_clip_pcm == {}  # noqa: SLF001
    assert not np.any(engine._ltc_chunk(0, SR) != 0.0)  # noqa: SLF001
    assert not np.any(engine._ltc_chunk(6 * SR, 1000) != 0.0)  # noqa: SLF001


def test_cache_pending_active_clip_bounded_fallback(monkeypatch) -> None:
    """Pending cache + playhead inside a clip: bounded fallback renders the
    correct TC (existing semantics), counted as cache_miss."""
    engine = _make_engine()
    song = _clip_song(clips=[(2.0, 3.0, "01:00:00:00")])
    engine.set_song_timebase(song.start_timecode, song.fps)
    engine.set_song(song)
    assert engine._ltc_clip_pcm == {}  # noqa: SLF001 — nothing published yet

    chunk = engine._ltc_chunk(2 * SR, 2 * SR)  # noqa: SLF001
    assert np.any(chunk != 0.0)
    assert _tc_close(decode_ltc_timecode(chunk, SR, FPS), Timecode(1, 0, 0, 0))
    diag = engine.ltc_clip_callback_diagnostics()
    assert diag["active_path_count"] >= 1
    assert diag["cache_miss"] >= 1
    assert diag["cache_hit"] == 0


def test_mixed_ready_and_pending_clips(monkeypatch) -> None:
    """Incremental publish: as soon as clip 1 is ready it is served from the
    cache while clip 2 still uses the bounded fallback."""
    gate = threading.Event()
    calls: list = []
    _install_gated_generator(monkeypatch, gate, calls, gate_clips=1)

    engine = _make_engine()
    song = _clip_song(clips=[
        (1.0, 2.0, "01:00:00:00"),
        (5.0, 2.0, "02:00:00:00"),
    ])
    engine.set_song_timebase(song.start_timecode, song.fps)
    engine.set_song(song)
    engine._ensure_clip_ltc_cache()  # noqa: SLF001 — blocked inside clip 1

    # Clip 2 is pending → fallback (its TC must still be correct).
    chunk = engine._ltc_chunk(int(5.5 * SR), SR)  # noqa: SLF001
    assert _tc_close(decode_ltc_timecode(chunk, SR, FPS), Timecode(2, 0, 0, 15))

    gate.set()
    _wait_clip_cache(engine)
    # Both clips ready: exact slices of the published PCM, no generation.
    spy_calls: list = []
    _install_generator_raise_spy(monkeypatch, spy_calls)
    pcm0 = engine._ltc_clip_pcm[0]  # noqa: SLF001
    chunk = engine._ltc_chunk(int(1.5 * SR), SR)  # noqa: SLF001
    offset = int(1.5 * SR) - int(1.0 * SR)
    assert np.array_equal(chunk, pcm0[offset : offset + SR])
    diag = engine.ltc_clip_callback_diagnostics()
    assert diag["cache_hit"] >= 1
    assert spy_calls == []


def test_ready_cache_uses_cached_pcm(monkeypatch) -> None:
    """Case A: cache already ready — the active path is a pure slice with no
    generation work at all (the cheap path the gap fast path was added for)."""
    engine = _make_engine()
    song = _clip_song(clips=[(2.0, 3.0, "01:00:00:00")])
    engine.set_song_timebase(song.start_timecode, song.fps)
    engine.set_song(song)
    engine._ensure_clip_ltc_cache()  # noqa: SLF001
    _wait_clip_cache(engine)

    spy_calls: list = []
    _install_generator_raise_spy(monkeypatch, spy_calls)
    pcm = engine._ltc_clip_pcm[0]  # noqa: SLF001
    ref = generate_ltc_pcm(3.0, SR, "01:00:00:00", FPS, amplitude=1.0)
    assert np.array_equal(pcm, ref)

    chunk = engine._ltc_chunk(2 * SR, SR)  # noqa: SLF001
    assert np.array_equal(chunk, pcm[:SR])
    assert _tc_close(decode_ltc_timecode(chunk * 8, SR, FPS), Timecode(1, 0, 0, 0))
    diag = engine.ltc_clip_callback_diagnostics()
    assert diag["cache_hit"] >= 1
    assert diag["cache_miss"] == 0
    assert spy_calls == []


def test_gap_path_identical_with_or_without_builder(monkeypatch) -> None:
    """A/B structural equivalence: the gap callback path performs the same
    zero-work fast path whether the builder is idle+ready (A) or actively
    generating (B) — i.e. the callback cost does not depend on builder state."""
    # Case A — cache ready, builder idle (no gating).
    engine_a = _make_engine()
    song_a = _clip_song(clips=[(1.0, 2.0, "01:00:00:00"), (5.0, 2.0, "02:00:00:00")])
    engine_a.set_song_timebase(song_a.start_timecode, song_a.fps)
    engine_a.set_song(song_a)
    engine_a._ensure_clip_ltc_cache()  # noqa: SLF001
    _wait_clip_cache(engine_a)

    # Case B — builder in flight (blocked), same gap. Both engines must be
    # constructed BEFORE any spy patches (construction itself builds a
    # full-track LtcPlaybackCursor).
    gate = threading.Event()
    calls_b: list = []
    _install_gated_generator(monkeypatch, gate, calls_b, gate_clips=2)
    engine_b = _make_engine()
    song_b = _clip_song(clips=[(1.0, 2.0, "01:00:00:00"), (5.0, 2.0, "02:00:00:00")])
    engine_b.set_song_timebase(song_b.start_timecode, song_b.fps)
    engine_b.set_song(song_b)
    engine_b._ensure_clip_ltc_cache()  # noqa: SLF001 — in-flight
    assert engine_b._ltc_clip_inflight is not None  # noqa: SLF001
    assert _wait_for_call_count(calls_b, 1)  # builder parked at clip-1 gate

    # Now install spies: the gap path must generate nothing and build no
    # cursor in either case.
    cursor_spy: list = []
    _install_cursor_raise_spy(monkeypatch, cursor_spy)

    chunk_a = engine_a._ltc_chunk(3 * SR, 512)  # noqa: SLF001
    assert not np.any(chunk_a != 0.0)
    diag_a = engine_a.ltc_clip_callback_diagnostics()
    assert diag_a["gap_fast_path_count"] >= 1
    assert diag_a["active_path_count"] == 0

    before = len(calls_b)
    chunk_b = engine_b._ltc_chunk(3 * SR, 512)  # noqa: SLF001
    assert not np.any(chunk_b != 0.0)
    diag_b = engine_b.ltc_clip_callback_diagnostics()
    assert diag_b["gap_fast_path_count"] >= 1
    assert diag_b["active_path_count"] == 0
    assert len(calls_b) == before  # callback generated nothing
    assert cursor_spy == []  # no cursor in either case
    assert engine_b._ltc_clip_inflight is not None  # noqa: SLF001
    gate.set()
    _wait_all_jobs(engine_b)


def test_clip_mode_skips_file_ltc_detect_scan() -> None:
    """clip_generator never consults the file stripe, so loading a stereo
    buffer must not kick the background LTC auto-detect scan."""
    from cueplayer.media.audio_loader import AudioBuffer

    engine = _make_engine()
    song = _clip_song(clips=[(2.0, 3.0, "01:00:00:00")])
    engine.set_song_timebase(song.start_timecode, song.fps)
    engine.set_song(song)
    music = np.ones((SR * 4, 2), dtype=np.float32) * 0.1
    buf = AudioBuffer(path=None, sample_rate=SR, samples=music,
                      mono=music[:, 0], peak_levels=[])
    engine.set_buffer(buf)
    engine._refresh_ltc_detection()  # noqa: SLF001
    assert engine._ltc_detect_ran  # noqa: SLF001
    assert engine._detected_ltc_channel is None  # noqa: SLF001
    assert not engine._ltc_detect_inflight  # noqa: SLF001


# --- Invalidation scope ------------------------------------------------------


def test_clip_invalidation_touches_only_clip_state() -> None:
    """_invalidate_clip_ltc_cache must not disturb the full-track PCM, the
    playback samples, or the MTC state — only the clip cache."""
    engine = _make_engine()
    song = _clip_song(clips=[(2.0, 3.0, "01:00:00:00")])
    engine.set_song_timebase(song.start_timecode, song.fps)
    engine.set_song(song)
    engine._ensure_clip_ltc_cache()  # noqa: SLF001
    _wait_clip_cache(engine)

    sentinel_full = np.ones(8, dtype=np.float32)
    sentinel_samples = np.ones((16, 2), dtype=np.float32)
    engine._ltc_pcm = sentinel_full  # noqa: SLF001
    engine._ltc_cache_key = ("sentinel",)  # noqa: SLF001
    engine._playback_samples = sentinel_samples  # noqa: SLF001
    engine._playback_cache_key = ("sentinel",)  # noqa: SLF001
    before_rebuilds = _counters().get("audio.ltc_clip.cache_rebuild_count", 0)

    engine._invalidate_clip_ltc_cache()  # noqa: SLF001

    assert engine._ltc_pcm is sentinel_full  # noqa: SLF001
    assert engine._ltc_cache_key == ("sentinel",)  # noqa: SLF001
    assert engine._playback_samples is sentinel_samples  # noqa: SLF001
    assert engine._ltc_clip_pcm == {}  # noqa: SLF001
    assert engine._ltc_clip_cache_key is None  # noqa: SLF001
    assert engine._ltc_clip_inflight is None  # noqa: SLF001
    assert _counters()["audio.ltc_clip.cache_rebuild_count"] == before_rebuilds + 1


def test_clip_edit_invalidates_only_necessary_cache() -> None:
    """Editing one clip drops the clip PCM cache (rebuild needed) but keeps
    the interval snapshot current and leaves other caches untouched."""
    engine = _make_engine()
    song = _clip_song(clips=[
        (1.0, 2.0, "01:00:00:00"),
        (5.0, 2.0, "02:00:00:00"),
    ])
    engine.set_song_timebase(song.start_timecode, song.fps)
    engine.set_song(song)
    engine._ensure_clip_ltc_cache()  # noqa: SLF001
    _wait_clip_cache(engine)
    old_gen = engine._ltc_clip_generation  # noqa: SLF001

    song.ltc_clips[0].duration_seconds = 3.0
    song.ltc_clips = sorted(song.ltc_clips, key=lambda c: c.timeline_start_seconds)
    engine._prepare_clip_ltc_intervals()  # noqa: SLF001
    engine._invalidate_clip_ltc_cache()  # noqa: SLF001

    # Intervals reflect the edit; cache is fully dropped; generation bumped.
    assert engine._ltc_clip_intervals[0] == (  # noqa: SLF001
        int(1.0 * SR), int(4.0 * SR), "01:00:00:00"
    )
    assert engine._ltc_clip_pcm == {}  # noqa: SLF001
    assert engine._ltc_clip_cache_key is None  # noqa: SLF001
    assert engine._ltc_clip_generation == old_gen + 1  # noqa: SLF001


def test_song_switch_cancels_previous_generation(monkeypatch) -> None:
    """Switching songs while a build is in flight: the stale build stops at
    the next clip boundary and never publishes song-A data into song-B's
    cache."""
    gate = threading.Event()
    calls: list = []
    _install_gated_generator(monkeypatch, gate, calls, gate_clips=1)

    engine = _make_engine()
    song_a = _clip_song(clips=[
        (1.0, 2.0, "01:00:00:00"),
        (5.0, 2.0, "03:00:00:00"),
    ])
    engine.set_song_timebase(song_a.start_timecode, song_a.fps)
    engine.set_song(song_a)
    engine._ensure_clip_ltc_cache()  # noqa: SLF001 — song-A build (blocked, clip 1)
    key_a = engine._clip_ltc_cache_key()

    song_b = _clip_song(clips=[(2.0, 2.0, "02:00:00:00")])
    engine.set_song(song_b)  # invalidate; stale build still blocked
    key_b = engine._clip_ltc_cache_key()
    assert key_a != key_b
    engine._ensure_clip_ltc_cache()  # noqa: SLF001 — song-B build (queued)

    gate.set()
    _wait_all_jobs(engine)

    c = _counters()
    assert c["audio.ltc_clip.builder_job_cancelled"] >= 1
    assert c["audio.ltc_clip.builder_job_completed"] == 1
    assert engine._ltc_clip_cache_key == key_b
    assert len(engine._ltc_clip_pcm) == 1
    # Song-A's first clip was 2.0 s; song-B's clip is also 2.0 s, so verify
    # by TC content: the published PCM must decode to 02:00:00:00, not the
    # stale song-A 01:00:00:00 start.
    pcm = engine._ltc_clip_pcm[0]  # noqa: SLF001
    assert _tc_close(decode_ltc_timecode(pcm[: SR], SR, FPS), Timecode(2, 0, 0, 0))
    # Stale build generated only its first clip before the token stopped it:
    # 1 (song-A, stale) + 1 (song-B) = 2 total generations.
    assert len(calls) == 2
