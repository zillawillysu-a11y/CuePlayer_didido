"""Mark overlays must repaint live during playback (not only on pause)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_playback_repaints_live_mark_overlays(app: QApplication) -> None:
    project = Project.create("Play Marks")
    song = project.songs[0]
    song.duration_seconds = 60.0
    song.add_mark(0, 5.0)
    widget = TimelineWidget()
    widget.resize(800, 500)
    widget.set_song(song)
    widget.show()
    app.processEvents()
    widget.set_playing(True)
    widget._rebuild_scrub_backdrop()
    assert widget._can_use_static_backdrop()

    mark_id = song.marks[0].id
    widget.set_selected_mark_ids([mark_id], emit=False)
    widget._hover_mark_lane_header = 1

    painter = QPainter(widget)
    widget.paintEvent(None)  # noqa: SLF001
    painter.end()
    app.processEvents()

    assert widget._playing is True
