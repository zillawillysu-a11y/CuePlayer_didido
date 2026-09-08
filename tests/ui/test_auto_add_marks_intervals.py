"""Auto Add Marks exposes the requested numeric beat intervals."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song
from cueplayer.ui.beat_grid_dialog import AutoAddMarksDialog


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_auto_add_interval_options_are_numeric_beats(app: QApplication) -> None:
    dialog = AutoAddMarksDialog(Song.create("Intervals"))

    assert [dialog.interval.itemText(i) for i in range(dialog.interval.count())] == [
        "0.5", "1", "2", "3", "4", "5", "6", "7", "8"
    ]
    assert [dialog.interval.itemData(i) for i in range(dialog.interval.count())] == [
        0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0
    ]
