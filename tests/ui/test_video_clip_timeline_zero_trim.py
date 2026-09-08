"""Video clip left-trim-at-zero hit area and body-move clamp regression tests.

Narrow scope: a Video Clip whose timeline_start_seconds == 0 sits with its
left edge exactly on the header/timeline-zero boundary. Two issues are
covered here:

1. The left trim handle's hit area must live *inside* the clip so it can be
   grabbed even at timeline 0 (not just to the left of the edge, which is
   outside the viewport / over the header-width splitter).
2. Dragging the clip *body* (not trimming) must clamp hard at
   timeline_start_seconds == 0 without touching trim/source state.

Uses a fake (nonexistent) media path — no real .mp4 bytes, no waveform
worker involvement.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song, VideoClip
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _timeline_with_clip(app: QApplication, clip: VideoClip) -> TimelineWidget:
    timeline = TimelineWidget()
    song = Song.create("Video Trim")
    song.duration_seconds = 60.0
    song.video_clips = [clip]
    timeline.resize(1200, 600)
    timeline.set_song(song)
    timeline.set_show_video_track(True)
    timeline.show()
    app.processEvents()
    return timeline


def _video_lane_y(timeline: TimelineWidget) -> int:
    # Hit-testing only covers the base clip row (_video_lane_base_height),
    # not the extra per-clip volume-fader chrome row below it.
    return int(timeline._video_lane_top_y() + timeline._video_lane_base_height / 2)


def _make_clip(
    *, start: float = 0.0, source_in: float = 0.0, duration: float = 10.0
) -> VideoClip:
    return VideoClip.create(
        "clip",
        Path("Z:/nonexistent/does-not-exist.mp4"),
        start_seconds=start,
        source_in_seconds=source_in,
        duration_seconds=duration,
        source_duration_seconds=60.0,
    )


def test_left_trim_hit_area_inside_clip_at_zero(app: QApplication) -> None:
    """TEST A: start==0, click just inside the clip's left edge -> left trim."""
    clip = _make_clip(start=0.0, duration=10.0)
    timeline = _timeline_with_clip(app, clip)
    y = _video_lane_y(timeline)
    x0 = timeline._x_for_time(0.0)
    x_inside = x0 + 3  # a few px inside the clip's left edge
    hit = timeline._hit_video_clip(x_inside, y)
    assert hit is not None
    assert hit == (clip.id, "left")


def test_left_trim_drag_right_from_zero(app: QApplication) -> None:
    """TEST B: left trim handle dragged right -> start > 0, duration shrinks."""
    clip = _make_clip(start=0.0, source_in=0.0, duration=10.0)
    timeline = _timeline_with_clip(app, clip)
    y = _video_lane_y(timeline)
    x0 = timeline._x_for_time(0.0)

    QTest.mousePress(timeline, Qt.MouseButton.LeftButton, pos=QPoint(int(x0) + 3, y))
    app.processEvents()
    pps = float(getattr(timeline, "_pixels_per_second"))
    QTest.mouseMove(timeline, QPoint(int(x0 + 2.0 * pps), y))
    app.processEvents()
    QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, pos=QPoint(int(x0 + 2.0 * pps), y))
    app.processEvents()

    updated = timeline._song.video_clip_by_id(clip.id)
    assert updated is not None
    assert updated.start_seconds > 0.0
    assert updated.duration_seconds < 10.0
    assert updated.source_in_seconds == pytest.approx(updated.start_seconds)


def test_left_trim_extend_stops_at_zero(app: QApplication) -> None:
    """TEST C: an already head-trimmed clip can restore media left, capped at 0."""
    clip = _make_clip(start=5.0, source_in=5.0, duration=10.0)
    timeline = _timeline_with_clip(app, clip)
    y = _video_lane_y(timeline)
    x0 = timeline._x_for_time(5.0)
    pps = float(getattr(timeline, "_pixels_per_second"))

    QTest.mousePress(timeline, Qt.MouseButton.LeftButton, pos=QPoint(int(x0) + 3, y))
    app.processEvents()
    # Drag far left — well past timeline 0.
    target_x = int(x0 - 20.0 * pps)
    QTest.mouseMove(timeline, QPoint(target_x, y))
    app.processEvents()
    QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, pos=QPoint(target_x, y))
    app.processEvents()

    updated = timeline._song.video_clip_by_id(clip.id)
    assert updated is not None
    assert updated.start_seconds == pytest.approx(0.0, abs=1e-6)
    assert updated.start_seconds >= 0.0
    assert updated.source_in_seconds == pytest.approx(0.0, abs=1e-6)


