"""Cue List Note editor: ↓ / ↑ commits and opens the adjacent row."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView, QApplication, QLineEdit

from cueplayer.domain.models import Song
from cueplayer.ui.cue_monitor_panel import CueMonitorPanel


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _note_editor(panel: CueMonitorPanel) -> QLineEdit:
    editor = panel.cue_table.focusWidget()
    assert isinstance(editor, QLineEdit), f"expected QLineEdit, got {type(editor)}"
    return editor


def test_note_down_arrow_opens_next_row_editor(app: QApplication) -> None:
    song = Song.create("Arrow nav")
    song.add_mark(1, 1.0, "Intro")
    song.add_mark(1, 2.0, "")
    song.add_mark(1, 3.0, "Outro")
    panel = CueMonitorPanel()
    panel.set_song(song)
    panel.refresh_list()
    note_col = panel._col_for_field("note")

    first = panel.cue_table.item(0, note_col)
    assert first is not None
    panel.cue_table.editItem(first)
    assert panel.cue_table.state() == QAbstractItemView.State.EditingState

    editor = _note_editor(panel)
    editor.setText("Intro edited")
    QTest.keyClick(editor, Qt.Key.Key_Down)
    QApplication.processEvents()

    assert song.marks[0].display_name == "Intro edited"
    assert panel.cue_table.state() == QAbstractItemView.State.EditingState
    assert panel.cue_table.currentRow() == 1
    assert panel.cue_table.currentColumn() == note_col


def test_note_up_arrow_opens_previous_row_editor(app: QApplication) -> None:
    song = Song.create("Arrow up")
    song.add_mark(1, 1.0, "A")
    song.add_mark(1, 2.0, "B")
    panel = CueMonitorPanel()
    panel.set_song(song)
    panel.refresh_list()
    note_col = panel._col_for_field("note")

    second = panel.cue_table.item(1, note_col)
    assert second is not None
    panel.cue_table.editItem(second)
    editor = _note_editor(panel)
    QTest.keyClick(editor, Qt.Key.Key_Up)
    QApplication.processEvents()

    assert panel.cue_table.state() == QAbstractItemView.State.EditingState
    assert panel.cue_table.currentRow() == 0


def test_note_down_on_last_row_just_commits(app: QApplication) -> None:
    song = Song.create("Arrow last")
    song.add_mark(1, 1.0, "Only")
    panel = CueMonitorPanel()
    panel.set_song(song)
    panel.refresh_list()
    note_col = panel._col_for_field("note")

    item = panel.cue_table.item(0, note_col)
    assert item is not None
    panel.cue_table.editItem(item)
    editor = _note_editor(panel)
    editor.setText("Solo")
    QTest.keyClick(editor, Qt.Key.Key_Down)
    QApplication.processEvents()

    assert song.marks[0].display_name == "Solo"
    assert panel.cue_table.state() != QAbstractItemView.State.EditingState
