"""Helpers for drawing mark head shapes on the timeline."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF

from cueplayer.domain.models import MarkerShape


def _shape_polygon(cx: float, cy: float, s: float, shape: str) -> QPolygonF | None:
    if shape == "diamond":
        return QPolygonF(
            [
                QPointF(cx, cy - s),
                QPointF(cx + s * 0.75, cy),
                QPointF(cx, cy + s),
                QPointF(cx - s * 0.75, cy),
            ]
        )
    if shape == "triangle_up":
        return QPolygonF(
            [QPointF(cx, cy - s), QPointF(cx + s, cy + s * 0.7), QPointF(cx - s, cy + s * 0.7)]
        )
    if shape == "triangle_down":
        return QPolygonF(
            [QPointF(cx, cy + s), QPointF(cx + s, cy - s * 0.7), QPointF(cx - s, cy - s * 0.7)]
        )
    if shape == "arrow_up":
        return QPolygonF(
            [
                QPointF(cx, cy - s),
                QPointF(cx + s * 0.85, cy),
                QPointF(cx + s * 0.3, cy),
                QPointF(cx + s * 0.3, cy + s),
                QPointF(cx - s * 0.3, cy + s),
                QPointF(cx - s * 0.3, cy),
                QPointF(cx - s * 0.85, cy),
            ]
        )
    if shape == "arrow_down":
        return QPolygonF(
            [
                QPointF(cx, cy + s),
                QPointF(cx + s * 0.85, cy),
                QPointF(cx + s * 0.3, cy),
                QPointF(cx + s * 0.3, cy - s),
                QPointF(cx - s * 0.3, cy - s),
                QPointF(cx - s * 0.3, cy),
                QPointF(cx - s * 0.85, cy),
            ]
        )
    if shape == "arrow_left":
        return QPolygonF(
            [
                QPointF(cx - s, cy),
                QPointF(cx, cy - s * 0.85),
                QPointF(cx, cy - s * 0.3),
                QPointF(cx + s, cy - s * 0.3),
                QPointF(cx + s, cy + s * 0.3),
                QPointF(cx, cy + s * 0.3),
                QPointF(cx, cy + s * 0.85),
            ]
        )
    if shape == "arrow_right":
        return QPolygonF(
            [
                QPointF(cx + s, cy),
                QPointF(cx, cy - s * 0.85),
                QPointF(cx, cy - s * 0.3),
                QPointF(cx - s, cy - s * 0.3),
                QPointF(cx - s, cy + s * 0.3),
                QPointF(cx, cy + s * 0.3),
                QPointF(cx, cy + s * 0.85),
            ]
        )
    return None


def draw_marker_shape(
    painter: QPainter,
    cx: float,
    cy: float,
    color: QColor,
    shape: MarkerShape | str,
    *,
    size: float = 7.0,
    outline: QColor | None = None,
    outline_width: float = 1.8,
) -> None:
    """Draw a filled marker centered at (cx, cy). Optional soft outline for hover."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    s = size
    shape = str(shape)

    def _draw_body(body_size: float, *, pen: QPen, brush) -> None:  # noqa: ANN001
        painter.setPen(pen)
        painter.setBrush(brush)
        if shape == "square":
            painter.drawRect(
                int(cx - body_size * 0.7),
                int(cy - body_size * 0.7),
                int(body_size * 1.4),
                int(body_size * 1.4),
            )
            return
        if shape == "cross":
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawLine(QPointF(cx - body_size, cy), QPointF(cx + body_size, cy))
            painter.drawLine(QPointF(cx, cy - body_size), QPointF(cx, cy + body_size))
            return
        poly = _shape_polygon(cx, cy, body_size, shape)
        if poly is not None:
            painter.drawPolygon(poly)
            return
        painter.drawEllipse(QPointF(cx, cy), body_size * 0.85, body_size * 0.85)

    if outline is not None:
        if shape == "cross":
            _draw_body(
                s,
                pen=QPen(outline, max(2.0, s * 0.35) + outline_width * 1.5),
                brush=Qt.BrushStyle.NoBrush,
            )
        else:
            _draw_body(
                s + outline_width * 0.55,
                pen=QPen(outline, outline_width),
                brush=Qt.BrushStyle.NoBrush,
            )

    if shape == "cross":
        _draw_body(s, pen=QPen(color, max(2.0, s * 0.35)), brush=Qt.BrushStyle.NoBrush)
    else:
        _draw_body(s, pen=QPen(color.darker(120), 1), brush=color)

    painter.restore()
