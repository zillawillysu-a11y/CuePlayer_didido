"""Cue List time uses double-click editing and an undoable move command."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project
from cueplayer.ui.main_window import MainWindow


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_time_item_edit_moves_mark_and_undo_restores(app: QApplication) -> None:
    window = MainWindow(Project.create("Time Edit"))
    song = window.current_song
    mark = song.add_mark(1, 2.0, "Cue")
    window.monitor.set_song(song)
    window.monitor.refresh_list()
    col = window.monitor._time_col()
    item = window.monitor.cue_table.item(0, col)
    assert item.flags() & Qt.ItemFlag.ItemIsEditable

    item.setText("00:05.500")
    app.processEvents()
    assert mark.time_seconds == pytest.approx(5.5)

    window._undo_action()
    assert mark.time_seconds == pytest.approx(2.0)
