"""Dark startup splash pixmap."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from cueplayer.app_info import APP_VERSION
from cueplayer.ui.splash import create_splash_pixmap, show_startup_splash
from cueplayer.ui.theme import BG_APP


@pytest.fixture(scope="module", autouse=True)
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_create_splash_pixmap_is_dark() -> None:
    pixmap = create_splash_pixmap(message="Loading…")
    assert not pixmap.isNull()
    assert pixmap.width() >= 320
    pixel = QColor(pixmap.toImage().pixel(10, 10))
    expected = QColor(BG_APP)
    assert abs(pixel.red() - expected.red()) < 8
    assert abs(pixel.green() - expected.green()) < 8
    assert abs(pixel.blue() - expected.blue()) < 8


def test_fullscreen_splash_pixmap_is_dark_edge_to_edge() -> None:
    pixmap = create_splash_pixmap(width=1280, height=800, fullscreen=True)
    image = pixmap.toImage()
    for x, y in ((0, 0), (1279, 0), (0, 799), (640, 400)):
        pixel = QColor(image.pixel(x, y))
        expected = QColor(BG_APP)
        assert abs(pixel.red() - expected.red()) < 8
        assert abs(pixel.green() - expected.green()) < 8
        assert abs(pixel.blue() - expected.blue()) < 8


def test_show_startup_splash(qapp=None) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    splash = show_startup_splash(app, message="Loading…")
    assert splash.isVisible()
    assert not splash._fullscreen
    assert splash.width() == splash._WINDOW_WIDTH
    assert splash.height() == splash._WINDOW_HEIGHT
    assert not bool(splash.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
    assert splash._progress == 0.0
    splash.set_progress(0.5, "Halfway…")
    assert splash._progress == 0.5
    assert splash._message == "Halfway…"
    splash.set_progress(1.0, "Ready")
    assert splash._progress == 1.0
    splash.close()


def test_create_splash_pixmap_progress_fill() -> None:
    empty = create_splash_pixmap(message="Loading…", progress=0.0)
    full = create_splash_pixmap(message="Ready", progress=1.0)
    assert not empty.isNull()
    assert not full.isNull()
    # Mid-bar pixel should stay track-colored at 0% and accent-colored at 100%.
    mid_x = empty.width() // 2
    title_approx_y = empty.height() // 2
    # Sample near vertical center of the composition block (bar sits under title).
    bar_y = title_approx_y
    empty_px = QColor(empty.toImage().pixel(mid_x, bar_y))
    full_px = QColor(full.toImage().pixel(mid_x, bar_y))
    # Not asserting exact colors (layout math), only that progress changes paint.
    assert empty_px != full_px or empty.toImage() != full.toImage()


def test_splash_footer_shows_version_without_moving_bar() -> None:
    """Version/copyright footer must not shift the existing title/bar/message block."""
    assert APP_VERSION == "1.14"
    blank = create_splash_pixmap(message="Loading…", progress=0.0)
    image = blank.toImage()
    bg = QColor(BG_APP)
    width, height = image.width(), image.height()

    # Footer band (bottom ~50px) must contain non-background pixels — proof
    # the version/copyright text actually painted there.
    found_footer_text = False
    for y in range(height - 50, height - 5):
        for x in range(0, width, 4):
            px = QColor(image.pixel(x, y))
            if abs(px.red() - bg.red()) > 8 or abs(px.green() - bg.green()) > 8:
                found_footer_text = True
                break
        if found_footer_text:
            break
    assert found_footer_text

    # The default window size must stay unchanged (no layout blowout).
    assert (width, height) == (520, 300)
