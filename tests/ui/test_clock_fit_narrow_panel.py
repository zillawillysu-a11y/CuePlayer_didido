"""Clock digits scale down when the monitor panel is narrow."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QApplication

from cueplayer.ui.cue_monitor_panel import (
    CueMonitorPanel,
    _CLOCK_FONT_MAX_PX,
    _CLOCK_FONT_MIN_PX,
)


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_clock_font_shrinks_when_panel_is_narrow(app: QApplication) -> None:
    panel = CueMonitorPanel()
    panel.configure_output_timecode_clock(visible=False, color="#3dd68c")
    panel.show()
    panel.resize(400, 700)
    app.processEvents()
    panel._fit_clock_fonts()  # noqa: SLF001
    wide_px = panel._clock_font_px  # noqa: SLF001
    assert wide_px == _CLOCK_FONT_MAX_PX

    panel.resize(180, 700)
    app.processEvents()
    panel._fit_clock_fonts()  # noqa: SLF001
    narrow_px = panel._clock_font_px  # noqa: SLF001
    assert narrow_px < wide_px
    assert narrow_px >= _CLOCK_FONT_MIN_PX

    budget = panel._clock_text_budget()  # noqa: SLF001
    metrics = QFontMetrics(panel._mono_clock_font(narrow_px))  # noqa: SLF001
    assert metrics.horizontalAdvance(panel.clock_label.text()) <= budget


def test_clock_font_grows_back_when_panel_widens(app: QApplication) -> None:
    panel = CueMonitorPanel()
    panel.configure_output_timecode_clock(visible=False, color="#3dd68c")
    panel.show()
    panel.resize(160, 700)
    app.processEvents()
    panel._fit_clock_fonts()  # noqa: SLF001
    assert panel._clock_font_px < _CLOCK_FONT_MAX_PX  # noqa: SLF001

    panel.resize(420, 700)
    app.processEvents()
    panel._fit_clock_fonts()  # noqa: SLF001
    assert panel._clock_font_px == _CLOCK_FONT_MAX_PX  # noqa: SLF001
