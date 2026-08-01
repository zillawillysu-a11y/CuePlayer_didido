"""Cue List Note column wraps and grows the whole row."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song
from cueplayer.ui.cue_monitor_panel import CueMonitorPanel, _ROW_HEIGHT


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_long_note_grows_cue_list_row_height(app: QApplication) -> None:
    song = Song.create("Note wrap")
    song.add_mark(
        1,
        1.0,
        "這是一段很長的備註用來測試換行顯示是否會把整列拉高" * 3,
    )
    panel = CueMonitorPanel()
    panel.resize(480, 640)
    panel.set_song(song)
    panel.cue_table.setColumnWidth(panel._col_for_field("note"), 120)
    panel.refresh_list()
    assert panel.cue_table.rowCount() == 1
    assert panel.cue_table.rowHeight(0) > _ROW_HEIGHT


def test_short_note_keeps_near_minimum_row_height(app: QApplication) -> None:
    song = Song.create("Note short")
    song.add_mark(1, 1.0, "Verse")
    panel = CueMonitorPanel()
    panel.set_song(song)
    panel.refresh_list()
    # FontMetrics + padding may be 1px above the nominal default.
    assert _ROW_HEIGHT <= panel.cue_table.rowHeight(0) <= _ROW_HEIGHT + 4


def test_note_column_resize_reflows_row_height(app: QApplication) -> None:
    song = Song.create("Note reflow")
    song.add_mark(1, 1.0, "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" * 4)
    panel = CueMonitorPanel()
    panel.set_song(song)
    note_col = panel._col_for_field("note")
    panel.cue_table.setColumnWidth(note_col, 80)
    panel.refresh_list()
    tall = panel.cue_table.rowHeight(0)
    panel.cue_table.setColumnWidth(note_col, 400)
    panel._reflow_note_row_heights()
    assert panel.cue_table.rowHeight(0) < tall
