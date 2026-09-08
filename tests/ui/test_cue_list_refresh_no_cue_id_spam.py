"""Cue List refresh must not spam Cue ID errors for Button lanes."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project
from cueplayer.ui.cue_monitor_panel import CueMonitorPanel


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_refresh_list_does_not_validate_button_lane_cue_ids(app: QApplication) -> None:
    song = Project.create("Button Lane").songs[0]
    lane = song.lane_by_index(2)
    assert lane is not None
    lane.cue_list_enabled = True
    lane.cue_id_enabled = False

    panel = CueMonitorPanel()
    panel.set_song(song)
    panel.show()
    app.processEvents()

    failures: list[str] = []
    panel.cue_id_edit_failed.connect(failures.append)

    for i in range(5):
        song.add_mark(lane.index, 1.0 + i * 0.1)
        panel.refresh_list()
        panel.set_position(1.0 + i * 0.1, 120.0)
        app.processEvents()

    assert failures == []
