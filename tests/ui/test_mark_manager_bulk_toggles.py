"""Mark Manager bulk column toggles."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song
from cueplayer.ui.mark_manager_dialog import (
    MarkManagerDialog,
    _COL_ASK_NOTE,
    _COL_CUE_ID,
    _COL_CUE_LIST,
    _COL_MIDI,
    _COL_PAUSE,
    _COL_VISIBLE,
    _COL_WAVE_NOTE,
)


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _bulk_columns() -> tuple[int, ...]:
    return (
        _COL_VISIBLE,
        _COL_CUE_LIST,
        _COL_CUE_ID,
        _COL_MIDI,
        _COL_PAUSE,
        _COL_ASK_NOTE,
        _COL_WAVE_NOTE,
    )


def test_bulk_visible_toggle_sets_all_lane_rows(app: QApplication) -> None:
    song = Song.create("Test")
    dialog = MarkManagerDialog(song)
    bulk = dialog._bulk_checks[_COL_VISIBLE]
    bulk.setCheckState(Qt.CheckState.Unchecked)
    dialog._on_bulk_toggle_changed(_COL_VISIBLE)
    for row in range(dialog._lane_row_count()):
        box = dialog._checkbox_at(row, _COL_VISIBLE)
        assert box is not None
        assert box.isChecked() is False
    bulk.setCheckState(Qt.CheckState.Checked)
    dialog._on_bulk_toggle_changed(_COL_VISIBLE)
    for row in range(dialog._lane_row_count()):
        box = dialog._checkbox_at(row, _COL_VISIBLE)
        assert box is not None
        assert box.isChecked() is True


def test_bulk_reflects_mixed_row_state(app: QApplication) -> None:
    song = Song.create("Test")
    dialog = MarkManagerDialog(song)
    dialog._refresh_bulk_toggle_states()
    assert dialog._bulk_checks[_COL_CUE_ID].checkState() == Qt.CheckState.PartiallyChecked


def test_bulk_toggles_live_in_table_footer_row(app: QApplication) -> None:
    song = Song.create("Align")
    dialog = MarkManagerDialog(song)
    footer = dialog._bulk_footer_row
    assert footer is not None
    assert footer == dialog.table.rowCount() - 1
    for col in _bulk_columns():
        wrap = dialog.table.cellWidget(footer, col)
        assert wrap is not None
        assert dialog._bulk_checks[col].parentWidget() is wrap


def test_bulk_footer_stays_column_aligned_after_resize(app: QApplication) -> None:
    song = Song.create("Align")
    dialog = MarkManagerDialog(song)
    dialog.resize(920, 640)
    dialog.show()
    app.processEvents()
    dialog.resize(640, 640)
    app.processEvents()

    footer = dialog._bulk_footer_row
    assert footer is not None
    header = dialog.table.horizontalHeader()
    for col in _bulk_columns():
        wrap = dialog.table.cellWidget(footer, col)
        assert wrap is not None
        assert dialog.table.columnWidth(col) == header.sectionSize(col)
        assert dialog._bulk_checks[col].parentWidget() is wrap
