"""Keep timeline zoom when switching setlist songs."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.media.audio_loader import AudioBuffer, PeakLevel
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _buffer(seconds: float = 20.0, sr: int = 44100) -> AudioBuffer:
    n = int(sr * seconds)
    mono = np.zeros(n, dtype=np.float32)
    mono[:: max(1, sr // 10)] = 0.5
    samples = mono.reshape(-1, 1)
    peaks = PeakLevel(
        samples_per_bucket=max(1, sr // 100),
        mins=mono[:: max(1, sr // 100)].copy(),
        maxs=mono[:: max(1, sr // 100)].copy(),
    )
    return AudioBuffer(
        path=Path("test.wav"),
        sample_rate=sr,
        samples=samples,
        mono=mono,
        peak_levels=[peaks],
    )


def test_set_audio_reset_view_false_keeps_zoom(app: QApplication) -> None:
    widget = TimelineWidget()
    widget.resize(800, 400)
    widget.set_audio(_buffer(30.0), reset_view=True)
    widget.set_zoom(420.0)
    assert widget.pixels_per_second() == pytest.approx(420.0, rel=1e-3)

    widget.set_audio(_buffer(45.0), reset_view=False)
    assert widget.pixels_per_second() == pytest.approx(420.0, rel=1e-3)


def test_set_audio_reset_view_true_uses_default_zoom(app: QApplication) -> None:
    widget = TimelineWidget()
    widget.resize(800, 400)
    widget.set_zoom(420.0)
    widget.set_audio(_buffer(30.0), reset_view=True)
    assert widget.pixels_per_second() == pytest.approx(150.0, rel=1e-3)
