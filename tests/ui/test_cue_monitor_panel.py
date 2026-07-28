"""Tests for cue monitor NOW body and labels."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Mark, Song
from cueplayer.ui.cue_monitor_panel import CueMonitorPanel, mark_now_body


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_mark_now_body_type_above_note() -> None:
    song = Song.create("Test")
    mark = Mark.create(lane_index=1, time_seconds=1.0, display_name="Verse")
    assert mark_now_body(song, mark) == "Main\nVerse"


def test_mark_now_body_type_only_when_note_empty() -> None:
    song = Song.create("Test")
    mark = Mark.create(lane_index=1, time_seconds=1.0, display_name="")
    assert mark_now_body(song, mark) == "Main"


def test_cue_list_hidden_shows_reveal_affordance(app: QApplication) -> None:
    song = Song.create("Test")
    song.cue_list_visible = False
    panel = CueMonitorPanel()
    panel.set_song(song)
    assert not panel._list_title.isVisible()
    assert not panel.cue_table.isVisible()
    assert panel._list_collapsed.isVisible()

    panel._show_cue_list()
    assert song.cue_list_visible
    assert panel._list_title.isVisible()
    assert panel.cue_table.isVisible()
    assert not panel._list_collapsed.isVisible()
