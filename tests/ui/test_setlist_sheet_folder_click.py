"""Set List Sheet folder row: only the triangle toggles expand/collapse."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project, SetlistCategory, Song
from cueplayer.ui.setlist_sheet_page import SetlistSheetPage, _TRIANGLE_HIT_MIN_PX


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _press(app: QApplication, page: SetlistSheetPage, x: int, y: int) -> None:
    pos = QPoint(x, y)
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        pos,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(page.table.viewport(), event)
    app.processEvents()


def test_sheet_folder_triangle_only_toggles(app: QApplication) -> None:
    project = Project.create("Sheet Click")
    project.songs.clear()
    folder = SetlistCategory.create("VIP")
    project.setlist_categories.append(folder)
    song = Song.create("Inside")
    song.category_id = folder.id
    project.songs.append(song)

    page = SetlistSheetPage()
    page.set_project(project)
    assert page.table.rowCount() == 2

    item = page.table.item(0, 0)
    assert item is not None
    rect = page.table.visualRect(page.table.model().index(0, 0))
    mid_y = rect.center().y()
    triangle_x = rect.left() + 4
    name_x = rect.left() + _TRIANGLE_HIT_MIN_PX + 12

    _press(app, page, triangle_x, mid_y)
    assert folder.sheet_collapsed is True
    assert page.table.rowCount() == 1
    assert folder.collapsed is False

    rect = page.table.visualRect(page.table.model().index(0, 0))
    mid_y = rect.center().y()
    triangle_x = rect.left() + 4
    _press(app, page, triangle_x, mid_y)
    assert folder.sheet_collapsed is False
    assert page.table.rowCount() == 2

    name_x = rect.left() + _TRIANGLE_HIT_MIN_PX + 12
    _press(app, page, name_x, mid_y)
    assert folder.sheet_collapsed is False
    assert page.table.rowCount() == 2
