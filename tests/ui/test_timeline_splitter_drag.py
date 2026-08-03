"""Splitter drag must not recurse into parent geometry sync."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song, VideoClip
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _press_move_release(widget: TimelineWidget, y0: float, y1: float) -> None:
    x = float(widget._header_width + 40)

    def _event(etype: QEvent.Type, y: float, button: Qt.MouseButton, buttons: Qt.MouseButton) -> QMouseEvent:
        return QMouseEvent(
            etype,
            QPointF(x, y),
            button,
            buttons,
            Qt.KeyboardModifier.NoModifier,
        )

    widget.mousePressEvent(
        _event(QEvent.Type.MouseButtonPress, y0, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
    )
    for y in (y0 + 8, y0 + 24, y1):
        widget.mouseMoveEvent(
            _event(QEvent.Type.MouseMove, y, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
        )
    widget.mouseReleaseEvent(
        _event(
            QEvent.Type.MouseButtonRelease,
            y1,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
    )


def test_wave_splitter_drag_defers_geometry_signal(app: QApplication) -> None:
    widget = TimelineWidget()
    song = Song.create("Split")
    song.add_video_clip(
        VideoClip.create(name="vj", path=Path("a.mp4"), start_seconds=0.0, duration_seconds=2.0)
    )
    widget.set_song(song)
    widget.resize(900, 500)
    emits: list[int] = []
    widget.content_geometry_changed.connect(lambda: emits.append(1))

    y_split = float(widget._wave_bottom_y())
    before = widget._wave_height
    _press_move_release(widget, y_split, y_split + 80)

    assert widget._wave_height > before
    assert widget._resizing_wave is False
    # One flush on mouse release is OK; must not spam during the drag.
    assert len(emits) <= 2
    assert widget._video_lane_top_y() == widget._wave_bottom_y()
    assert widget._tracks_top_y() > widget._video_lane_top_y()


def test_video_lane_splitter_drag_defers_geometry_signal(app: QApplication) -> None:
    widget = TimelineWidget()
    song = Song.create("Split")
    song.add_video_clip(
        VideoClip.create(name="vj", path=Path("a.mp4"), start_seconds=0.0, duration_seconds=2.0)
    )
    widget.set_song(song)
    widget.resize(900, 500)
    emits: list[int] = []
    widget.content_geometry_changed.connect(lambda: emits.append(1))

    y_split = float(widget._video_lane_clip_bottom_y())
    before = widget._video_lane_base_height
    _press_move_release(widget, y_split, y_split + 60)

    assert widget._video_lane_base_height > before
    assert widget._resizing_video_lane is False
    assert len(emits) <= 2
