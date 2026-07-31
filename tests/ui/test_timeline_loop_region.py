"""A/B loop region is stored and painted as a visible span."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_set_loop_region_keeps_span_without_enabled(app: QApplication) -> None:
    widget = TimelineWidget()
    widget.set_song(Song.create("Loop"))
    widget.resize(800, 400)
    widget.set_loop_region(10.0, 20.0, enabled=False)
    assert widget._loop_a == pytest.approx(10.0)
    assert widget._loop_b == pytest.approx(20.0)
    # Range fill is shown whenever both points exist (not only when Loop is on).
    assert abs(widget._loop_b - widget._loop_a) >= 0.01
