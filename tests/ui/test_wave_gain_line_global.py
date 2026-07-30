"""Waveform volume line visibility is project-global (not per song)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project
from cueplayer.ui.main_window import MainWindow


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_wave_gain_line_visibility_survives_song_switch(app: QApplication) -> None:
    project = Project.create("Gain Global")
    project.show_wave_gain_line = True
    project.songs[0].duration_seconds = 60.0
    project.new_song("Song 2")
    window = MainWindow(project)
    window.show()
    app.processEvents()

    assert window.timeline._show_wave_gain_line is True

    window._activate_song(1, stop_playback=True)
    app.processEvents()
    assert window.timeline._show_wave_gain_line is True

    window.timeline.set_show_wave_gain_line(False)
    app.processEvents()
    assert project.show_wave_gain_line is False

    window._activate_song(0, stop_playback=True)
    app.processEvents()
    assert window.timeline._show_wave_gain_line is False
