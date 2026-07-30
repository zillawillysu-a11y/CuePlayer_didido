"""Setlist LTC column keeps a fixed width so the badge is not squeezed."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QHeaderView

from cueplayer.ui.main_window import SetlistWidget
from cueplayer.ui import setlist_delegate


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_ltc_column_is_fixed_and_wide_enough(app: QApplication) -> None:
    widget = SetlistWidget()
    header = widget.horizontalHeader()
    assert header.sectionResizeMode(SetlistWidget.COL_LTC) == QHeaderView.ResizeMode.Fixed
    assert header.sectionResizeMode(SetlistWidget.COL_TITLE) == QHeaderView.ResizeMode.Interactive
    assert not header.stretchLastSection()
    assert widget.columnWidth(SetlistWidget.COL_LTC) >= SetlistWidget._LTC_COLUMN_WIDTH
    assert SetlistWidget._LTC_COLUMN_WIDTH == setlist_delegate._LTC_COLUMN_WIDTH


def test_ltc_width_survives_bpm_and_name_toggles(app: QApplication) -> None:
    widget = SetlistWidget()
    widget.resize(280, 200)
    widget.set_show_bpm(True)
    widget.set_name_mode("both")
    assert widget.columnWidth(SetlistWidget.COL_LTC) >= SetlistWidget._LTC_COLUMN_WIDTH
    assert widget.horizontalHeader().sectionResizeMode(SetlistWidget.COL_LTC) == (
        QHeaderView.ResizeMode.Fixed
    )
    assert widget.horizontalHeader().sectionResizeMode(SetlistWidget.COL_TITLE) == (
        QHeaderView.ResizeMode.Interactive
    )
    assert widget.horizontalHeader().sectionResizeMode(SetlistWidget.COL_EN) == (
        QHeaderView.ResizeMode.Interactive
    )
    widget.set_name_mode("zh")
    widget.set_show_bpm(False)
    assert widget.columnWidth(SetlistWidget.COL_LTC) >= SetlistWidget._LTC_COLUMN_WIDTH
    assert widget.horizontalHeader().sectionResizeMode(SetlistWidget.COL_TITLE) == (
        QHeaderView.ResizeMode.Interactive
    )
