"""Scrub backdrop must paint with the widget font (not QApplication default)."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QFont, QPainter
from PySide6.QtWidgets import QApplication

from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_scrub_backdrop_uses_widget_font(app: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: mid-scrub text looked smaller until mouse-up.

    ``_rebuild_scrub_backdrop`` paints into a QPixmap. QPainter(pixmap) starts
    with ``QApplication.font()``, while ``paintEvent`` uses the stylesheet
    widget font — those differ when the app sheet sets ``font-size: 13px``.
    """
    widget = TimelineWidget()
    widget.resize(640, 280)
    widget.show()
    app.processEvents()

    styled = QFont(widget.font())
    styled.setPixelSize(18)
    widget.setFont(styled)

    seen: list[QFont] = []
    original = TimelineWidget._paint_static_layers

    def _capture(self: TimelineWidget, painter: QPainter) -> None:
        seen.append(QFont(painter.font()))
        original(self, painter)

    monkeypatch.setattr(TimelineWidget, "_paint_static_layers", _capture)
    widget._rebuild_scrub_backdrop()

    assert seen, "expected _paint_static_layers to run during backdrop rebuild"
    assert seen[0].pixelSize() == 18
    assert seen[0].family() == styled.family()
