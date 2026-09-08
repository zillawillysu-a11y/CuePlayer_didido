"""Marquee selection box must paint above mark track colors."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPointF
from PySide6.QtGui import QPaintEvent
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _rig_order_spies(widget: TimelineWidget, order: list[str]) -> None:
    """Wrap the paint helpers that decide background-vs-overlay order.

    ``_blit_scrub_backdrop`` covers the cache-hit path (the retained native
    pixmap, which already has lanes baked into it, is blitted as-is —
    ``_paint_lanes`` is *not* re-invoked that frame). ``_paint_lanes`` covers
    the fresh-bake path (cache invalidated: ``_rebuild_scrub_backdrop`` calls
    ``_paint_static_layers`` -> ``_paint_lanes`` before the blit returns).
    Either way, exactly one of these fires before ``_paint_selection_box``.
    """
    real_blit = widget._blit_scrub_backdrop
    real_lanes = widget._paint_lanes
    real_box = widget._paint_selection_box

    def _blit(painter):  # noqa: ANN001
        result = real_blit(painter)
        order.append("blit" if result else "blit_miss")
        return result

    def _lanes(painter, *, start_y: int) -> None:  # noqa: ANN001
        order.append("lanes")
        real_lanes(painter, start_y=start_y)

    def _box(painter) -> None:  # noqa: ANN001
        order.append("box")
        real_box(painter)

    widget._blit_scrub_backdrop = _blit  # type: ignore[method-assign]
    widget._paint_lanes = _lanes  # type: ignore[method-assign]
    widget._paint_selection_box = _box  # type: ignore[method-assign]


def test_selection_box_paints_after_mark_track_colors_fresh_bake(
    app: QApplication,
) -> None:
    """Box-select with an invalidated cache: lanes are baked, then the box
    overlay paints on top — track colors must never end up above it."""
    project = Project.create("Marquee")
    song = project.new_song("Song")
    project.songs.append(song)
    widget = TimelineWidget()
    widget.set_song(song)
    widget.resize(800, 400)
    widget.show()
    app.processEvents()

    widget._show_mark_track_colors = True
    widget._invalidate_scrub_backdrop(reason="test_force_rebake")
    widget._box_selecting = True
    widget._box_origin = QPointF(200, 100)
    widget._box_current = QPointF(400, 280)
    widget._playing = False
    widget._scrubbing = False

    order: list[str] = []
    _rig_order_spies(widget, order)

    widget.paintEvent(QPaintEvent(widget.rect()))

    assert "lanes" in order, "cache was invalidated — a fresh bake must run"
    assert "box" in order
    assert order.index("lanes") < order.index("box")


def test_selection_box_paints_after_mark_track_colors_cached_backdrop(
    app: QApplication,
) -> None:
    """Box-select with a warm cache: the retained backdrop (lanes already
    baked into it) is blitted, then the box overlay paints on top. The
    product invariant is overlay-after-background, not "lanes re-painted
    every frame" — re-baking every box-select tick would defeat the whole
    point of the static backdrop cache."""
    project = Project.create("Marquee")
    song = project.new_song("Song")
    project.songs.append(song)
    widget = TimelineWidget()
    widget.set_song(song)
    widget.resize(800, 400)
    widget._show_mark_track_colors = True
    widget.show()
    app.processEvents()
    # Warm the cache with track colors already baked in before box-select.
    widget.paintEvent(QPaintEvent(widget.rect()))
    assert widget._scrub_backdrop is not None and not widget._scrub_backdrop.isNull()

    widget._box_selecting = True
    widget._box_origin = QPointF(200, 100)
    widget._box_current = QPointF(400, 280)
    widget._playing = False
    widget._scrubbing = False

    order: list[str] = []
    _rig_order_spies(widget, order)

    widget.paintEvent(QPaintEvent(widget.rect()))

    assert "blit" in order, "warm cache should be reused, not rebuilt"
    assert "box" in order
    assert order.index("blit") < order.index("box")
