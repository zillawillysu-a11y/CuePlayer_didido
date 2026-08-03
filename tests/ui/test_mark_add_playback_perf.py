"""Adding marks during playback must not rebuild the scrub backdrop each time."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project
from cueplayer.ui.main_window import MainWindow


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_add_mark_while_playing_skips_backdrop_invalidate(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = Project.create("Mark Perf")
    song = project.songs[0]
    song.duration_seconds = 120.0
    window = MainWindow(project)
    window.show()
    app.processEvents()
    window.engine.play()
    app.processEvents()
    window.timeline._rebuild_scrub_backdrop()
    assert window.timeline._playing is True

    calls: list[int] = []
    original = window.timeline.invalidate_static_layers

    def _track() -> None:
        calls.append(1)
        original()

    monkeypatch.setattr(window.timeline, "invalidate_static_layers", _track)

    before = len(song.marks)
    for _ in range(5):
        window._add_mark(1)
    app.processEvents()

    assert len(song.marks) == before + 5
    assert calls == []
