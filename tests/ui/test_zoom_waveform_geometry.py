from pathlib import Path

import numpy as np
import pytest
from PySide6.QtGui import QImage, QPainter

from cueplayer.domain.models import Song
from cueplayer.media.audio_loader import AudioBuffer, PeakLevel, build_peak_pyramid
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.mark.parametrize('zoom', [150.0, 200.0, 350.0])
@pytest.mark.parametrize('dpr', [1.0, 1.5, 2.0])
def test_cached_zoom_music_matches_direct_current_resolution(zoom, dpr):
    widget = TimelineWidget()
    song = Song.create('鼓點縮放')
    song.duration_seconds = 10
    widget.set_song(song)
    widget.resize(900, 400)
    pcm = np.zeros((480000, 2), np.float32)
    pcm[48000:48020] = 1
    pcm[72000:72040] = -.7
    mono, peaks = build_peak_pyramid(pcm, 48000)
    widget._audio = AudioBuffer(Path('鼓.wav'), 48000, pcm, mono, peaks)
    widget._audio_loading = False
    widget._pixels_per_second = 100
    widget._scroll_x = 0
    widget.devicePixelRatioF = lambda: dpr
    widget._rebuild_scrub_backdrop()
    widget._pixels_per_second = zoom
    preview = QImage(round(widget.width()*dpr), round(widget.height()*dpr), QImage.Format.Format_ARGB32)
    direct = QImage(preview.size(), QImage.Format.Format_ARGB32)
    preview.setDevicePixelRatio(dpr)
    direct.setDevicePixelRatio(dpr)
    preview.fill(0)
    direct.fill(0)
    painter = QPainter(preview)
    assert widget._blit_zoom_preview(painter)
    painter.end()
    painter = QPainter(direct)
    widget._paint_waveform(painter)
    painter.end()
    x, y = widget._header_width + 2, widget._ruler_height + 2
    w, h = widget.width() - x - 2, widget._wave_height - 4
    actual = preview.copy(round(x*dpr), round(y*dpr), round(w*dpr), round(h*dpr))
    expected = direct.copy(round(x*dpr), round(y*dpr), round(w*dpr), round(h*dpr))
    assert bytes(actual.constBits()) == bytes(expected.constBits())


def test_pixel_interval_includes_partially_overlapping_end_bucket():
    widget = TimelineWidget()
    song = Song.create('邊界')
    song.duration_seconds = 1
    widget.set_song(song)
    widget._pixels_per_second = 100  # 10 samples / pixel at 1k
    widget._scroll_x = .5  # first pixel covers samples [5,15)
    peaks = [PeakLevel(10, np.zeros(100, np.float32), np.zeros(100, np.float32))]
    peaks[0].maxs[1] = 1  # bucket [10,20) intersects the first pixel
    buf = AudioBuffer(Path('邊界.wav'), 1000, np.zeros((1000, 2), np.float32),
                      np.zeros(1000, np.float32), peaks)

    class Recorder:
        lines = []
        def drawLines(self, lines): self.lines.extend(lines)

    painter = Recorder()
    left = widget._header_width
    widget._paint_waveform_peaks(painter, buf, 50, 40, left, left + 1, 10)
    assert max(line.y2() for line in painter.lines) == 90
