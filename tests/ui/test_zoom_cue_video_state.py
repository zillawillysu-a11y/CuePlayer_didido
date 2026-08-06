"""Sprint 8 follow-up: zoom screen-space annotations, Cue List O(1) follow, video states."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from cueplayer.diagnostics import perf as perf_diag
from cueplayer.domain.models import Mark, Song, VideoClip
from cueplayer.playback.video_sync import (
    DisplaySource,
    PreviewVideoState,
    VideoSyncController,
)
from cueplayer.ui.cue_monitor_panel import CueMonitorPanel
from cueplayer.ui.timeline_widget import TimelineWidget
from cueplayer.ui.video_preview import VideoPreviewWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _dense_song(n: int = 400, spacing: float = 0.05) -> Song:
    song = Song.create("密集標記測試")
    lane = song.mark_lanes[0]
    lane.visible = True
    lane.cue_list_enabled = True
    lane.show_note_on_wave = True
    marks = []
    for i in range(n):
        marks.append(
            Mark.create(
                lane_index=lane.index,
                time_seconds=i * spacing,
                display_name=f"標記{i}",
            )
        )
    song.marks = marks
    song.sort_marks()
    song.duration_seconds = max(60.0, n * spacing + 5.0)
    return song


def test_zoom_preview_keeps_spatial_and_annotation_caches(app: QApplication) -> None:
    tl = TimelineWidget()
    tl.resize(800, 400)
    tl.show()
    app.processEvents()
    song = _dense_song(80)
    tl.set_song(song)
    tl._rebuild_scrub_backdrop(reason="test_seed")  # noqa: SLF001
    assert tl._scrub_backdrop is not None  # noqa: SLF001
    assert tl._spatial_backdrop is not None  # noqa: SLF001
    assert len(tl._mark_annotation_sprites) > 0  # noqa: SLF001
    # Zoom busy: preview must use spatial + sprites (not scale full mark bake alone).
    tl._begin_view_transform_gesture()  # noqa: SLF001
    tl._pixels_per_second *= 1.25  # noqa: SLF001
    assert tl._blit_zoom_preview  # noqa: SLF001
    # Debounce longer than prior 64 ms.
    assert tl._view_transform_debounce_ms >= 120  # noqa: SLF001


def test_zoom_final_rebuild_is_atomic(app: QApplication) -> None:
    tl = TimelineWidget()
    tl.resize(800, 400)
    tl.show()
    app.processEvents()
    tl.set_song(_dense_song(40))
    tl._rebuild_scrub_backdrop(reason="seed")  # noqa: SLF001
    old_full = tl._scrub_backdrop  # noqa: SLF001
    old_spatial = tl._spatial_backdrop  # noqa: SLF001
    assert old_full is not None and old_spatial is not None
    tl._begin_view_transform_gesture()  # noqa: SLF001
    tl._pixels_per_second *= 1.5  # noqa: SLF001
    # Finish must not clear before swap — caches remain valid throughout rebuild.
    tl._finish_view_transform_gesture()  # noqa: SLF001
    assert tl._scrub_backdrop is not None  # noqa: SLF001
    assert tl._spatial_backdrop is not None  # noqa: SLF001
    assert tl._scrub_backdrop is not old_full or tl._spatial_backdrop is not old_spatial  # noqa: SLF001


def test_cue_list_follow_uses_mark_id_map_not_full_scan(app: QApplication) -> None:
    perf_diag.set_enabled(True)
    perf_diag.clear()
    panel = CueMonitorPanel()
    panel.resize(400, 600)
    panel.show()
    app.processEvents()
    song = _dense_song(500)
    panel.set_song(song)
    app.processEvents()
    assert len(panel._mark_id_to_row) == 500  # noqa: SLF001
    perf_diag.clear()
    # Simulate dense-region playback ticks: same active mark stays early-out.
    start_t = song.marks[200].time_seconds
    panel.set_position(start_t, song.duration_seconds)
    app.processEvents()
    before = int(
        perf_diag.snapshot()["counters"].get("cue_list.mark_id_at_row.calls", 0)
    )
    for i in range(120):
        panel.set_position(start_t + 0.001 * (i % 3), song.duration_seconds)
    after = int(
        perf_diag.snapshot()["counters"].get("cue_list.mark_id_at_row.calls", 0)
    )
    # Old path scanned ~500 rows × 120 ticks ≈ 60k. Mapped path is O(ticks).
    assert after - before < 2000
    assert after - before < 500 * 10
    perf_diag.set_enabled(False)


def test_cue_list_follow_scrolls_only_when_row_changes(app: QApplication) -> None:
    panel = CueMonitorPanel()
    panel.show()
    app.processEvents()
    song = _dense_song(50)
    panel.set_song(song)
    app.processEvents()
    m0 = song.marks[5]
    panel.set_position(m0.time_seconds, song.duration_seconds)
    app.processEvents()
    row0 = panel._follow_target_row  # noqa: SLF001
    assert row0 >= 0
    mid = panel._playhead_list_mark_id  # noqa: SLF001
    # Tiny move still on same mark — early-out keeps target row.
    panel.set_position(m0.time_seconds + 0.01, song.duration_seconds)
    assert panel._playhead_list_mark_id == mid  # noqa: SLF001
    assert panel._follow_target_row == row0  # noqa: SLF001
    # Advance to a later mark — row must update.
    m1 = song.marks[20]
    panel.set_position(m1.time_seconds, song.duration_seconds)
    app.processEvents()
    assert panel._playhead_list_mark_id == m1.id  # noqa: SLF001
    assert panel._follow_target_row == panel._row_for_mark_id(m1.id)  # noqa: SLF001


def test_no_video_song_does_not_show_loading(app: QApplication) -> None:
    perf_diag.set_enabled(True)
    perf_diag.clear()
    ctrl = VideoSyncController()
    loading: list[str] = []
    ctrl.activation_loading.connect(lambda t: loading.append(t))
    song = Song.create("無影片")
    song.video_clips = []
    ctrl.set_video_output_active(True)
    ctrl.set_song(song)
    assert ctrl._preview_video_state == PreviewVideoState.NO_VIDEO_FOR_SONG  # noqa: SLF001
    assert ctrl._display_source == DisplaySource.INTENTIONAL_GAP  # noqa: SLF001
    assert any(t == "" for t in loading) or not any(
        "Loading" in t for t in loading if t
    )
    src = perf_diag.snapshot()["attrs"].get("video.activation_poster.source")
    assert src in {None, "no_video_for_song"} or src is None
    # empty_widget_visible_ms must not be opened for NO_VIDEO.
    assert ctrl._empty_widget_since_mono is None  # noqa: SLF001
    perf_diag.set_enabled(False)


def test_timeline_gap_before_clip_start_no_loading(app: QApplication) -> None:
    perf_diag.set_enabled(True)
    perf_diag.clear()
    ctrl = VideoSyncController()
    loading: list[str] = []
    ctrl.activation_loading.connect(lambda t: loading.append(t))
    song = Song.create("延遲開始影片")
    clip = VideoClip.create(
        "clip",
        Path("/tmp/nonexistent_gap_test.mp4"),
        start_seconds=0.456,
        duration_seconds=10.0,
    )
    song.video_clips = [clip]
    ctrl.set_video_output_active(True)
    ctrl.set_song(song)  # activates at t=0 → gap
    assert ctrl._preview_video_state == PreviewVideoState.VIDEO_TIMELINE_GAP  # noqa: SLF001
    assert not any(t and "Loading" in t for t in loading)
    assert (
        perf_diag.snapshot()["attrs"].get("video.activation_poster.source")
        == "timeline_gap"
    )
    # Position still in gap.
    ctrl.update_position(0.2, source="engine")
    assert ctrl._preview_video_state == PreviewVideoState.VIDEO_TIMELINE_GAP  # noqa: SLF001
    perf_diag.set_enabled(False)


def test_valid_target_pending_may_show_loading(app: QApplication) -> None:
    perf_diag.set_enabled(True)
    perf_diag.clear()
    ctrl = VideoSyncController()
    loading: list[str] = []
    ctrl.activation_loading.connect(lambda t: loading.append(t))
    song = Song.create("影片歌")
    clip = VideoClip.create(
        "clip",
        Path("/tmp/nonexistent_pending_test.mp4"),
        start_seconds=0.0,
        duration_seconds=10.0,
    )
    song.video_clips = [clip]
    ctrl.set_video_output_active(True)
    ctrl.set_song(song)
    assert ctrl._preview_video_state == PreviewVideoState.VALID_VIDEO_TARGET_PENDING  # noqa: SLF001
    src = perf_diag.snapshot()["attrs"].get("video.activation_poster.source")
    assert src in {
        "scrub_cache",
        "sync_short_deadline",
        "last_valid",
        "loading_placeholder",
    }
    assert any(t and "Loading" in t for t in loading) or src in {
        "scrub_cache",
        "sync_short_deadline",
        "last_valid",
    }
    perf_diag.set_enabled(False)


def test_last_valid_not_reused_across_songs(app: QApplication) -> None:
    ctrl = VideoSyncController()
    song_a = Song.create("A")
    clip_a = VideoClip.create(
        "a", Path("/tmp/a.mp4"), start_seconds=0.0, duration_seconds=5.0
    )
    song_a.video_clips = [clip_a]
    song_b = Song.create("B")
    clip_b = VideoClip.create(
        "b", Path("/tmp/b.mp4"), start_seconds=0.0, duration_seconds=5.0
    )
    song_b.video_clips = [clip_b]
    ctrl.set_video_output_active(True)
    ctrl.set_song(song_a)
    # Fabricate a last_valid bound to song A.
    import numpy as np

    fake = np.zeros((48, 64, 3), dtype=np.uint8)
    fake[:] = (10, 20, 30)
    ctrl._active_clip_id = clip_a.id  # noqa: SLF001
    ctrl._emit_frame(fake, reason="activate_poster")  # noqa: SLF001
    assert ctrl._last_valid_frame is not None  # noqa: SLF001
    ctrl.set_song(song_b)
    assert ctrl._last_valid_frame is None  # noqa: SLF001
    assert not ctrl._same_session_last_valid(clip_b.id)  # noqa: SLF001


def test_preview_loading_clear_drops_slate(app: QApplication) -> None:
    w = VideoPreviewWidget()
    w.set_loading(True, "Loading video…")
    assert w._loading is True  # noqa: SLF001
    w.set_loading(False)
    assert w._loading is False  # noqa: SLF001
    assert w._image is None  # noqa: SLF001


def test_unicode_mark_names_preserved_in_cue_map(app: QApplication) -> None:
    panel = CueMonitorPanel()
    song = _dense_song(5)
    panel.set_song(song)
    assert song.marks[0].display_name == "標記0"
    assert panel._row_for_mark_id(song.marks[0].id) == 0  # noqa: SLF001
