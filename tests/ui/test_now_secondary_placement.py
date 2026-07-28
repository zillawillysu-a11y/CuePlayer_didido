"""NOW Secondary placement: right or below."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song
from cueplayer.ui.cue_monitor_panel import (
    CueMonitorPanel,
    _NOW_SECONDARY_COL_MIN,
    _NOW_TITLE_CHROME,
)


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


def test_body_drag_keeps_secondary_visible(app: QApplication) -> None:
    panel = CueMonitorPanel()
    panel.set_song(Song.create("Test"))
    panel.resize(360, 800)
    panel.show()
    app.processEvents()
    panel.set_now_secondary_placement("below")
    panel._now_splitter.setSizes([160, 90])
    panel._body_splitter.setSizes([320, 400])
    panel._apply_below_body_to_secondary()
    app.processEvents()

    # Drag Cue List up aggressively — Secondary must stay at/above floor.
    panel._body_splitter.setSizes([100, 620])
    panel._on_body_splitter_moved()
    app.processEvents()

    primary, secondary = panel._now_splitter.sizes()
    assert secondary >= _NOW_SECONDARY_COL_MIN
    assert primary >= 40
    # Secondary stays visible; Primary may shrink only if the panel is short.
    assert secondary > 0
    assert sum(panel._body_splitter.sizes()) <= 720 + 5


def test_width_drag_does_not_grow_panel_min_height(app: QApplication) -> None:
    panel = CueMonitorPanel()
    panel.set_song(Song.create("Test"))
    panel.resize(360, 700)
    panel.show()
    app.processEvents()
    before = panel.minimumSizeHint().height()
    panel._now_splitter.setSizes([80, 200])
    panel._on_now_splitter_moved()
    app.processEvents()
    panel._fit_now_cards()
    app.processEvents()
    after = panel.minimumSizeHint().height()
    # Width redistribution must not balloon the panel's minimum height.
    assert after <= before + 80
    assert panel._now_section.minimumHeight() <= _NOW_TITLE_CHROME + 120


def test_secondary_text_is_vertically_centered(app: QApplication) -> None:
    panel = CueMonitorPanel()
    align = panel.secondary_cue.alignment()
    assert align & Qt.AlignmentFlag.AlignVCenter
    assert panel.secondary_cue.testAttribute(Qt.WidgetAttribute.WA_StyledBackground)
