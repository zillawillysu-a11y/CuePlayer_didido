"""Sort by Number: per-section and All menus."""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project, SetlistCategory
from cueplayer.ui.main_window import MainWindow


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _sample_project() -> Project:
    project = Project.create("Sort")
    folder = SetlistCategory.create("Archive")
    project.setlist_categories.append(folder)
    main_a = project.new_song("Main A")
    main_a.setlist_number = 3.0
    main_b = project.new_song("Main B")
    main_b.setlist_number = 1.0
    arch_a = project.new_song("Arch A")
    arch_a.category_id = folder.id
    arch_a.setlist_number = 5.0
    arch_b = project.new_song("Arch B")
    arch_b.category_id = folder.id
    arch_b.setlist_number = 2.0
    project.songs = [main_a, main_b, arch_a, arch_b]
    return project


def test_sort_main_list_only_leaves_folder_order(app: QApplication) -> None:
    project = _sample_project()
    folder_id = project.setlist_categories[0].id
    with patch.object(MainWindow, "_confirm_discard_if_dirty", return_value=True):
        window = MainWindow(project=project)
        window._sort_songs_in_category(None)
        main = window._songs_in_category_display_order(None)
        arch = window._songs_in_category_display_order(folder_id)
        assert [s.name for s in main] == ["Main B", "Main A"]
        assert [s.setlist_number for s in main] == [1.0, 3.0]
        assert [s.name for s in arch] == ["Arch A", "Arch B"]
        window.close()
        app.processEvents()


def test_sort_all_sections(app: QApplication) -> None:
    project = _sample_project()
    folder_id = project.setlist_categories[0].id
    with patch.object(MainWindow, "_confirm_discard_if_dirty", return_value=True):
        window = MainWindow(project=project)
        window._sort_all_sections()
        main = window._songs_in_category_display_order(None)
        arch = window._songs_in_category_display_order(folder_id)
        assert [s.name for s in main] == ["Main B", "Main A"]
        assert [s.name for s in arch] == ["Arch B", "Arch A"]
        window.close()
        app.processEvents()
