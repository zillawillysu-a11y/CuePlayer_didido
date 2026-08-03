"""Main window layout: Video Preview under Mark Timeline, not under Cue list."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QSplitter

from cueplayer.domain.models import Project
from cueplayer.ui.main_window import MainWindow


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_video_preview_is_under_timeline_not_cuelist(app: QApplication) -> None:
    window = MainWindow(project=Project.create("版面測試"))
    preview = window.video_preview_panel
    monitor = window.monitor
    timeline = window.timeline

    preview_split = preview.parentWidget()
    assert isinstance(preview_split, QSplitter)
    assert preview_split.objectName() == "timelinePreviewSplitter"
    assert window._timeline_scroll.widget() is timeline
    assert preview_split.indexOf(window._timeline_center) == 0
    assert preview_split.indexOf(preview) == 1

    # Cue list must not contain the preview.
    assert not monitor.isAncestorOf(preview)
    assert preview.parentWidget() is not monitor

    horiz = preview_split.parentWidget()
    assert isinstance(horiz, QSplitter)
    assert horiz.objectName() == "timelineSplit"
    assert horiz.indexOf(preview_split) == 0
    assert horiz.indexOf(monitor) == 1
