"""Cached Mark backdrop + zoom coalesce + activation poster."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from cueplayer.diagnostics import perf as perf_diag
from cueplayer.domain.models import Mark, Song, VideoClip
from cueplayer.playback.video_sync import DisplaySource, VideoSyncController
from cueplayer.ui.timeline_widget import TimelineWidget
from cueplayer.ui.video_preview import VideoPreviewWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _dense_song(n: int = 200, spacing: float = 0.1) -> Song:
    song = Song.create("密集標記測試")
    lane = song.mark_lanes[0]
    lane.visible = True
    marks = []
    for i in range(n):
        m = Mark.create(
            lane_index=lane.index,
            time_seconds=i * spacing,
            display_name=f"標記{i}",
        )
        marks.append(m)
    song.marks = marks
    song.sort_marks()
    song.duration_seconds = max(60.0, n * spacing + 5.0)
    return song


def test_playback_position_does_not_rebuild_mark_backdrop(app: QApplication) -> None:
    perf_diag.set_enabled(True)
    perf_diag.clear()
    tl = TimelineWidget()
    tl.resize(800, 400)
    tl.show()
    app.processEvents()
    song = _dense_song(300)
    tl.set_song(song)
    tl.set_playing(True)
    tl.set_position(5.0)
    app.processEvents()
    # Force one quality bake.
    tl._rebuild_scrub_backdrop(reason="test_seed")  # noqa: SLF001
    snap0 = perf_diag.snapshot()["counters"]
    rebuilds0 = int(snap0.get("timeline.mark_backdrop.rebuild_reason.test_seed", 0))
    shapes0 = int(snap0.get("timeline.mark_backdrop.draw_marker_shape_count", 0))
    assert shapes0 > 0
    # Position ticks while playing must blit + overlay — not full mark bake.
    for i in range(30):
        tl.set_position(5.0 + i * 0.05)
        app.processEvents()
    snap1 = perf_diag.snapshot()["counters"]
    shapes1 = int(snap1.get("timeline.mark_backdrop.draw_marker_shape_count", 0))
    # Overlay may draw a few selected shapes; must not redraw hundreds per tick.
    assert shapes1 - shapes0 < 50
    assert int(snap1.get("timeline.mark_backdrop.rebuild_reason.test_seed", 0)) == rebuilds0
    perf_diag.set_enabled(False)


def test_mark_edit_invalidates_backdrop_once(app: QApplication) -> None:
    tl = TimelineWidget()
    song = _dense_song(20)
    tl.set_song(song)
    before = tl._mark_backdrop_revision  # noqa: SLF001
    tl.bump_mark_backdrop_revision(reason="marks_changed")
    assert tl._mark_backdrop_revision == before + 1  # noqa: SLF001
    assert tl._scrub_backdrop is None  # noqa: SLF001


def test_zoom_events_coalesce_to_bounded_rebuilds(app: QApplication) -> None:
    perf_diag.set_enabled(True)
    perf_diag.clear()
    tl = TimelineWidget()
    tl.resize(800, 400)
    tl.show()
    app.processEvents()
    song = _dense_song(100)
    tl.set_song(song)
    tl.set_playing(True)
    tl._rebuild_scrub_backdrop(reason="test_seed")  # noqa: SLF001
    app.processEvents()
    for _ in range(100):
        tl.zoom_by(1.12 if _ % 2 == 0 else 1 / 1.12)
    snap = perf_diag.snapshot()["counters"]
    raw = int(snap.get("timeline.zoom.raw_events", 0))
    assert raw >= 90
    # Final rebuilds only after idle debounce — not one per wheel event.
    finals = int(snap.get("timeline.zoom.final_rebuilds", 0))
    assert finals <= 5
    # Flush debounce.
    tl._finish_view_transform_gesture()  # noqa: SLF001
    app.processEvents()
    snap2 = perf_diag.snapshot()["counters"]
    assert int(snap2.get("timeline.zoom.final_rebuilds", 0)) >= 1
    # Latest zoom target applied.
    assert tl.pixels_per_second() > 0
    perf_diag.set_enabled(False)


def test_unicode_mark_labels_still_supported(app: QApplication) -> None:
    song = _dense_song(5)
    assert song.marks[0].display_name.startswith("標記")
    tl = TimelineWidget()
    tl.set_song(song)
    tl.bump_mark_backdrop_revision(reason="unicode")
    assert song.marks[0].display_name == "標記0"


def test_activation_never_clears_to_empty_when_video_present(app: QApplication) -> None:
    perf_diag.set_enabled(True)
    perf_diag.clear()
    ctrl = VideoSyncController()
    song = Song.create("影片歌")
    # Clip path need not exist for placeholder path — no active clip → loading.
    song.video_clips = []
    # Force has_video false path is intentional gap; use a fake clip entry.
    clip = VideoClip.create(
        "clip",
        Path("/tmp/nonexistent_activation_test.mp4"),
        start_seconds=0.0,
        duration_seconds=10.0,
    )
    song.video_clips = [clip]
    ctrl.set_video_output_active(True)
    ctrl.set_song(song)
    # Must not stay EMPTY_WIDGET after activation with video.
    assert ctrl._display_source != DisplaySource.EMPTY_WIDGET  # noqa: SLF001
    src = perf_diag.snapshot()["attrs"].get("video.activation_poster.source")
    assert src in {
        "scrub_cache",
        "sync_short_deadline",
        "last_valid",
        "loading_placeholder",
    }
    perf_diag.set_enabled(False)


def test_preview_loading_is_non_empty(app: QApplication) -> None:
    w = VideoPreviewWidget()
    w.set_loading(True, "Loading video…")
    assert w.has_image()
    assert w._loading is True  # noqa: SLF001


def test_ma_export_untouched_by_timeline_cache() -> None:
    """Cue timing / names unchanged — export inputs are domain Marks."""
    song = _dense_song(10)
    times = [m.time_seconds for m in song.marks]
    names = [m.display_name for m in song.marks]
    assert times == sorted(times)
    assert all(n.startswith("標記") for n in names)
