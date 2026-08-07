"""Video Track waveform must survive always-static backdrop caching.

Loss stage (pre-fix): async waveform-ready deferred while playing (C), and
geometry_ok ignored the wave epoch so an empty bake was reused for the whole
play session (D). Peaks were still generated (not A) and paint still drew them
when baked (not B).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from cueplayer.diagnostics import perf as perf_diag
from cueplayer.domain.models import Song, VideoClip
from cueplayer.media.video_clip_waveform import ClipWaveformPeaks
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _song_with_clip(tmp_path: Path) -> tuple[Song, VideoClip]:
    media = tmp_path / "clip.mov"
    media.write_bytes(b"fake")
    song = Song.create("VidWave")
    clip = VideoClip.create(
        path=media,
        name="Clip",
        start_seconds=0.0,
        duration_seconds=4.0,
        media_kind="video",
    )
    song.video_clips.append(clip)
    song.duration_seconds = 8.0
    return song, clip


def _peaks() -> ClipWaveformPeaks:
    return ClipWaveformPeaks(
        sample_rate=48000,
        mono_origin_seconds=0.0,
        mono=np.linspace(-0.5, 0.5, 48000, dtype=np.float32),
        peak_levels=[],
        mins=np.full(128, -0.55, dtype=np.float32),
        maxs=np.full(128, 0.55, dtype=np.float32),
    )


def _inject_peaks(tl: TimelineWidget, clip: VideoClip, peaks: ClipWaveformPeaks) -> None:
    key = tl._video_waveform_cache.key_for(clip)  # noqa: SLF001
    tl._video_waveform_cache._peaks[key] = peaks  # noqa: SLF001


def _count_rebuilds(tl: TimelineWidget) -> list[str]:
    reasons: list[str] = []
    orig = tl._rebuild_scrub_backdrop  # noqa: SLF001

    def _wrap(reason: str = "rebuild") -> None:
        reasons.append(reason)
        return orig(reason)

    tl._rebuild_scrub_backdrop = _wrap  # type: ignore[method-assign]  # noqa: SLF001
    return reasons


def _backdrop_has_non_bg_pixels(tl: TimelineWidget) -> bool:
    """True when the retained static bake has content beyond a flat fill."""
    pm = tl._scrub_backdrop  # noqa: SLF001
    assert pm is not None and not pm.isNull()
    img = pm.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    dpr = max(1.0, float(pm.devicePixelRatio()))
    overscan = int(tl._scrub_backdrop_overscan)  # noqa: SLF001
    # Bake uses scroll = saved_scroll - overscan, so logical x maps to
    # device X = (logical_x + overscan) * dpr inside the pixmap.
    y0 = max(0, int((tl._video_lane_top_y() + 8) * dpr))  # noqa: SLF001
    y1 = min(
        img.height() - 1,
        int((tl._video_lane_top_y() + tl._video_lane_base_height - 8) * dpr),  # noqa: SLF001
    )
    x0 = max(0, int((tl._header_width + 8 + overscan) * dpr))  # noqa: SLF001
    x1 = min(img.width() - 1, int((tl._header_width + 220 + overscan) * dpr))  # noqa: SLF001
    seen: set[int] = set()
    for y in range(y0, max(y0, y1) + 1, 2):
        for x in range(x0, max(x0, x1) + 1, 3):
            seen.add(int(img.pixel(x, y)))
            if len(seen) > 3:
                return True
    return len(seen) > 2


def test_progressive_overlay_restrokes_mark_stems(
    app: QApplication, tmp_path: Path
) -> None:
    """Video-lane progressive overlay must not bury Mark stems permanently."""
    del app
    song, clip = _song_with_clip(tmp_path)
    from cueplayer.domain.models import Mark

    song.marks.append(
        Mark.create(lane_index=0, time_seconds=1.0, display_name="M1")
    )
    song.sort_marks()
    tl = TimelineWidget()
    tl.resize(800, 420)
    tl.set_show_video_track(True, emit=False)
    tl.set_song(song)
    _inject_peaks(tl, clip, _peaks())
    tl._rebuild_scrub_backdrop(reason="with_marks")  # noqa: SLF001
    assert tl._scrub_backdrop is not None  # noqa: SLF001

    calls: list[tuple[bool, bool]] = []
    orig = tl._paint_marks  # noqa: SLF001

    def _wrap(painter, *, start_y: int, waveform_lines: bool = True, lane_shapes: bool = True, mode: str = "live"):  # noqa: ANN001
        calls.append((bool(waveform_lines), bool(lane_shapes)))
        return orig(
            painter,
            start_y=start_y,
            waveform_lines=waveform_lines,
            lane_shapes=lane_shapes,
            mode=mode,
        )

    tl._paint_marks = _wrap  # type: ignore[method-assign]  # noqa: SLF001
    from PySide6.QtGui import QPainter, QPixmap
    from PySide6.QtCore import Qt

    pm = QPixmap(800, 420)
    pm.fill(Qt.GlobalColor.black)
    painter = QPainter(pm)
    try:
        tl._paint_progressive_waveform_overlay(painter)  # noqa: SLF001
    finally:
        painter.end()
    assert any(wl and not ls for wl, ls in calls), (
        "progressive overlay must re-stroke Mark stems (waveform_lines, no lane shapes)"
    )


def test_waveform_ready_before_first_paint_bakes_peaks(
    app: QApplication, tmp_path: Path
) -> None:
    del app
    song, clip = _song_with_clip(tmp_path)
    tl = TimelineWidget()
    tl.resize(800, 420)
    tl.set_show_video_track(True, emit=False)
    tl.set_song(song)
    _inject_peaks(tl, clip, _peaks())
    # Peaks landed before any bake: ready must bump epoch then paint includes them.
    before = tl._video_waveform_revision  # noqa: SLF001
    tl._apply_video_waveform_ready()  # noqa: SLF001
    assert tl._video_waveform_revision == before + 1  # noqa: SLF001
    assert tl._scrub_backdrop is None  # noqa: SLF001
    tl._rebuild_scrub_backdrop(reason="test_ready_before")  # noqa: SLF001
    assert tl._video_waveform_baked_revision == tl._video_waveform_revision  # noqa: SLF001
    assert tl._scrub_backdrop_geometry_ok()  # noqa: SLF001
    assert _backdrop_has_non_bg_pixels(tl)


def test_async_ready_after_empty_bake_uses_overlay_not_mark_rebuild(
    app: QApplication, tmp_path: Path
) -> None:
    """Progressive ready must not drop the Mark backdrop (overlay path)."""
    perf_diag.set_enabled(True)
    perf_diag.clear()
    song, clip = _song_with_clip(tmp_path)
    tl = TimelineWidget()
    tl.resize(800, 420)
    tl.show()
    tl.set_show_video_track(True, emit=False)
    # Suppress real async extraction so only our controlled ready applies.
    tl._video_waveform_cache.set_on_ready(None)  # noqa: SLF001
    tl.set_song(song)
    app.processEvents()

    # Bake while peaks are still missing (async not done).
    tl._rebuild_scrub_backdrop(reason="empty_seed")  # noqa: SLF001
    empty_rev = tl._video_waveform_revision  # noqa: SLF001
    assert tl._video_waveform_baked_revision == empty_rev  # noqa: SLF001
    assert tl._scrub_backdrop_geometry_ok()  # noqa: SLF001
    pm_before = tl._scrub_backdrop  # noqa: SLF001

    rebuilds = _count_rebuilds(tl)
    tl.set_playing(True)
    _inject_peaks(tl, clip, _peaks())
    overlay0 = int(
        perf_diag.snapshot()["counters"].get(
            "timeline.video_waveform.ready_overlay", 0
        )
    )
    mark0 = int(
        perf_diag.snapshot()["counters"].get(
            "timeline.mark_backdrop.rebuild_reason.video_waveform_ready", 0
        )
    )
    tl._apply_video_waveform_ready(False)  # noqa: SLF001
    overlay1 = int(
        perf_diag.snapshot()["counters"].get(
            "timeline.video_waveform.ready_overlay", 0
        )
    )
    mark1 = int(
        perf_diag.snapshot()["counters"].get(
            "timeline.mark_backdrop.rebuild_reason.video_waveform_ready", 0
        )
    )
    assert overlay1 == overlay0 + 1
    assert mark1 == mark0  # progressive must not rebuild Marks
    assert tl._video_waveform_revision == empty_rev  # noqa: SLF001
    assert tl._scrub_backdrop is pm_before  # noqa: SLF001
    assert tl._scrub_backdrop_geometry_ok()  # noqa: SLF001
    assert rebuilds == []

    # Completion does one atomic invalidate.
    tl._apply_video_waveform_ready(True)  # noqa: SLF001
    assert tl._scrub_backdrop is None  # noqa: SLF001
    tl._rebuild_scrub_backdrop(reason="after_complete")  # noqa: SLF001
    assert rebuilds == ["after_complete"]
    assert _backdrop_has_non_bg_pixels(tl)
    perf_diag.set_enabled(False)


def test_song_switch_does_not_keep_stale_waveform(
    app: QApplication, tmp_path: Path
) -> None:
    del app
    song_a, clip_a = _song_with_clip(tmp_path)
    song_b, clip_b = _song_with_clip(tmp_path)
    song_b.video_clips[0].name = "Other"
    tl = TimelineWidget()
    tl.resize(800, 420)
    tl.set_show_video_track(True, emit=False)
    tl.set_song(song_a)
    _inject_peaks(tl, clip_a, _peaks())
    tl._apply_video_waveform_ready()  # noqa: SLF001
    tl._rebuild_scrub_backdrop(reason="song_a")  # noqa: SLF001
    rev_a = tl._video_waveform_revision  # noqa: SLF001
    baked_a = tl._video_waveform_baked_revision  # noqa: SLF001
    assert baked_a == rev_a

    tl.set_song(song_b)
    assert tl._video_waveform_revision == rev_a + 1  # noqa: SLF001
    assert tl._scrub_backdrop is None  # noqa: SLF001
    assert tl._video_waveform_cache.get_peaks(clip_a) is None  # noqa: SLF001
    # New song empty until its own peaks land — must not geometry-match song A.
    assert not tl._scrub_backdrop_geometry_ok()  # noqa: SLF001
    _inject_peaks(tl, clip_b, _peaks())
    tl._apply_video_waveform_ready()  # noqa: SLF001
    tl._rebuild_scrub_backdrop(reason="song_b")  # noqa: SLF001
    assert tl._video_waveform_baked_revision == tl._video_waveform_revision  # noqa: SLF001


def test_zoom_resize_dpr_retain_waveform_via_geometry(
    app: QApplication, tmp_path: Path
) -> None:
    del app
    song, clip = _song_with_clip(tmp_path)
    tl = TimelineWidget()
    tl.resize(800, 420)
    tl.set_show_video_track(True, emit=False)
    tl.set_song(song)
    _inject_peaks(tl, clip, _peaks())
    tl._apply_video_waveform_ready()  # noqa: SLF001
    tl._rebuild_scrub_backdrop(reason="base")  # noqa: SLF001
    assert tl._scrub_backdrop_geometry_ok()  # noqa: SLF001

    tl.zoom_by(1.5)
    tl._finish_view_transform_gesture()  # noqa: SLF001
    # Zoom path invalidates; force a quality bake at the new PPS.
    if not tl._scrub_backdrop_geometry_ok():  # noqa: SLF001
        tl._rebuild_scrub_backdrop(reason="zoom_bake")  # noqa: SLF001
    assert tl._scrub_backdrop_geometry_ok()  # noqa: SLF001
    assert tl._video_waveform_baked_revision == tl._video_waveform_revision  # noqa: SLF001
    assert _backdrop_has_non_bg_pixels(tl)

    tl.resize(960, 480)
    tl._invalidate_scrub_backdrop(reason="resize")  # noqa: SLF001
    tl._rebuild_scrub_backdrop(reason="resize_bake")  # noqa: SLF001
    assert tl._scrub_backdrop_size.width() == 960  # noqa: SLF001
    assert _backdrop_has_non_bg_pixels(tl)

    # DPR mismatch must force rebuild (identity includes DPR).
    tl._scrub_backdrop_dpr = float(tl._scrub_backdrop_dpr) + 1.0  # noqa: SLF001
    assert not tl._scrub_backdrop_geometry_ok()  # noqa: SLF001


def test_play_ticks_do_not_rebuild_video_waveform_backdrop(
    app: QApplication, tmp_path: Path
) -> None:
    song, clip = _song_with_clip(tmp_path)
    tl = TimelineWidget()
    tl.resize(800, 420)
    tl.show()
    tl.set_show_video_track(True, emit=False)
    tl._video_waveform_cache.set_on_ready(None)  # noqa: SLF001
    tl.set_song(song)
    _inject_peaks(tl, clip, _peaks())
    tl._apply_video_waveform_ready()  # noqa: SLF001
    app.processEvents()
    tl._rebuild_scrub_backdrop(reason="play_static")  # noqa: SLF001
    rebuilds = _count_rebuilds(tl)
    tl.set_playing(True)
    app.processEvents()
    n0 = len(rebuilds)
    for i in range(40):
        tl.set_position(0.2 + i * 0.05)
        app.processEvents()
    assert len(rebuilds) == n0
    assert tl._scrub_backdrop is not None  # noqa: SLF001
    assert tl._video_waveform_baked_revision == tl._video_waveform_revision  # noqa: SLF001


def test_mute_does_not_clear_or_hide_waveform_bake(
    app: QApplication, tmp_path: Path
) -> None:
    del app
    song, clip = _song_with_clip(tmp_path)
    tl = TimelineWidget()
    tl.resize(800, 420)
    tl.set_show_video_track(True, emit=False)
    tl.set_song(song)
    _inject_peaks(tl, clip, _peaks())
    tl._apply_video_waveform_ready()  # noqa: SLF001
    tl._rebuild_scrub_backdrop(reason="unmuted")  # noqa: SLF001
    pm_before = tl._scrub_backdrop  # noqa: SLF001
    rev_before = tl._video_waveform_revision  # noqa: SLF001

    tl.set_video_track_muted(True)
    assert tl._scrub_backdrop is pm_before  # noqa: SLF001
    assert tl._video_waveform_revision == rev_before  # noqa: SLF001
    assert tl._scrub_backdrop_geometry_ok()  # noqa: SLF001

    # Direct paint path still draws peaks while muted (lower alpha, still visible).
    pm = QPixmap(200, 40)
    pm.fill(Qt.GlobalColor.black)
    painter = QPainter(pm)
    from PySide6.QtCore import QRectF

    widget_rect = QRectF(10, 5, 180, 30)
    tl._paint_video_clip_waveform(painter, clip, widget_rect)  # noqa: SLF001
    painter.end()
    assert tl._video_waveform_cache.get_peaks(clip) is not None  # noqa: SLF001

    tl.set_video_track_muted(False)
    assert tl._scrub_backdrop is pm_before  # noqa: SLF001


def test_ready_while_playing_progressive_keeps_backdrop(
    app: QApplication, tmp_path: Path
) -> None:
    """Progressive ready while playing must not wipe the retained Mark bake."""
    del app
    song, clip = _song_with_clip(tmp_path)
    tl = TimelineWidget()
    tl.set_song(song)
    tl.set_playing(True)
    # Pretend a bake is retained.
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap

    tl._scrub_backdrop = QPixmap(10, 10)  # noqa: SLF001
    tl._scrub_backdrop.fill(Qt.GlobalColor.black)
    tl._video_waveform_baked_revision = tl._video_waveform_revision  # noqa: SLF001
    pm = tl._scrub_backdrop  # noqa: SLF001
    _inject_peaks(tl, clip, _peaks())

    tl._apply_video_waveform_ready(False)  # noqa: SLF001

    assert tl._video_waveform_pending_refresh is False  # noqa: SLF001
    assert tl._scrub_backdrop is pm  # noqa: SLF001
    assert tl._waveform_overlay_revision > 0  # noqa: SLF001


def test_complete_ready_while_playing_invalidates_once(
    app: QApplication, tmp_path: Path
) -> None:
    del app
    song, clip = _song_with_clip(tmp_path)
    tl = TimelineWidget()
    tl.set_song(song)
    tl.set_playing(True)
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap

    tl._scrub_backdrop = QPixmap(10, 10)  # noqa: SLF001
    tl._scrub_backdrop.fill(Qt.GlobalColor.black)
    tl._video_waveform_baked_revision = tl._video_waveform_revision  # noqa: SLF001
    _inject_peaks(tl, clip, _peaks())

    tl._apply_video_waveform_ready(True)  # noqa: SLF001

    assert tl._video_waveform_pending_refresh is False  # noqa: SLF001
    assert tl._scrub_backdrop is None  # noqa: SLF001
    assert tl._video_waveform_baked_revision == -1  # noqa: SLF001
