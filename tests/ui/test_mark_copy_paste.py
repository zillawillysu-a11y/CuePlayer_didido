"""Multi-Mark copy/paste preserves spacing and is undoable."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from cueplayer.domain.models import Project
from cueplayer.ui.main_window import MainWindow


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_multi_mark_copy_paste_relative_time_and_undo(app: QApplication) -> None:
    window = MainWindow(Project.create("Copy Marks"))
    song = window.current_song
    first = song.add_mark(1, 2.0, "A")
    second = song.add_mark(2, 3.25, "B")

    window._copy_marks([first.id, second.id])
    window._paste_marks(10.0)

    pasted = [m for m in song.marks if m.id not in {first.id, second.id}]
    assert len(pasted) == 2
    assert [m.time_seconds for m in pasted] == pytest.approx([10.0, 11.25])
    assert [m.lane_index for m in pasted] == [1, 2]
    assert [m.display_name for m in pasted] == ["A", "B"]

    window._undo_action()
    assert {m.id for m in song.marks} == {first.id, second.id}


def test_ctrl_c_ctrl_v_from_timeline_uses_main_window_shortcuts(app: QApplication) -> None:
    window = MainWindow(Project.create("Keyboard Copy"))
    song = window.current_song
    mark = song.add_mark(1, 2.0, "Keyboard")
    window.timeline.set_song(song)
    window.timeline.set_selected_mark_ids([mark.id])
    window.show()
    window.timeline.setFocus()
    app.processEvents()

    QTest.keyClick(window.timeline, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert len(window._mark_clipboard) == 1
    window.playback.seek(10.0)
    QTest.keyClick(window.timeline, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    app.processEvents()

    pasted = [item for item in song.marks if item.id != mark.id]
    assert len(pasted) == 1
    assert pasted[0].time_seconds == pytest.approx(10.0)

    QTest.keyClick(window.timeline, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert [item.id for item in song.marks] == [mark.id]
