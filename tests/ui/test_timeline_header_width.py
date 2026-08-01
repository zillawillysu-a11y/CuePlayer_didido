"""Timeline Mark Type column can be dragged narrower / wider."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _press_move_release(widget: TimelineWidget, x0: float, x1: float, y: float = 40.0) -> None:
    press = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(x0, y),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mousePressEvent(press)
    move = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPointF(x1, y),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mouseMoveEvent(move)
    release = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        QPointF(x1, y),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mouseReleaseEvent(release)


def test_header_width_drag_narrower(app: QApplication) -> None:
    widget = TimelineWidget()
    song = Project.create("H").new_song("Song")
    widget.set_song(song)
    widget.resize(900, 400)
    app.processEvents()

    assert widget.header_width() == 140
    assert widget._near_header_split(140.0)
    assert not widget._near_header_split(100.0)

    _press_move_release(widget, 140.0, 90.0)
    assert widget.header_width() == 90
    assert not widget._resizing_header


def test_header_width_clamps_to_min_max(app: QApplication) -> None:
    widget = TimelineWidget()
    widget.resize(900, 400)
    app.processEvents()

    widget.set_header_width(40)
    assert widget.header_width() == widget._header_width_min

    widget.set_header_width(999)
    assert widget.header_width() == widget._header_width_max


def test_header_split_preferred_over_mark_lane_hit(app: QApplication) -> None:
    widget = TimelineWidget()
    song = Project.create("H").new_song("Song")
    widget.set_song(song)
    widget.resize(900, 400)
    widget.set_header_width(140)
    app.processEvents()
    widget._apply_layout_heights()

    # Edge of the header is reserved for the drag handle, not "add mark".
    lanes = list(widget._lane_rects())
    assert lanes
    mid_y = (lanes[0][1] + lanes[0][2]) / 2.0
    assert widget._hit_mark_lane_header(widget.header_width() - 1, mid_y) is None
    assert widget._hit_mark_lane_header(40.0, mid_y) == lanes[0][0]
