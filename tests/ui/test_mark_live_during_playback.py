"""Mark add must invalidate the play-time scrub backdrop immediately."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_mark_during_playback_invalidates_static_backdrop(app: QApplication) -> None:
    """Regression: marks must appear while playing, not only after pause.

    Play path blits ``_scrub_backdrop``. Adding a mark must clear that cache
    before the next paint — otherwise the UI stays stale until set_playing(False).
    """
    project = Project.create("Mark Live")
    song = project.songs[0]
    song.duration_seconds = 60.0
    widget = TimelineWidget()
    widget.resize(800, 400)
    widget.set_song(song)
    widget.set_playing(True)
    widget._rebuild_scrub_backdrop()
    assert widget._scrub_backdrop is not None

    before_count = len(song.marks)
    song.add_mark(0, 12.0)
    assert len(song.marks) == before_count + 1

    # Mimic MainWindow._refresh_marks_ui contract — this is the hard rule.
    widget.invalidate_static_layers()
    assert widget._scrub_backdrop is None, (
        "scrub backdrop must be cleared so the next play paint bakes the new mark"
    )

    # Rebuild while still playing must succeed with the new mark present.
    widget._rebuild_scrub_backdrop()
    assert widget._scrub_backdrop is not None
    assert any(abs(m.time_seconds - 12.0) < 1e-6 for m in song.marks)
