"""Mark Manager table columns should show full header and combo labels."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QComboBox

from cueplayer.domain.models import Song
from cueplayer.ui.mark_manager_dialog import (
    MarkManagerDialog,
    _COL_CUE_ID,
    _COL_CUE_LIST,
    _COL_KEY,
    _COL_MIDI_NOTE,
    _COL_NOW,
    _COL_SHAPE,
    _COLUMN_MIN_WIDTHS,
    _HEADER_LABELS,
)


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_cue_list_column_before_cue_id(app: QApplication) -> None:
    dialog = MarkManagerDialog(Song.create("Marks"))
    assert dialog.table.horizontalHeaderItem(_COL_CUE_LIST).text() == "Cue List"
    assert dialog.table.horizontalHeaderItem(_COL_CUE_ID).text() == "Cue ID"
    assert _COL_CUE_LIST < _COL_CUE_ID


def test_shortcut_combo_uses_compact_digit_labels(app: QApplication) -> None:
    dialog = MarkManagerDialog(Song.create("Marks"))
    key = dialog.table.cellWidget(0, _COL_KEY)
    assert isinstance(key, QComboBox)
    assert key.itemText(0) == "(None)"
    assert key.itemText(1) == "1"
    assert "Shortcut" not in key.itemText(1)


def test_columns_can_be_narrowed_after_widening(app: QApplication) -> None:
    dialog = MarkManagerDialog(Song.create("Marks"))
    dialog.show()
    app.processEvents()
    header = dialog.table.horizontalHeader()
    header.resizeSection(_COL_SHAPE, 220)
    app.processEvents()
    assert header.sectionSize(_COL_SHAPE) == 220
    header.resizeSection(_COL_SHAPE, 100)
    app.processEvents()
    assert header.sectionSize(_COL_SHAPE) == 100


def test_headers_are_full_labels_not_truncated(app: QApplication) -> None:
    dialog = MarkManagerDialog(Song.create("Marks"))
    for col, label in enumerate(_HEADER_LABELS):
        assert dialog.table.horizontalHeaderItem(col).text() == label


def test_column_widths_cover_headers_and_combo_samples(app: QApplication) -> None:
    dialog = MarkManagerDialog(Song.create("Marks"))
    dialog.show()
    app.processEvents()
    header = dialog.table.horizontalHeader()
    metrics = dialog.table.fontMetrics()
    for col, label in enumerate(_HEADER_LABELS):
        width = header.sectionSize(col)
        assert width >= _COLUMN_MIN_WIDTHS[col]
        assert width >= metrics.horizontalAdvance(label) + 20


def test_now_and_note_combos_show_full_labels(app: QApplication) -> None:
    dialog = MarkManagerDialog(Song.create("Marks"))
    dialog.show()
    app.processEvents()
    now = dialog.table.cellWidget(0, _COL_NOW)
    note = dialog.table.cellWidget(0, _COL_MIDI_NOTE)
    shape = dialog.table.cellWidget(0, _COL_SHAPE)
    assert isinstance(now, QComboBox)
    assert isinstance(note, QComboBox)
    assert isinstance(shape, QComboBox)
    assert "Secondary" in [now.itemText(i) for i in range(now.count())]
    assert any(t.startswith("auto") for t in (note.itemText(i) for i in range(note.count())))
    assert dialog.table.columnWidth(_COL_NOW) >= _COLUMN_MIN_WIDTHS[_COL_NOW]
    assert dialog.table.columnWidth(_COL_MIDI_NOTE) >= _COLUMN_MIN_WIDTHS[_COL_MIDI_NOTE]
    assert dialog.table.columnWidth(_COL_SHAPE) >= _COLUMN_MIN_WIDTHS[_COL_SHAPE]
