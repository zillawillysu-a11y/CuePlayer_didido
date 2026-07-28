"""Setlist folder row: only the triangle toggles expand/collapse."""

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
    triangle_edge = rect.left() + max(
        SetlistWidget._TRIANGLE_HIT_MIN_PX, fm.horizontalAdvance("▸ ") + 4
    )
    assert widget._category_triangle_hit(0, triangle_edge - 1) is True
    assert widget._category_triangle_hit(0, triangle_edge + 2) is False


def test_folder_name_click_does_not_change_collapse_or_song(app: QApplication) -> None:
    project = Project.create("Folder Click")
    folder = SetlistCategory.create("Archive")
    folder.collapsed = True
    project.setlist_categories.append(folder)
    first = project.new_song("First in folder")
    first.category_id = folder.id
    second = project.new_song("Second in folder")
    second.category_id = folder.id
    project.songs = [first, second]

    toggles: list[str] = []

    with patch.object(MainWindow, "_confirm_discard_if_dirty", return_value=True):
        window = MainWindow(project=project)
        window._toggle_setlist_category = lambda cid: toggles.append(cid)  # type: ignore[method-assign]
        window.show()
        app.processEvents()

        window._activate_song(1, stop_playback=True)
        assert window.current_song is second
        assert folder.collapsed is True

        row = next(
            r
            for r in range(window.song_list.rowCount())
            if window.song_list.row_category_id(r) == folder.id
        )
        rect = window.song_list.visualRect(
            window.song_list.model().index(row, SetlistWidget.COL_NUM)
        )
        name_x = rect.left() + SetlistWidget._TRIANGLE_HIT_MIN_PX + 20
        from PySide6.QtCore import QPoint, QPointF
        from PySide6.QtGui import QMouseEvent

        viewport_pt = QPoint(name_x, int(rect.center().y()))
        widget_pt = window.song_list.viewport().mapTo(window.song_list, viewport_pt)
        event = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(widget_pt),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        window.song_list.mousePressEvent(event)

        assert toggles == []
        assert folder.collapsed is True
        assert window.current_song is second

        window.close()
        app.processEvents()


def test_folder_name_double_click_requests_rename(app: QApplication) -> None:
    project = Project.create("Folder Rename")
    folder = SetlistCategory.create("Archive")
    project.setlist_categories.append(folder)

    renames: list[str] = []

    def _capture_rename(_self, category_id: str) -> None:
        renames.append(category_id)

    with patch.object(MainWindow, "_confirm_discard_if_dirty", return_value=True):
        with patch.object(MainWindow, "_rename_setlist_category", _capture_rename):
            window = MainWindow(project=project)
            window.show()
        app.processEvents()

        row = next(
            r
            for r in range(window.song_list.rowCount())
            if window.song_list.row_category_id(r) == folder.id
        )
        rect = window.song_list.visualRect(
            window.song_list.model().index(row, SetlistWidget.COL_NUM)
        )
        name_x = rect.left() + SetlistWidget._TRIANGLE_HIT_MIN_PX + 20
        from PySide6.QtCore import QPoint, QPointF
        from PySide6.QtGui import QMouseEvent

        viewport_pt = QPoint(name_x, int(rect.center().y()))
        widget_pt = window.song_list.viewport().mapTo(window.song_list, viewport_pt)
        event = QMouseEvent(
            QMouseEvent.Type.MouseButtonDblClick,
            QPointF(widget_pt),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        window.song_list.mouseDoubleClickEvent(event)

        assert renames == [folder.id]

        window.close()
        app.processEvents()
