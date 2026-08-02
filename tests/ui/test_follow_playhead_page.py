"""Auto-scroll play cache keeps waveform filled (overscan blit)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song
from cueplayer.media.audio_loader import AudioBuffer, PeakLevel
from cueplayer.ui.theme import BG_APP
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _fake_audio(seconds: float = 60.0, sr: int = 2000) -> AudioBuffer:
    n = int(seconds * sr)
    mono = np.zeros(n, dtype=np.float32)
    mono[:: max(1, sr // 20)] = 0.8
    samples = mono.reshape(-1, 1)
    step = max(1, sr // 100)
    peaks = PeakLevel(
        samples_per_bucket=step,
        mins=mono[::step].copy(),
        maxs=mono[::step].copy(),
    )
    return AudioBuffer(
        path=Path("fake.wav"),
        sample_rate=sr,
        samples=samples,
        mono=mono,
        peak_levels=[peaks],
    )


def test_follow_playhead_parks_on_edge(app: QApplication) -> None:
    widget = TimelineWidget()
    widget.set_song(Song.create("Follow"))
    widget.resize(900, 400)
    widget.set_zoom(100.0)
    widget._playing = True
    widget._auto_scroll = True
    widget._view_pinned = False

    view_w = widget._view_width()
    widget._scroll_x = 0.0
    right_edge_time = (view_w * 0.75 + 20.0) / widget._pixels_per_second
    widget._position = right_edge_time
    widget._follow_playhead()

    x = widget._x_for_time(widget._position)
    expected = float(widget._header_width) + view_w * 0.75
    assert abs(x - expected) < 2.0


def test_play_scroll_keeps_backdrop_within_overscan(app: QApplication) -> None:
    widget = TimelineWidget()
    widget.set_song(Song.create("Cache"))
    widget.resize(900, 400)
    widget.set_zoom(200.0)
    widget._playing = True
    widget._auto_scroll = True
    widget._view_pinned = False
    widget._rebuild_scrub_backdrop()
    assert widget._scrub_backdrop is not None
    cached = widget._scrub_backdrop
    overscan = widget._scrub_backdrop_overscan
    assert overscan >= 64

    widget._scroll_x = widget._scrub_backdrop_scroll + overscan * 0.4
    widget._clamp_scroll()
    img = QImage(widget.size(), QImage.Format.Format_ARGB32)
    img.fill(QColor(BG_APP))
    painter = QPainter(img)
    assert widget._blit_scrub_backdrop(painter) is True
    painter.end()
    assert widget._scrub_backdrop is cached


def test_blit_keeps_waveform_filled_after_scroll(app: QApplication) -> None:
    """Scrolling during play must not leave a BG_APP void on the exposed side."""
    widget = TimelineWidget()
    widget.set_song(Song.create("Wave"))
    widget.set_audio(_fake_audio())
    widget.resize(800, 360)
    widget.set_zoom(120.0)
    widget._playing = True
    widget._auto_scroll = True
    widget._view_pinned = False
    widget._rebuild_scrub_backdrop()
    assert widget._scrub_backdrop_overscan > 0

    widget._scroll_x = widget._scrub_backdrop_scroll + widget._view_width() * 0.33
    widget._clamp_scroll()

    img = QImage(widget.size(), QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0))
    painter = QPainter(img)
    assert widget._blit_scrub_backdrop(painter) is True
    painter.end()

    bg = QColor(BG_APP)
    bed = QColor("#09090b")
    y = widget._ruler_height + widget._wave_height // 3
    bg_hits = 0
    bed_hits = 0
    for x in range(widget.width() - 48, widget.width() - 4):
        c = QColor(img.pixel(x, y))
        if c.red() == bg.red() and c.green() == bg.green() and c.blue() == bg.blue():
            bg_hits += 1
        if c.red() == bed.red() and c.green() == bed.green() and c.blue() == bed.blue():
            bed_hits += 1
    assert bed_hits > bg_hits, (
        f"right edge looks like a scroll void (bg={bg_hits}, bed={bed_hits})"
    )
