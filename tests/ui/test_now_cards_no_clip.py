"""NOW Primary/Secondary cards must not clip when the monitor is narrow."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project
from cueplayer.ui.cue_monitor_panel import CueMonitorPanel


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_now_cards_fit_inside_narrow_panel(app: QApplication) -> None:
    panel = CueMonitorPanel()
    song = Project.create("N").new_song("Song")
    panel.set_song(song)
    panel.set_now_secondary_placement("below")
    panel.resize(150, 700)
    panel.show()
    app.processEvents()
    panel._fit_now_chrome()
    app.processEvents()

    assert panel.primary_cue.width() <= panel.width()
    assert panel.secondary_cue.width() <= panel.width()
    # Cards must sit fully inside the panel (no right-edge clip).
    for card in (panel.primary_cue, panel.secondary_cue):
        left = card.mapTo(panel, card.rect().topLeft()).x()
        right = card.mapTo(panel, card.rect().topRight()).x()
        assert left >= 0
        assert right <= panel.width()
    assert panel._now_primary_font_px <= 14


def test_now_side_by_side_sizes_do_not_exceed_width(app: QApplication) -> None:
    panel = CueMonitorPanel()
    song = Project.create("N").new_song("Song")
    panel.set_song(song)
    panel.set_now_secondary_placement("right")
    panel.resize(160, 700)
    panel.show()
    app.processEvents()
    # Old bug: setSizes used a synthetic total of 320px inside a 160px panel.
    panel._sync_now_splitter_visibility()
    panel._clamp_now_splitter_to_bounds()
    app.processEvents()
    sizes = panel._now_splitter.sizes()
    assert sum(sizes) <= max(panel._now_splitter.width(), 1) + 2
    assert panel.primary_cue.mapTo(panel, panel.primary_cue.rect().topRight()).x() <= panel.width()
