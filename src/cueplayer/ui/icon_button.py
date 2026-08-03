"""Small flat transport icon buttons (vector glyphs, not emoji)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QSize
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QPushButton

from cueplayer.ui.theme import BG_RAISED


class IconButton(QPushButton):
    """Compact toolbar button with a painted icon."""

    def __init__(
        self,
        kind: str,
        tooltip: str,
        parent=None,  # noqa: ANN001
        *,
        size: QSize | None = None,
        overlay: bool = False,
    ) -> None:
        super().__init__(parent)
        self._kind = kind
        self._active = False
        self._overlay = overlay
        self.setToolTip(tooltip)
        self.setFixedSize(size or QSize(34, 30))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def set_active(self, active: bool) -> None:
        self._active = active
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ANN001
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(1, 1, -1, -1)
        radius = 8 if self.width() >= 44 else 6

        if self._overlay:
            if self.isDown():
                bg = QColor(30, 38, 52, 230)
            elif self.underMouse() and self.isEnabled():
                bg = QColor(36, 46, 64, 220)
            else:
                bg = QColor(18, 22, 30, 195)
            border = QColor(90, 110, 140, 180) if self.isEnabled() else QColor(50, 58, 72, 140)
        elif self.isDown():
            bg = QColor("#2a3344")
            border = QColor("#3d4a5c")
        elif self._active:
            bg = QColor("#243044")
            border = QColor("#3d4a5c")
        elif self.underMouse() and self.isEnabled():
            bg = QColor("#222833")
            border = QColor("#3d4a5c")
        else:
            # Same idle base color as the plain QPushButton A/B loop buttons
            # (global QSS QPushButton background) so the transport strip
            # doesn't show a mismatched bluish chip behind Play/Pause/Stop/X.
            bg = QColor(BG_RAISED)
            border = QColor("#3d4a5c") if self.isEnabled() else QColor("#2a2f3a")

        painter.setPen(QPen(border, 1))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, radius, radius)

        color = QColor("#e8eef7") if self.isEnabled() else QColor("#5a6575")
        if self._active and self.isEnabled():
            color = QColor("#7eb6ff")

        # Glyphs authored for ~34×30; scale for larger transport buttons.
        scale = min(self.width() / 34.0, self.height() / 30.0)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.scale(scale, scale)
        cx, cy = 0.0, 0.0
        kind = self._kind
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)

        if kind == "play":
            path = QPainterPath()
            path.moveTo(cx - 5, cy - 8)
            path.lineTo(cx - 5, cy + 8)
            path.lineTo(cx + 9, cy)
            path.closeSubpath()
            painter.drawPath(path)
        elif kind == "pause":
            painter.drawRoundedRect(QRectF(cx - 8, cy - 8, 5.5, 16), 1.2, 1.2)
            painter.drawRoundedRect(QRectF(cx + 2.5, cy - 8, 5.5, 16), 1.2, 1.2)
        elif kind == "stop":
            painter.drawRoundedRect(QRectF(cx - 7, cy - 7, 14, 14), 1.5, 1.5)
        elif kind == "fit":
            # Fit-to-view — empty magnifying glass (no +/-).
            painter.setPen(QPen(color, 1.8))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(cx - 1, cy - 1), 6, 6)
            painter.drawLine(QPointF(cx + 3.5, cy + 3.5), QPointF(cx + 8, cy + 8))
        elif kind == "zoom_in":
            painter.setPen(QPen(color, 1.8))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(cx - 1, cy - 1), 6, 6)
            painter.drawLine(QPointF(cx - 1, cy - 5), QPointF(cx - 1, cy + 3))
            painter.drawLine(QPointF(cx - 5, cy - 1), QPointF(cx + 3, cy - 1))
            painter.drawLine(QPointF(cx + 3.5, cy + 3.5), QPointF(cx + 8, cy + 8))
        elif kind == "zoom_out":
            painter.setPen(QPen(color, 1.8))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(cx - 1, cy - 1), 6, 6)
            painter.drawLine(QPointF(cx - 5, cy - 1), QPointF(cx + 3, cy - 1))
            painter.drawLine(QPointF(cx + 3.5, cy + 3.5), QPointF(cx + 8, cy + 8))
        elif kind == "clear":
            painter.setPen(QPen(color, 2.0))
            painter.drawLine(QPointF(cx - 6, cy - 6), QPointF(cx + 6, cy + 6))
            painter.drawLine(QPointF(cx + 6, cy - 6), QPointF(cx - 6, cy + 6))
        elif kind == "letter_a":
            # Auto Scroll glyph — capital A.
            painter.setPen(QPen(color, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawLine(QPointF(cx, cy - 8), QPointF(cx - 6.5, cy + 7))
            painter.drawLine(QPointF(cx, cy - 8), QPointF(cx + 6.5, cy + 7))
            painter.drawLine(QPointF(cx - 3.2, cy + 1.5), QPointF(cx + 3.2, cy + 1.5))
        elif kind == "marquee":
            # Box-select mode — dashed rectangle.
            painter.setPen(QPen(color, 1.6, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(cx - 7, cy - 6, 14, 12))
        elif kind == "speaker_mute":
            # Track Mute — speaker cone with an X (always drawn; `_active`
            # still switches the fill/border to the highlighted "on" color).
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            path = QPainterPath()
            path.moveTo(cx - 8, cy - 3)
            path.lineTo(cx - 4, cy - 3)
            path.lineTo(cx + 1, cy - 7)
            path.lineTo(cx + 1, cy + 7)
            path.lineTo(cx - 4, cy + 3)
            path.lineTo(cx - 8, cy + 3)
            path.closeSubpath()
            painter.drawPath(path)
            painter.setPen(QPen(color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(cx + 3.5, cy - 4), QPointF(cx + 9, cy + 4))
            painter.drawLine(QPointF(cx + 9, cy - 4), QPointF(cx + 3.5, cy + 4))
        elif kind == "chevron":
            # Expand/collapse toggle — points down when collapsed, up when
            # `_active` (expanded), so the glyph itself hints at the action.
            painter.setPen(
                QPen(color, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            )
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if self._active:
                painter.drawLine(QPointF(cx - 6, cy + 3), QPointF(cx, cy - 4))
                painter.drawLine(QPointF(cx, cy - 4), QPointF(cx + 6, cy + 3))
            else:
                painter.drawLine(QPointF(cx - 6, cy - 3), QPointF(cx, cy + 4))
                painter.drawLine(QPointF(cx, cy + 4), QPointF(cx + 6, cy - 3))
        elif kind == "eye_off":
            # Hide track — simple eye outline with a slash.
            painter.setPen(QPen(color, 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath()
            path.moveTo(cx - 8, cy)
            path.cubicTo(cx - 4, cy - 6, cx + 4, cy - 6, cx + 8, cy)
            path.cubicTo(cx + 4, cy + 6, cx - 4, cy + 6, cx - 8, cy)
            painter.drawPath(path)
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(cx, cy), 2.2, 2.2)
            painter.setPen(QPen(color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(cx - 7, cy + 6), QPointF(cx + 7, cy - 6))
        elif kind == "eye":
            # Show track — open eye (no slash).
            painter.setPen(QPen(color, 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath()
            path.moveTo(cx - 8, cy)
            path.cubicTo(cx - 4, cy - 6, cx + 4, cy - 6, cx + 8, cy)
            path.cubicTo(cx + 4, cy + 6, cx - 4, cy + 6, cx - 8, cy)
            painter.drawPath(path)
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(cx, cy), 2.2, 2.2)
        elif kind == "letter_s":
            # Setup mode — capital S.
            painter.setPen(QPen(color, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath()
            path.moveTo(cx + 5, cy - 6)
            path.cubicTo(cx + 5, cy - 10, cx - 6, cy - 10, cx - 6, cy - 5)
            path.cubicTo(cx - 6, cy - 1, cx + 5, cy - 1, cx + 5, cy + 3)
            path.cubicTo(cx + 5, cy + 8, cx - 6, cy + 8, cx - 6, cy + 4)
            painter.drawPath(path)
