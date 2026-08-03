"""Add Song Browse… cell + New Project confirmation helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import AudioTrack, Project
from cueplayer.ui.main_window import MainWindow
from cueplayer.ui.song_edit_dialog import SongDraft, SongEditDialog, _AudioFileCell


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_audio_file_cell_starts_empty(app: QApplication) -> None:
    cell = _AudioFileCell(None)
    assert cell.path is None
    assert cell._label.text() == "—"


def test_audio_file_cell_shows_name(app: QApplication, tmp_path: Path) -> None:
    wav = tmp_path / "開場.wav"
    wav.write_bytes(b"RIFF")
    cell = _AudioFileCell(wav)
    assert cell.path == wav
    assert cell._label.text() == "開場.wav"


def test_song_edit_dialog_has_browse_cell(app: QApplication) -> None:
    dialog = SongEditDialog(
        [SongDraft(name="Song", setlist_number=1.0, audio_path=None)],
        title="Add Song",
    )
    from cueplayer.ui import song_edit_dialog as sed

    cell = dialog.table.cellWidget(0, sed._COL_FILE)
    assert isinstance(cell, _AudioFileCell)
    assert cell.path is None
    cell._clear()
    assert cell.path is None


def test_project_is_pristine_and_new_confirm(app: QApplication) -> None:
    window = MainWindow(Project.create("Untitled Project"))
    assert window._project_is_pristine() is True
    assert window._confirm_new_project() is True

    window.project.songs[0].name = "已有內容"
    window._dirty = False
    window._project_path = None
    assert window._project_is_pristine() is False

    # Loaded clean project: New should not prompt (returns True without dialog).
    window._project_path = Path("C:/shows/demo.cueplayer.json")
    window._dirty = False
    assert window._confirm_new_project() is True


def test_apply_draft_sets_audio_track(app: QApplication, tmp_path: Path) -> None:
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    window = MainWindow(Project.create("Untitled Project"))
    song = window.project.songs[0]
    draft = SongDraft(name="A", setlist_number=1.0, audio_path=wav)
    window._apply_draft_to_song(song, draft)
    assert len(song.audio_tracks) == 1
    assert song.audio_tracks[0].path == wav
