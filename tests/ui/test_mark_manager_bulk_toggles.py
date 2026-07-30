"""Mark Manager bulk column toggles."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song
from cueplayer.ui.mark_manager_dialog import (
    MarkManagerDialog,
    _COL_COUNT,
    _COL_CUE_ID,
    _COL_MIDI,
    _COL_MIDI_NOTE,
    _COL_VISIBLE,
)


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_bulk_visible_toggle_sets_all_rows(app: QApplication) -> None:
    song = Song.create("Test")
    dialog = MarkManagerDialog(song)
    bulk = dialog._bulk_checks[_COL_VISIBLE]
    bulk.setCheckState(Qt.CheckState.Unchecked)
    dialog._on_bulk_toggle_changed(_COL_VISIBLE)
    for row in range(dialog.table.rowCount()):
        box = dialog._checkbox_at(row, _COL_VISIBLE)
        assert box is not None
        assert box.isChecked() is False
    bulk.setCheckState(Qt.CheckState.Checked)
    dialog._on_bulk_toggle_changed(_COL_VISIBLE)
    for row in range(dialog.table.rowCount()):
        box = dialog._checkbox_at(row, _COL_VISIBLE)
        assert box is not None
        assert box.isChecked() is True


def test_bulk_reflects_mixed_row_state(app: QApplication) -> None:
    song = Song.create("Test")
    dialog = MarkManagerDialog(song)
    dialog._refresh_bulk_toggle_states()
    assert dialog._bulk_checks[_COL_CUE_ID].checkState() == Qt.CheckState.PartiallyChecked


def test_bulk_toggle_row_tracks_table_columns_on_resize(app: QApplication) -> None:
    song = Song.create("Align")
    dialog = MarkManagerDialog(song)
    dialog.resize(920, 640)
    dialog.show()
    app.processEvents()
    dialog.resize(640, 640)
    app.processEvents()
    dialog._sync_bulk_toggle_layout()
    app.processEvents()

    header = dialog.table.horizontalHeader()
    assert len(dialog._bulk_column_cells) == _COL_COUNT
    for col, cell in enumerate(dialog._bulk_column_cells):
        assert cell.width() == header.sectionSize(col)
    assert dialog._bulk_checks[_COL_VISIBLE].parentWidget() is dialog._bulk_column_cells[_COL_VISIBLE]
    assert dialog._bulk_column_cells[_COL_MIDI_NOTE].width() == header.sectionSize(_COL_MIDI_NOTE)


def test_bulk_toggle_cells_track_header_section_positions(app: QApplication) -> None:
    song = Song.create("Align")
    dialog = MarkManagerDialog(song)
    dialog.resize(1120, 640)
    dialog.show()
    app.processEvents()
    dialog._sync_bulk_toggle_layout()
    app.processEvents()

    viewport = dialog.table.viewport()
    origin_x = viewport.mapTo(dialog._bulk_row, QPoint(0, 0)).x()
    expected_visible_x = origin_x + dialog.table.columnViewportPosition(_COL_VISIBLE)
    assert dialog._bulk_column_cells[_COL_VISIBLE].x() == expected_visible_x
    assert dialog._bulk_checks[_COL_VISIBLE].parentWidget() is dialog._bulk_column_cells[_COL_VISIBLE]
