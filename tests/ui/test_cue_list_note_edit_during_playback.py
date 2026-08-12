"""Playback cue changes must not reset an active Cue List Note editor."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QAbstractItemDelegate

from cueplayer.domain.models import Song
from cueplayer.ui.cue_monitor_panel import CueMonitorPanel


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_crossing_next_cue_preserves_uncommitted_note_text(
    app: QApplication,
) -> None:
    song = Song.create("Live Note edit")
    song.duration_seconds = 10.0
    first = song.add_mark(1, 1.0)
    second = song.add_mark(1, 2.0)
    lane = song.lane_by_index(1)
    assert lane is not None
    lane.cue_list_enabled = True
    lane.now_display = "primary"

    panel = CueMonitorPanel()
    panel.resize(700, 700)
    panel.set_song(song)
    panel.show()
    panel.set_position(first.time_seconds + 0.01, song.duration_seconds)
    app.processEvents()

    row = panel._row_for_mark_id(first.id)
    note_col = panel._col_for_field("note")
    item = panel.cue_table.item(row, note_col)
    assert item is not None
    panel.cue_table.setCurrentItem(item)
    panel.cue_table.editItem(item)
    app.processEvents()
    editor = panel.cue_table.findChild(QLineEdit)
    assert editor is not None
    editor.setText("Still typing this note")

    panel.set_position(second.time_seconds + 0.01, song.duration_seconds)
    app.processEvents()

    assert editor.text() == "Still typing this note"
    assert first.display_name == ""  # still intentionally uncommitted
    panel.cue_table.closeEditor(
        editor, QAbstractItemDelegate.EndEditHint.RevertModelCache
    )
    panel.close()
    app.processEvents()


def test_crossing_cue_does_not_interrupt_adjacent_note_editor(
    app: QApplication,
) -> None:
    song = Song.create("Continuous Note edit")
    song.duration_seconds = 10.0
    first = song.add_mark(1, 1.0)
    second = song.add_mark(1, 2.0)
    third = song.add_mark(1, 3.0)
    lane = song.lane_by_index(1)
    assert lane is not None
    lane.cue_list_enabled = True
    lane.now_display = "primary"

    panel = CueMonitorPanel()
    panel.resize(700, 700)
    panel.set_song(song)
    panel.show()
    panel.set_position(first.time_seconds + 0.01, song.duration_seconds)
    app.processEvents()

    note_col = panel._col_for_field("note")
    first_row = panel._row_for_mark_id(first.id)
    panel.cue_table.setCurrentCell(first_row, note_col)
    panel.cue_table.editItem(panel.cue_table.item(first_row, note_col))
    app.processEvents()
    editor = app.focusWidget()
    assert isinstance(editor, QLineEdit)
    editor.setText("First note")
    QTest.keyClick(editor, Qt.Key.Key_Down)
    app.processEvents()

    next_editor = app.focusWidget()
    assert isinstance(next_editor, QLineEdit)
    assert int(next_editor.property("cue_list_row")) == panel._row_for_mark_id(second.id)
    next_editor.setText("Still entering second note")

    panel.set_position(third.time_seconds + 0.01, song.duration_seconds)
    app.processEvents()

    assert app.focusWidget() is next_editor
    assert next_editor.text() == "Still entering second note"
    assert panel.cue_table.currentRow() == panel._row_for_mark_id(second.id)
    panel.cue_table.closeEditor(
        next_editor, QAbstractItemDelegate.EndEditHint.RevertModelCache
    )
    panel.close()
    app.processEvents()


def test_mouse_handoff_to_another_note_survives_playhead_follow(
    app: QApplication,
) -> None:
    song = Song.create("Mouse Note edit")
    song.duration_seconds = 10.0
    first = song.add_mark(1, 1.0)
    second = song.add_mark(1, 2.0)
    third = song.add_mark(1, 3.0)
    lane = song.lane_by_index(1)
    assert lane is not None
    lane.cue_list_enabled = True

    panel = CueMonitorPanel()
    panel.resize(700, 700)
    panel.set_song(song)
    panel.show()
    panel.set_position(first.time_seconds + 0.01, song.duration_seconds)
    app.processEvents()

    note_col = panel._col_for_field("note")
    first_row = panel._row_for_mark_id(first.id)
    second_row = panel._row_for_mark_id(second.id)
    panel.cue_table.setCurrentCell(first_row, note_col)
    panel.cue_table.editItem(panel.cue_table.item(first_row, note_col))
    app.processEvents()
    first_editor = app.focusWidget()
    assert isinstance(first_editor, QLineEdit)
    first_editor.setText("First mouse note")

    target_index = panel.cue_table.model().index(second_row, note_col)
    target = panel.cue_table.visualRect(target_index).center()
    QTest.mouseClick(panel.cue_table.viewport(), Qt.MouseButton.LeftButton, pos=target)
    app.processEvents()

    second_editor = app.focusWidget()
    assert isinstance(second_editor, QLineEdit)
    assert int(second_editor.property("cue_list_row")) == second_row
    second_editor.setText("Typing after mouse handoff")
    panel.set_position(third.time_seconds + 0.01, song.duration_seconds)
    app.processEvents()

    assert app.focusWidget() is second_editor
    assert second_editor.text() == "Typing after mouse handoff"
    assert panel.cue_table.currentRow() == second_row
    panel.cue_table.closeEditor(
        second_editor, QAbstractItemDelegate.EndEditHint.RevertModelCache
    )
    panel.close()
    app.processEvents()
