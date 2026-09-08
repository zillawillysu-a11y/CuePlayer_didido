"""Cue monitor follows timeline scrub preview before mouse release."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Mark, MarkLane, Project
from cueplayer.ui.main_window import MainWindow


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_scrub_preview_updates_monitor_position(app: QApplication) -> None:
    window = MainWindow(Project.create("Scrub"))
    song = window.current_song
    song.mark_lanes = [MarkLane(name="Main", index=0, color="#ff5a5f")]
    song.marks = [
        Mark(id="m1", lane_index=0, time_seconds=0.0, display_name="A"),
        Mark(id="m2", lane_index=0, time_seconds=10.0, display_name="B"),
    ]
    window.monitor.set_song(song)
    window.monitor.set_position(0.0, 60.0)

    window._on_scrub_preview(12.5)

    assert abs(window.monitor._position - 12.5) < 1e-6
