"""Mark Manager bulk column toggles."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song
from cueplayer.ui.mark_manager_dialog import MarkManagerDialog, _COL_CUE_ID, _COL_VISIBLE


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
