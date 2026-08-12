from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import BeatGridRegion, Song
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_clicking_beat_grid_selects_it_and_still_seeks(app: QApplication) -> None:
    timeline = TimelineWidget()
    song = Song.create("Grid")
    song.duration_seconds = 10.0
    grid = BeatGridRegion.create(1.0, 8.0, bpm=120.0)
    song.beat_grids.append(grid)
    timeline.resize(900, 500)
    timeline.set_song(song)
    timeline.show()
    app.processEvents()
    sought: list[float] = []
    timeline.seek_requested.connect(sought.append)

    # Click inside the forgiving hit band, not exactly on the painted line.
    x = int(round(timeline._x_for_time(2.0))) + 12
    y = timeline._ruler_height + 60
    QTest.mouseClick(timeline, Qt.MouseButton.LeftButton, pos=QPoint(x, y))

    assert timeline._selected_beat_grid_id == grid.id
    assert sought
    assert sought[-1] == pytest.approx(2.0, abs=0.02)


def test_setup_drag_moves_entire_grid(app: QApplication) -> None:
    timeline = TimelineWidget()
    song = Song.create("Grid drag")
    song.duration_seconds = 10.0
    grid = BeatGridRegion.create(1.0, 5.0, bpm=120.0)
    song.beat_grids.append(grid)
    timeline.resize(900, 500)
    timeline.set_song(song)
    timeline.show()
    timeline._setup_mode = True
    app.processEvents()

    start = QPoint(int(round(timeline._x_for_time(2.0))), timeline._ruler_height + 60)
    end = QPoint(start.x() + 40, start.y())
    QTest.mousePress(timeline, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(timeline, end, delay=10)
    QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, pos=end)

    assert grid.start_seconds > 1.0
    assert grid.end_seconds - grid.start_seconds == pytest.approx(4.0)


def test_setup_click_without_drag_still_seeks(app: QApplication) -> None:
    timeline = TimelineWidget()
    song = Song.create("Grid setup seek")
    song.duration_seconds = 10.0
    grid = BeatGridRegion.create(1.0, 5.0, bpm=120.0)
    song.beat_grids.append(grid)
    timeline.resize(900, 500)
    timeline.set_song(song)
    timeline.show()
    timeline._setup_mode = True
    app.processEvents()
    sought: list[float] = []
    timeline.seek_requested.connect(sought.append)

    pos = QPoint(int(round(timeline._x_for_time(2.0))) + 12, timeline._ruler_height + 60)
    QTest.mouseClick(timeline, Qt.MouseButton.LeftButton, pos=pos)

    assert sought and sought[-1] == pytest.approx(2.0, abs=0.02)
    assert grid.start_seconds == pytest.approx(1.0)


