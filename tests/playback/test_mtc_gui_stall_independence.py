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

import time
import threading

from cueplayer.playback.audio_engine import AudioEngine


class _Port:
    def __init__(self) -> None:
        self.messages: list = []
        self.sent = threading.Event()

    def send(self, message) -> None:
        self.messages.append(message)
        if getattr(message, "type", "") == "quarter_frame":
            self.sent.set()

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
            type(engine),
            "raw_position",
            property(lambda self: time.monotonic() - t0),
        )

        engine._mtc.on_play(0.0)
        engine._mtc._port.messages.clear()

        engine._start_mtc_thread()
        try:
            # A timeout is only a deadlock guard; correctness is synchronized
            # to the first QF send, not to a fragile expected wall-clock count.
            assert engine._mtc._port.sent.wait(timeout=1.0)
        finally:
            engine._stop_mtc_thread()

        messages = engine._mtc._port.messages
        quarter_frames = [m for m in messages if m.type == "quarter_frame"]
        assert quarter_frames, (
            "MTC produced no output while the GUI event loop was never "
            "pumped — scheduling has regressed to depending on a QTimer."
        )

        # _stop joins the generation, so no timing-based quiet-period check is
        # needed to prove that delivery has stopped.
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
