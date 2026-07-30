"""Auto-scroll follow should page the view, not jitter every tick."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_follow_playhead_pages_instead_of_edge_parking(app: QApplication) -> None:
    widget = TimelineWidget()
    widget.set_song(Song.create("Follow"))
    widget.resize(900, 400)
    widget.set_zoom(100.0)
    widget._playing = True
    widget._auto_scroll = True
    widget._view_pinned = False

    # Place playhead past the right 75% band.
    view_w = widget._view_width()
    widget._scroll_x = 0.0
    right_edge_time = (view_w * 0.75 + 20.0) / widget._pixels_per_second
    widget._position = right_edge_time
    before = widget._scroll_x
    widget._follow_playhead()
    after = widget._scroll_x

    assert after > before
    # Playhead should land near 25% (paged), not sit on the 75% edge.
    x = widget._x_for_time(widget._position)
    expected = float(widget._header_width) + view_w * 0.25
    assert abs(x - expected) < 2.0
