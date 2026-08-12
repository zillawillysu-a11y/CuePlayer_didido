"""Playback cue changes must not reset an active Cue List Note editor."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

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
