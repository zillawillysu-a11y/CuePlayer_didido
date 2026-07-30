"""Auto-scroll keeps edge follow; play scroll must not thrash the backdrop."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_follow_playhead_parks_on_edge(app: QApplication) -> None:
    """Original continuous follow: playhead stays on the 75% edge while advancing."""
    widget = TimelineWidget()
    widget.set_song(Song.create("Follow"))
    widget.resize(900, 400)
    widget.set_zoom(100.0)
    widget._playing = True
    widget._auto_scroll = True
    widget._view_pinned = False

    view_w = widget._view_width()
    widget._scroll_x = 0.0
    right_edge_time = (view_w * 0.75 + 20.0) / widget._pixels_per_second
    widget._position = right_edge_time
    widget._follow_playhead()

    x = widget._x_for_time(widget._position)
    expected = float(widget._header_width) + view_w * 0.75
    assert abs(x - expected) < 2.0


def test_play_scroll_keeps_backdrop_cache(app: QApplication) -> None:
    """Auto-scroll during play must not drop the static backdrop every tick."""
    widget = TimelineWidget()
    widget.set_song(Song.create("Cache"))
    widget.resize(900, 400)
    widget.set_zoom(200.0)
    widget._playing = True
    widget._auto_scroll = True
    widget._view_pinned = False
    widget._rebuild_scrub_backdrop()
    assert widget._scrub_backdrop is not None
    cached = widget._scrub_backdrop

    # Simulate a follow scroll without going through set_position's old invalidate.
    prev = widget._scroll_x
    widget._scroll_x = prev + 40.0
    widget._clamp_scroll()
    # Geometry still matches — blit path may use an offset.
    assert widget._scrub_backdrop_geometry_ok()
    assert widget._scrub_backdrop is cached
    assert isinstance(widget._scrub_backdrop, QPixmap)
