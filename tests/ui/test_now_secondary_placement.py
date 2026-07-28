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
    assert "body" in state

    panel2 = CueMonitorPanel()
    panel2.set_song(Song.create("Test"))
    panel2.restore_now_splitter_state(state)
    assert panel2.now_secondary_placement() == "below"
    assert panel2._now_splitter.orientation() == Qt.Orientation.Vertical


def test_body_splitter_sits_above_cue_list(app: QApplication) -> None:
    panel = CueMonitorPanel()
    panel.set_song(Song.create("Test"))
    panel.resize(360, 800)
    panel.show()
    app.processEvents()
    panel.ensure_now_splitter_ready()
    app.processEvents()

    assert panel._body_splitter.count() == 2
    assert panel._body_splitter.widget(0) is panel._now_section
    assert panel._body_splitter.widget(1) is panel._cue_list_block
    handle = panel._body_splitter.handle(1)
    assert handle.isEnabled()
    assert panel._now_splitter.handle(1).isEnabled()


def test_body_splitter_does_not_change_now_split(app: QApplication) -> None:
    panel = CueMonitorPanel()
    panel.set_song(Song.create("Test"))
    panel.resize(360, 800)
    panel.show()
    app.processEvents()
    panel.set_now_secondary_placement("below")
    panel._now_splitter.setSizes([160, 90])
    panel._pin_now_inner_height()
    app.processEvents()
    before = list(panel._now_splitter.sizes())

    panel._body_splitter.setSizes([400, 300])
    panel._on_body_splitter_moved()
    app.processEvents()

    after = list(panel._now_splitter.sizes())
    assert after == before


def test_secondary_text_is_vertically_centered(app: QApplication) -> None:
    panel = CueMonitorPanel()
    align = panel.secondary_cue.alignment()
    assert align & Qt.AlignmentFlag.AlignVCenter
    assert panel.secondary_cue.testAttribute(Qt.WidgetAttribute.WA_StyledBackground)

