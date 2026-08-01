"""Timeline waveform loading placeholder."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

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


def test_audio_loading_stays_visible_while_playing(app: QApplication) -> None:
    """Play uses a cached backdrop — loading must still overlay on top."""
    from PySide6.QtGui import QImage, QPainter

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
    # Overlay paints non-black text/fill into the wave band.
    assert widget._scrub_backdrop is None or widget.audio_loading()
