"""Marquee selection box must paint above mark track colors."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPointF
from PySide6.QtGui import QPaintEvent
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_selection_box_paints_after_mark_track_colors(app: QApplication) -> None:
    """Track-color lane fills used to cover the dashed marquee mid-drag."""
    project = Project.create("Marquee")
    song = project.new_song("Song")
    project.songs.append(song)
    widget = TimelineWidget()
    widget.set_song(song)
    widget.resize(800, 400)
    widget.show()
    app.processEvents()

    widget._box_selecting = True
    widget._box_origin = QPointF(200, 100)
    widget._box_current = QPointF(400, 280)
    widget._show_mark_track_colors = True

    order: list[str] = []
    real_lanes = widget._paint_lanes
    real_box = widget._paint_selection_box

    def _lanes(painter, *, start_y: int) -> None:  # noqa: ANN001
        order.append("lanes")
        real_lanes(painter, start_y=start_y)

    def _box(painter) -> None:  # noqa: ANN001
        order.append("box")
        real_box(painter)

    widget._paint_lanes = _lanes  # type: ignore[method-assign]
    widget._paint_selection_box = _box  # type: ignore[method-assign]
    # Force the full paint path (box-select already disables backdrop).
    widget._playing = False
    widget._scrubbing = False

    widget.paintEvent(QPaintEvent(widget.rect()))

    assert "lanes" in order
    assert "box" in order
    assert order.index("lanes") < order.index("box")
