"""Right monitor scrolls between display (clock/NOW) and Cue List when short."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QScrollArea

from cueplayer.ui.cue_monitor_panel import CueMonitorPanel, _MONITOR_BODY_SCROLL_MIN


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
    assert panel._body_splitter.minimumHeight() >= _MONITOR_BODY_SCROLL_MIN  # noqa: SLF001


def test_short_monitor_can_scroll_to_cue_list(app: QApplication) -> None:
    panel = CueMonitorPanel()
    panel.configure_output_timecode_clock(visible=True, color="#3dd68c")
    panel.configure_output_quick_toggles(visible=True)
    panel.show()
    # Short enough that clock + NOW + Cue List cannot all fit.
    panel.resize(280, 220)
    app.processEvents()
    panel._fit_clock_fonts()  # noqa: SLF001
    app.processEvents()

    scroll = panel._monitor_scroll  # noqa: SLF001
    bar = scroll.verticalScrollBar()
    # Content should exceed the viewport so the user can scroll to Cue List.
    content_h = panel._monitor_scroll_content.sizeHint().height()  # noqa: SLF001
    assert content_h >= _MONITOR_BODY_SCROLL_MIN
    assert bar.maximum() > 0 or scroll.viewport().height() < content_h

    # Clock digits keep a floor height — not crushed to a clipped strip.
    assert panel.clock_label.minimumHeight() >= 16
    assert panel.clock_label.height() >= panel.clock_label.minimumHeight() - 1


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
