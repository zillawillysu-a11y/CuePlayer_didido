"""Edit Song dialog should not demote auto-detected BPM to manual."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project
from cueplayer.ui.main_window import MainWindow
from cueplayer.ui.song_edit_dialog import SongDraft


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_apply_draft_preserves_auto_bpm_when_unchanged(app: QApplication) -> None:
    window = MainWindow(Project.create("BPM Edit"))
    song = window.project.songs[0]
    song.bpm = 128.0
    song.bpm_auto = True

    draft = window._song_to_draft(song)
    draft.name = "Renamed Song"

    window._apply_draft_to_song(song, draft)

    assert song.name == "Renamed Song"
    assert song.bpm == 128.0
    assert song.bpm_auto is True


def test_apply_draft_marks_changed_bpm_as_manual(app: QApplication) -> None:
    window = MainWindow(Project.create("BPM Edit"))
    song = window.project.songs[0]
    song.bpm = 128.0
    song.bpm_auto = True

    draft = window._song_to_draft(song)
    draft.bpm = 130.0

    window._apply_draft_to_song(song, draft)

    assert song.bpm == 130.0
    assert song.bpm_auto is False


def test_apply_draft_clears_auto_when_bpm_cleared(app: QApplication) -> None:
    window = MainWindow(Project.create("BPM Edit"))
    song = window.project.songs[0]
    song.bpm = 128.0
    song.bpm_auto = True

    draft = window._song_to_draft(song)
    draft.bpm = None

    window._apply_draft_to_song(song, draft)

    assert song.bpm is None
    assert song.bpm_auto is False
