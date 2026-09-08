"""Video Track continuous envelope paint (no comb-column holes)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song, VideoClip
from cueplayer.media.video_clip_waveform import ClipWaveformPeaks
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_video_lane_peak_strokes_are_continuous_dense(
    app: QApplication, tmp_path: Path
) -> None:
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

    n = 400
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
        f"expected dense envelope, painted={sum(painted)}/{len(painted)}"
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
