"""Mouse-up / mouse-down / drag must share one canonical static Timeline backdrop."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QImage, QMouseEvent
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cueplayer.domain.models import Mark, Song, VideoClip
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _song_video_and_edge_marks() -> Song:
    """Video lane + Marks at viewport edges (edge overlap is allowed / preserved)."""
    song = Song.create("滑鼠靜態對齊")
    song.show_video_track = True
    song.duration_seconds = 40.0
    lane = song.mark_lanes[0]
    lane.visible = True
    lane.show_note_on_wave = True
    # Sparse center so scrub clicks miss Mark hit-tests; edges still present.
    song.marks = [
        Mark.create(lane_index=lane.index, time_seconds=0.05, display_name="LEFT"),
        Mark.create(lane_index=lane.index, time_seconds=2.5, display_name="A"),
        Mark.create(lane_index=lane.index, time_seconds=12.0, display_name="B"),
        Mark.create(lane_index=lane.index, time_seconds=38.5, display_name="RIGHT"),
    ]
    song.sort_marks()
    song.add_video_clip(
        VideoClip.create(
            name="ClipNameVisible",
            path=Path("dummy_clip.mp4"),
            start_seconds=1.0,
            duration_seconds=8.0,
        )
    )
    return song


def _song_dense_marks() -> Song:
    song = _song_video_and_edge_marks()
    lane = song.mark_lanes[0]
    extra = [
        Mark.create(
            lane_index=lane.index,
            time_seconds=i * 0.12,
            display_name=f"M{i}",
        )
        for i in range(60)
    ]
    song.marks = list(song.marks) + extra
    song.sort_marks()
    return song


def _render(tl: TimelineWidget) -> QImage:
    img = QImage(tl.size(), QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.black)
    tl.render(img)
    return img


def _mask_columns(img: QImage, xs: set[int], *, pad: int = 20) -> QImage:
    out = img.copy()
    for cx in xs:
        for x in range(max(0, cx - pad), min(out.width(), cx + pad + 1)):
            for y in range(out.height()):
                out.setPixel(x, y, 0)
    return out


def _dynamic_xs(tl: TimelineWidget, *extra_times: float) -> set[int]:
    xs: set[int] = set()
    xs.add(int(round(tl._device_snap(tl._x_for_time(tl._position)))))  # noqa: SLF001
    for mid in tl._selected_mark_ids:  # noqa: SLF001
        mark = tl._song.mark_by_id(mid) if tl._song else None  # noqa: SLF001
        if mark is not None:
            xs.add(int(round(tl._device_snap(tl._x_for_time(mark.time_seconds)))))  # noqa: SLF001
    for t in extra_times:
        xs.add(int(round(tl._device_snap(tl._x_for_time(float(t))))))  # noqa: SLF001
    return xs


def _pixel_diff(a: QImage, b: QImage) -> int:
    if a.size() != b.size():
        return a.width() * a.height()
    n = 0
    for y in range(a.height()):
        for x in range(a.width()):
            if a.pixel(x, y) != b.pixel(x, y):
                n += 1
    return n


def _mouse(etype: QEvent.Type, x: float, y: float, *, buttons: Qt.MouseButton) -> QMouseEvent:
    button = (
        Qt.MouseButton.LeftButton
        if etype != QEvent.Type.MouseMove
        else Qt.MouseButton.NoButton
    )
    return QMouseEvent(
        etype,
        QPointF(x, y),
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


def test_mouse_up_down_drag_share_static_backdrop(app: QApplication) -> None:
    tl = TimelineWidget()
    tl.resize(960, 480)
    tl.show()
    app.processEvents()
    tl.set_song(_song_video_and_edge_marks())
    tl.set_show_video_track(True)
    tl.set_auto_scroll(False)
    tl.set_position(5.0)
    tl._rebuild_scrub_backdrop(reason="mouse_parity")  # noqa: SLF001
    app.processEvents()

    assert tl._can_use_static_backdrop() is True  # noqa: SLF001
    assert tl._video_lane_visible() is True  # noqa: SLF001
    held = tl._scrub_backdrop  # noqa: SLF001
    assert held is not None and not held.isNull()

    wave_y = float(tl._ruler_height + tl._wave_height // 2)
    scrub_x = float(tl._header_width + 220)
    assert tl._hit_mark_at(scrub_x, wave_y) is None  # noqa: SLF001
    assert tl._in_scrub_zone(scrub_x, wave_y)  # noqa: SLF001

    idle = _render(tl)
    # Mouse-down on waveform (scrub) without movement.
    tl.mousePressEvent(
        _mouse(QEvent.Type.MouseButtonPress, scrub_x, wave_y, buttons=Qt.MouseButton.LeftButton)
    )
    app.processEvents()
    assert tl._scrubbing is True  # noqa: SLF001
    assert tl._can_use_static_backdrop() is True  # noqa: SLF001
    assert tl._scrub_backdrop is held  # noqa: SLF001
    down = _render(tl)

    # Drag a short distance (still scrubbing) — playhead moves.
    tl.mouseMoveEvent(
        _mouse(
            QEvent.Type.MouseMove,
            scrub_x + 48,
            wave_y,
            buttons=Qt.MouseButton.LeftButton,
        )
    )
    app.processEvents()
    assert tl._can_use_static_backdrop() is True  # noqa: SLF001
    assert tl._scrub_backdrop is held  # noqa: SLF001
    drag = _render(tl)

    tl.mouseReleaseEvent(
        _mouse(
            QEvent.Type.MouseButtonRelease,
            scrub_x + 48,
            wave_y,
            buttons=Qt.MouseButton.NoButton,
        )
    )
    app.processEvents()
    assert tl._scrubbing is False  # noqa: SLF001
    assert tl._scrub_backdrop is held  # noqa: SLF001
    released = _render(tl)

    # Mask playhead columns across all states (union of positions).
    xs = set()
    for img_tl_pos in (5.0, tl._position):  # noqa: SLF001
        xs |= _dynamic_xs(tl, float(img_tl_pos))
    # Also mask the scrub X range the playhead traveled.
    for t in (tl._time_for_x(scrub_x), tl._time_for_x(scrub_x + 48)):  # noqa: SLF001
        xs |= _dynamic_xs(tl, float(t))
    idle_m = _mask_columns(idle, xs)
    down_m = _mask_columns(down, xs)
    drag_m = _mask_columns(drag, xs)
    up_m = _mask_columns(released, xs)

    assert _pixel_diff(idle_m, down_m) == 0, "mouse-down changed static pixels"
    assert _pixel_diff(idle_m, drag_m) == 0, "drag changed static pixels"
    assert _pixel_diff(idle_m, up_m) == 0, "release changed static pixels"


def test_mark_press_keeps_same_static_cache(app: QApplication) -> None:
    tl = TimelineWidget()
    tl.resize(900, 460)
    tl.show()
    app.processEvents()
    tl.set_song(_song_dense_marks())
    tl.set_show_video_track(True)
    tl.set_auto_scroll(False)
    tl.set_position(4.0)
    tl._rebuild_scrub_backdrop(reason="mark_press")  # noqa: SLF001
    app.processEvents()
    held = tl._scrub_backdrop  # noqa: SLF001

    idle = _render(tl)
    mark = tl._song.marks[10]  # noqa: SLF001
    mx = tl._x_for_time(mark.time_seconds)  # noqa: SLF001
    tracks_top = tl._tracks_top_y()  # noqa: SLF001
    tl.mousePressEvent(
        _mouse(
            QEvent.Type.MouseButtonPress,
            mx,
            tracks_top + 8,
            buttons=Qt.MouseButton.LeftButton,
        )
    )
    app.processEvents()
    assert tl._dragging_marks is True  # noqa: SLF001
    assert tl._can_use_static_backdrop() is True  # noqa: SLF001
    assert tl._scrub_backdrop is held  # noqa: SLF001
    pressed = _render(tl)
    # Mask playhead + the pressed Mark stem (selection overlay only).
    xs = _dynamic_xs(tl, mark.time_seconds)
    assert _pixel_diff(_mask_columns(idle, xs), _mask_columns(pressed, xs)) == 0
    tl.mouseReleaseEvent(
        _mouse(
            QEvent.Type.MouseButtonRelease,
            mx,
            tracks_top + 8,
            buttons=Qt.MouseButton.NoButton,
        )
    )


def test_video_lane_region_unchanged_on_scrub_press(app: QApplication) -> None:
    """Black strip / Video name must not pop only because LMB is held."""
    tl = TimelineWidget()
    tl.resize(960, 480)
    tl.show()
    app.processEvents()
    tl.set_song(_song_video_and_edge_marks())
    tl.set_show_video_track(True)
    tl.set_auto_scroll(False)
    tl.set_position(5.0)
    tl._rebuild_scrub_backdrop(reason="video_lane")  # noqa: SLF001
    app.processEvents()

    def _lane_strip(img: QImage) -> QImage:
        top = tl._video_lane_top_y()  # noqa: SLF001
        h = max(1, int(tl._video_lane_height) + 8)
        return img.copy(0, max(0, top - 4), img.width(), h)

    wave_y = float(tl._ruler_height + 40)
    scrub_x = float(tl._header_width + 220)
    assert tl._hit_mark_at(scrub_x, wave_y) is None  # noqa: SLF001

    idle_pos = float(tl._position)  # noqa: SLF001
    idle_lane = _lane_strip(_render(tl))
    tl.mousePressEvent(
        _mouse(QEvent.Type.MouseButtonPress, scrub_x, wave_y, buttons=Qt.MouseButton.LeftButton)
    )
    app.processEvents()
    assert tl._scrubbing is True  # noqa: SLF001
    assert tl._can_use_static_backdrop() is True  # noqa: SLF001
    down_lane = _lane_strip(_render(tl))
    # Scrub press seeks playhead — mask both old and new playhead columns.
    xs = _dynamic_xs(tl, idle_pos, tl._time_for_x(scrub_x))  # noqa: SLF001
    assert _pixel_diff(_mask_columns(idle_lane, xs), _mask_columns(down_lane, xs)) == 0
    tl.mouseReleaseEvent(
        _mouse(
            QEvent.Type.MouseButtonRelease,
            scrub_x,
            wave_y,
            buttons=Qt.MouseButton.NoButton,
        )
    )
