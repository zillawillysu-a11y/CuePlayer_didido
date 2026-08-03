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
