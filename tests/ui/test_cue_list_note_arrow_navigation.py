from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit

from cueplayer.domain.models import Mark, Song
from cueplayer.ui.cue_monitor_panel import CueMonitorPanel


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _song() -> Song:
    song = Song.create("方向鍵 Note")
    lane = song.mark_lanes[0]
    lane.visible = True
    lane.cue_list_enabled = True
    song.marks = [
        Mark.create(lane_index=lane.index, time_seconds=float(i), display_name=f"舊{i}")
        for i in range(3)
    ]
    song.sort_marks()
    return song


def test_down_commits_note_and_opens_next_note_editor(app: QApplication) -> None:
    panel = CueMonitorPanel()
    panel.resize(500, 700)
    panel.show()
    song = _song()
    panel.set_song(song)
    app.processEvents()
    note_col = panel._col_for_field("note")  # noqa: SLF001
    item = panel.cue_table.item(0, note_col)
    panel.cue_table.setCurrentCell(0, note_col)
    panel.cue_table.editItem(item)
    app.processEvents()
    editor = panel.cue_table.findChild(QLineEdit)
    assert editor is not None
    editor.selectAll()
    QTest.keyClicks(editor, "Hello")
    QTest.keyClick(editor, Qt.Key.Key_Down)
    app.processEvents()
    assert song.marks[0].display_name == "Hello"
    assert panel.cue_table.currentRow() == 1
    next_editor = app.focusWidget()
    assert isinstance(next_editor, QLineEdit)
    assert int(next_editor.property("cue_list_row")) == 1


def test_up_from_second_row_opens_previous_editor(app: QApplication) -> None:
    panel = CueMonitorPanel()
    panel.resize(500, 700)
    panel.show()
    panel.set_song(_song())
    app.processEvents()
    note_col = panel._col_for_field("note")  # noqa: SLF001
    panel.cue_table.setCurrentCell(1, note_col)
    panel.cue_table.editItem(panel.cue_table.item(1, note_col))
    app.processEvents()
    editor = panel.cue_table.findChild(QLineEdit)
    assert editor is not None
    QTest.keyClick(editor, Qt.Key.Key_Up)
    app.processEvents()
    assert panel.cue_table.currentRow() == 0
    previous_editor = app.focusWidget()
    assert isinstance(previous_editor, QLineEdit)
    assert int(previous_editor.property("cue_list_row")) == 0
