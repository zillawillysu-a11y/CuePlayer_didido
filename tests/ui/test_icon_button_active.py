"""Overlay toggles must show a clear on/off chip in greyscale UI."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from cueplayer.ui.icon_button import IconButton


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _avg_luma(btn: IconButton) -> float:
    img = QImage(btn.size(), QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0))
    btn.render(img, QPoint())
    total = 0.0
    n = img.width() * img.height()
    for y in range(img.height()):
        for x in range(img.width()):
            c = QColor(img.pixel(x, y))
            total += 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
    return total / max(1, n)


def test_overlay_active_chip_is_brighter(app: QApplication) -> None:
    off = IconButton("letter_a", "off", size=QSize(30, 26), overlay=True)
    on = IconButton("letter_a", "on", size=QSize(30, 26), overlay=True)
    off.set_active(False)
    on.set_active(True)
    off.resize(30, 26)
    on.resize(30, 26)
    # Active = light chip; must read clearly brighter than idle dark chip.
    assert _avg_luma(on) > _avg_luma(off) + 40
