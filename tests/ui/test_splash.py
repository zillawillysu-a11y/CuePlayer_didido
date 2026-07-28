"""Dark startup splash pixmap."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtGui import QColor

from cueplayer.ui.splash import create_splash_pixmap, show_startup_splash
from cueplayer.ui.theme import BG_APP


def test_create_splash_pixmap_is_dark() -> None:
    pixmap = create_splash_pixmap(message="Loading…")
    assert not pixmap.isNull()
    assert pixmap.width() >= 320
    pixel = QColor(pixmap.toImage().pixel(10, 10))
    expected = QColor(BG_APP)
    assert abs(pixel.red() - expected.red()) < 8
    assert abs(pixel.green() - expected.green()) < 8
    assert abs(pixel.blue() - expected.blue()) < 8


def test_show_startup_splash(qapp=None) -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    splash = show_startup_splash(app, message="Loading…")
    assert splash.isVisible()
    splash.close()
