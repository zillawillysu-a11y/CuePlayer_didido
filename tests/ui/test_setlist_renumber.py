"""Setlist renumber: per-folder, selection, and main list."""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox

from cueplayer.domain.models import Project, SetlistCategory
from cueplayer.ui.main_window import MainWindow


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _sample_project() -> Project:
    project = Project.create("Renumber")
    folder = SetlistCategory.create("Archive")
    project.setlist_categories.append(folder)
    main_a = project.new_song("Main A")
    main_a.setlist_number = 5.0
    main_b = project.new_song("Main B")
    main_b.setlist_number = 9.0
    arch_a = project.new_song("Arch A")
    arch_a.category_id = folder.id
    arch_a.setlist_number = 2.5
    arch_b = project.new_song("Arch B")
    arch_b.category_id = folder.id
    arch_b.setlist_number = 7.0
    project.songs = [main_a, main_b, arch_a, arch_b]
    return project


def test_renumber_main_list_only(app: QApplication) -> None:
    project = _sample_project()
    with patch.object(MainWindow, "_confirm_discard_if_dirty", return_value=True):
        window = MainWindow(project=project)
        with patch.object(
            QMessageBox,
            "question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            window._renumber_songs_in_category(None)
        assert [s.setlist_number for s in project.songs_in_category(None)] == [1.0, 2.0]
        assert project.songs[2].setlist_number == 2.5
        window.close()
        app.processEvents()


def test_renumber_folder_only(app: QApplication) -> None:
    project = _sample_project()
    folder_id = project.setlist_categories[0].id
    with patch.object(MainWindow, "_confirm_discard_if_dirty", return_value=True):
        window = MainWindow(project=project)
        with patch.object(
            QMessageBox,
            "question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            window._renumber_songs_in_category(folder_id)
        assert [s.setlist_number for s in project.songs_in_category(None)] == [5.0, 9.0]
        assert [s.setlist_number for s in project.songs_in_category(folder_id)] == [
            1.0,
            2.0,
        ]
        window.close()
        app.processEvents()


def test_renumber_selected_songs_in_display_order(app: QApplication) -> None:
    project = _sample_project()
    folder_id = project.setlist_categories[0].id
    with patch.object(MainWindow, "_confirm_discard_if_dirty", return_value=True):
        window = MainWindow(project=project)
        window.show()
        app.processEvents()
        # Select only Arch B (index 3) and Arch A (index 2) — display order A then B.
        window.song_list.clearSelection()
        sm = window.song_list.selectionModel()
        assert sm is not None
        from PySide6.QtCore import QItemSelectionModel

        for row in range(window.song_list.rowCount()):
            idx = window.song_list.row_song_index(row)
            if idx in (2, 3):
                index = window.song_list.model().index(row, 0)
                sm.select(
                    index,
                    QItemSelectionModel.SelectionFlag.Select
                    | QItemSelectionModel.SelectionFlag.Rows,
                )
        assert window._selected_song_indexes() == [2, 3]
        with patch.object(
            QMessageBox,
            "question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            window._renumber_selected_songs()
        arch = project.songs_in_category(folder_id)
        assert arch[0].name == "Arch A"
        assert arch[0].setlist_number == 1.0
        assert arch[1].name == "Arch B"
        assert arch[1].setlist_number == 2.0
        window.close()
        app.processEvents()
