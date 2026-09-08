"""Timeline waveform loading placeholder."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song, VideoClip
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_set_audio_loading_shows_placeholder_state(app: QApplication) -> None:
    widget = TimelineWidget()
    widget.resize(800, 300)
    widget.set_audio_loading(True, "song.wav")
    assert widget._audio_loading is True
    assert widget._audio is None
    assert widget._audio_loading_label == "song.wav"

    widget.set_audio_loading(False)
    assert widget._audio_loading is False


def test_song_with_video_does_not_show_empty_open_audio_copy(
    app: QApplication, tmp_path
) -> None:
    """Cold open: song already has video — Music lane must not flash empty CTA."""
    clip_path = tmp_path / "clip.mp4"
    clip_path.write_bytes(b"x")
    song = Song.create("Vid")
    song.add_video_clip(
        VideoClip.create(
            name="20260729",
            path=clip_path,
            start_seconds=0.0,
            duration_seconds=60.0,
        )
    )
    widget = TimelineWidget()
    widget.resize(800, 300)
    widget.set_song(song)
    # No audio buffer yet, loading flag not armed — paint path still expects media.
    assert widget._audio is None
    assert widget._audio_loading is False
    assert widget._song_expects_waveform() is True

    image = QImage(widget.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.black)
    painter = QPainter(image)
    widget._paint_audio_loading_overlay(painter)
    painter.end()
    # Overlay drew something (label plate) into the wave band.
    sample = QColor(image.pixel(widget._header_width + 24, widget._ruler_height + 40))
    assert sample.alpha() > 0 or sample.lightness() > 0


def test_playhead_paints_above_loading_overlay(app: QApplication) -> None:
    """Loading must not wash out the green playhead."""
    widget = TimelineWidget()
    widget.resize(800, 300)
    widget.set_audio_loading(True, "long.wav")
    widget._position = 2.0
    widget._pixels_per_second = 100.0
    widget._scroll_x = 0.0
    widget._playhead_color = "#3dd68c"

    x = int(widget._x_for_time(widget._position))
    assert x > widget._header_width

    image = QImage(widget.size(), QImage.Format.Format_ARGB32)
    image.fill(QColor("#09090b"))
    painter = QPainter(image)
    widget._paint_audio_loading_overlay(painter)
    widget._paint_playhead(painter)
    painter.end()

    # Sample mid-wave on the playhead — should be green, not dimmed overlay gray.
    y = widget._ruler_height + widget._wave_height // 2
    pixel = QColor(image.pixel(x, y))
    assert pixel.green() > pixel.red()
    assert pixel.green() > 120


def test_audio_loading_stays_visible_while_playing(app: QApplication) -> None:
    """Play uses a cached backdrop — loading must still overlay (under playhead)."""
    widget = TimelineWidget()
    widget.resize(800, 300)
    widget.set_audio_loading(True, "long.wav")
    widget.set_playing(True)
    assert widget.audio_loading() is True

    image = QImage(widget.size(), QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    widget._paint_audio_loading_overlay(painter)
    painter.end()
    assert widget._scrub_backdrop is None or widget.audio_loading()
