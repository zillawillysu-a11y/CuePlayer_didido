"""Cue ID Up/Down vertical navigation (reuses the Note column's editor-swap
mechanism: commit-and-open-adjacent via the shared item delegate)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QLineEdit

from cueplayer.domain.models import Song
from cueplayer.ui.cue_monitor_panel import CueMonitorPanel, LOGICAL_INDEX_BY_FIELD


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _song_with_marks() -> tuple[Song, list[str]]:
    song = Song.create("Nav")
    ids = []
    for i, cue_id in enumerate(("101", "102", "103"), start=1):
        mark = song.add_mark(1, float(i))
        mark.main_cue_id = cue_id
        ids.append(mark.id)
    return song, ids


def _panel_with_song() -> tuple[CueMonitorPanel, Song, list[str]]:
    song, ids = _song_with_marks()
    panel = CueMonitorPanel()
    panel.set_song(song)
    return panel, song, ids


def _send_vertical_key(editor: QLineEdit, key) -> None:
    event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(editor, event)


from PySide6.QtCore import Qt  # noqa: E402  (kept near usage above)


def test_cue_id_down_commits_and_opens_next_row_editor(app: QApplication) -> None:
    del app
    panel, song, ids = _panel_with_song()
    col = LOGICAL_INDEX_BY_FIELD["cue_id"]
    row0 = panel._mark_id_to_row[ids[0]]  # noqa: SLF001
    item0 = panel.cue_table.item(row0, col)
    panel.cue_table.setCurrentCell(row0, col)
    panel.cue_table.editItem(item0)

    editor = panel.cue_table.focusWidget()
    assert isinstance(editor, QLineEdit)
    editor.setText("100")  # still fits order: less than the next mark's 102

    _send_vertical_key(editor, Qt.Key.Key_Down)
    QApplication.processEvents()
    QApplication.processEvents()  # second pump for the QTimer.singleShot(0, ...) hop

    mark0 = next(m for m in song.marks if m.id == ids[0])
    assert mark0.main_cue_id == "100"  # committed before navigating away

    assert panel.cue_table.state() == panel.cue_table.State.EditingState
    row1 = panel._mark_id_to_row[ids[1]]  # noqa: SLF001
    assert panel.cue_table.currentRow() == row1
    assert panel.cue_table.currentColumn() == col

    next_editor = panel.cue_table.focusWidget()
    assert isinstance(next_editor, QLineEdit)
    assert next_editor.text() == "102"
    assert next_editor.selectedText() == "102"  # select-all on arrival


def test_cue_id_up_commits_and_opens_previous_row_editor(app: QApplication) -> None:
    del app
    panel, song, ids = _panel_with_song()
    col = LOGICAL_INDEX_BY_FIELD["cue_id"]
    row1 = panel._mark_id_to_row[ids[1]]  # noqa: SLF001
    item1 = panel.cue_table.item(row1, col)
    panel.cue_table.setCurrentCell(row1, col)
    panel.cue_table.editItem(item1)

    editor = panel.cue_table.focusWidget()
    editor.setText("101.5")  # still fits order: between neighbors 101 and 103
    _send_vertical_key(editor, Qt.Key.Key_Up)
    QApplication.processEvents()
    QApplication.processEvents()

    mark1 = next(m for m in song.marks if m.id == ids[1])
    assert mark1.main_cue_id == "101.5"

    row0 = panel._mark_id_to_row[ids[0]]  # noqa: SLF001
    assert panel.cue_table.currentRow() == row0
    assert panel.cue_table.state() == panel.cue_table.State.EditingState


def test_cue_id_first_row_up_does_not_wrap(app: QApplication) -> None:
    del app
    panel, song, ids = _panel_with_song()
    col = LOGICAL_INDEX_BY_FIELD["cue_id"]
    row0 = panel._mark_id_to_row[ids[0]]  # noqa: SLF001
    item0 = panel.cue_table.item(row0, col)
    panel.cue_table.setCurrentCell(row0, col)
    panel.cue_table.editItem(item0)

    editor = panel.cue_table.focusWidget()
    _send_vertical_key(editor, Qt.Key.Key_Up)
    QApplication.processEvents()
    QApplication.processEvents()

    assert panel.cue_table.currentRow() == row0  # stayed on the first row


def test_cue_id_last_row_down_does_not_wrap(app: QApplication) -> None:
    del app
    panel, song, ids = _panel_with_song()
    col = LOGICAL_INDEX_BY_FIELD["cue_id"]
    last_row = panel._mark_id_to_row[ids[-1]]  # noqa: SLF001
    item_last = panel.cue_table.item(last_row, col)
    panel.cue_table.setCurrentCell(last_row, col)
    panel.cue_table.editItem(item_last)

    editor = panel.cue_table.focusWidget()
    _send_vertical_key(editor, Qt.Key.Key_Down)
    QApplication.processEvents()
    QApplication.processEvents()

    assert panel.cue_table.currentRow() == last_row  # stayed on the last row


def test_note_navigation_regression_still_works(app: QApplication) -> None:
    # B8: widening the Cue ID guard must not disturb the existing Note nav.
    del app
    panel, song, ids = _panel_with_song()
    col = LOGICAL_INDEX_BY_FIELD["note"]
    row0 = panel._mark_id_to_row[ids[0]]  # noqa: SLF001
    item0 = panel.cue_table.item(row0, col)
    panel.cue_table.setCurrentCell(row0, col)
    panel.cue_table.editItem(item0)

    editor = panel.cue_table.focusWidget()
    editor.setText("hello")
    _send_vertical_key(editor, Qt.Key.Key_Down)
    QApplication.processEvents()
    QApplication.processEvents()

    mark0 = next(m for m in song.marks if m.id == ids[0])
    assert mark0.display_name == "hello"
    row1 = panel._mark_id_to_row[ids[1]]  # noqa: SLF001
    assert panel.cue_table.currentRow() == row1
    assert panel.cue_table.currentColumn() == col
