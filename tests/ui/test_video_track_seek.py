"""Video Track click-to-seek: empty-lane seek, clip-body select+seek, and
regression guards for Move/Trim/Marquee (no stray seeks during those gestures).
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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


def _mouse(etype, x, y, button, buttons, modifiers=Qt.KeyboardModifier.NoModifier):
    return QMouseEvent(etype, QPointF(x, y), button, buttons, modifiers)


def _press(widget, x, y, modifiers=Qt.KeyboardModifier.NoModifier):
    widget.mousePressEvent(
        _mouse(QEvent.Type.MouseButtonPress, x, y, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, modifiers)
    )


def _move(widget, x, y):
    widget.mouseMoveEvent(
        _mouse(QEvent.Type.MouseMove, x, y, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
    )


def _release(widget, x, y):
    widget.mouseReleaseEvent(
        _mouse(QEvent.Type.MouseButtonRelease, x, y, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
    )


def _setup_song(tmp_path: Path, *, clip_start=10.0, clip_duration=20.0) -> tuple[Song, VideoClip]:
    song = Song.create("Seek")
    song.duration_seconds = 60.0
    song.show_video_track = True
    # Non-existent path: avoids kicking off the real async waveform decode
    # (video_waveform_worker), which hangs on garbage bytes in this sandbox.
    clip = VideoClip.create(
        name="a", path=tmp_path / "a.mp4", start_seconds=clip_start, duration_seconds=clip_duration
    )
    song.add_video_clip(clip)
    return song, clip


def _build_widget(song: Song) -> TimelineWidget:
    tl = TimelineWidget()
    tl.resize(1200, 700)
    tl.set_show_video_track(True, emit=False)
    tl.set_song(song)
    tl._pixels_per_second = 30.0  # noqa: SLF001
    tl._scroll_x = 0.0  # noqa: SLF001
    tl.show()
    return tl


def test_empty_video_lane_click_seeks_playhead(app: QApplication, tmp_path: Path) -> None:
    del app
    song, clip = _setup_song(tmp_path)
    tl = _build_widget(song)
    seeks: list[float] = []
    tl.seek_requested.connect(seeks.append)

    x = tl._x_for_time(45.0)  # noqa: SLF001 — well past the clip, still empty lane
    y = tl._video_lane_top_y() + 15  # noqa: SLF001
    _press(tl, x, y)
    _release(tl, x, y)

    assert seeks == [pytest.approx(45.0)]


def test_video_clip_body_click_selects_and_seeks_to_click_time(app: QApplication, tmp_path: Path) -> None:
    del app
    song, clip = _setup_song(tmp_path, clip_start=10.0, clip_duration=60.0)
    tl = _build_widget(song)
    seeks: list[float] = []
    tl.seek_requested.connect(seeks.append)

    click_time = 23.25  # inside the clip and still on-screen at 30px/s
    x = tl._x_for_time(click_time)  # noqa: SLF001 — inside the clip, not at its start
    y = tl._video_lane_top_y() + 15  # noqa: SLF001
    _press(tl, x, y)
    _release(tl, x, y)

    assert set(tl.selected_video_clip_ids()) == {clip.id}
    assert seeks == [pytest.approx(click_time)]


def test_video_clip_body_drag_moves_without_stray_seek(app: QApplication, tmp_path: Path) -> None:
    del app
    song, clip = _setup_song(tmp_path)
    tl = _build_widget(song)
    seeks: list[float] = []
    tl.seek_requested.connect(seeks.append)

    x0 = tl._x_for_time(clip.start_seconds + 2.0)  # noqa: SLF001
    y = tl._video_lane_top_y() + 15  # noqa: SLF001
    _press(tl, x0, y)
    _move(tl, x0 + 150, y)  # well past drag threshold
    _release(tl, x0 + 150, y)

    assert clip.start_seconds == pytest.approx(15.0)  # moved
    assert seeks == []  # no seek should fire from a body drag


def test_video_clip_edge_trim_without_stray_seek(app: QApplication, tmp_path: Path) -> None:
    del app
    song, clip = _setup_song(tmp_path)
    tl = _build_widget(song)
    seeks: list[float] = []
    tl.seek_requested.connect(seeks.append)

    x0 = tl._x_for_time(clip.start_seconds)  # noqa: SLF001 — left trim handle
    y = tl._video_lane_top_y() + 15  # noqa: SLF001
    _press(tl, x0, y)
    _move(tl, x0 + 50, y)
    _release(tl, x0 + 50, y)

    assert clip.start_seconds > 10.0  # trimmed
    assert seeks == []


def test_marquee_over_video_lane_does_not_seek(app: QApplication, tmp_path: Path) -> None:
    del app
    song, clip = _setup_song(tmp_path)
    far_clip = VideoClip.create(name="b", path=tmp_path / "b.mp4", start_seconds=40.0, duration_seconds=3.0)
    song.add_video_clip(far_clip)
    tl = _build_widget(song)
    seeks: list[float] = []
    tl.seek_requested.connect(seeks.append)

    x0 = tl._x_for_time(0.0)  # noqa: SLF001
    y0 = tl._video_lane_top_y() + 5  # noqa: SLF001
    x1 = tl._x_for_time(60.0)  # noqa: SLF001
    y1 = y0 + 20
    _press(tl, x0, y0, modifiers=Qt.KeyboardModifier.ShiftModifier)
    _move(tl, x1, y1)
    _release(tl, x1, y1)

    assert seeks == []


def test_split_after_video_clip_click_seek_splits_at_clicked_time(app: QApplication, tmp_path: Path) -> None:
    # Regression per A9: click-seek on a Video Clip feeds a usable playhead
    # time for Split at Playhead.
    del app
    from cueplayer.domain.models import Project
    from cueplayer.ui.main_window import MainWindow

    window = MainWindow(Project.create("Seek+Split"))
    song = window.current_song
    song.video_clips = []
    song.show_video_track = True
    clip = VideoClip.create(name="a", path=tmp_path / "a.mp4", start_seconds=10.0, duration_seconds=20.0)
    song.add_video_clip(clip)
    tl = window.timeline
    tl.resize(1200, 700)
    tl.set_show_video_track(True, emit=False)
    tl.set_song(song)
    tl._pixels_per_second = 30.0  # noqa: SLF001
    tl._scroll_x = 0.0  # noqa: SLF001
    tl.show()

    seeks: list[float] = []
    tl.seek_requested.connect(seeks.append)

    click_time = 18.0
    x = tl._x_for_time(click_time)  # noqa: SLF001
    y = tl._video_lane_top_y() + 15  # noqa: SLF001
    _press(tl, x, y)
    _release(tl, x, y)
    assert seeks == [pytest.approx(click_time)]

    window._split_video_clip(clip.id, seeks[0])
    clips = sorted(window.current_song.video_clips, key=lambda c: c.start_seconds)
    assert len(clips) == 2
    assert clips[1].start_seconds == pytest.approx(click_time)
