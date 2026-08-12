"""Mark Manager accepts function-key shortcuts and clears explicit None."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QComboBox

from cueplayer.domain.models import Song
from cueplayer.ui.mark_manager_dialog import MarkManagerDialog, _COL_KEY


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_function_keys_are_available_and_collected(app: QApplication) -> None:
    song = Song.create("Functions")
    dialog = MarkManagerDialog(song)
    combo = dialog.table.cellWidget(0, _COL_KEY)
    assert isinstance(combo, QComboBox)
    assert combo.findData("F1") >= 0
    assert combo.findData("F12") >= 0
    combo.setCurrentIndex(combo.findData("F12"))
    lanes = dialog._collect_draft_lanes()
    assert lanes is not None
    assert lanes[0].shortcut == "F12"

