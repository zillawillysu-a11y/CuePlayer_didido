"""Setlist operations are undoable with Ctrl+Z."""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox

from cueplayer.domain.models import Project
from cueplayer.domain.undo import UndoContext
from cueplayer.ui.main_window import MainWindow


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_renumber_is_undoable(app: QApplication) -> None:
    project = Project.create("Undo Renumber")
    a = project.songs[0]
    a.setlist_number = 5.0
    b = project.new_song("Second")
    b.setlist_number = 9.0
    project.songs.append(b)

    with patch.object(MainWindow, "_confirm_discard_if_dirty", return_value=True):
        window = MainWindow(project=project)
        with patch.object(
            QMessageBox,
            "question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            window._renumber_songs_in_category(None)

        assert [s.setlist_number for s in project.songs] == [1.0, 2.0]

        result = window._undo.undo(window._undo_ctx)
        assert result is not None
        label, setlist_cmd, _song_id = result
        assert label == "Renumber"
        assert setlist_cmd is not None
        window._sync_after_setlist_undo_redo(setlist_cmd)

        assert [s.setlist_number for s in project.songs] == [5.0, 9.0]
        window.close()
        app.processEvents()


def test_sort_is_undoable(app: QApplication) -> None:
    project = Project.create("Undo Sort")
    a = project.songs[0]
    a.name = "B"
    a.setlist_number = 2.0
    b = project.new_song("A")
    b.setlist_number = 1.0
    project.songs = [a, b]

    with patch.object(MainWindow, "_confirm_discard_if_dirty", return_value=True):
        window = MainWindow(project=project)
        window._sort_songs_in_category(None)
        assert [s.name for s in project.songs] == ["A", "B"]

        result = window._undo.undo(UndoContext(project, window.current_song.id))
        assert result is not None
        _, setlist_cmd, _song_id = result
        assert setlist_cmd is not None
        window._sync_after_setlist_undo_redo(setlist_cmd)

        assert [s.name for s in project.songs] == ["B", "A"]
        window.close()
        app.processEvents()
