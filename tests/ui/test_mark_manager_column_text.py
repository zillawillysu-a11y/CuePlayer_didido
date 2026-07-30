"""Mark Manager table columns should show full header and combo labels."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QComboBox

from cueplayer.domain.models import Song
from cueplayer.ui.mark_manager_dialog import MarkManagerDialog, _COL_KEY, _COL_MIDI, _COL_MIDI_NOTE


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_shortcut_combo_uses_compact_digit_labels(app: QApplication) -> None:
    dialog = MarkManagerDialog(Song.create("Marks"))
    key = dialog.table.cellWidget(0, _COL_KEY)
    assert isinstance(key, QComboBox)
    assert key.itemText(0) == "(None)"
    assert key.itemText(1) == "1"
    assert "Shortcut" not in key.itemText(1)


def test_fixed_columns_keep_minimum_width_for_headers(app: QApplication) -> None:
    dialog = MarkManagerDialog(Song.create("Marks"))
    dialog.show()
    app.processEvents()
    dialog.resize(720, 560)
    app.processEvents()
    dialog._ensure_column_readability()
    header = dialog.table.horizontalHeader()
    assert header.sectionSize(_COL_MIDI) >= 80
    assert header.sectionSize(_COL_MIDI_NOTE) >= 116
