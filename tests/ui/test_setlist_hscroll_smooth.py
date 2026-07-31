"""Setlist horizontal scrollbar scrolls smoothly and stays put on select."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QAbstractItemView, QApplication, QTableWidgetItem

from cueplayer.domain.models import Project
from cueplayer.ui.main_window import MainWindow, SetlistWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_setlist_horizontal_scroll_is_per_pixel(app: QApplication) -> None:
    widget = SetlistWidget()
    assert widget.horizontalScrollMode() == QAbstractItemView.ScrollMode.ScrollPerPixel
    assert widget.verticalScrollMode() == QAbstractItemView.ScrollMode.ScrollPerPixel


def test_select_row_does_not_yank_horizontal_scroll(app: QApplication) -> None:
    widget = SetlistWidget()
    widget.setRowCount(3)
    widget.setColumnWidth(SetlistWidget.COL_TITLE, 400)
    for row in range(3):
        for col in range(SetlistWidget.COL_COUNT):
            widget.setItem(row, col, QTableWidgetItem(f"{row}-{col}"))
    widget.resize(180, 240)
    widget.show()
    app.processEvents()

    bar = widget.horizontalScrollBar()
    assert bar.maximum() > 0
    target = max(1, bar.maximum() // 3)
    bar.setValue(target)
    assert bar.value() == target

    widget.selectRow(1)
    widget.setCurrentCell(1, SetlistWidget.COL_TITLE)
    widget.scrollTo(
        widget.model().index(1, SetlistWidget.COL_LTC),
        QAbstractItemView.ScrollHint.PositionAtCenter,
    )
    app.processEvents()
    assert widget.horizontalScrollBar().value() == target


def test_rebuild_preserves_horizontal_scroll(app: QApplication) -> None:
    window = MainWindow(Project.create("HScroll"))
    for i in range(4):
        window.project.new_song(f"Song {i} long title for overflow")
    window.song_list.setColumnWidth(SetlistWidget.COL_TITLE, 420)
    window.resize(900, 600)
    window.show()
    app.processEvents()
    # Squeeze the left pane so the Song column overflows.
    window._main_splitter.setSizes([160, 740])  # noqa: SLF001
    app.processEvents()

    bar = window.song_list.horizontalScrollBar()
    if bar.maximum() <= 0:
        window.song_list.setColumnWidth(SetlistWidget.COL_TITLE, 800)
        app.processEvents()
    assert bar.maximum() > 0
    target = max(1, min(40, bar.maximum()))
    window.song_list.set_horizontal_scroll_value(target)
    assert window.song_list.horizontal_scroll_value() == target

    window._rebuild_song_list(select_indexes=[2])
    app.processEvents()
    assert window.song_list.horizontal_scroll_value() == target
