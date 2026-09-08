"""Per-lane Cue List inclusion."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project, Song
from cueplayer.persistence.project_store import project_from_dict, project_to_dict
from cueplayer.ui.cue_monitor_panel import CueMonitorPanel


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_cue_list_skips_lanes_with_cue_list_disabled(app: QApplication) -> None:
    song = Song.create("Test")
    button_lane = next(lane for lane in song.mark_lanes if lane.lane_type == "top_button")
    button_lane.cue_list_enabled = False
    song.add_mark(1, 1.0)
    song.add_mark(button_lane.index, 2.0)

    panel = CueMonitorPanel()
    panel.set_song(song)
    assert panel.cue_table.rowCount() == 1


def test_cue_list_enabled_persists() -> None:
    project = Project.create("Persist")
    project.songs[0].mark_lanes[1].cue_list_enabled = True
    data = project_to_dict(project)
    loaded = project_from_dict(data)
    assert loaded.songs[0].mark_lanes[1].cue_list_enabled is True
