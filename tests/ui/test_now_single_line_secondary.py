"""Single-line NOW format applies to Primary and Secondary."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song
from cueplayer.ui.cue_monitor_panel import CueMonitorPanel


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_single_line_applies_to_secondary_card(app: QApplication) -> None:
    panel = CueMonitorPanel()
    song = Song.create("Both")
    main = song.add_mark(1, 1.0, display_name="VERSE")
    main.main_cue_id = "45"
    top = song.add_mark(2, 1.0, display_name="FLASH")
    top.main_cue_id = "1"
    panel.set_song(song)
    panel._now_primary_single_line = True
    panel._now_primary_show_cue_id = True
    panel.set_now_secondary_placement("right")
    panel.set_position(1.0)
    panel.resize(640, 400)
    panel.show()
    app.processEvents()
    panel._sync_current(force_now=True)
    app.processEvents()

    assert "Main - Cue 45" in panel.primary_cue.text()
    assert "\n" not in panel.primary_cue.text()
    # Secondary uses the same single-line formatter (Cue ID when Show Cue ID is on).
    assert "FLASH" in panel.secondary_cue.text() or "Cue" in panel.secondary_cue.text()
    assert "\n" not in panel.secondary_cue.text()
    assert panel._now_splitter.orientation() == Qt.Orientation.Horizontal


def test_multi_line_secondary_still_omits_cue_id_without_single_line(
    app: QApplication,
) -> None:
    panel = CueMonitorPanel()
    song = Song.create("Multi")
    song.add_mark(2, 1.0, display_name="FLASH")
    panel.set_song(song)
    panel._now_primary_single_line = False
    panel._now_primary_show_cue_id = True
    panel.set_position(1.0)
    panel.show()
    app.processEvents()
    panel._sync_current(force_now=True)
    app.processEvents()

    assert "FLASH" in panel.secondary_cue.text()
    assert "Cue" not in panel.secondary_cue.text()
