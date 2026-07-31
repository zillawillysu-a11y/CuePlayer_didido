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
    # Setlist must not collapse to zero when the splitter is dragged narrow.
    assert not window._main_splitter.childrenCollapsible()
    assert not window._main_splitter.isCollapsible(0)
    assert not window._main_splitter.isCollapsible(1)
    left = window._main_splitter.widget(0)
    assert left is not None
    assert left.minimumWidth() >= 160
    right = window._main_splitter.widget(1)
    assert right is not None
    # Explicit content floor (not transport sizeHint) so Setlist can expand.
    assert right.minimumWidth() == 280
    assert right.minimumWidth() < 400


def test_setlist_splitter_can_expand_on_narrow_window(app: QApplication) -> None:
    """Narrow windows must still allow dragging Setlist wider (no snap-back)."""
    window = MainWindow(Project.create("Narrow"))
    window.show()
    window.resize(800, 500)
    app.processEvents()
    window._sync_transport_layout()
    app.processEvents()

    main = window._main_splitter
    total = sum(main.sizes())
    assert total >= 700
    # Start near the Setlist floor, then grow it — previously stuck at 160
    # because transport minimumSizeHint was ~1200px.
    main.setSizes([160, total - 160])
    app.processEvents()
    assert main.sizes()[0] <= 180

    target_left = min(420, total - 300)
    main.setSizes([target_left, total - target_left])
    app.processEvents()
    window._sync_transport_layout()
    app.processEvents()
    got_left = main.sizes()[0]
    assert got_left >= target_left - 20, (
        f"Setlist should expand toward {target_left}px on an 800px window; got {got_left}"
    )
    assert main.sizes()[1] >= 280
    # Monitor should yield width so the timeline column is not crushed.
    timeline_w, mon_w = window._timeline_split.sizes()
    assert timeline_w >= 180
    assert mon_w >= window.monitor.minimumWidth()
