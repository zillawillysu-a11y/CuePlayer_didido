"""Timeline zoom overlay stays pinned to the top-right on resize."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QScrollArea

from cueplayer.domain.models import Song
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_zoom_overlay_tracks_width_while_layout_busy(app: QApplication) -> None:
    """MainWindow syncs geometry with ``_layout_heights_busy`` — overlays must move."""
    widget = TimelineWidget()
    song = Song.create("Overlay")
    widget.set_song(song)
    widget.setMinimumHeight(400)

    scroll = QScrollArea()
    scroll.setWidgetResizable(False)
    scroll.setWidget(widget)
    scroll.resize(920, 520)
    scroll.show()
    widget.resize(900, 400)
    app.processEvents()

    right_before = widget.fit_button.x() + widget.fit_button.width()
    assert right_before == pytest.approx(900 - 8, abs=2)

    # Same path as MainWindow._sync_timeline_geometry during window resize.
    widget._layout_heights_busy = True
    try:
        widget.resize(500, 400)
        app.processEvents()
    finally:
        widget._layout_heights_busy = False

    right_after = widget.fit_button.x() + widget.fit_button.width()
    assert right_after == pytest.approx(500 - 8, abs=2)
    assert widget.auto_scroll_button.x() < widget.fit_button.x()
