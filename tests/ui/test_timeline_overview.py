"""Slim overview scrubber under the Timeline."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song
from cueplayer.ui.timeline_overview import TimelineOverviewBar
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_overview_seek_emits(app: QApplication) -> None:
    bar = TimelineOverviewBar()
    bar.resize(400, 18)
    bar.set_state(duration=100.0, position=10.0, view_start=0.0, view_end=20.0)
    got: list[float] = []
    bar.seek_requested.connect(got.append)
    # Click near the middle of the track.
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    # Track sits between label gutters; inset matches paint/seek geometry.
    gutter, inset = 44, 6
    track_left = gutter + inset
    track_w = 400 - gutter * 2 - inset * 2
    mid_x = track_left + track_w * 0.5
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(mid_x, 9),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    bar.mousePressEvent(press)
    assert got
    assert 40.0 <= got[0] <= 60.0


def test_timeline_visible_window(app: QApplication) -> None:
    widget = TimelineWidget()
    song = Song.create("Overview")
    widget.set_song(song)
    widget.resize(900, 400)
    widget.set_zoom(200.0)
    start, end = widget.visible_time_window()
    assert end > start
    assert start >= 0.0
