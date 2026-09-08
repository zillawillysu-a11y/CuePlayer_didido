"""Regression: MTC/MIDI-cue scheduling must not depend on the Qt GUI event loop.

Root cause (see .ai/handoffs): on Windows, dragging or press-holding a
top-level window's title bar (main window or Clean Video Output) enters a
native modal move/resize loop that suspends that thread's Qt event loop —
including every QTimer on it — for as long as the interaction lasts. MTC
quarter-frame output used to be paced entirely by a GUI `QTimer`
(`AudioEngine._mtc_timer`), so real MIDI Timecode output froze along with the
UI for the whole drag, even though the actual PortAudio audio callback (music
+ audio LTC) and the Playback Engine's sample-accurate position kept running
on their own thread the whole time.

This test proves the fix: MTC ticking now runs on a dedicated daemon thread
(`AudioEngine._start_mtc_thread` / `_mtc_thread_loop`) paced by a wall-clock
wait, so it keeps sending quarter frames purely from wall-clock time elapsing
— with no Qt event loop processing at all — and does not burst-resend stale
frames once resumed, and stops cleanly on pause/shutdown.
"""

from __future__ import annotations

import threading
import time

import pytest

from cueplayer.diagnostics import perf as perf_diag
from cueplayer.playback import audio_engine as audio_engine_module
from cueplayer.playback.audio_engine import AudioEngine


class _Port:
    def __init__(self) -> None:
        self.messages: list = []

    def send(self, message) -> None:
        self.messages.append(message)

    def close(self) -> None:
        pass


def test_mtc_thread_keeps_ticking_with_zero_qt_event_loop_processing(monkeypatch):
    """No QCoreApplication.processEvents() call anywhere in this test.

    If MTC scheduling were still driven by a GUI QTimer, none of its
    quarter-frame messages could ever be sent here, because a QTimer only
    fires from inside the Qt event loop and this test never runs one.
    """
    engine = AudioEngine()
    try:
        engine._mtc._port = _Port()
        engine._mtc._enabled = True
        engine._playing = True

        # Simulate the Playback Engine's real clock advancing in wall time,
        # exactly as the PortAudio callback thread does independently of the
        # GUI thread — this stands in for "audio keeps playing" during a
        # title-bar drag.
        t0 = time.monotonic()
        monkeypatch.setattr(
            engine,
            "_mtc_clock_position",
            lambda: (time.monotonic() - t0, 0.0, 0.0),
        )

        engine._mtc.on_play(0.0)
        engine._mtc._port.messages.clear()

        engine._start_mtc_thread()
        try:
            # Hold for a bit of wall-clock time with *no* Qt event loop
            # activity at all (this thread does not call processEvents()).
            time.sleep(0.25)
        finally:
            engine._stop_mtc_thread()

        messages = engine._mtc._port.messages
        # 4 quarter frames per timecode frame at 30fps => 120 QF/sec. Over
        # ~0.25s we expect roughly 30, allow generous slack for CI jitter,
        # but zero would mean the old GUI-QTimer-only behavior regressed.
        quarter_frames = [m for m in messages if m.type == "quarter_frame"]
        assert len(quarter_frames) > 5, (
            "MTC produced no output while the GUI event loop was never "
            "pumped — scheduling has regressed to depending on a QTimer."
        )

        # Thread must actually stop: no more messages arrive after _stop.
        engine._mtc._port.messages.clear()
        time.sleep(0.05)
        assert engine._mtc._port.messages == []
        assert engine._mtc_thread is None
    finally:
        engine._playing = False
        engine.shutdown_midi_outputs()


def test_mtc_thread_resume_after_stall_does_not_burst_stale_frames():
    """A long gap between ticks re-anchors instead of dumping a backlog."""
    engine = AudioEngine()
    try:
        engine._mtc._port = _Port()
        engine._mtc._enabled = True
        engine._playing = True
        engine._mtc.on_play(0.0)
        engine._mtc._port.messages.clear()

        # Simulate a long GUI stall: the position "jumps" far ahead because
        # real audio/playback time kept moving while nothing ticked MTC.
        engine._mtc.tick(100.0)

        messages = engine._mtc._port.messages
        # Bounded re-anchor (one full frame + at most one QF group), never a
        # multi-second backlog of quarter frames replayed all at once.
        assert len(messages) <= 9
    finally:
        engine._playing = False
        engine.shutdown_midi_outputs()


def test_mtc_clock_read_does_not_wait_for_audio_mix_lock():
    """MTC consumes the published sample-clock snapshot without lock contention."""
    engine = AudioEngine()
    done = threading.Event()
    result: list[tuple[float, float, float]] = []
    try:
        engine._playing = True
        with engine._lock:
            engine._stamp_write_head_unlocked()
            worker = threading.Thread(
                target=lambda: (result.append(engine._mtc_clock_position()), done.set()),
                daemon=True,
            )
            worker.start()
            assert done.wait(0.25), "MTC clock read blocked on AudioEngine._lock"
        worker.join(timeout=0.25)
        assert result
        assert result[0][0] >= 0.0
    finally:
        engine._playing = False
        engine.shutdown_midi_outputs()


