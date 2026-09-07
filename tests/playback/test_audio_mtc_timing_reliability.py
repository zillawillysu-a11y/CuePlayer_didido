"""Audio callback / MTC interaction regressions for backend timing diagnostics."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from cueplayer.diagnostics import perf as perf_diag
from cueplayer.domain.models import AudioOutputSettings
from cueplayer.playback.audio_engine import AudioEngine


class _ProbePort:
    def __init__(self, engine: AudioEngine) -> None:
        self.engine = engine
        self.sent = []
        self.engine_lock_was_free: list[bool] = []

    def send(self, message) -> None:
        acquired = self.engine._lock.acquire(blocking=False)
        self.engine_lock_was_free.append(acquired)
        if acquired:
            self.engine._lock.release()
        self.sent.append(message)

    def close(self) -> None:
        pass


def _arm_mtc(engine: AudioEngine) -> _ProbePort:
    port = _ProbePort(engine)
    engine._mtc._port = port
    engine._mtc._enabled = True
    engine._playing = True
    with engine._lock:
        engine._position_frame = 960
        engine._stamp_write_head_unlocked()
    engine._mtc.on_play(0.0)
    port.sent.clear()
    port.engine_lock_was_free.clear()
    return port


def test_mtc_midi_send_never_holds_audio_callback_lock() -> None:
    engine = AudioEngine()
    try:
        port = _arm_mtc(engine)
        engine._mtc_tick()
        assert port.sent
        assert all(port.engine_lock_was_free)
    finally:
        engine._playing = False
        engine.shutdown_midi_outputs()


def test_mtc_clock_lock_wait_metric_measures_only_lock_acquire(monkeypatch) -> None:
    from cueplayer.playback import audio_engine as module

    now = [20.0]

    class Lock:
        def acquire(self, blocking=True):
            del blocking
            now[0] += 0.003
            return True

        def release(self):
            pass

    engine = AudioEngine()
    engine._lock = Lock()
    engine._playing = False
    monkeypatch.setattr(module.time, "perf_counter", lambda: now[0])
    perf_diag.set_enabled(True)
    try:
        _pos, wait_s = engine._mtc_raw_position()
    finally:
        perf_diag.set_enabled(False)
    assert wait_s == pytest.approx(0.003)


def test_variable_callback_frames_keep_cursor_continuous_with_mtc_enabled() -> None:
    frames = (480, 960, 240, 720)
    positions = []
    for with_mtc in (False, True):
        engine = AudioEngine()
        try:
            engine._playing = True
            engine._playback_rate = 48000
            engine._playback_samples = np.zeros((10000, 2), np.float32)
            if with_mtc:
                _arm_mtc(engine)
                with engine._lock:
                    engine._position_frame = 0
            callback = engine._make_stream_callback(48000)
            for count in frames:
                callback(
                    np.zeros((count, 2), np.float32),
                    count,
                    SimpleNamespace(),
                    0,
                )
                if with_mtc:
                    engine._mtc_tick()
            positions.append(engine._position_frame)
        finally:
            engine._playing = False
            engine.shutdown_midi_outputs()
    assert positions == [sum(frames), sum(frames)]


def test_mtc_send_duration_is_reported() -> None:
    engine = AudioEngine()
    perf_diag.set_enabled(True)
    try:
        _arm_mtc(engine)
        engine._mtc_tick()
        snap = engine._mtc.timing_diagnostics()
        assert snap["send_count"] > 0
        assert snap["send_ms"] >= 0.0
        assert snap["send_max_ms"] >= snap["send_ms"]
    finally:
        perf_diag.set_enabled(False)
        engine._playing = False
        engine.shutdown_midi_outputs()


def test_stream_report_exposes_backend_configuration(monkeypatch) -> None:
    from cueplayer.playback import audio_engine as module

    engine = AudioEngine()
    engine._audio_settings = AudioOutputSettings(
        output_device_name="Focusrite DS",
        output_hostapi="Windows DirectSound",
    )
    engine._device_index = None
    engine._playback_rate = 48000
    engine._output_channel_count = 4
    engine._stream = SimpleNamespace(latency=0.12)
    engine._stream_requested_latency = "low"
    monkeypatch.setattr(
        module, "resolve_output_hostapi", lambda name: name
    )
    snap = engine.audio_stream_diagnostics()
    assert snap == {
        "requested_blocksize": 0,
        "sample_rate": 48000,
        "host_api": "Windows DirectSound",
        "device": "Focusrite DS",
        "device_index": None,
        "dtype": "float32",
        "channels": 4,
        "requested_latency": "low",
        "output_latency": 0.12,
    }
