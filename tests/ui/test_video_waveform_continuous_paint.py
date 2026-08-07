"""Video Track waveform continuous envelope (no comb-column holes)."""

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


def test_video_lane_waveform_has_no_regular_column_holes(
    app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Filled envelope must paint contiguous columns (step=2/3 was the comb)."""
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

    n = 400
    peaks = ClipWaveformPeaks(
        sample_rate=50,
        mono_origin_seconds=0.0,
        mono=np.linspace(-0.6, 0.6, n, dtype=np.float32),
        peak_levels=[],
        mins=np.full(n, -0.5, dtype=np.float32),
        maxs=np.full(n, 0.5, dtype=np.float32),
        coverage=np.ones(n, dtype=np.uint8),
    )
    key = tl._video_waveform_cache.key_for(clip)  # noqa: SLF001
    tl._video_waveform_cache._peaks[key] = peaks  # noqa: SLF001

    # Bypass timeline mapping so every column samples covered peaks.
    import cueplayer.ui.timeline_widget as tw

    monkeypatch.setattr(tw, "timeline_to_clip_local", lambda _t, _c: 0.5)
    monkeypatch.setattr(
        tw, "sample_source_peaks_for_clip_times", lambda *a, **k: (-0.5, 0.5)
    )
    monkeypatch.setattr(
        tw, "sample_source_raw_for_clip_times", lambda *a, **k: (-0.5, 0.5)
    )

    path_calls: list[int] = []
    orig_draw = QPainter.drawPath

    def _spy_draw(self, path) -> None:  # noqa: ANN001
        path_calls.append(int(path.elementCount()))
        return orig_draw(self, path)

    monkeypatch.setattr(QPainter, "drawPath", _spy_draw)

    pm = QPixmap(400, 80)
    pm.fill()
    painter = QPainter(pm)
    tl._paint_video_clip_waveform(painter, clip, QRectF(10, 10, 380, 60))  # noqa: SLF001
    painter.end()

    assert path_calls, "expected continuous QPainterPath envelope"
    # One contiguous segment across the rect (not sparse per-column lines).
    assert path_calls[0] >= 100

    img = pm.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    y = 40
    painted = [img.pixel(x, y) != 0xFFFFFFFF for x in range(20, 380)]
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
    assert gaps < 8, f"too many comb-like holes: {gaps}"
    assert sum(painted) > 100


def test_gui_notify_coalesces_while_building(app: QApplication, tmp_path: Path) -> None:
    del app
    from cueplayer.media.video_clip_waveform import VideoClipWaveformCache
    from cueplayer.media.video_waveform_artifact import (
        EmbeddedWaveformArtifact,
        set_waveform_build_paused,
    )

    cache = VideoClipWaveformCache()
    cache._gui_coalesce_s = 10.0  # noqa: SLF001
    notifies = []
    cache.set_on_ready(lambda: notifies.append(1))

    art = EmbeddedWaveformArtifact(
        path="x",
        mtime_ns=0,
        size=0,
        stream_index=0,
        format_version=1,
        peaks_per_second=1.0,
        origin_seconds=0.0,
        duration_seconds=10.0,
        mins=np.zeros(10, dtype=np.float32),
        maxs=np.ones(10, dtype=np.float32),
        coverage=np.ones(10, dtype=np.uint8),
        complete=False,
    )
    set_waveform_build_paused(False)
    cache._notify_ready()  # first  # noqa: SLF001
    cache._notify_ready()  # coalesced  # noqa: SLF001
    cache._notify_ready()  # coalesced  # noqa: SLF001
    assert len(notifies) == 1
    cache._notify_ready(complete=True)  # noqa: SLF001
    assert len(notifies) == 2

    set_waveform_build_paused(True)
    before = len(notifies)
    cache._notify_ready()  # suppressed while playing  # noqa: SLF001
    assert len(notifies) == before
    set_waveform_build_paused(False)
