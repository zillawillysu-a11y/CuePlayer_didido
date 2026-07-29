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
    bar.resize(400, 32)
    bar.set_state(duration=100.0, position=10.0, view_start=0.0, view_end=20.0)
    got: list[float] = []
    bar.seek_requested.connect(got.append)
    # Click near the middle of the track.
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    mid_x = 8 + (400 - 16) * 0.5
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(mid_x, 16),
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
