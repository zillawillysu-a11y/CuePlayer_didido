"""Cue List keeps the playhead row visible (not buried at the bottom edge)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project
from cueplayer.ui.cue_monitor_panel import CueMonitorPanel, _ROW_HEIGHT


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _song_with_marks(count: int = 40):
    song = Project.create("S").new_song("Song")
    for i in range(count):
        song.add_mark(1, float(i))
    return song


def _prepare_short_cue_list(panel: CueMonitorPanel, app: QApplication) -> None:
    """Collapse NOW and use a short panel so the Cue List viewport is tight."""
    panel._now_primary_visible = False  # noqa: SLF001
    panel._now_secondary_visible = False  # noqa: SLF001
    panel._apply_now_panel_visibility()  # noqa: SLF001
    panel.resize(320, 420)
    app.processEvents()
    # Leave room for clock; Cue List still gets a usable but short viewport.
    assert panel.cue_table.viewport().height() > 60


def test_playhead_cue_scrolls_into_view_with_bottom_margin(app: QApplication) -> None:
    panel = CueMonitorPanel()
    song = _song_with_marks(40)
    panel.set_song(song)
    panel.show()
    app.processEvents()
    _prepare_short_cue_list(panel, app)

    # Mid-list target so PositionAtCenter has room above and below.
    target = song.marks[20]
    panel.set_position(float(target.time_seconds) + 0.01)
    app.processEvents()
    panel._scroll_cue_row_into_view(target.id)  # noqa: SLF001
    app.processEvents()

    row = next(
        r
        for r in range(panel.cue_table.rowCount())
        if panel._mark_id_at_row(r) == target.id  # noqa: SLF001
    )
    index = panel.cue_table.model().index(row, 0)
    rect = panel.cue_table.visualRect(index)
    vp_h = panel.cue_table.viewport().height()
    assert vp_h > 60
    assert rect.height() > 0
    assert rect.top() >= 0
    # Not flush against / past the bottom edge.
    assert rect.bottom() <= vp_h - max(8, _ROW_HEIGHT // 4)


def test_layout_change_rescrolls_obscured_playhead_cue(app: QApplication) -> None:
    panel = CueMonitorPanel()
    song = _song_with_marks(40)
    panel.set_song(song)
    panel.show()
    panel.resize(320, 700)
    app.processEvents()

    target = song.marks[25]
    panel.set_position(float(target.time_seconds) + 0.01)
    app.processEvents()
    assert panel._playhead_list_mark_id == target.id  # noqa: SLF001

    # Collapse NOW + shrink window — previous scroll position is no longer valid.
    _prepare_short_cue_list(panel, app)
    # Push the selection out of view, then ask the panel to recover.
    bar = panel.cue_table.verticalScrollBar()
    bar.setValue(0)
    app.processEvents()
    panel._ensure_playhead_cue_visible()  # noqa: SLF001
    app.processEvents()

    row = next(
        r
        for r in range(panel.cue_table.rowCount())
        if panel._mark_id_at_row(r) == target.id  # noqa: SLF001
    )
    rect = panel.cue_table.visualRect(panel.cue_table.model().index(row, 0))
    vp_h = panel.cue_table.viewport().height()
    assert vp_h > 0
    assert rect.top() >= 0
    assert rect.bottom() <= vp_h
