"""Playhead / mark times must not stick to the audio-block millisecond grid."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.media.audio_loader import AudioBuffer
from cueplayer.playback.audio_engine import AudioEngine
from cueplayer.ui.transport_bar import format_time


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _buffer(*, seconds: float = 120.0, sr: int = 48000) -> AudioBuffer:
    frames = int(seconds * sr)
    samples = np.zeros((frames, 2), dtype=np.float32)
    mono = samples[:, 0].copy()
    return AudioBuffer(
        path=Path("tone.wav"),
        sample_rate=sr,
        samples=samples,
        mono=mono,
        peak_levels=[],
    )


def test_seek_uses_round_not_truncation(app: QApplication) -> None:
    engine = AudioEngine()
    engine.set_buffer(_buffer())
    engine.seek(90.227)
    assert engine.raw_position == pytest.approx(90.227, abs=1e-6)


def test_playing_position_interpolates_between_audio_blocks(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = AudioEngine()
    engine.set_buffer(_buffer())
    engine.seek(90.227)

    # Simulate a WASAPI-sized callback landing the write-head, then wall time
    # advancing without another callback — UI time must move off the *.?7 grid.
    with engine._lock:
        engine._playing = True
        engine._position_frame = int(round(90.227 * 48000))
        engine._pos_epoch_frame = engine._position_frame
        engine._pos_epoch_mono = 1000.0

    mono = {"t": 1000.0}

    def _fake_mono() -> float:
        return float(mono["t"])

    monkeypatch.setattr("cueplayer.playback.audio_engine.time.monotonic", _fake_mono)

    first = format_time(engine.raw_position)
    assert first.endswith("7")

    digits: list[str] = []
    for ms in (3, 7, 11, 14, 18, 21, 25, 28):
        mono["t"] = 1000.0 + ms / 1000.0
        digits.append(format_time(engine.raw_position)[-1])

    # Must not be stuck on the seek-point's last millisecond digit.
    assert any(d != "7" for d in digits)
    assert len(set(digits)) >= 3


def test_paused_position_does_not_extrapolate(app: QApplication) -> None:
    engine = AudioEngine()
    engine.set_buffer(_buffer())
    engine.seek(12.345)
    time.sleep(0.02)
    assert engine.raw_position == pytest.approx(12.345, abs=1e-6)
