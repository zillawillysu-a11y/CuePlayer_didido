"""Cue List right-click menu includes Renumber."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMenu

from cueplayer.domain.models import Song
from cueplayer.ui.cue_monitor_panel import CueMonitorPanel


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_cue_list_context_menu_includes_renumber(app: QApplication) -> None:
    song = Song.create("Test")
    panel = CueMonitorPanel()
    panel.set_song(song)
    menu = QMenu()
    panel._append_renumber_cue_id_actions(menu, panel.cue_table.viewport().rect().center())
    labels = [action.text() for action in menu.actions()]
    assert "Renumber" in labels
