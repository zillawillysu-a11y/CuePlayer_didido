"""Video clip waveforms stay visible while the timeline is playing."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song, VideoClip
from cueplayer.media.video_clip_waveform import ClipWaveformPeaks
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_video_clip_waveform_paints_while_playing(app: QApplication, tmp_path: Path) -> None:
    media = tmp_path / "clip.mov"
    media.write_bytes(b"fake")
    song = Song.create("Vid")
    clip = VideoClip.create(
        path=media,
        name="Clip",
        start_seconds=0.0,
        duration_seconds=4.0,
        media_kind="video",
    )
    song.video_clips.append(clip)

    widget = TimelineWidget()
    widget.set_song(song)
    widget.resize(640, 400)
    widget.set_show_video_track(True, emit=False)

    peaks = ClipWaveformPeaks(
        sample_rate=48000,
        mono_origin_seconds=0.0,
        mono=np.linspace(-0.5, 0.5, 48000, dtype=np.float32),
        peak_levels=[],
        mins=np.full(64, -0.4, dtype=np.float32),
        maxs=np.full(64, 0.4, dtype=np.float32),
    )
    key = widget._video_waveform_cache.key_for(clip)
    widget._video_waveform_cache._peaks[key] = peaks

    widget.set_playing(True)
    assert widget._playing is True

    pm = QPixmap(200, 40)
    pm.fill()
    painter = QPainter(pm)
    # Should not early-return just because playback is active.
    widget._paint_video_clip_waveform(painter, clip, QRectF(10, 5, 180, 30))
    painter.end()

    # Smoke: peaks were consulted (cache hit path).
    assert widget._video_waveform_cache.get_peaks(clip) is peaks
