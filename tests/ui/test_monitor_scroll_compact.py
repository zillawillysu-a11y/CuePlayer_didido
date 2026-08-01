"""Right monitor keeps Clock + Cue List usable when the panel is short."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QScrollArea

from cueplayer.domain.models import Project
from cueplayer.ui.cue_monitor_panel import CueMonitorPanel, _CUE_LIST_BODY_MIN


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_monitor_uses_vertical_scroll_area(app: QApplication) -> None:
    panel = CueMonitorPanel()
    assert isinstance(panel._monitor_scroll, QScrollArea)  # noqa: SLF001
    assert panel._monitor_scroll.widget() is panel._monitor_scroll_content  # noqa: SLF001
    assert (
        panel._monitor_scroll.verticalScrollBarPolicy()
        == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    )
    assert panel._body_splitter.minimumHeight() >= _CUE_LIST_BODY_MIN  # noqa: SLF001


def test_short_monitor_keeps_clock_and_scrollable_cue_list(app: QApplication) -> None:
    """Short column: Clock stays on screen; Cue List table can scroll internally."""
    panel = CueMonitorPanel()
    song = Project.create("S").new_song("Song")
    for i in range(40):
        song.add_mark(1, float(i))
    panel.set_song(song)
    panel.configure_output_timecode_clock(visible=True, color="#3dd68c")
    panel.configure_output_quick_toggles(visible=True)
    panel._now_primary_visible = False  # noqa: SLF001
    panel._now_secondary_visible = False  # noqa: SLF001
    panel._apply_now_panel_visibility()  # noqa: SLF001
    panel.show()
    panel.resize(280, 320)
    app.processEvents()
    panel._fit_clock_fonts()  # noqa: SLF001
    panel._fit_monitor_body_to_viewport()  # noqa: SLF001
    app.processEvents()

    assert panel.clock_label.minimumHeight() >= 16
    assert panel.clock_label.height() >= panel.clock_label.minimumHeight() - 1
    assert panel.cue_table.viewport().height() >= 20

    target = song.marks[25]
    panel.set_position(float(target.time_seconds) + 0.01)
    app.processEvents()
    panel._scroll_cue_row_into_view(target.id)  # noqa: SLF001
    app.processEvents()

    row = next(
        r
        for r in range(panel.cue_table.rowCount())
        if panel._mark_id_at_row(r) == target.id  # noqa: SLF001
    )
    rect = panel.cue_table.visualRect(panel.cue_table.model().index(row, 0))
    vp_h = panel.cue_table.viewport().height()
    assert rect.height() > 0
    assert rect.top() < vp_h
    assert rect.bottom() > 0


def test_showing_tc_clock_does_not_zero_clock_height(app: QApplication) -> None:
    panel = CueMonitorPanel()
    panel.show()
    panel.resize(300, 500)
    app.processEvents()
    panel.configure_output_timecode_clock(visible=False, color="#3dd68c")
    app.processEvents()
    before = panel.clock_label.height()

    panel.configure_output_timecode_clock(visible=True, color="#3dd68c")
    app.processEvents()
    panel._fit_clock_fonts()  # noqa: SLF001
    app.processEvents()

    assert panel._tc_output_block.isVisible()  # noqa: SLF001
    assert panel.clock_label.height() >= 16
    from PySide6.QtWidgets import QSizePolicy

    # Frame keeps Minimum policy so showing TC grows content (scroll) instead of
    # clipping the main clock against a fixed short box.
    assert (
        panel._clock_frame.sizePolicy().verticalPolicy()  # noqa: SLF001
        == QSizePolicy.Policy.Minimum
    )
    assert before >= 0  # smoke: layout ran
