"""Hiding mark track colors restores neutral beds and gray dividers."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_hiding_track_colors_removes_lane_gaps(app: QApplication) -> None:
    project = Project.create("Hide Colors")
    song = project.songs[0]
    widget = TimelineWidget()
    widget.resize(800, 500)
    widget.set_song(song)
    widget.show()
    app.processEvents()

    n = widget._visible_lane_count()
    assert n >= 1

    widget.apply_mark_track_colors(True)
    app.processEvents()
    with_gaps = widget._marks_content_height()
    assert widget._mark_lane_gap_px() == 2
    assert with_gaps == n * widget._lane_height + max(0, n - 1) * 2

    widget.apply_mark_track_colors(False)
    app.processEvents()
    without_gaps = widget._marks_content_height()
    assert widget._mark_lane_gap_px() == 0
    assert without_gaps == n * widget._lane_height
    assert without_gaps < with_gaps or n <= 1
