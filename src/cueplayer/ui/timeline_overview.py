"""Slim full-song overview scrubber under the main Timeline."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from cueplayer.ui.theme import BORDER, BORDER_STRONG, TEXT_MUTED, with_alpha


class TimelineOverviewBar(QWidget):
    """
    Compact navigator: whole song on one thin strip.

    Drag / click to seek. A soft window shows the main Timeline's visible range.
    """

    seek_requested = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._duration = 1.0
        self._position = 0.0
        self._view_start = 0.0
        self._view_end = 1.0
        self._dragging = False
        self._bar_height = 22
        self.setFixedHeight(self._bar_height + 10)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Overview — drag to jump in the song")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def set_state(
        self,
        *,
        duration: float,
        position: float,
        view_start: float,
        view_end: float,
    ) -> None:
        duration = max(0.1, float(duration))
        position = min(max(0.0, float(position)), duration)
        view_start = min(max(0.0, float(view_start)), duration)
        view_end = min(max(view_start + 0.01, float(view_end)), duration)
        changed = (
            abs(duration - self._duration) > 1e-6
            or abs(position - self._position) > 1e-4
            or abs(view_start - self._view_start) > 1e-4
            or abs(view_end - self._view_end) > 1e-4
        )
        self._duration = duration
        self._position = position
        self._view_start = view_start
        self._view_end = view_end
        if changed:
            self.update()

    def _track_rect(self):
        margin_x = 8
        margin_y = 5
        return (
            margin_x,
            margin_y,
            max(1, self.width() - margin_x * 2),
            self._bar_height,
        )

    def _time_for_x(self, x: float) -> float:
        left, _top, width, _h = self._track_rect()
        if width <= 1:
            return 0.0
        t = (x - left) / width * self._duration
        return min(max(0.0, t), self._duration)

    def _x_for_time(self, t: float) -> float:
        left, _top, width, _h = self._track_rect()
        return left + (t / self._duration) * width

    def _seek_at(self, x: float) -> None:
        self.seek_requested.emit(self._time_for_x(x))

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self.grabMouse()
            self._seek_at(event.position().x())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001
        if self._dragging and event.buttons() & Qt.MouseButton.LeftButton:
            self._seek_at(event.position().x())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self.releaseMouse()
            self._seek_at(event.position().x())
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: ANN001
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        left, top, width, height = self._track_rect()

        # Track bed
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#0c0c0e"))
        painter.drawRoundedRect(left, top, width, height, 4, 4)
        painter.setPen(QPen(QColor(BORDER), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(left, top, width, height, 4, 4)

        # Visible window on the main Timeline
        x0 = self._x_for_time(self._view_start)
        x1 = self._x_for_time(self._view_end)
        win_w = max(3.0, x1 - x0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(with_alpha(BORDER_STRONG, 160))
        painter.drawRoundedRect(int(x0), top + 1, int(win_w), height - 2, 3, 3)
        painter.setPen(QPen(with_alpha(TEXT_MUTED, 180), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(int(x0), top + 1, int(win_w), height - 2, 3, 3)

        # Playhead
        px = self._x_for_time(self._position)
        painter.setPen(QPen(QColor("#ff5a5f"), 1.5))
        painter.drawLine(QPointF(px, top + 1), QPointF(px, top + height - 1))

        # Tiny end labels when wide enough
        if width >= 160:
            painter.setPen(QColor(TEXT_MUTED))
            font = painter.font()
            font.setPointSize(max(8, font.pointSize() - 2))
            painter.setFont(font)
            painter.drawText(left + 4, top + height - 4, "0")
            end = self._format_time(self._duration)
            tw = painter.fontMetrics().horizontalAdvance(end)
            painter.drawText(left + width - tw - 4, top + height - 4, end)

        painter.end()

    @staticmethod
    def _format_time(seconds: float) -> str:
        total = max(0, int(seconds))
        m, s = divmod(total, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"
