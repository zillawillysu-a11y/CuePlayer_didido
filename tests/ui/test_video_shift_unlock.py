"""Shift frees locked video clips and disables zero snap while dragging."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song, VideoClip
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _song_with_locked_clip() -> Song:
    song = Song.create("Aligned")
    clip = VideoClip.create(
        name="vj",
        path=Path("a.mp4"),
        start_seconds=0.0,
        duration_seconds=4.0,
    )
    clip.locked = True
    song.add_video_clip(clip)
    return song


def test_locked_clip_body_hit_without_shift(app: QApplication) -> None:
    widget = TimelineWidget()
    song = _song_with_locked_clip()
    widget.set_song(song)
    widget.resize(900, 400)
    clip = song.video_clips[0]
    x = widget._x_for_time(clip.start_seconds + 0.5)
    y = widget._video_lane_top_y() + 10
    hit = widget._hit_video_clip(x, y)
    assert hit == (clip.id, "body")
    # Edge is not a trim zone while locked.
    edge = widget._hit_video_clip(widget._x_for_time(clip.start_seconds), y)
    assert edge == (clip.id, "body")


def test_shift_allows_locked_clip_trim_hit(app: QApplication) -> None:
    widget = TimelineWidget()
    song = _song_with_locked_clip()
    widget.set_song(song)
    widget.resize(900, 400)
    clip = song.video_clips[0]
    y = widget._video_lane_top_y() + 10
    edge = widget._hit_video_clip(
        widget._x_for_time(clip.start_seconds), y, allow_locked_edit=True
    )
    assert edge == (clip.id, "left")


def test_shift_begin_allows_drag_on_locked_clip(app: QApplication) -> None:
    widget = TimelineWidget()
    song = _song_with_locked_clip()
    widget.set_song(song)
    widget.resize(900, 400)
    clip = song.video_clips[0]
    x = widget._x_for_time(1.0)
    widget._begin_video_clip_interaction(clip.id, "body", x, shift=False, ctrl=False)
    assert widget._dragging_clip is None

    widget._begin_video_clip_interaction(clip.id, "body", x, shift=True, ctrl=False)
    assert widget._dragging_clip == clip.id
    assert clip.locked is True  # still locked after temporary free
