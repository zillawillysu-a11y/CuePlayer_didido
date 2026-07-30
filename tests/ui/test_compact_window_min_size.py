"""Main window can shrink for MA / Depence screen sharing."""

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


def test_timeline_minimum_height_is_viewport_floor_not_full_content(app: QApplication) -> None:
    widget = TimelineWidget()
    song = Project.create("Compact").new_song("Song")
    # Tall-ish layout: wave + video + marks.
    song.show_video_track = True
    widget.set_song(song)
    widget.resize(900, 200)
    app.processEvents()
    widget._apply_layout_heights()

    assert widget._content_height > widget._viewport_min_height()
    assert widget.minimumHeight() == widget._viewport_min_height()
    assert widget.minimumHeight() < widget._content_height
    assert widget.minimumSizeHint().height() == widget._viewport_min_height()


def test_main_window_minimum_size_is_compact(app: QApplication) -> None:
    window = MainWindow(Project.create("Compact"))
    window.show()
    app.processEvents()
    assert window.minimumWidth() <= 720
    assert window.minimumHeight() <= 420
    # Timeline content must not inflate the window floor.
    assert window.minimumHeight() < window.timeline._content_height
