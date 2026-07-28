"""Inline rename of Mark track names from the timeline header."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_hit_mark_lane_header(app: QApplication) -> None:
    song = Song.create("Test")
    widget = TimelineWidget()
    widget.resize(800, 500)
    widget.set_song(song)
    widget.show()
    app.processEvents()

    lanes = widget._lane_rects()
    assert lanes
    lane_index, y0, y1 = lanes[0]
    mid_y = (y0 + y1) / 2
    assert widget._hit_mark_lane_header(20, mid_y) == lane_index
    assert widget._hit_mark_lane_header(200, mid_y) is None


def test_rename_mark_lane_updates_name(app: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    song = Song.create("Test")
    widget = TimelineWidget()
    widget.set_song(song)
    renamed: list[tuple[int, str]] = []
    widget.lane_name_changed.connect(lambda i, n: renamed.append((i, n)))

    monkeypatch.setattr(
        "cueplayer.ui.timeline_widget.QInputDialog.getText",
        lambda *args, **kwargs: ("Verse Hits", True),
    )
    widget._rename_mark_lane_at(1)
    assert song.lane_by_index(1).name == "Verse Hits"
    assert renamed == [(1, "Verse Hits")]
