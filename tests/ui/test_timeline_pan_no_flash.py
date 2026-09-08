"""Middle-button pan must not flash Mark+wave on release."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from cueplayer.diagnostics import perf as perf_diag
from cueplayer.domain.models import Song
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_middle_pan_release_does_not_invalidate_backdrop(app: QApplication) -> None:
    del app
    perf_diag.set_enabled(True)
    perf_diag.clear()
    tl = TimelineWidget()
    tl.resize(800, 400)
    tl.show()
    song = Song.create("Pan")
    song.duration_seconds = 120.0
    tl.set_song(song)
    tl._pixels_per_second = 40.0  # noqa: SLF001
    tl._rebuild_scrub_backdrop(reason="seed")  # noqa: SLF001
    pm_before = tl._scrub_backdrop  # noqa: SLF001
    assert pm_before is not None and not pm_before.isNull()

    # Middle-button drag pan across the waveform.
    press = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPoint(400, 120),
        Qt.MouseButton.MiddleButton,
        Qt.MouseButton.MiddleButton,
        Qt.KeyboardModifier.NoModifier,
    )
    tl.mousePressEvent(press)
    assert tl._panning  # noqa: SLF001
    move = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPoint(340, 120),
        Qt.MouseButton.MiddleButton,
        Qt.MouseButton.MiddleButton,
        Qt.KeyboardModifier.NoModifier,
    )
    tl.mouseMoveEvent(move)
    assert tl._pan_moved  # noqa: SLF001
    release = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        QPoint(340, 120),
        Qt.MouseButton.MiddleButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    tl.mouseReleaseEvent(release)

    assert tl._scrub_backdrop is pm_before  # noqa: SLF001
    assert not tl._view_transform_busy  # noqa: SLF001
    assert int(
        perf_diag.snapshot()["counters"].get("timeline.pan.release_no_invalidate", 0)
    ) >= 1
    # Must not have counted a mark-backdrop miss from pan release.
    assert (
        int(
            perf_diag.snapshot()["counters"].get(
                "timeline.mark_backdrop.rebuild_reason.generic", 0
            )
        )
        == 0
    )
    perf_diag.set_enabled(False)


def test_wheel_pan_does_not_schedule_zoom_final_rebuild(app: QApplication) -> None:
    del app
    perf_diag.set_enabled(True)
    perf_diag.clear()
    tl = TimelineWidget()
    tl.resize(800, 400)
    song = Song.create("WheelPan")
    song.duration_seconds = 120.0
    tl.set_song(song)
    tl._rebuild_scrub_backdrop(reason="seed")  # noqa: SLF001
    finals0 = int(perf_diag.snapshot()["counters"].get("timeline.zoom.final_rebuilds", 0))
    tl._apply_wheel_pan(40.0)  # noqa: SLF001
    assert not tl._view_transform_busy  # noqa: SLF001
    assert not tl._zoom_quality_timer.isActive()  # noqa: SLF001
    # Idle finish must not fire a final rebuild for pan-only.
    tl._finish_view_transform_gesture()  # noqa: SLF001
    finals1 = int(perf_diag.snapshot()["counters"].get("timeline.zoom.final_rebuilds", 0))
    assert finals1 == finals0
    perf_diag.set_enabled(False)


def test_zoom_idle_debounce_at_least_250ms(app: QApplication) -> None:
    del app
    tl = TimelineWidget()
    assert tl._view_transform_debounce_ms >= 250  # noqa: SLF001
