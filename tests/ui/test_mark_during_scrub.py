"""Mark shortcuts follow the visual playhead during mid-scrub drag."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project
from cueplayer.ui.main_window import MainWindow
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_playhead_seconds_tracks_mid_scrub(app: QApplication) -> None:
    widget = TimelineWidget()
    widget._position = 10.0
    widget._scrubbing = True
    # Simulate drag without releasing — engine would still be at press time.
    widget._position = 42.5
    assert widget.is_scrubbing()
    assert widget.playhead_seconds() == pytest.approx(42.5)


def test_add_mark_during_scrub_uses_timeline_playhead(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CRITICAL: Mark while dragging the timeline must land under the playhead."""
    project = Project.create("Scrub Mark")
    song = project.songs[0]
    song.duration_seconds = 120.0
    window = MainWindow(project)
    window.show()
    app.processEvents()

    # Engine still at the scrub press point; visual playhead already moved.
    monkeypatch.setattr(type(window.engine), "position", property(lambda self: 5.0))
    window.timeline._scrubbing = True
    window.timeline._position = 33.0

    before = len(song.marks)
    window._add_mark(1)  # default Main lane index
    assert len(song.marks) == before + 1
    assert song.marks[-1].time_seconds == pytest.approx(33.0)
    assert song.marks[-1].time_seconds != pytest.approx(5.0)
