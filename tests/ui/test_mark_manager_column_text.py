"""Mark Manager table columns should show full header and combo labels."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QComboBox

from cueplayer.domain.models import Song
from cueplayer.ui.mark_manager_dialog import MarkManagerDialog, _COL_KEY, _COL_SHAPE


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
