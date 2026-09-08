"""Fit-to-view must not crash at minimum timeline width while playing."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song
from cueplayer.media.audio_loader import AudioBuffer, build_peak_pyramid
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _buffer(seconds: float = 30.0) -> AudioBuffer:
    frames = int(48000 * seconds)
    samples = np.zeros((frames, 2), dtype=np.float32)
    samples[::200, 0] = 0.4
    mono, levels = build_peak_pyramid(samples, 48000)
    return AudioBuffer(
        path=Path("fit_crash.wav"),
        sample_rate=48000,
        samples=samples,
        mono=mono,
        peak_levels=levels,
    )


def test_busy_resize_clamps_header_below_width(app: QApplication) -> None:
    """MainWindow geometry sync used to skip header clamp → header > width."""
    widget = TimelineWidget()
    widget.show()
    widget.resize(400, 300)
    app.processEvents()
    assert widget._header_width == 140

    widget._layout_heights_busy = True
    try:
        widget.resize(160, 300)
        app.processEvents()
    finally:
        widget._layout_heights_busy = False

    assert widget._header_width < widget.width()
    assert widget._view_width() >= 48


def test_fit_to_view_while_playing_at_narrow_width(app: QApplication) -> None:
    widget = TimelineWidget()
    widget.show()
    widget.resize(400, 300)
    app.processEvents()
    widget.set_song(Song.create("Fit"))
    widget.set_audio(_buffer(45.0))
    widget.set_playing(True)
    widget.set_auto_scroll(True)
    widget.set_position(2.0)
    app.processEvents()

    # Simulate min-window timeline: busy resize left header stuck wide.
    widget._header_width = 140
    widget._layout_heights_busy = True
    try:
        widget.resize(170, 280)
        app.processEvents()
    finally:
        widget._layout_heights_busy = False

    widget.fit_to_view()
    app.processEvents()
    pix = widget.grab()
    assert not pix.isNull()
    assert widget.pixels_per_second() <= widget._min_pixels_per_second() + 1e-6
    assert widget._header_width < widget.width()
    assert widget._view_width() >= 40

    # Keep playing after fit — follow + backdrop blit must stay safe.
    for t in (0.0, 5.0, 12.0, 20.0):
        widget.set_position(t)
        app.processEvents()
    assert widget.grab().width() == widget.width()
