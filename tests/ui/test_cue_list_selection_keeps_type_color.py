"""Cue List selection must keep Mark Type lane colors (not force white)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QModelIndex, QRect, Qt
from PySide6.QtGui import QColor, QPainter, QImage
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionViewItem

from cueplayer.domain.models import Project
from cueplayer.ui.cue_monitor_panel import CueMonitorPanel, _PaddedItemDelegate
from cueplayer.ui.theme import apply_dark_palette, build_stylesheet


@pytest.fixture
def app() -> QApplication:
    application = QApplication.instance() or QApplication([])
    application.setStyle("Fusion")
    apply_dark_palette(application)
    application.setStyleSheet(build_stylesheet())
    return application


def test_selected_type_cell_keeps_lane_foreground(app: QApplication) -> None:
    project = Project.create("Cue Color")
    song = project.songs[0]
    song.duration_seconds = 60.0
    mark = song.add_mark(1, 17.139)
    lane = song.lane_by_index(1)
    assert lane is not None
    lane.color = "#e67e22"
    lane.name = "Mark 2"

    panel = CueMonitorPanel()
    panel.resize(400, 600)
    panel.set_song(song)
    panel.show()
    app.processEvents()

    type_col = panel._col_for_field("type")
    row = 0
    for r in range(panel.cue_table.rowCount()):
        if panel._mark_id_at_row(r) == mark.id:
            row = r
            break
    item = panel.cue_table.item(row, type_col)
    assert item is not None
    lane_fg = item.foreground().color()
    assert lane_fg.name() == QColor("#e67e22").name()

    panel.set_selected_mark_ids([mark.id])
    app.processEvents()

    # Foreground role must survive selection (display uses the delegate).
    assert item.foreground().color().name() == QColor("#e67e22").name()

    index = panel.cue_table.model().index(row, type_col)
    option = QStyleOptionViewItem()
    delegate = panel.cue_table.itemDelegate()
    assert isinstance(delegate, _PaddedItemDelegate)
    delegate.initStyleOption(option, index)
    option.rect = QRect(0, 0, 160, 34)
    option.state |= QStyle.StateFlag.State_Selected
    option.widget = panel.cue_table

    image = QImage(160, 34, QImage.Format.Format_ARGB32)
    image.fill(QColor("#111111"))
    painter = QPainter(image)
    delegate.paint(painter, option, index)
    painter.end()

    # Scan for orange chroma from the Mark Type label (not pure white / grey fill).
    found_lane_color = False
    for y in range(4, 30):
        for x in range(8, 150):
            sample = image.pixelColor(x, y)
            if sample.red() > sample.blue() + 30 and sample.red() > 140:
                found_lane_color = True
                break
        if found_lane_color:
            break
    assert found_lane_color, "selected Type cell should still paint lane orange, not white"
