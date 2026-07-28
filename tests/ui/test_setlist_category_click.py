"""Setlist folder row: triangle toggles; name selects first song."""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QApplication, QTableWidgetItem

from cueplayer.domain.models import Project, SetlistCategory
from cueplayer.ui.main_window import MainWindow, SetlistWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_category_triangle_hit_detects_arrow_zone(app: QApplication) -> None:
    widget = SetlistWidget()
    widget.show()
    app.processEvents()

    item = QTableWidgetItem("▸ Rehearsal")
    item.setData(SetlistWidget.ROLE_KIND, "category")
    item.setData(Qt.ItemDataRole.UserRole, "cat-1")
    widget.setRowCount(1)
    widget.setItem(0, SetlistWidget.COL_NUM, item)
    widget.setSpan(0, SetlistWidget.COL_NUM, 1, 4)
    app.processEvents()

    rect = widget.visualRect(widget.model().index(0, SetlistWidget.COL_NUM))
    fm = QFontMetrics(item.font())
    triangle_edge = rect.left() + fm.horizontalAdvance("▸ ")
    assert widget._category_triangle_hit(0, triangle_edge - 1) is True
    assert widget._category_triangle_hit(0, triangle_edge + 2) is False


def test_select_first_song_keeps_collapsed_folder_collapsed(app: QApplication) -> None:
    project = Project.create("Folder Click")
    folder = SetlistCategory.create("Archive")
    folder.collapsed = True
    project.setlist_categories.append(folder)
    first = project.new_song("First in folder")
    first.category_id = folder.id
    second = project.new_song("Second in folder")
    second.category_id = folder.id
    project.songs = [first, second]

    with patch.object(MainWindow, "_confirm_discard_if_dirty", return_value=True):
        window = MainWindow(project=project)
        window.show()
        app.processEvents()

        window._activate_song(1, stop_playback=True)
        assert window.current_song is second

        window._select_first_song_in_category(folder.id)
        assert window.current_song is first
        assert folder.collapsed is True

        window.close()
        app.processEvents()
