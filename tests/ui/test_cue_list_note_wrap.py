"""Cue List Note column wraps and grows the whole row."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song
from cueplayer.ui.cue_monitor_panel import (
    CueMonitorPanel,
    _NOTE_PAD_X,
    _NOTE_PAD_Y,
    _NOTE_WRAP_FLAGS,
    _ROW_HEIGHT,
    _note_text_height,
)


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
    # One extra lineSpacing of slack is OK for short notes.
    fm = QFontMetrics(panel.cue_table.font())
    assert _ROW_HEIGHT <= panel.cue_table.rowHeight(0) <= _ROW_HEIGHT + fm.lineSpacing() + 2


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


def test_tall_note_row_centers_time_type_cue_id(app: QApplication) -> None:
    song = Song.create("Note center")
    song.add_mark(
        1,
        1.0,
        "我現在跟你說我現在要超過整行了喔你最好要小心" * 2,
    )
    panel = CueMonitorPanel()
    panel.resize(480, 640)
    panel.set_song(song)
    panel.cue_table.setColumnWidth(panel._col_for_field("note"), 100)
    panel.refresh_list()
    assert panel.cue_table.rowHeight(0) > _ROW_HEIGHT
    center = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
    for field in ("time", "type", "cue_id"):
        item = panel.cue_table.item(0, panel._col_for_field(field))
        assert item is not None
        assert item.textAlignment() & Qt.AlignmentFlag.AlignHCenter
        assert item.textAlignment() & Qt.AlignmentFlag.AlignVCenter
        assert int(item.textAlignment()) & int(center) == int(center)
    note = panel.cue_table.item(0, panel._col_for_field("note"))
    assert note is not None
    assert note.textAlignment() & Qt.AlignmentFlag.AlignVCenter
    assert note.textAlignment() & Qt.AlignmentFlag.AlignLeft


def test_cjk_note_row_tall_enough_for_full_text(app: QApplication) -> None:
    """Regression: last glyphs must not be clipped into an ellipsis."""
    text = "我現在跟你說我現在要超過整行了喔你最好要小心"
    song = Song.create("Note full")
    song.add_mark(1, 1.0, text)
    panel = CueMonitorPanel()
    panel.resize(480, 640)
    panel.set_song(song)
    note_col = panel._col_for_field("note")
    panel.cue_table.setColumnWidth(note_col, 96)
    panel.refresh_list()

    width = panel.cue_table.columnWidth(note_col)
    fm = QFontMetrics(panel.cue_table.font())
    inner = max(24, width - 2 * _NOTE_PAD_X)
    br = fm.boundingRect(0, 0, inner, 100000, _NOTE_WRAP_FLAGS, text)
    needed = int(br.height()) + 2 * _NOTE_PAD_Y
    assert panel.cue_table.rowHeight(0) >= needed
    assert panel.cue_table.rowHeight(0) == _note_text_height(fm, text, width)
    # Full string must fit in the inner text rect we paint into.
    paint_h = panel.cue_table.rowHeight(0) - 2 * _NOTE_PAD_Y
    fitted = fm.boundingRect(0, 0, inner, paint_h, _NOTE_WRAP_FLAGS, text)
    assert fitted.height() <= paint_h
