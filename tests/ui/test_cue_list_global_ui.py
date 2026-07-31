"""Cue List columns: Interactive resize, reorder, smooth scroll; global NOW chrome."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QAbstractItemView, QApplication, QHeaderView

from cueplayer.domain.models import Project
from cueplayer.ui.cue_list_columns import LOGICAL_INDEX_BY_FIELD
from cueplayer.ui.cue_monitor_panel import CueMonitorPanel
from cueplayer.ui.main_window import MainWindow
from cueplayer.ui.transport_bar import BottomTransportBar


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_cue_list_columns_interactive_and_scroll_per_pixel(app: QApplication) -> None:
    panel = CueMonitorPanel()
    header = panel.cue_table.horizontalHeader()
    for field, logical in LOGICAL_INDEX_BY_FIELD.items():
        del field
        assert header.sectionResizeMode(logical) == QHeaderView.ResizeMode.Interactive
    assert panel.cue_table.horizontalScrollMode() == QAbstractItemView.ScrollMode.ScrollPerPixel
    assert panel.cue_table.verticalScrollMode() == QAbstractItemView.ScrollMode.ScrollPerPixel
    assert header.sectionsMovable()


def test_now_visibility_is_global_across_songs(app: QApplication) -> None:
    project = Project.create("G")
    a = project.new_song("A")
    b = project.new_song("B")
    panel = CueMonitorPanel()
    panel.set_song(a)
    panel._now_primary_visible = False
    panel._now_secondary_visible = False
    panel._apply_now_panel_visibility()

    panel.set_song(b)
    app.processEvents()
    # Switching songs must keep both displays off (global chrome).
    assert panel._now_section.isHidden()
    assert not panel._now_primary_visible
    assert not panel._now_secondary_visible


def test_monitor_ui_prefs_round_trip(app: QApplication) -> None:
    panel = CueMonitorPanel()
    panel.apply_monitor_ui_prefs(
        {
            "now_primary_visible": False,
            "now_secondary_visible": True,
            "cue_list_visible": False,
            "now_primary_show_cue_id": False,
            "cue_list_show_cue_id": False,
            "cue_list_column_order": ["note", "time", "type", "cue_id"],
        }
    )
    prefs = panel.monitor_ui_prefs()
    assert prefs["now_primary_visible"] is False
    assert prefs["now_secondary_visible"] is True
    assert prefs["cue_list_visible"] is False
    assert prefs["cue_list_column_order"][0] == "note"
    assert panel.cue_table.isHidden()
    assert not panel._list_collapsed.isHidden()


def test_volume_rail_stays_visible_when_narrow(app: QApplication) -> None:
    bar = BottomTransportBar()
    bar.resize(520, 80)
    bar.show()
    app.processEvents()
    bar.sync_geometry()
    app.processEvents()
    assert bar._right_rail.width() >= bar._volume_rail_min
    assert bar.volume_slider.isVisible()
    assert bar.volume_slider.width() >= 48


def test_main_window_syncs_monitor_prefs_to_all_songs(app: QApplication) -> None:
    project = Project.create("Sync")
    project.new_song("One")
    project.new_song("Two")
    window = MainWindow(project)
    window.monitor._now_primary_visible = False
    window.monitor._cue_list_visible = False
    window._on_monitor_ui_prefs_changed()
    for song in window.project.songs:
        assert song.now_primary_visible is False
        assert song.cue_list_visible is False