def test_body_drag_left_clamps_at_zero_without_trim(app: QApplication) -> None:
    """TEST D: dragging the clip body past 0 clamps start only; no trim/offset change."""
    clip = _make_clip(start=10.0, source_in=5.0, duration=30.0)
    timeline = _timeline_with_clip(app, clip)
    y = _video_lane_y(timeline)
    x_body = timeline._x_for_time(15.0)  # well inside the body, away from edges
    pps = float(getattr(timeline, "_pixels_per_second"))

    QTest.mousePress(timeline, Qt.MouseButton.LeftButton, pos=QPoint(int(x_body), y))
    app.processEvents()
    target_x = int(x_body - 20.0 * pps)  # 20s left drag from a 10s start
    QTest.mouseMove(timeline, QPoint(target_x, y))
    app.processEvents()
    QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, pos=QPoint(target_x, y))
    app.processEvents()

    updated = timeline._song.video_clip_by_id(clip.id)
    assert updated is not None
    assert updated.start_seconds == pytest.approx(0.0, abs=1e-6)
    assert updated.duration_seconds == pytest.approx(30.0, abs=1e-6)
    assert updated.source_in_seconds == pytest.approx(5.0, abs=1e-6)


def test_body_drag_stays_pinned_at_zero_no_jitter(app: QApplication) -> None:
    """TEST E: continuing to drag left from 0 keeps the clip stable at 0."""
    clip = _make_clip(start=0.0, source_in=5.0, duration=20.0)
    timeline = _timeline_with_clip(app, clip)
    y = _video_lane_y(timeline)
    x_body = timeline._x_for_time(10.0)
    pps = float(getattr(timeline, "_pixels_per_second"))

    QTest.mousePress(timeline, Qt.MouseButton.LeftButton, pos=QPoint(int(x_body), y))
    app.processEvents()
    for extra in (5.0, 15.0, 30.0):
        QTest.mouseMove(timeline, QPoint(int(x_body - extra * pps), y))
        app.processEvents()
        updated = timeline._song.video_clip_by_id(clip.id)
        assert updated is not None
        assert updated.start_seconds == pytest.approx(0.0, abs=1e-6)
        assert updated.source_in_seconds == pytest.approx(5.0, abs=1e-6)
        assert updated.duration_seconds == pytest.approx(20.0, abs=1e-6)
    QTest.mouseRelease(
        timeline, Qt.MouseButton.LeftButton, pos=QPoint(int(x_body - 30.0 * pps), y)
    )
    app.processEvents()


def test_group_move_left_clamps_earliest_at_zero_preserves_spacing(app: QApplication) -> None:
    """TEST F: multi-selected group dragged left clamps as one; relative gaps stay."""
    clip_a = _make_clip(start=5.0, source_in=0.0, duration=10.0)
    clip_b = VideoClip.create(
        "clip_b",
        Path("Z:/nonexistent/does-not-exist-2.mp4"),
        start_seconds=20.0,
        duration_seconds=10.0,
        source_duration_seconds=60.0,
    )
    timeline = _timeline_with_clip(app, clip_a)
    timeline._song.video_clips.append(clip_b)
    timeline.set_selected_video_clip_ids([clip_a.id, clip_b.id])

    y = _video_lane_y(timeline)
    x_body = timeline._x_for_time(7.0)  # inside clip_a's body
    pps = float(getattr(timeline, "_pixels_per_second"))

    QTest.mousePress(timeline, Qt.MouseButton.LeftButton, pos=QPoint(int(x_body), y))
    app.processEvents()
    target_x = int(x_body - 30.0 * pps)  # far past what would push clip_a negative
    QTest.mouseMove(timeline, QPoint(target_x, y))
    app.processEvents()
    QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, pos=QPoint(target_x, y))
    app.processEvents()

    a = timeline._song.video_clip_by_id(clip_a.id)
    b = timeline._song.video_clip_by_id(clip_b.id)
    assert a is not None and b is not None
    assert a.start_seconds == pytest.approx(0.0, abs=1e-6)
    # Original gap between clip_a and clip_b start was 15s — preserved.
    assert (b.start_seconds - a.start_seconds) == pytest.approx(15.0, abs=1e-6)
