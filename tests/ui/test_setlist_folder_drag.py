"""Setlist folder drag-reorder."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTableWidgetItem

from cueplayer.domain.models import Project, SetlistCategory
from cueplayer.ui.main_window import MainWindow, SetlistWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_folder_insert_index_counts_headers_before_drop_row(app: QApplication) -> None:
    widget = SetlistWidget()
    widget.setRowCount(5)

    def _cat(row: int, cat_id: str) -> None:
        item = QTableWidgetItem(f"▾ Folder {cat_id}")
        item.setData(SetlistWidget.ROLE_KIND, "category")
        item.setData(Qt.ItemDataRole.UserRole, cat_id)
        widget.setItem(row, SetlistWidget.COL_NUM, item)

    def _song(row: int, song_id: str) -> None:
        item = QTableWidgetItem("1")
        item.setData(SetlistWidget.ROLE_KIND, "song")
        item.setData(Qt.ItemDataRole.UserRole, song_id)
        widget.setItem(row, SetlistWidget.COL_NUM, item)

    _song(0, "s0")
    _cat(1, "a")
    _song(2, "s1")
    _cat(3, "b")
    _song(4, "s2")

    assert widget._folder_insert_index_at(0) == 0
    assert widget._folder_insert_index_at(1) == 0
    assert widget._folder_insert_index_at(2) == 1
    assert widget._folder_insert_index_at(3) == 1
    assert widget._folder_insert_index_at(4) == 2
    assert widget._folder_insert_index_at(5) == 2


def test_reorder_folders_keeps_song_membership(app: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    project = Project.create("Folders")
    a = SetlistCategory.create("A")
    b = SetlistCategory.create("B")
    project.setlist_categories = [a, b]
    song_a = project.new_song("In A")
    song_a.category_id = a.id
    song_b = project.new_song("In B")
    song_b.category_id = b.id
    project.songs = [song_a, song_b]

    monkeypatch.setattr(MainWindow, "_confirm_discard_if_dirty", lambda self: True)
    window = MainWindow(project=project)
    window._on_setlist_categories_reordered(a.id, 2)  # move A after B
    assert [c.id for c in project.setlist_categories] == [b.id, a.id]
    assert song_a.category_id == a.id
    assert song_b.category_id == b.id

    window._on_setlist_categories_reordered(a.id, 0)  # move A before B again
    assert [c.id for c in project.setlist_categories] == [a.id, b.id]
