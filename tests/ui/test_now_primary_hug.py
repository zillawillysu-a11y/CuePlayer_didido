"""PRIMARY NOW card hugs one-line text but grows when Primary is pulled taller."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song
from cueplayer.ui.cue_monitor_panel import (
    CueMonitorPanel,
    _NOW_CARD_MIN_H,
    _NOW_CARD_MIN_H_SINGLE,
)


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_single_line_primary_min_hugs_text(app: QApplication) -> None:
    panel = CueMonitorPanel()
    song = Song.create("Hug")
    song.add_mark(1, 1.0, display_name="NOTE")
    panel.set_song(song)
    panel._now_primary_single_line = True
    panel._now_primary_show_cue_id = True
    panel.set_position(1.0)
    panel.resize(320, 700)
    panel.show()
    app.processEvents()
    panel._sync_primary_card_alignment()
    panel._fit_now_cards()
    app.processEvents()

    assert panel._primary_should_hug() is True
    assert panel.primary_cue.minimumHeight() >= _NOW_CARD_MIN_H_SINGLE
    assert panel.primary_cue.minimumHeight() <= 48
    # Max stays open so dragging Primary taller can grow the card.
    assert panel.primary_cue.maximumHeight() >= 1000
    assert "\n" not in panel.primary_cue.text()


def test_primary_card_grows_when_column_taller(app: QApplication) -> None:
    panel = CueMonitorPanel()
    song = Song.create("Grow")
    song.add_mark(1, 1.0, display_name="NOTE")
    panel.set_song(song)
    panel._now_primary_single_line = True
    panel._now_primary_show_cue_id = True
    panel.set_position(1.0)
    panel.resize(320, 900)
    panel.show()
    app.processEvents()
    panel._sync_primary_card_alignment()
    panel._fit_now_cards()
    app.processEvents()

    compact_min = panel.primary_cue.minimumHeight()
    assert compact_min <= 48

    # Simulate user pulling NOW / Primary taller: column gains spare height.
    panel._primary_now_column.setMinimumHeight(220)
    panel._primary_now_column.resize(280, 220)
    panel.primary_cue.setMinimumHeight(compact_min)
    panel.primary_cue.setMaximumHeight(16777215)
    panel._sync_primary_card_alignment()
    app.processEvents()
    panel._primary_now_column.layout().activate()
    app.processEvents()

    assert panel.primary_cue.height() >= 120
    assert panel.primary_cue.height() > compact_min + 40


def test_empty_primary_also_hugs_min(app: QApplication) -> None:
    panel = CueMonitorPanel()
    panel.set_song(Song.create("Empty"))
    panel.set_position(0.0)
    panel.resize(320, 700)
    panel.show()
    app.processEvents()
    panel._sync_current(force_now=True)
    panel._fit_now_cards()
    app.processEvents()

    assert panel.primary_cue.text() == "—"
    assert panel._primary_should_hug() is True
    assert panel.primary_cue.minimumHeight() < _NOW_CARD_MIN_H + 8
    assert panel.primary_cue.maximumHeight() >= 1000
