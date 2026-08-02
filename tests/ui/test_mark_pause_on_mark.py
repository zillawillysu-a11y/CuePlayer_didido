"""Mark Manager Pause column pauses playback when placing that type."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project, Song
from cueplayer.persistence.mark_template import dicts_to_lanes, lanes_to_dicts
from cueplayer.persistence.project_store import project_from_dict, project_to_dict
from cueplayer.ui.main_window import MainWindow
from cueplayer.ui.mark_manager_dialog import MarkManagerDialog, _COL_PAUSE


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_pause_on_mark_defaults_false() -> None:
    song = Song.create("Pause")
    assert all(lane.pause_on_mark is False for lane in song.mark_lanes)


def test_pause_on_mark_roundtrip_project() -> None:
    project = Project.create("Pause")
    project.songs[0].mark_lanes[0].pause_on_mark = True
    restored = project_from_dict(project_to_dict(project))
    assert restored.songs[0].mark_lanes[0].pause_on_mark is True
    # Legacy projects without the field stay off.
    data = project_to_dict(project)
    del data["songs"][0]["mark_lanes"][0]["pause_on_mark"]
    legacy = project_from_dict(data)
    assert legacy.songs[0].mark_lanes[0].pause_on_mark is False


def test_pause_on_mark_roundtrip_template() -> None:
    song = Song.create("Tpl")
    song.mark_lanes[1].pause_on_mark = True
    lanes = dicts_to_lanes(lanes_to_dicts(song.mark_lanes))
    assert lanes[0].pause_on_mark is False
    assert next(lane for lane in lanes if lane.index == 2).pause_on_mark is True


def test_mark_manager_has_pause_column(app: QApplication) -> None:
    dialog = MarkManagerDialog(Song.create("UI"))
    headers = [
        dialog.table.horizontalHeaderItem(c).text()
        for c in range(dialog.table.columnCount())
    ]
    assert "Pause" in headers
    assert headers.index("Pause") == _COL_PAUSE
    box = dialog._checkbox_at(0, _COL_PAUSE)
    assert box is not None
    assert box.isChecked() is False


def test_add_mark_pauses_when_lane_flag_set(app: QApplication) -> None:
    window = MainWindow(Project.create("PauseMark"))
    song = window.current_song
    lane = song.lane_by_index(1)
    assert lane is not None
    lane.pause_on_mark = True
    window.engine._playing = True  # noqa: SLF001 — simulate transport playing
    window._add_mark(1)
    assert window.engine.playing is False
    assert any(mark.lane_index == 1 for mark in song.marks)