def test_only_hovered_division_is_highlighted_temporarily(app: QApplication) -> None:
    timeline = TimelineWidget()
    song = Song.create("Grid hover")
    song.duration_seconds = 10.0
    grid = BeatGridRegion.create(1.0, 5.0, bpm=120.0)
    song.beat_grids.append(grid)
    timeline.resize(900, 500)
    timeline.set_song(song)
    timeline.show()
    app.processEvents()

    y = timeline._ruler_height + 60
    def move_to(x: int) -> None:
        pos = QPointF(float(x), float(y))
        timeline.mouseMoveEvent(
            QMouseEvent(
                QEvent.Type.MouseMove,
                pos,
                pos,
                Qt.MouseButton.NoButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )

    move_to(int(round(timeline._x_for_time(2.0))))
    assert timeline._hover_beat_grid_id == grid.id
    assert timeline._hover_beat_grid_index == 2
    assert timeline.cursor().shape() == Qt.CursorShape.PointingHandCursor

    timeline._setup_mode = True
    move_to(int(round(timeline._x_for_time(2.0))))
    assert timeline.cursor().shape() == Qt.CursorShape.SizeHorCursor
    timeline._setup_mode = False

    move_to(int(round(timeline._x_for_time(9.0))))
    assert timeline._hover_beat_grid_id is None
    assert timeline._hover_beat_grid_index is None


def test_grid_hit_area_is_centered_on_painted_line(app: QApplication) -> None:
    timeline = TimelineWidget()
    song = Song.create("Grid hit")
    song.duration_seconds = 10.0
    grid = BeatGridRegion.create(1.0, 5.0, bpm=120.0)
    song.beat_grids.append(grid)
    timeline.resize(900, 500)
    timeline.set_song(song)
    timeline.show()
    app.processEvents()

    line_x = timeline._device_snap(timeline._x_for_time(2.0))
    y = timeline._ruler_height + 60
    center = timeline._hit_beat_grid_division(line_x, y)
    left = timeline._hit_beat_grid_division(line_x - 15.0, y)
    right = timeline._hit_beat_grid_division(line_x + 15.0, y)

    assert center is not None and center[1] == 2
    assert left is not None and left[1] == 2
    assert right is not None and right[1] == 2


def test_mark_hit_band_seeks_to_exact_mark_time(app: QApplication) -> None:
    timeline = TimelineWidget()
    song = Song.create("Mark snap")
    song.duration_seconds = 10.0
    mark = song.add_mark(1, 2.345)
    timeline.resize(900, 500)
    timeline.set_song(song)
    timeline.show()
    app.processEvents()
    sought: list[float] = []
    timeline.seek_requested.connect(sought.append)
    lane = next(rect for rect in timeline._lane_rects() if rect[0] == 1)
    y = int((lane[1] + lane[2]) / 2)

    QTest.mouseClick(
        timeline,
        Qt.MouseButton.LeftButton,
        pos=QPoint(int(round(timeline._x_for_time(mark.time_seconds))) + 8, y),
    )

    assert sought and sought[-1] == pytest.approx(mark.time_seconds, abs=1e-9)


def test_delete_key_requests_selected_grid_delete(app: QApplication) -> None:
    timeline = TimelineWidget()
    song = Song.create("Grid delete")
    grid = BeatGridRegion.create(1.0, 5.0)
    song.beat_grids.append(grid)
    timeline.set_song(song)
    timeline._selected_beat_grid_id = grid.id
    deleted: list[str] = []
    timeline.beat_grid_delete_requested.connect(deleted.append)

    QTest.keyClick(timeline, Qt.Key.Key_Delete)

    assert deleted == [grid.id]


def test_magnet_snaps_dragged_mark_to_nearest_grid(app: QApplication) -> None:
    timeline = TimelineWidget()
    song = Song.create("Snap")
    song.duration_seconds = 10.0
    grid = BeatGridRegion.create(1.0, 5.0, bpm=120.0)
    song.beat_grids.append(grid)
    mark = song.add_mark(1, 1.0)
    timeline.resize(900, 500)
    timeline.set_song(song)
    timeline.show()
    timeline._setup_mode = True
    timeline._beat_snap_enabled = True
    app.processEvents()
    lane = next(rect for rect in timeline._lane_rects() if rect[0] == 1)
    y = int((lane[1] + lane[2]) / 2)
    start = QPoint(int(round(timeline._x_for_time(1.0))), y)
    end = QPoint(int(round(timeline._x_for_time(1.96))), y)

    QTest.mousePress(timeline, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(timeline, end, delay=10)
    QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, pos=end)

    assert mark.time_seconds == pytest.approx(2.0, abs=1e-9)


def test_play_state_change_does_not_center_viewport(app: QApplication) -> None:
    timeline = TimelineWidget()
    song = Song.create("No transport jump")
    song.duration_seconds = 100.0
    timeline.resize(900, 500)
    timeline.set_song(song)
    timeline._pixels_per_second = 100.0
    timeline._scroll_x = 1234.0
    timeline._position = 50.0
    timeline._auto_scroll = True

    timeline.set_playing(True)
    assert timeline._scroll_x == pytest.approx(1234.0)
    timeline.set_playing(False)
    assert timeline._scroll_x == pytest.approx(1234.0)


def test_pause_freeze_blocks_final_auto_scroll_position_ticks(app: QApplication) -> None:
    timeline = TimelineWidget()
    song = Song.create("Pause freeze")
    song.duration_seconds = 100.0
    timeline.resize(900, 500)
    timeline.set_song(song)
    timeline._pixels_per_second = 100.0
    timeline._scroll_x = 1234.0
    timeline._auto_scroll = True
    timeline._playing = True
    timeline.freeze_viewport_for_pause(1000)

    timeline.set_position(80.0)

    assert timeline._position == pytest.approx(80.0)
    assert timeline._scroll_x == pytest.approx(1234.0)
    timeline._transport_view_freeze_timer.stop()
    timeline._release_transport_view_freeze()
    timeline._playing = False
    timeline.set_position(90.0)
    assert timeline._scroll_x == pytest.approx(1234.0)


def test_overlap_drag_always_prioritizes_mark(app: QApplication) -> None:
    timeline = TimelineWidget()
    song = Song.create("Overlap")
    song.duration_seconds = 10.0
    grid = BeatGridRegion.create(1.0, 5.0, bpm=120.0)
    song.beat_grids.append(grid)
    mark = song.add_mark(1, 2.0)
    timeline.resize(900, 500)
    timeline.set_song(song)
    timeline.show()
    timeline._setup_mode = True
    app.processEvents()
    pos = QPoint(
        int(round(timeline._x_for_time(2.0))), timeline._ruler_height + 60
    )

    timeline._beat_snap_enabled = True
    QTest.mousePress(timeline, Qt.MouseButton.LeftButton, pos=pos)
    assert timeline._dragging_marks is True
    assert timeline._dragging_beat_grid_id is None
    assert mark.id in timeline._drag_ids
    QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, pos=pos)

    timeline._beat_snap_enabled = False
    QTest.mousePress(timeline, Qt.MouseButton.LeftButton, pos=pos)
    assert timeline._dragging_marks is True
    assert timeline._dragging_beat_grid_id is None
    assert mark.id in timeline._drag_ids
    QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, pos=pos)

    uncovered_pos = QPoint(
        int(round(timeline._x_for_time(2.5))), timeline._ruler_height + 60
    )
    QTest.mousePress(timeline, Qt.MouseButton.LeftButton, pos=uncovered_pos)
    assert timeline._dragging_beat_grid_id == grid.id
    assert timeline._dragging_marks is False
    QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, pos=uncovered_pos)
