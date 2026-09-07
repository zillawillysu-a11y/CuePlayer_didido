"""Video Clip Move/Trim snapping onto existing show anchors (Magnet)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import LtcClip, Mark, Song, VideoClip
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _widget_with_clip(song: Song, clip: VideoClip) -> TimelineWidget:
    widget = TimelineWidget()
    widget.set_song(song)
    widget.resize(1200, 400)
    widget._pixels_per_second = 100.0
    return widget


def _drag_clip_body(widget: TimelineWidget, clip: VideoClip, dt_seconds: float) -> None:
    x0 = widget._x_for_time(clip.start_seconds)
    widget._begin_video_clip_interaction(clip.id, "body", x0, shift=False, ctrl=False)
    dx = dt_seconds * widget._pixels_per_second
    widget._update_video_clip_drag(x0 + dx)


def _trim_clip(widget: TimelineWidget, clip: VideoClip, zone: str, dt_seconds: float) -> None:
    x0 = widget._x_for_time(clip.start_seconds if zone == "left" else clip.end_seconds)
    widget._begin_video_clip_interaction(clip.id, zone, x0, shift=False, ctrl=False)
    dx = dt_seconds * widget._pixels_per_second
    widget._update_video_clip_trim(x0 + dx)


def test_move_start_snaps_to_mark(app: QApplication) -> None:
    # TEST N1
    song = Song.create("Song")
    clip = VideoClip.create(name="a", path=Path("a.mp4"), start_seconds=0.0, duration_seconds=10.0)
    song.add_video_clip(clip)
    song.marks.append(Mark.create(1, 30.0))
    widget = _widget_with_clip(song, clip)
    widget._beat_snap_enabled = True

    _drag_clip_body(widget, clip, dt_seconds=29.95)
    assert clip.start_seconds == pytest.approx(30.0)
    assert clip.duration_seconds == pytest.approx(10.0)
    assert clip.source_in_seconds == pytest.approx(0.0)


def test_move_end_snaps_to_mark(app: QApplication) -> None:
    # TEST N2
    song = Song.create("Song")
    clip = VideoClip.create(name="a", path=Path("a.mp4"), start_seconds=0.0, duration_seconds=10.0)
    song.add_video_clip(clip)
    song.marks.append(Mark.create(1, 30.0))  # clip end target -> start = 20.0
    widget = _widget_with_clip(song, clip)
    widget._beat_snap_enabled = True

    _drag_clip_body(widget, clip, dt_seconds=19.95)  # end lands near 29.95, within 0.16s of 30
    assert clip.start_seconds == pytest.approx(20.0)
    assert clip.duration_seconds == pytest.approx(10.0)


def test_head_trim_snaps_to_mark(app: QApplication) -> None:
    # TEST N3
    song = Song.create("Song")
    clip = VideoClip.create(
        name="a", path=Path("a.mp4"), start_seconds=10.0, source_in_seconds=5.0, duration_seconds=20.0
    )
    song.add_video_clip(clip)
    song.marks.append(Mark.create(1, 15.0))
    widget = _widget_with_clip(song, clip)
    widget._beat_snap_enabled = True

    _trim_clip(widget, clip, "left", dt_seconds=4.95)
    assert clip.start_seconds == pytest.approx(15.0)
    assert clip.source_in_seconds == pytest.approx(10.0)
    assert clip.duration_seconds == pytest.approx(15.0)


def test_tail_trim_snaps_to_mark(app: QApplication) -> None:
    # TEST N4
    song = Song.create("Song")
    clip = VideoClip.create(
        name="a", path=Path("a.mp4"), start_seconds=10.0, source_in_seconds=5.0, duration_seconds=20.0
    )
    song.add_video_clip(clip)
    song.marks.append(Mark.create(1, 25.0))  # end target: clip.end_seconds starts at 30
    widget = _widget_with_clip(song, clip)
    widget._beat_snap_enabled = True

    _trim_clip(widget, clip, "right", dt_seconds=-4.95)
    assert clip.duration_seconds == pytest.approx(15.0)


def test_snap_to_playhead(app: QApplication) -> None:
    # TEST N5
    song = Song.create("Song")
    clip = VideoClip.create(name="a", path=Path("a.mp4"), start_seconds=0.0, duration_seconds=10.0)
    song.add_video_clip(clip)
    widget = _widget_with_clip(song, clip)
    widget._position = 12.0
    widget._beat_snap_enabled = True

    _drag_clip_body(widget, clip, dt_seconds=11.95)
    assert clip.start_seconds == pytest.approx(12.0)


def test_snap_to_other_video_clip_edge_not_self(app: QApplication) -> None:
    # TEST N6
    song = Song.create("Song")
    a = VideoClip.create(name="a", path=Path("a.mp4"), start_seconds=0.0, duration_seconds=10.0)
    b = VideoClip.create(name="b", path=Path("b.mp4"), start_seconds=40.0, duration_seconds=5.0)
    song.add_video_clip(a)
    song.add_video_clip(b)
    widget = _widget_with_clip(song, a)
    widget._beat_snap_enabled = True

    _drag_clip_body(widget, a, dt_seconds=39.95)  # a.start -> near b.start (40)
    assert a.start_seconds == pytest.approx(40.0)

    # No jitter snapping to itself: dragging with no other targets nearby must
    # land exactly on the raw (unsnapped) position.
    a.start_seconds = 0.0
    _drag_clip_body(widget, a, dt_seconds=5.0)
    assert a.start_seconds == pytest.approx(5.0)


def test_snap_to_ltc_clip_edge(app: QApplication) -> None:
    # TEST N7
    song = Song.create("Song")
    clip = VideoClip.create(name="a", path=Path("a.mp4"), start_seconds=0.0, duration_seconds=10.0)
    song.add_video_clip(clip)
    song.ltc_clips.append(
        LtcClip.create(timeline_start_seconds=20.0, duration_seconds=5.0, start_timecode="01:00:00:00")
    )
    widget = _widget_with_clip(song, clip)
    widget._beat_snap_enabled = True

    _drag_clip_body(widget, clip, dt_seconds=19.95)
    assert clip.start_seconds == pytest.approx(20.0)


def test_magnet_off_disables_all_snapping(app: QApplication) -> None:
    # TEST N8
    song = Song.create("Song")
    clip = VideoClip.create(name="a", path=Path("a.mp4"), start_seconds=0.0, duration_seconds=10.0)
    song.add_video_clip(clip)
    song.marks.append(Mark.create(1, 30.0))
    widget = _widget_with_clip(song, clip)
    widget._beat_snap_enabled = False

    _drag_clip_body(widget, clip, dt_seconds=29.95)
    assert clip.start_seconds == pytest.approx(29.95)


def test_snap_threshold_boundary(app: QApplication) -> None:
    # TEST N9: 16px @ 100px/s == 0.16s threshold.
    song = Song.create("Song")
    clip = VideoClip.create(name="a", path=Path("a.mp4"), start_seconds=0.0, duration_seconds=10.0)
    song.add_video_clip(clip)
    song.marks.append(Mark.create(1, 30.0))
    widget = _widget_with_clip(song, clip)
    widget._beat_snap_enabled = True

    # Just outside threshold: no snap.
    _drag_clip_body(widget, clip, dt_seconds=29.8)
    assert clip.start_seconds == pytest.approx(29.8)

    # Just inside threshold: snaps.
    clip.start_seconds = 0.0
    _drag_clip_body(widget, clip, dt_seconds=29.85)
    assert clip.start_seconds == pytest.approx(30.0)


def test_move_snap_never_reintroduces_negative_start(app: QApplication) -> None:
    # TEST N10
    song = Song.create("Song")
    clip = VideoClip.create(name="a", path=Path("a.mp4"), start_seconds=5.0, duration_seconds=10.0)
    song.add_video_clip(clip)
    song.marks.append(Mark.create(1, -0.05))
    widget = _widget_with_clip(song, clip)
    widget._beat_snap_enabled = True

    _drag_clip_body(widget, clip, dt_seconds=-5.05)
    assert clip.start_seconds == pytest.approx(0.0)


def test_body_move_snap_keeps_source_in_and_duration(app: QApplication) -> None:
    # TEST N11
    song = Song.create("Song")
    clip = VideoClip.create(
        name="a", path=Path("a.mp4"), start_seconds=0.0, source_in_seconds=3.0, duration_seconds=10.0
    )
    song.add_video_clip(clip)
    song.marks.append(Mark.create(1, 30.0))
    widget = _widget_with_clip(song, clip)
    widget._beat_snap_enabled = True

    _drag_clip_body(widget, clip, dt_seconds=29.95)
    assert clip.start_seconds == pytest.approx(30.0)
    assert clip.source_in_seconds == pytest.approx(3.0)
    assert clip.duration_seconds == pytest.approx(10.0)