def test_mtc_clock_clamps_interpolation_regression_but_allows_seek(monkeypatch):
    """An early callback stamp is jitter; a new transport generation is a seek."""
    engine = AudioEngine()
    mono = {"now": 10.010}
    monkeypatch.setattr(audio_engine_module.time, "monotonic", lambda: mono["now"])
    try:
        engine._playing = True
        with engine._lock:
            engine._position_frame = 4800
            engine._pos_epoch_frame = 4800
            engine._pos_epoch_mono = 10.000
            engine._publish_mtc_clock_snapshot_unlocked()
        first, _, first_regression = engine._mtc_clock_position()
        assert first == pytest.approx(0.110)
        assert first_regression == 0.0

        # The next callback arrives early: its exact write head plus elapsed
        # interpolation is behind the position already observed by MTC.
        mono["now"] = 10.011
        with engine._lock:
            engine._position_frame = 5040
            engine._pos_epoch_frame = 5040
            engine._pos_epoch_mono = 10.011
            engine._publish_mtc_clock_snapshot_unlocked()
        clamped, _, regression = engine._mtc_clock_position()
        assert clamped == pytest.approx(first)
        assert regression == pytest.approx(0.005)

        # A real backward seek increments the generation and must not clamp.
        with engine._lock:
            engine._diagnostic_transport_generation += 1
            engine._position_frame = 960
            engine._pos_epoch_frame = 960
            engine._pos_epoch_mono = 10.011
            engine._publish_mtc_clock_snapshot_unlocked()
        sought, _, seek_regression = engine._mtc_clock_position()
        assert sought == pytest.approx(0.020)
        assert seek_regression == 0.0
    finally:
        engine._playing = False
        engine.shutdown_midi_outputs()


def test_mtc_clock_regression_does_not_emit_full_frame_reanchor(monkeypatch):
    """Callback interpolation jitter must not masquerade as a backward seek."""
    engine = AudioEngine()
    mono = {"now": 10.010}
    monkeypatch.setattr(audio_engine_module.time, "monotonic", lambda: mono["now"])
    perf_diag.set_enabled(True)
    perf_diag.clear()
    try:
        port = _Port()
        engine._mtc._port = port
        engine._mtc._enabled = True
        engine._playing = True
        engine._mtc.on_play(0.100)
        port.messages.clear()

        with engine._lock:
            engine._position_frame = 4800
            engine._pos_epoch_frame = 4800
            engine._pos_epoch_mono = 10.000
            engine._publish_mtc_clock_snapshot_unlocked()
        engine._mtc_tick()
        port.messages.clear()

        mono["now"] = 10.011
        with engine._lock:
            engine._position_frame = 5040
            engine._pos_epoch_frame = 5040
            engine._pos_epoch_mono = 10.011
            engine._publish_mtc_clock_snapshot_unlocked()
        engine._mtc_tick()

        assert not any(message.type == "sysex" for message in port.messages)
        snap = perf_diag.snapshot()
        assert snap["counters"]["mtc.clock_regression_clamps"] == 1
        assert snap["counters"].get("mtc.backward_reanchors", 0) == 0
        assert snap["spans"]["mtc.clock_regression_ms"]["max_ms"] == pytest.approx(5.0)
    finally:
        perf_diag.set_enabled(False)
        perf_diag.clear()
        engine._playing = False
        engine.shutdown_midi_outputs()


class _FakeStop:
    def __init__(self, clock, *, stop_after: int, oversleep: float = 0.0) -> None:
        self.clock = clock
        self.stop_after = stop_after
        self.oversleep = oversleep
        self.waits: list[float] = []
        self.was_set = False

    def set(self) -> None:
        self.was_set = True

    def wait(self, timeout: float) -> bool:
        self.waits.append(timeout)
        self.clock[0] += timeout + self.oversleep
        return len(self.waits) >= self.stop_after


def test_mtc_scheduler_uses_absolute_deadlines(monkeypatch):
    """Tick work is absorbed by the next 4 ms period instead of adding drift."""
    engine = AudioEngine()
    clock = [0.0]
    stop = _FakeStop(clock, stop_after=4)
    monkeypatch.setattr(audio_engine_module.time, "monotonic", lambda: clock[0])
    engine._mtc_thread_stop = stop
    engine._mtc_tick = lambda: clock.__setitem__(0, clock[0] + 0.003)

    engine._mtc_thread_loop()

    assert stop.waits[0] == pytest.approx(0.004)
    assert stop.waits[1:3] == pytest.approx([0.001, 0.001])


def test_mtc_scheduler_records_wakeup_lateness_and_missed_slots(monkeypatch):
    engine = AudioEngine()
    clock = [0.0]
    stop = _FakeStop(clock, stop_after=4, oversleep=0.001)
    monkeypatch.setattr(audio_engine_module.time, "monotonic", lambda: clock[0])
    engine._mtc_thread_stop = stop
    engine._mtc_tick = lambda: clock.__setitem__(0, clock[0] + 0.006)
    perf_diag.set_enabled(True)
    perf_diag.clear()
    try:
        engine._mtc_thread_loop()
        snap = perf_diag.snapshot()
        assert snap["counters"]["mtc.scheduler.wakeups"] == 3
        assert snap["counters"]["mtc.scheduler.missed_wake_slots"] >= 3
        assert snap["spans"]["mtc.scheduler.wakeup_lateness_ms"]["max_ms"] >= 1.0
        assert "MTC sender continuity:" in perf_diag.report_text()
    finally:
        perf_diag.set_enabled(False)
        perf_diag.clear()
