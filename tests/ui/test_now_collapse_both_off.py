"""NOW section collapses when Primary and Secondary displays are both off."""

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


def test_now_section_collapses_when_both_displays_off(app: QApplication) -> None:
    panel = CueMonitorPanel()
    song = Project.create("N").new_song("Song")
    panel.set_song(song)
    panel.resize(320, 720)
    app.processEvents()
    panel._body_splitter.setSizes([220, 400])
    app.processEvents()

    assert not panel._now_section.isHidden()
    assert panel._body_splitter.sizes()[0] > 40

    song.now_primary_visible = False
    song.now_secondary_visible = False
    panel._now_primary_visible = False
    panel._now_secondary_visible = False
    panel._apply_now_panel_visibility()
    app.processEvents()

    assert panel._now_section.isHidden()
    sizes = panel._body_splitter.sizes()
    assert sizes[0] == 0
    assert sizes[1] > 0
    assert sizes[1] == sum(sizes)
    assert not panel._body_splitter.handle(1).isEnabled()


def test_now_section_restores_when_a_display_returns(app: QApplication) -> None:
    panel = CueMonitorPanel()
    song = Project.create("N").new_song("Song")
    panel.set_song(song)
    panel.resize(320, 720)
    app.processEvents()
    panel._body_splitter.setSizes([220, 400])
    app.processEvents()

    panel._now_primary_visible = False
    panel._now_secondary_visible = False
    panel._apply_now_panel_visibility()
    app.processEvents()

    panel._now_primary_visible = True
    panel._apply_now_panel_visibility()
    app.processEvents()

    assert not panel._now_section.isHidden()
    assert not panel._primary_now_column.isHidden()
    assert panel._secondary_now_column.isHidden()
    assert panel._body_splitter.sizes()[0] > 40
    assert panel._body_splitter.handle(1).isEnabled()
