"""Peak artifacts render as outlines after zoom exceeds cache resolution."""

from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song
from cueplayer.media.video_waveform_artifact import VideoWaveformArtifact
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_high_zoom_artifact_does_not_fill_between_envelopes(app: QApplication) -> None:
    timeline = TimelineWidget()
    song = Song.create("Outline")
    song.duration_seconds = 10.0
    timeline.set_song(song)
    timeline._pixels_per_second = 100.0
    timeline._scroll_x = 0.0
    timeline._wave_height = 100
    timeline._waveform_color = "#ff0000"
    art = VideoWaveformArtifact(
        path="video.mp4",
        mtime_ns=1,
        size=1,
        stream_index=0,
        format_version=1,
        peaks_per_second=5.0,
        origin_seconds=0.0,
        duration_seconds=10.0,
        sample_rate=48000,
        channels=2,
        mins=np.full(50, -0.8, dtype=np.float32),
        maxs=np.full(50, 0.8, dtype=np.float32),
        coverage=np.ones(50, dtype=np.uint8),
        complete=True,
    )
    image = QImage(700, 100, QImage.Format.Format_ARGB32)
    image.fill(QColor("#09090b"))
    painter = QPainter(image)
    timeline._paint_artifact_waveform(painter, art, 0, 100, 700)
    painter.end()

    # Interior between the two red outlines stays unfilled.
    interior = image.pixelColor(timeline._header_width + 100, 70)
    assert interior.red() < 100
