"""Progressive Video waveform painting must not cover Beat Grid lines."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtGui import QPaintEvent
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import BeatGridRegion, Song
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_progressive_waveform_restrokes_grid_after_video_overlay(
    app: QApplication,
) -> None:
    timeline = TimelineWidget()
    song = Song.create("Video grid layering")
    song.duration_seconds = 10.0
    song.beat_grids.append(BeatGridRegion.create(1.0, 8.0))
    timeline.resize(900, 500)
    timeline.set_song(song)
    timeline.show()
    timeline._rebuild_scrub_backdrop(reason="grid_video_order")
    app.processEvents()
    calls: list[str] = []

    with (
        patch.object(timeline, "_needs_waveform_overlay", return_value=True),
        patch.object(
            timeline,
            "_paint_progressive_waveform_overlay",
            side_effect=lambda _painter: calls.append("waveform"),
        ),
        patch.object(
            timeline,
            "_paint_beat_grids",
            side_effect=lambda _painter: calls.append("grid"),
        ),
    ):
        timeline.paintEvent(QPaintEvent(timeline.rect()))

    assert calls == ["waveform", "grid"]
