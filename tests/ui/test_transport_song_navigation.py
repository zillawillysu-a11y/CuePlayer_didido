"""Transport start/previous and next-song behavior."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project, Song
from cueplayer.ui.main_window import MainWindow


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_start_then_previous_and_next(app: QApplication) -> None:
    project = Project.create("Navigation", with_song=False)
    first = Song.create("First")
    second = Song.create("Second")
    project.songs = [first, second]
    window = MainWindow(project)
    window._rebuild_song_list(select_indexes=[1])
    window._activate_song(1, stop_playback=False)
    window.playback.seek(4.0)

    window._go_to_song_start_or_previous()
    assert window.playback.position == pytest.approx(0.0)
    assert window.current_song is second

    window._go_to_song_start_or_previous()
    assert window.current_song is first
    window._go_to_next_song()
    assert window.current_song is second
