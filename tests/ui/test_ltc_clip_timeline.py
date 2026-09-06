"""Timeline interaction for LTC generator clips (Phase 3, UI layer).

Covers: clip lane visibility per resolved mode, body drag, left/right trim
(left trim keeps the start timecode), overlap clamp, selection, and the
edit-request signals (double-click + empty-lane add).
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _timeline_with_song(app: QApplication, *, mode: str, clips=None) -> TimelineWidget:
    timeline = TimelineWidget()
    song = Song.create("LTC")
    song.duration_seconds = 60.0
    song.ltc_source_mode = mode
    if clips:
        song.ltc_clips = list(clips)
    timeline.resize(1200, 600)
    timeline.set_song(song)
    timeline.set_show_video_track(True)
    timeline.set_ltc_source_mode(mode)
    timeline.show()
    app.processEvents()
    return timeline


def _ltc_lane_y(timeline: TimelineWidget) -> int:
    return int(timeline._ltc_lane_top_y() + timeline._ltc_band_height() / 2)


def _pps(timeline: TimelineWidget) -> float:
    # getattr() instead of direct LOAD_ATTR: PySide6's QObject attribute
    # wrapper intermittently raises AttributeError for direct private reads
    # from outside the class (reproduced in offscreen test runs). getattr()
    # and method calls are stable, so tests read the zoom level through it.
    return float(getattr(timeline, "_pixels_per_second"))


def test_clip_lane_visible_without_stripe_audio_in_clip_mode(app: QApplication) -> None:
    timeline = _timeline_with_song(app, mode="clip_generator")
    assert timeline._ltc_clip_lane_active()
    assert timeline._ltc_lane_visible()
    # No stripe audio fed — the lane still shows (clip editing lane).
    assert timeline._ltc_audio is None
    assert timeline._ltc_band_height() > 0


@pytest.mark.parametrize("mode", ["off", "striped_file", "full_track_generator"])
def test_clip_lane_inactive_in_other_modes(app: QApplication, mode: str) -> None:
    timeline = _timeline_with_song(app, mode=mode)
    assert not timeline._ltc_clip_lane_active()
    assert timeline._ltc_audio is None
    assert timeline._ltc_band_height() == 0


def test_body_drag_moves_clip_and_emits_edit_once(app: QApplication) -> None:
    from cueplayer.domain.ltc_clips import add_ltc_clip

    timeline = _timeline_with_song(app, mode="clip_generator")
    song = getattr(timeline, "_song")
    clip = add_ltc_clip(song, timeline_start_seconds=10.0, duration_seconds=20.0, start_timecode="01:00:05:00")
    emitted: list[tuple] = []
    timeline.ltc_clip_edited.connect(lambda *a: emitted.append(a))

    y = _ltc_lane_y(timeline)
    start = QPoint(int(round(timeline._x_for_time(15.0))), y)
    end = QPoint(start.x() + int(round(5.0 * _pps(timeline))), y)
    QTest.mousePress(timeline, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(timeline, end, delay=10)
    QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, pos=end)

    assert len(emitted) == 1
    clip_id, old, new = emitted[0]
    assert clip_id == clip.id
    assert old == (10.0, 20.0, "01:00:05:00")
    assert new[0] == pytest.approx(15.0, abs=0.05)
    assert new[1] == pytest.approx(20.0, abs=1e-9)
    assert new[2] == "01:00:05:00"  # body drag never changes the start TC
    assert clip.timeline_start_seconds == pytest.approx(new[0], abs=0.05)
    assert clip.start_timecode == "01:00:05:00"


def test_left_trim_keeps_start_timecode(app: QApplication) -> None:
    from cueplayer.domain.ltc_clips import add_ltc_clip

    timeline = _timeline_with_song(app, mode="clip_generator")
    song = getattr(timeline, "_song")
    clip = add_ltc_clip(song, timeline_start_seconds=10.0, duration_seconds=20.0, start_timecode="01:00:05:00")
    emitted: list[tuple] = []
    timeline.ltc_clip_edited.connect(lambda *a: emitted.append(a))

    y = _ltc_lane_y(timeline)
    # Press right on the left edge (inside the forgiving hit band).
    start = QPoint(int(round(timeline._x_for_time(10.0))), y)
    end = QPoint(start.x() - int(round(5.0 * _pps(timeline))), y)
    QTest.mousePress(timeline, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(timeline, end, delay=10)
    QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, pos=end)

    assert len(emitted) == 1
    _cid, old, new = emitted[0]
    assert old == (10.0, 20.0, "01:00:05:00")
    assert new[0] == pytest.approx(5.0, abs=0.05)
    assert new[1] == pytest.approx(25.0, abs=0.05)  # duration grows by the same span
    assert new[2] == "01:00:05:00"  # the new head still sends the original start TC
    assert clip.start_timecode == "01:00:05:00"
    assert clip.timeline_start_seconds == pytest.approx(5.0, abs=0.05)
    assert clip.duration_seconds == pytest.approx(25.0, abs=0.05)


def test_right_trim_extends_clip(app: QApplication) -> None:
    from cueplayer.domain.ltc_clips import add_ltc_clip

    timeline = _timeline_with_song(app, mode="clip_generator")
    song = getattr(timeline, "_song")
    clip = add_ltc_clip(song, timeline_start_seconds=10.0, duration_seconds=20.0, start_timecode="01:00:05:00")

    y = _ltc_lane_y(timeline)
    start = QPoint(int(round(timeline._x_for_time(30.0))), y)
    end = QPoint(start.x() + int(round(5.0 * _pps(timeline))), y)
    QTest.mousePress(timeline, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(timeline, end, delay=10)
    QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, pos=end)

    assert clip.timeline_start_seconds == pytest.approx(10.0, abs=1e-9)
    assert clip.duration_seconds == pytest.approx(25.0, abs=0.05)


def test_drag_is_clamped_away_from_neighbour(app: QApplication) -> None:
    from cueplayer.domain.ltc_clips import add_ltc_clip

    timeline = _timeline_with_song(app, mode="clip_generator")
    song = getattr(timeline, "_song")
    left = add_ltc_clip(song, timeline_start_seconds=0.0, duration_seconds=10.0, start_timecode="01:00:00:00")
    right = add_ltc_clip(song, timeline_start_seconds=25.0, duration_seconds=10.0, start_timecode="01:00:10:00")

    y = _ltc_lane_y(timeline)
    # Drag the left clip far enough right to collide with the right clip —
    # it must park touching the neighbour's left edge (no overlap).
    start = QPoint(int(round(timeline._x_for_time(5.0))), y)
    end = QPoint(start.x() + int(round(25.0 * _pps(timeline))), y)
    QTest.mousePress(timeline, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(timeline, end, delay=10)
    QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, pos=end)

    assert left.timeline_start_seconds == pytest.approx(15.0, abs=0.02)
    assert left.end_seconds <= right.timeline_start_seconds + 1e-9

    # Drag the right clip left into the left clip's territory — it is pushed
    # back out to the neighbour's end (touching, no overlap).
    start2 = QPoint(int(round(timeline._x_for_time(30.0))), y)
    end2 = QPoint(start2.x() - int(round(15.0 * _pps(timeline))), y)
    QTest.mousePress(timeline, Qt.MouseButton.LeftButton, pos=start2)
    QTest.mouseMove(timeline, end2, delay=10)
    QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, pos=end2)

    assert right.timeline_start_seconds == pytest.approx(25.0, abs=0.02)

    # Drag it further left — now it clears the gap and moves freely.
    start3 = QPoint(int(round(timeline._x_for_time(30.0))), y)
    end3 = QPoint(start3.x() - int(round(20.0 * _pps(timeline))), y)
    QTest.mousePress(timeline, Qt.MouseButton.LeftButton, pos=start3)
    QTest.mouseMove(timeline, end3, delay=10)
    QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, pos=end3)

    assert right.timeline_start_seconds == pytest.approx(5.0, abs=0.02)


def test_left_trim_clamped_at_previous_clip(app: QApplication) -> None:
    from cueplayer.domain.ltc_clips import add_ltc_clip

    timeline = _timeline_with_song(app, mode="clip_generator")
    song = getattr(timeline, "_song")
    prev = add_ltc_clip(song, timeline_start_seconds=0.0, duration_seconds=8.0, start_timecode="01:00:00:00")
    clip = add_ltc_clip(song, timeline_start_seconds=10.0, duration_seconds=10.0, start_timecode="01:00:05:00")

    y = _ltc_lane_y(timeline)
    start = QPoint(int(round(timeline._x_for_time(10.0))), y)
    end = QPoint(start.x() - int(round(12.0 * _pps(timeline))), y)
    QTest.mousePress(timeline, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(timeline, end, delay=10)
    QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, pos=end)

    assert clip.timeline_start_seconds == pytest.approx(prev.end_seconds, abs=0.02)
    assert clip.start_timecode == "01:00:05:00"


def test_click_empty_lane_clears_ltc_selection(app: QApplication) -> None:
    from cueplayer.domain.ltc_clips import add_ltc_clip

    timeline = _timeline_with_song(app, mode="clip_generator")
    song = getattr(timeline, "_song")
    clip = add_ltc_clip(song, timeline_start_seconds=10.0, duration_seconds=10.0, start_timecode="01:00:05:00")
    timeline.set_selected_ltc_clip_ids([clip.id])

    y = _ltc_lane_y(timeline)
    QTest.mouseClick(timeline, Qt.MouseButton.LeftButton, pos=QPoint(int(round(timeline._x_for_time(50.0))), y))
    assert timeline.selected_ltc_clip_ids() == []


def test_double_click_body_emits_edit_request(app: QApplication) -> None:
    from cueplayer.domain.ltc_clips import add_ltc_clip

    timeline = _timeline_with_song(app, mode="clip_generator")
    song = getattr(timeline, "_song")
    clip = add_ltc_clip(song, timeline_start_seconds=10.0, duration_seconds=10.0, start_timecode="01:00:05:00")
    edits: list[str] = []
    timeline.edit_ltc_clip_requested.connect(edits.append)

    pos = QPoint(int(round(timeline._x_for_time(15.0))), _ltc_lane_y(timeline))
    # PySide's QTest.mouseDClick sends only the doubleClick event, so drive
    # the two press/release pairs manually first (as a real double-click does).
    QTest.mousePress(timeline, Qt.MouseButton.LeftButton, pos=pos)
    QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, pos=pos)
    QTest.mousePress(timeline, Qt.MouseButton.LeftButton, pos=pos)
    QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, pos=pos)
    QTest.mouseDClick(timeline, Qt.MouseButton.LeftButton, pos=pos)

    assert edits == [clip.id]
    assert timeline.selected_ltc_clip_ids() == [clip.id]


def test_delete_key_deletes_selected_ltc_clips(app: QApplication) -> None:
    from cueplayer.domain.ltc_clips import add_ltc_clip

    timeline = _timeline_with_song(app, mode="clip_generator")
    song = getattr(timeline, "_song")
    clip = add_ltc_clip(song, timeline_start_seconds=10.0, duration_seconds=10.0, start_timecode="01:00:05:00")
    deleted: list[list] = []
    timeline.delete_ltc_clips_requested.connect(deleted.append)
    timeline.set_selected_ltc_clip_ids([clip.id])

    QTest.keyClick(timeline, Qt.Key.Key_Delete)

    assert deleted == [[clip.id]]
