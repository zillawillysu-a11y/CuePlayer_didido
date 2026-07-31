"""Scrub/play waveform blit must stay aligned under Windows DPI scaling."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("dpr", [1.0, 1.25, 1.5, 2.0])
def test_high_dpr_blit_keeps_logical_column_aligned(app: QApplication, dpr: float) -> None:
    """Play/scrub cache source rects are device pixels — scale by DPR.

    At 125%/150% Windows scaling the old int drawPixmap(sx=logical) pulled the
    wrong strip, so the waveform drifted while marks/playhead (painted live)
    stayed put.
    """
    widget = TimelineWidget()
    widget.set_song(Song.create("DPR"))
    widget.resize(480, 240)
    widget.set_zoom(100.0)
    app.processEvents()

    widget.devicePixelRatioF = lambda: float(dpr)  # type: ignore[method-assign]
    widget._rebuild_scrub_backdrop()
    pm = widget._scrub_backdrop
    assert pm is not None
    assert abs(float(pm.devicePixelRatio()) - float(dpr)) < 1e-6

    # Scroll inside overscan so blit uses a non-zero delta (amplifies the bug).
    overscan = int(widget._scrub_backdrop_overscan)
    delta = max(40, overscan // 3)
    widget._scroll_x = float(widget._scrub_backdrop_scroll) + float(delta)
    widget._clamp_scroll()
    delta = int(round(widget._scroll_x - widget._scrub_backdrop_scroll))

    hw = int(widget._header_width)
    h = widget.height()
    src_x = hw + overscan + delta
    # Paint a green probe at the logical column that should land on dest x=hw.
    painter_pm = QPainter(pm)
    painter_pm.fillRect(src_x, 0, 3, h, QColor(0, 255, 0))
    painter_pm.end()

    img = QImage(widget.size(), QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 255))
    painter = QPainter(img)
    assert widget._blit_scrub_backdrop(painter) is True
    painter.end()

    y = max(1, h // 2)
    greens = [
        x
        for x in range(hw, min(widget.width(), hw + 12))
        if QColor(img.pixel(x, y)).green() > 200 and QColor(img.pixel(x, y)).red() < 40
    ]
    assert greens, (
        f"dpr={dpr}: green probe missing at header edge "
        f"(src_x={src_x}, delta={delta}, overscan={overscan})"
    )
    assert abs(greens[0] - hw) <= 2, (
        f"dpr={dpr}: waveform column landed at x={greens[0]}, expected ~{hw}"
    )


def test_dpr_blit_still_works_at_100_percent(app: QApplication) -> None:
    widget = TimelineWidget()
    widget.set_song(Song.create("DPR1"))
    widget.resize(640, 300)
    widget.devicePixelRatioF = lambda: 1.0  # type: ignore[method-assign]
    widget._rebuild_scrub_backdrop()
    widget._scroll_x = float(widget._scrub_backdrop_scroll) + 25.0
    img = QImage(widget.size(), QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0))
    painter = QPainter(img)
    assert widget._blit_scrub_backdrop(painter) is True
    painter.end()
