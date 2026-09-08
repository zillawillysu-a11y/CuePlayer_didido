"""Marquee (box) multi-selection across Video/LTC/Mark lanes + group move.

Regression for the new cross-type marquee selection and group-drag feature:
a Song already has Video Clips, LTC Clips, and Marks laid out; the user drags
a selection rectangle across all three lanes and then drags any one selected
item to move the whole group together, as one undo entry.
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

from cueplayer.domain.models import LtcClip, Song, VideoClip
from cueplayer.domain.undo import GroupMoveCommand, UndoStack
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


def _setup_song(tmp_path: Path) -> Song:
    song = Song.create("Marquee")
    song.duration_seconds = 60.0
    song.show_video_track = True
    # Deliberately NOT an existing file: a real file on disk would pass the
    # waveform-cache stat check and kick off a real async decode subprocess
    # (video_waveform_worker) that hangs on garbage bytes in this sandbox.
    # A path that doesn't resolve fails the stat check harmlessly instead —
    # selection/group-move logic here never needs real waveform peaks.
    video_path = tmp_path / "a.mp4"
    video_a = VideoClip.create(name="A", path=video_path, start_seconds=10.0, duration_seconds=4.0)
    song.add_video_clip(video_a)
    song.ltc_clips = [
        LtcClip.create(timeline_start_seconds=10.0, duration_seconds=3.0, start_timecode="01:00:00:00")
    ]
    song.add_mark(1, 12.0)
    return song


def _build_widget(song: Song) -> TimelineWidget:
    tl = TimelineWidget()
    tl.resize(1200, 700)
    tl.set_show_video_track(True, emit=False)
    tl.set_ltc_source_mode("clip_generator")
    tl.set_song(song)
    tl._pixels_per_second = 30.0  # noqa: SLF001
    tl._scroll_x = 0.0  # noqa: SLF001
    tl.show()
    return tl


def _mark_row_y(tl: TimelineWidget, lane_index: int) -> float:
    y0, y1 = next((r[1], r[2]) for r in tl._lane_rects() if r[0] == lane_index)  # noqa: SLF001
    return (y0 + y1) / 2.0


def test_marquee_selects_across_video_ltc_mark_lanes(app: QApplication, tmp_path: Path) -> None:
    del app
    song = _setup_song(tmp_path)
    tl = _build_widget(song)
    video_a = song.video_clips[0]
    ltc_a = song.ltc_clips[0]
    mark_a = song.marks[0]

    x0 = tl._x_for_time(5.0)  # noqa: SLF001 — before every item, still empty video-lane space
    y0 = tl._video_lane_top_y() + 15  # noqa: SLF001
    x1 = tl._x_for_time(16.0)  # noqa: SLF001 — after every item
    y1 = _mark_row_y(tl, 1) + 10

    _press(tl, x0, y0)
    assert tl._box_selecting  # noqa: SLF001
    _move(tl, x1, y1)
    _release(tl, x1, y1)

    assert video_a.id in tl.selected_video_clip_ids()
    assert ltc_a.id in tl.selected_ltc_clip_ids()
    assert mark_a.id in tl.selected_mark_ids()


def test_marquee_excludes_items_outside_rectangle(app: QApplication, tmp_path: Path) -> None:
    del app
    song = _setup_song(tmp_path)
    # A second, far-away video clip that must stay unselected (path does not
    # exist on disk — see _setup_song for why that matters here).
    far_path = tmp_path / "far.mp4"
    far_clip = VideoClip.create(name="Far", path=far_path, start_seconds=40.0, duration_seconds=3.0)
    song.add_video_clip(far_clip)
    tl = _build_widget(song)
    video_a = song.video_clips[0]

    x0 = tl._x_for_time(5.0)  # noqa: SLF001
    y0 = tl._video_lane_top_y() + 15  # noqa: SLF001
    x1 = tl._x_for_time(16.0)  # noqa: SLF001
    y1 = _mark_row_y(tl, 1) + 10

    _press(tl, x0, y0)
    _move(tl, x1, y1)
    _release(tl, x1, y1)

    assert video_a.id in tl.selected_video_clip_ids()
    assert far_clip.id not in tl.selected_video_clip_ids()


def test_group_move_applies_same_delta_to_every_selected_item(
    app: QApplication, tmp_path: Path
) -> None:
    del app
    song = _setup_song(tmp_path)
    tl = _build_widget(song)
    video_a = song.video_clips[0]
    ltc_a = song.ltc_clips[0]
    mark_a = song.marks[0]

    v0, l0, m0 = video_a.start_seconds, ltc_a.timeline_start_seconds, mark_a.time_seconds

    x0 = tl._x_for_time(5.0)  # noqa: SLF001
    y0 = tl._video_lane_top_y() + 15  # noqa: SLF001
    x1 = tl._x_for_time(16.0)  # noqa: SLF001
    y1 = _mark_row_y(tl, 1) + 10
    _press(tl, x0, y0)
    _move(tl, x1, y1)
    _release(tl, x1, y1)
    assert {video_a.id, ltc_a.id, mark_a.id} <= (
        set(tl.selected_video_clip_ids()) | set(tl.selected_ltc_clip_ids()) | set(tl.selected_mark_ids())
    )

    committed: list[tuple] = []
    tl.group_move_committed.connect(lambda v, l, m: committed.append((dict(v), dict(l), dict(m))))

    clip_body_x = tl._x_for_time((video_a.start_seconds + video_a.end_seconds) / 2)  # noqa: SLF001
    clip_body_y = tl._video_lane_top_y() + 15  # noqa: SLF001
    drag_dx = 10.0 * tl._pixels_per_second  # noqa: SLF001
    _press(tl, clip_body_x, clip_body_y)
    assert tl._group_dragging  # noqa: SLF001
    _move(tl, clip_body_x + drag_dx, clip_body_y)
    _release(tl, clip_body_x + drag_dx, clip_body_y)

    assert video_a.start_seconds == pytest.approx(v0 + 10.0, abs=1e-6)
    assert ltc_a.timeline_start_seconds == pytest.approx(l0 + 10.0, abs=1e-6)
    assert mark_a.time_seconds == pytest.approx(m0 + 10.0, abs=1e-6)

    assert len(committed) == 1
    video_changes, ltc_changes, mark_changes = committed[0]
    assert video_a.id in video_changes and ltc_a.id in ltc_changes and mark_a.id in mark_changes


def test_group_move_clamps_at_zero_and_keeps_relative_spacing(
    app: QApplication, tmp_path: Path
) -> None:
    del app
    song = _setup_song(tmp_path)  # video/ltc @10s, mark @12s
    tl = _build_widget(song)
    video_a = song.video_clips[0]
    ltc_a = song.ltc_clips[0]
    mark_a = song.marks[0]

    x0 = tl._x_for_time(5.0)  # noqa: SLF001
    y0 = tl._video_lane_top_y() + 15  # noqa: SLF001
    x1 = tl._x_for_time(16.0)  # noqa: SLF001
    y1 = _mark_row_y(tl, 1) + 10
    _press(tl, x0, y0)
    _move(tl, x1, y1)
    _release(tl, x1, y1)

    # Earliest selected item is the video/LTC clip at 10s; drag -20s (would
    # go to -10s) must clamp the whole group to exactly -10s of travel.
    clip_body_x = tl._x_for_time((video_a.start_seconds + video_a.end_seconds) / 2)  # noqa: SLF001
    clip_body_y = tl._video_lane_top_y() + 15  # noqa: SLF001
    drag_dx = -20.0 * tl._pixels_per_second  # noqa: SLF001
    _press(tl, clip_body_x, clip_body_y)
    _move(tl, clip_body_x + drag_dx, clip_body_y)
    _release(tl, clip_body_x + drag_dx, clip_body_y)

    assert video_a.start_seconds == pytest.approx(0.0, abs=1e-6)
    assert ltc_a.timeline_start_seconds == pytest.approx(0.0, abs=1e-6)
    # Mark was 2s after the clip start — spacing must be preserved exactly.
    assert mark_a.time_seconds == pytest.approx(2.0, abs=1e-6)


def test_unselected_item_does_not_move_during_group_drag(
    app: QApplication, tmp_path: Path
) -> None:
    del app
    song = _setup_song(tmp_path)
    other_mark = song.add_mark(1, 30.0)
    tl = _build_widget(song)
    video_a = song.video_clips[0]
    mark_a = song.marks[0]

    x0 = tl._x_for_time(5.0)  # noqa: SLF001
    y0 = tl._video_lane_top_y() + 15  # noqa: SLF001
    x1 = tl._x_for_time(16.0)  # noqa: SLF001 — excludes the mark at 30s
    y1 = _mark_row_y(tl, 1) + 10
    _press(tl, x0, y0)
    _move(tl, x1, y1)
    _release(tl, x1, y1)
    assert other_mark.id not in tl.selected_mark_ids()
    assert mark_a.id in tl.selected_mark_ids()

    clip_body_x = tl._x_for_time((video_a.start_seconds + video_a.end_seconds) / 2)  # noqa: SLF001
    clip_body_y = tl._video_lane_top_y() + 15  # noqa: SLF001
    drag_dx = 10.0 * tl._pixels_per_second  # noqa: SLF001
    _press(tl, clip_body_x, clip_body_y)
    _move(tl, clip_body_x + drag_dx, clip_body_y)
    _release(tl, clip_body_x + drag_dx, clip_body_y)

    assert other_mark.time_seconds == pytest.approx(30.0, abs=1e-6)


def test_undo_once_restores_whole_group(app: QApplication, tmp_path: Path) -> None:
    del app
    song = _setup_song(tmp_path)
    video_a = song.video_clips[0]
    ltc_a = song.ltc_clips[0]
    mark_a = song.marks[0]
    v0, l0, m0 = video_a.start_seconds, ltc_a.timeline_start_seconds, mark_a.time_seconds

    cmd = GroupMoveCommand(
        video_changes={video_a.id: ((v0, video_a.source_in_seconds, video_a.duration_seconds), (v0 + 10.0, video_a.source_in_seconds, video_a.duration_seconds))},
        ltc_changes={ltc_a.id: ((l0, ltc_a.duration_seconds, ltc_a.start_timecode), (l0 + 10.0, ltc_a.duration_seconds, ltc_a.start_timecode))},
        mark_changes={mark_a.id: (m0, m0 + 10.0)},
    )
    cmd.redo(song)
    assert video_a.start_seconds == pytest.approx(v0 + 10.0)
    assert ltc_a.timeline_start_seconds == pytest.approx(l0 + 10.0)
    assert mark_a.time_seconds == pytest.approx(m0 + 10.0)

    cmd.undo(song)
    assert video_a.start_seconds == pytest.approx(v0)
    assert ltc_a.timeline_start_seconds == pytest.approx(l0)
    assert mark_a.time_seconds == pytest.approx(m0)


def test_undo_stack_single_entry_for_group_move(app: QApplication, tmp_path: Path) -> None:
    """Ctrl+Z once must revert the whole group — not one item per undo step."""
    del app
    song = _setup_song(tmp_path)
    video_a = song.video_clips[0]
    ltc_a = song.ltc_clips[0]
    mark_a = song.marks[0]
    v0, l0, m0 = video_a.start_seconds, ltc_a.timeline_start_seconds, mark_a.time_seconds

    stack = UndoStack()
    cmd = GroupMoveCommand(
        video_changes={video_a.id: ((v0, video_a.source_in_seconds, video_a.duration_seconds), (v0 + 5.0, video_a.source_in_seconds, video_a.duration_seconds))},
        ltc_changes={ltc_a.id: ((l0, ltc_a.duration_seconds, ltc_a.start_timecode), (l0 + 5.0, ltc_a.duration_seconds, ltc_a.start_timecode))},
        mark_changes={mark_a.id: (m0, m0 + 5.0)},
    )
    # Apply once (as the caller does before pushing), then push for undo/redo.
    cmd.redo(song)
    stack.push(cmd, song_id=song.id)
    assert video_a.start_seconds == pytest.approx(v0 + 5.0)

    result = stack.undo(song)
    assert result is not None
    assert video_a.start_seconds == pytest.approx(v0)
    assert ltc_a.timeline_start_seconds == pytest.approx(l0)
    assert mark_a.time_seconds == pytest.approx(m0)

    result = stack.redo(song)
    assert result is not None
    assert video_a.start_seconds == pytest.approx(v0 + 5.0)
    assert ltc_a.timeline_start_seconds == pytest.approx(l0 + 5.0)
    assert mark_a.time_seconds == pytest.approx(m0 + 5.0)


def test_single_item_click_drag_still_works_without_regression(
    app: QApplication, tmp_path: Path
) -> None:
    """A lone selected clip drags itself only — no group-drag path taken."""
    del app
    song = _setup_song(tmp_path)
    tl = _build_widget(song)
    video_a = song.video_clips[0]
    ltc_a = song.ltc_clips[0]
    mark_a = song.marks[0]
    l0 = ltc_a.timeline_start_seconds
    m0 = mark_a.time_seconds

    clip_body_x = tl._x_for_time((video_a.start_seconds + video_a.end_seconds) / 2)  # noqa: SLF001
    clip_body_y = tl._video_lane_top_y() + 15  # noqa: SLF001
    _press(tl, clip_body_x, clip_body_y)
    assert not tl._group_dragging  # noqa: SLF001
    assert tl.selected_video_clip_ids() == [video_a.id]
    drag_dx = 5.0 * tl._pixels_per_second  # noqa: SLF001
    _move(tl, clip_body_x + drag_dx, clip_body_y)
    _release(tl, clip_body_x + drag_dx, clip_body_y)

    assert video_a.start_seconds == pytest.approx(15.0, abs=1e-6)
    # Nothing else moved — this was a single-item drag, not a group move.
    assert ltc_a.timeline_start_seconds == pytest.approx(l0, abs=1e-6)
    assert mark_a.time_seconds == pytest.approx(m0, abs=1e-6)


def test_single_clip_trim_still_works_without_regression(app: QApplication, tmp_path: Path) -> None:
    del app
    song = _setup_song(tmp_path)
    tl = _build_widget(song)
    video_a = song.video_clips[0]

    left_x = tl._x_for_time(video_a.start_seconds)  # noqa: SLF001
    y = tl._video_lane_top_y() + 15  # noqa: SLF001
    _press(tl, left_x, y)
    assert tl._trimming_clip is not None  # noqa: SLF001
    dx = 2.0 * tl._pixels_per_second  # noqa: SLF001
    _move(tl, left_x + dx, y)
    _release(tl, left_x + dx, y)

    assert video_a.start_seconds == pytest.approx(12.0, abs=1e-6)
