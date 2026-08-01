"""Ask Note prompt + Wave Note lane flags."""

from __future__ import annotations

import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QInputDialog

from cueplayer.domain.models import Project, Song
from cueplayer.persistence.mark_template import dicts_to_lanes, lanes_to_dicts
from cueplayer.persistence.project_store import project_from_dict, project_to_dict
from cueplayer.ui.main_window import MainWindow
from cueplayer.ui.mark_manager_dialog import (
    MarkManagerDialog,
    _COL_ASK_NOTE,
    _COL_WAVE_NOTE,
)
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_ask_and_wave_note_defaults_false() -> None:
    song = Song.create("Notes")
    assert all(lane.prompt_note_on_mark is False for lane in song.mark_lanes)
    assert all(lane.show_note_on_wave is False for lane in song.mark_lanes)


def test_ask_and_wave_note_project_roundtrip() -> None:
    project = Project.create("Notes")
    lane = project.songs[0].mark_lanes[0]
    lane.prompt_note_on_mark = True
    lane.show_note_on_wave = True
    restored = project_from_dict(project_to_dict(project))
    got = restored.songs[0].mark_lanes[0]
    assert got.prompt_note_on_mark is True
    assert got.show_note_on_wave is True


def test_ask_and_wave_note_template_roundtrip() -> None:
    song = Song.create("Tpl")
    song.mark_lanes[0].prompt_note_on_mark = True
    song.mark_lanes[0].show_note_on_wave = True
    lanes = dicts_to_lanes(lanes_to_dicts(song.mark_lanes))
    main = next(lane for lane in lanes if lane.index == 1)
    assert main.prompt_note_on_mark is True
    assert main.show_note_on_wave is True


def test_mark_manager_has_ask_and_wave_columns(app: QApplication) -> None:
    dialog = MarkManagerDialog(Song.create("UI"))
    headers = [
        dialog.table.horizontalHeaderItem(c).text()
        for c in range(dialog.table.columnCount())
    ]
    assert headers[_COL_ASK_NOTE] == "Ask Note"
    assert headers[_COL_WAVE_NOTE] == "Wave Note"


def test_add_mark_prompts_for_note(app: QApplication) -> None:
    window = MainWindow(Project.create("Ask"))
    lane = window.current_song.lane_by_index(1)
    assert lane is not None
    lane.prompt_note_on_mark = True
    with patch.object(QInputDialog, "getText", return_value=("VERSE", True)):
        window._add_mark(1)
    marks = [m for m in window.current_song.marks if m.lane_index == 1]
    assert marks
    assert marks[-1].display_name == "VERSE"


def test_wave_note_flag_does_not_crash_paint(app: QApplication) -> None:
    widget = TimelineWidget()
    song = Song.create("Wave")
    song.mark_lanes[0].show_note_on_wave = True
    mark = song.add_mark(1, 1.0, display_name="INTRO")
    assert mark.display_name == "INTRO"
    widget.set_song(song)
    widget.resize(800, 400)
    widget.show()
    app.processEvents()
    widget.repaint()
    app.processEvents()
