"""Video clip selection must stay visible during playback (static backdrop path)."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QPainter
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song, VideoClip
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _song_with_clip() -> tuple[Song, VideoClip]:
    song = Song.create("Song")
    song.duration_seconds = 60.0
    song.show_video_track = True
    clip = VideoClip.create(
        name="S14.唱衰_v1",
        path=Path("clip.mp4"),
        start_seconds=1.0,
        duration_seconds=8.0,
    )
    song.add_video_clip(clip)
    return song, clip


def _mouse(
    etype: QEvent.Type,
    x: float,
    y: float,
    button: Qt.MouseButton,
    buttons: Qt.MouseButton,
) -> QMouseEvent:
    return QMouseEvent(etype, QPointF(x, y), button, buttons, Qt.KeyboardModifier.NoModifier)


def _press_at(widget: TimelineWidget, x: float, y: float) -> None:
    widget.mousePressEvent(
        _mouse(
            QEvent.Type.MouseButtonPress,
            x,
            y,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
    )


def _release_at(widget: TimelineWidget, x: float, y: float) -> None:
    widget.mouseReleaseEvent(
        _mouse(
            QEvent.Type.MouseButtonRelease,
            x,
            y,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
    )


def test_playback_repaints_live_video_selection(app: QApplication) -> None:
    song, clip = _song_with_clip()
    widget = TimelineWidget()
    widget.resize(900, 600)
    widget.set_song(song)
    widget.show()
    app.processEvents()
    widget.set_playing(True)
    widget._rebuild_scrub_backdrop()
    assert widget._can_use_static_backdrop()

    widget.set_selected_video_clip_ids([clip.id], emit=False)
    assert widget._single_selected_video_clip() is clip

    painter = QPainter(widget)
    widget.paintEvent(None)  # noqa: SLF001
    painter.end()
    app.processEvents()

    assert widget._playing is True
    assert widget._can_use_static_backdrop()
    assert clip.id in widget.selected_video_clip_ids()


def test_click_select_during_play_survives_release(app: QApplication) -> None:
    """Click without drag must keep selection after returning to the backdrop path."""
    song, clip = _song_with_clip()
    widget = TimelineWidget()
    widget.resize(900, 600)
    widget.set_song(song)
    widget.show()
    app.processEvents()
    widget.set_playing(True)
    widget._rebuild_scrub_backdrop()

    mid_t = clip.start_seconds + clip.duration_seconds / 2
    x = widget._x_for_time(mid_t)
    y = widget._video_lane_top_y() + widget._video_lane_base_height / 2
    _press_at(widget, x, y)
    assert clip.id in widget.selected_video_clip_ids()
    _release_at(widget, x, y)
    app.processEvents()

    assert clip.id in widget.selected_video_clip_ids()
    assert widget._dragging_clip is None
    assert widget._can_use_static_backdrop()
    assert widget._single_selected_video_clip() is clip

    painter = QPainter(widget)
    widget.paintEvent(None)  # noqa: SLF001
    painter.end()


def test_press_prefers_clip_over_video_lane_splitter(app: QApplication) -> None:
    song, clip = _song_with_clip()
    widget = TimelineWidget()
    widget.resize(900, 600)
    widget.set_song(song)
    widget.show()
    app.processEvents()

    mid_t = clip.start_seconds + clip.duration_seconds / 2
    x = widget._x_for_time(mid_t)
    # Inside the splitter hit band but still on the clip row.
    y = float(widget._video_lane_clip_bottom_y()) - 2.0
    assert widget._near_video_lane_split(y)
    assert widget._hit_video_clip(x, y) is not None

    _press_at(widget, x, y)
    assert widget._resizing_video_lane is False
    assert clip.id in widget.selected_video_clip_ids()
    _release_at(widget, x, y)
