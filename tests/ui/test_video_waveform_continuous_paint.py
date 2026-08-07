"""Video Track waveform — Music-lane style per-pixel bipolar strokes."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song, VideoClip
from cueplayer.media.video_clip_waveform import ClipWaveformPeaks, VideoClipWaveformCache
from cueplayer.media.video_waveform_artifact import (
    set_waveform_build_paused,
)
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_video_lane_peak_strokes_are_continuous_dense(
    app: QApplication, tmp_path: Path
) -> None:
    """Per-pixel drawLine must paint a dense Music-lane-like body (no comb holes)."""
    del app
    media = tmp_path / "clip.mov"
    media.write_bytes(b"fake")
    song = Song.create("Vid")
    clip = VideoClip.create(
        path=media,
        name="Clip",
        start_seconds=0.0,
        duration_seconds=8.0,
        media_kind="video",
    )
    song.video_clips.append(clip)

    tl = TimelineWidget()
    tl.resize(900, 420)
    tl.set_show_video_track(True, emit=False)
    tl.set_song(song)
    tl._scroll_x = 0.0  # noqa: SLF001
    tl._pixels_per_second = 40.0  # noqa: SLF001

    # Source-aligned bipolar envelope (artifact style) at 50 Hz.
    n = 400  # 8s * 50
    mins = np.full(n, -0.7, dtype=np.float32)
    maxs = np.full(n, 0.7, dtype=np.float32)
    peaks = ClipWaveformPeaks(
        sample_rate=50,
        mono_origin_seconds=0.0,
        mono=np.linspace(-0.7, 0.7, n, dtype=np.float32),
        peak_levels=[],
        mins=mins,
        maxs=maxs,
        coverage=np.ones(n, dtype=np.uint8),
    )
    key = tl._video_waveform_cache.key_for(clip)  # noqa: SLF001
    tl._video_waveform_cache._peaks[key] = peaks  # noqa: SLF001

    x0 = int(tl._x_for_time(0.0))  # noqa: SLF001
    x1 = int(tl._x_for_time(8.0))  # noqa: SLF001
    pm = QPixmap(max(400, x1 + 20), 120)
    pm.fill()
    painter = QPainter(pm)
    rect = QRectF(float(x0), 20.0, float(max(40, x1 - x0)), 80.0)
    tl._paint_video_clip_waveform(painter, clip, rect)  # noqa: SLF001
    painter.end()

    img = pm.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    y = 60
    painted = [img.pixel(x, y) != 0xFFFFFFFF for x in range(x0 + 2, max(x0 + 3, x1 - 2))]
    assert sum(painted) > len(painted) * 0.7, (
        f"expected dense peak strokes, painted={sum(painted)}/{len(painted)}"
    )
    gaps = 0
    i = 0
    while i < len(painted):
        if not painted[i]:
            run = 0
            while i < len(painted) and not painted[i]:
                run += 1
                i += 1
            if 1 <= run <= 2:
                gaps += 1
        else:
            i += 1
    assert gaps < 8, f"comb-like holes={gaps}"


def test_video_wave_paint_samples_per_pixel_like_music(
    app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Zoom rebuilds sample peaks once per visible pixel (Music-lane style)."""
    del app
    media = tmp_path / "clip.mov"
    media.write_bytes(b"fake")
    song = Song.create("Vid")
    clip = VideoClip.create(
        path=media,
        name="Clip",
        start_seconds=0.0,
        duration_seconds=60.0,
        media_kind="video",
    )
    song.video_clips.append(clip)
    tl = TimelineWidget()
    tl.resize(1200, 400)
    tl.set_show_video_track(True, emit=False)
    tl.set_song(song)
    tl._pixels_per_second = 20.0  # noqa: SLF001

    n = 64
    peaks = ClipWaveformPeaks(
        sample_rate=25,
        mono_origin_seconds=0.0,
        mono=np.ones(n, dtype=np.float32) * 0.4,
        peak_levels=[],
        mins=np.full(n, -0.5, dtype=np.float32),
        maxs=np.full(n, 0.5, dtype=np.float32),
        coverage=np.ones(n, dtype=np.uint8),
    )
    key = tl._video_waveform_cache.key_for(clip)  # noqa: SLF001
    tl._video_waveform_cache._peaks[key] = peaks  # noqa: SLF001

    import cueplayer.ui.timeline_widget as tw

    calls = {"peaks": 0, "raw": 0}

    def _boom_peaks(*_a, **_k):  # noqa: ANN001
        calls["peaks"] += 1
        return -0.5, 0.5

    def _boom_raw(*_a, **_k):  # noqa: ANN001
        calls["raw"] += 1
        return -0.5, 0.5

    monkeypatch.setattr(tw, "sample_source_peaks_for_clip_times", _boom_peaks)
    monkeypatch.setattr(tw, "sample_source_raw_for_clip_times", _boom_raw)

    pm = QPixmap(800, 80)
    pm.fill()
    painter = QPainter(pm)
    x0 = int(tl._x_for_time(0.0))  # noqa: SLF001
    x1 = int(tl._x_for_time(60.0))  # noqa: SLF001
    # Clip rect is viewport-clipped in real paint; here clamp to pixmap width.
    rx1 = min(x1, 780)
    tl._paint_video_clip_waveform(  # noqa: SLF001
        painter, clip, QRectF(float(x0), 10.0, float(max(50, rx1 - x0)), 60.0)
    )
    painter.end()
    visible_px = max(1, rx1 - x0)
    # samples_per_pixel = 25/20 = 1.25 → use_raw path
    assert calls["raw"] == visible_px
    assert calls["peaks"] == 0


def test_gui_notify_coalesces_while_building(app: QApplication) -> None:
    del app
    cache = VideoClipWaveformCache()
    cache._gui_coalesce_s = 10.0  # noqa: SLF001
    notifies: list[int] = []
    cache.set_on_ready(lambda: notifies.append(1))

    set_waveform_build_paused(False)
    cache._notify_ready()  # noqa: SLF001
    cache._notify_ready()  # noqa: SLF001
    cache._notify_ready()  # noqa: SLF001
    assert len(notifies) == 1
    cache._notify_ready(complete=True)  # noqa: SLF001
    assert len(notifies) == 2

    set_waveform_build_paused(True)
    before = len(notifies)
    cache._notify_ready()  # noqa: SLF001
    assert len(notifies) == before
    set_waveform_build_paused(False)
