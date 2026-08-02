"""TC output status / toggles must stay readable when the monitor is narrow."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QApplication, QSizePolicy, QVBoxLayout, QWidget

from cueplayer.ui.cue_monitor_panel import CueMonitorPanel


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _narrow_panel(app: QApplication, width: int) -> CueMonitorPanel:
    host = QWidget()
    host.setFixedWidth(width)
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    panel = CueMonitorPanel()
    panel.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
    lay.addWidget(panel)
    panel.configure_output_timecode_clock(visible=True, color="#3dd68c")
    panel.configure_output_quick_toggles(visible=True)
    panel.set_output_timecode(
        timecode="10:04:55:20",
        outputs=("LTC → MTC", "Notes"),
        sending=True,
    )
    host.show()
    app.processEvents()
    panel._fit_clock_fonts()  # noqa: SLF001
    app.processEvents()
    panel._test_host = host  # noqa: SLF001
    return panel


def test_cue_list_collapse_label_hidden_on_init(app: QApplication) -> None:
    panel = CueMonitorPanel()
    # Must not stay visible alongside the table — that forced the column wider
    # than the splitter and clipped the TC status / LTC chip.
    assert panel._cue_list_visible  # noqa: SLF001
    assert not panel._list_collapsed.isVisible()  # noqa: SLF001


def test_tc_status_fits_when_monitor_is_narrow(app: QApplication) -> None:
    panel = _narrow_panel(app, 140)
    frame = panel._clock_frame  # noqa: SLF001
    viewport = panel._monitor_scroll.viewport()  # noqa: SLF001
    assert frame.width() <= viewport.width() + 1

    status = panel.tc_output_status
    budget = panel._clock_text_budget()  # noqa: SLF001
    metrics = QFontMetrics(status.font())
    assert metrics.horizontalAdvance(status.text()) <= budget + 1
    assert status.mapTo(panel, status.rect().topRight()).x() <= panel.width() + 1


def test_output_toggles_stay_inside_narrow_monitor(app: QApplication) -> None:
    panel = _narrow_panel(app, 140)
    toggles = panel.output_quick_toggles
    assert toggles._wrapped  # noqa: SLF001
    for chip in toggles._all_chips():  # noqa: SLF001
        right = chip.mapTo(panel, chip.rect().topRight()).x()
        assert right <= panel.width() + 1
        assert chip.width() >= chip.fontMetrics().horizontalAdvance(chip.text()) - 1
