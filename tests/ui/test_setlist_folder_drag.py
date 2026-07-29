"""Setlist folder drag-reorder."""

from __future__ import annotations

import os

# Headless CI / cloud agents: Qt needs an offscreen platform.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QDrag, QMouseEvent
from PySide6.QtWidgets import QApplication, QTableWidgetItem

from cueplayer.domain.models import Project, SetlistCategory
from cueplayer.ui.main_window import MainWindow, SetlistWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _cat(widget: SetlistWidget, row: int, cat_id: str) -> None:
    item = QTableWidgetItem(f"▾ Folder {cat_id}")
    item.setData(SetlistWidget.ROLE_KIND, "category")
    item.setData(Qt.ItemDataRole.UserRole, cat_id)
    item.setFlags(
        Qt.ItemFlag.ItemIsEnabled
        | Qt.ItemFlag.ItemIsSelectable
        | Qt.ItemFlag.ItemIsDragEnabled
    )
    widget.setItem(row, SetlistWidget.COL_NUM, item)


def _song(widget: SetlistWidget, row: int, song_id: str) -> None:
    item = QTableWidgetItem("1")
    item.setData(SetlistWidget.ROLE_KIND, "song")
    item.setData(Qt.ItemDataRole.UserRole, song_id)
    item.setFlags(
        Qt.ItemFlag.ItemIsEnabled
        | Qt.ItemFlag.ItemIsSelectable
        | Qt.ItemFlag.ItemIsDragEnabled
    )
    widget.setItem(row, SetlistWidget.COL_NUM, item)


def test_category_drop_target_hits_folder_title(app: QApplication) -> None:
    widget = SetlistWidget()
    widget.resize(320, 240)
    widget.setRowCount(4)
    for row in range(4):
        widget.setRowHeight(row, 28)
    _song(widget, 0, "s0")
    _cat(widget, 1, "folder-a")
    _song(widget, 2, "s1")
    _song(widget, 3, "s2")
    widget.show()
    app.processEvents()

    rect = widget._row_visual_rect(1)
    assert widget._category_drop_target(QPoint(20, rect.center().y())) == "folder-a"
    # Just under the header still counts as the folder (not main list).
    assert widget._category_drop_target(QPoint(20, rect.bottom() + 4)) == "folder-a"
    # Deep into a song row under the folder is not a folder-title drop.
    song_rect = widget._row_visual_rect(3)
    assert widget._category_drop_target(QPoint(20, song_rect.center().y())) is None

    widget = SetlistWidget()
    widget.setRowCount(5)

    _song(widget, 0, "s0")
    _cat(widget, 1, "a")
    _song(widget, 2, "s1")
    _cat(widget, 3, "b")
    _song(widget, 4, "s2")

    assert widget._folder_insert_index_at(0) == 0
    assert widget._folder_insert_index_at(1) == 0
    assert widget._folder_insert_index_at(2) == 1
    assert widget._folder_insert_index_at(3) == 1
    assert widget._folder_insert_index_at(4) == 2
    assert widget._folder_insert_index_at(5) == 2


def test_folder_boundary_insert_snaps_to_folder_edges(app: QApplication) -> None:
    widget = SetlistWidget()
    widget.resize(320, 240)
    widget.setRowCount(5)
    for row in range(5):
        widget.setRowHeight(row, 28)

    _song(widget, 0, "s0")
    _cat(widget, 1, "a")
    _song(widget, 2, "s1")
    _cat(widget, 3, "b")
    _song(widget, 4, "s2")
    widget.show()
    app.processEvents()

    # Above folder A midpoint → insert before A (row 1).
    rect_a = widget._row_visual_rect(1)
    assert widget._folder_boundary_insert_row(QPoint(10, rect_a.top() + 2)) == 1

    # Below folder A midpoint / on its songs → after A's block (row 3 = folder B).
    rect_song = widget._row_visual_rect(2)
    assert widget._folder_boundary_insert_row(QPoint(10, rect_song.center().y())) == 3

    # Below last folder midpoint → after last folder block (end).
    rect_b = widget._row_visual_rect(3)
    assert widget._folder_boundary_insert_row(QPoint(10, rect_b.bottom() - 1)) == 5


def test_folder_title_press_clears_unrelated_song_selection(app: QApplication) -> None:
    widget = SetlistWidget()
    widget.resize(320, 240)
    widget.setRowCount(4)
    for row in range(4):
        widget.setRowHeight(row, 28)

    _cat(widget, 0, "a")
    _song(widget, 1, "s1")
    _cat(widget, 2, "b")
    _song(widget, 3, "s2")
    widget.show()
    app.processEvents()

    widget.item(1, SetlistWidget.COL_NUM).setSelected(True)
    widget.item(3, SetlistWidget.COL_NUM).setSelected(True)
    assert widget._selected_song_rows() == [1, 3]

    # Press on folder B title (away from triangle).
    rect = widget._row_visual_rect(2)
    press_pos = QPoint(rect.left() + 80, rect.center().y())

    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        press_pos,
        widget.viewport().mapToGlobal(press_pos),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mousePressEvent(press)

    assert widget._press_category_id == "b"
    assert widget._drag_song_ids == []
    assert widget._selected_song_rows() == []
    # Folder row alone is selected for the pending drag.
    assert widget.row_category_id(widget.currentRow()) == "b"
    assert widget._saved_song_selection_rows == [1, 3]

    # Release without dragging restores prior song selection.
    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        press_pos,
        widget.viewport().mapToGlobal(press_pos),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mouseReleaseEvent(release)
    assert widget._press_category_id is None
    assert widget._selected_song_rows() == [1, 3]


def test_start_folder_drag_ignores_selected_songs(app: QApplication) -> None:
    widget = SetlistWidget()
    widget.setRowCount(3)
    _cat(widget, 0, "a")
    _song(widget, 1, "s1")
    _song(widget, 2, "s2")
    widget.item(1, SetlistWidget.COL_NUM).setSelected(True)
    widget.item(2, SetlistWidget.COL_NUM).setSelected(True)
    widget._press_category_id = "a"
    widget._drag_song_ids = ["s1", "s2"]  # stale leftover must be cleared

    # Don't call real drag.exec in headless — exercise the prep path via a stub.
    started: list[str] = []

    def _fake_exec(self, *_args, **_kwargs):  # noqa: ANN001
        started.append(widget._drag_category_id or "")
        return Qt.DropAction.IgnoreAction

    original = QDrag.exec
    QDrag.exec = _fake_exec  # type: ignore[method-assign]
    try:
        widget._start_folder_drag()
    finally:
        QDrag.exec = original  # type: ignore[method-assign]

    assert started == ["a"]
    assert widget._drag_song_ids == []
    assert widget._drag_category_id is None
    assert widget._press_category_id is None


def test_reorder_folders_keeps_song_membership(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
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
