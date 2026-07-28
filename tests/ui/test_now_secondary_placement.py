"""NOW Secondary placement: right or below."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song
from cueplayer.ui.cue_monitor_panel import CueMonitorPanel


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_secondary_placement_switches_orientation(app: QApplication) -> None:
    panel = CueMonitorPanel()
    panel.set_song(Song.create("Test"))
    panel.show()
    app.processEvents()

    assert panel.now_secondary_placement() == "right"
    assert panel._now_splitter.orientation() == Qt.Orientation.Horizontal

    panel.set_now_secondary_placement("below")
    assert panel.now_secondary_placement() == "below"
    assert panel._now_splitter.orientation() == Qt.Orientation.Vertical

    panel.set_now_secondary_placement("right")
    assert panel._now_splitter.orientation() == Qt.Orientation.Horizontal


def test_now_layout_roundtrip(app: QApplication) -> None:
    panel = CueMonitorPanel()
    panel.set_song(Song.create("Test"))
    panel.set_now_secondary_placement("below")
    state = panel.save_now_splitter_state()
    assert state["placement"] == "below"

    panel2 = CueMonitorPanel()
    panel2.set_song(Song.create("Test"))
    panel2.restore_now_splitter_state(state)
    assert panel2.now_secondary_placement() == "below"
    assert panel2._now_splitter.orientation() == Qt.Orientation.Vertical
