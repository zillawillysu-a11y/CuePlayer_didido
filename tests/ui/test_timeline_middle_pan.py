"""Middle-button pan must not replay a deferred left-click seek on release."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _release_left(widget: TimelineWidget, x: float, y: float) -> None:
    event = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(x, y),
        QPointF(),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mouseReleaseEvent(event)


def test_middle_pan_cancels_deferred_mark_seek(app: QApplication) -> None:
    widget = TimelineWidget()
    widget.resize(900, 400)
    song = Song.create("Song")
    song.duration_seconds = 60.0
    song.add_mark(1, 5.0, "Verse")
    widget.set_song(song)
    mark_id = song.marks[0].id

    seeks: list[float] = []
    widget.seek_requested.connect(seeks.append)

    x = widget._x_for_time(5.0)
    y = widget._tracks_top_y() + 12.0
    widget._begin_mark_interaction(mark_id, x, shift=False, ctrl=False)
    assert widget._drag_click_seek == pytest.approx(5.0)

    widget._begin_pan(x + 40.0)
    widget._pan_moved = True
    widget._panning = False

    _release_left(widget, x + 80.0, y)
    assert seeks == []


def test_middle_pan_cancels_active_scrub(app: QApplication) -> None:
    widget = TimelineWidget()
    widget.resize(900, 400)
    song = Song.create("Song")
    song.duration_seconds = 60.0
    widget.set_song(song)

    seeks: list[float] = []
    widget.seek_requested.connect(seeks.append)

    ended: list[int] = []
    widget.scrub_ended.connect(lambda: ended.append(1))

    x = widget._x_for_time(10.0)
    y = widget._ruler_height + widget._wave_height * 0.5
    widget._scrubbing = True
    widget.scrub_started.emit()

    widget._begin_pan(x + 20.0)
    assert widget._scrubbing is False
    assert ended == [1]

    _release_left(widget, x + 60.0, y)
    assert seeks == []
