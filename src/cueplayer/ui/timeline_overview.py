"""Slim full-song overview scrubber (transport-integrated)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from cueplayer.ui.theme import TEXT_MUTED


class TimelineOverviewBar(QWidget):
    """
    Short full-width time bar above Play / Pause / Stop.

    Drag / click to seek. Shows progress, optional A/B, and a short white
    playhead — no zoom-window frame, no song-title chrome.
    """

    seek_requested = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._duration = 1.0
        self._position = 0.0
        self._view_start = 0.0
        self._view_end = 1.0
        self._title = ""
        self._loop_a: float | None = None
        self._loop_b: float | None = None
        self._dragging = False
        self._hover = False
        self._bar_height = 18
        self.setFixedHeight(self._bar_height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Overview — drag to jump in the song")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)

    def set_title(self, title: str) -> None:
        # Title kept for API compat; not drawn (user wants a plain time bar).
        self._title = (title or "").strip()

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

    def set_loop(self, a: float | None, b: float | None) -> None:
        if a == self._loop_a and b == self._loop_b:
            return
        self._loop_a = float(a) if a is not None else None
        self._loop_b = float(b) if b is not None else None
        self.update()

    def _track_rect(self):
        margin_x = 4
        margin_y = 2
        return (
            margin_x,
            margin_y,
            max(1, self.width() - margin_x * 2),
            max(1, self._bar_height - margin_y * 2),
        )

    def _time_for_x(self, x: float) -> float:
        left, _top, width, _h = self._track_rect()
        inset = 10
        track_left = left + inset
        track_w = max(1, width - inset * 2)
        t = (x - track_left) / track_w * self._duration
        return min(max(0.0, t), self._duration)

    def _seek_at(self, x: float) -> None:
        self.seek_requested.emit(self._time_for_x(x))

    def enterEvent(self, event) -> None:  # noqa: ANN001
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: ANN001
        self._hover = False
        self.update()
        super().leaveEvent(event)

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

        bed = QColor("#1e1e1e") if (self._hover or self._dragging) else QColor("#141414")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bed)
        painter.drawRoundedRect(left, top, width, height, 5, 5)

        mid_y = top + height / 2.0
        inset = 10
        track_left = left + inset
        track_w = max(1, width - inset * 2)

        def x_on_track(t: float) -> float:
            return track_left + (t / self._duration) * track_w

        # Progress hairline only — no zoom-window frame.
        painter.setBrush(QColor("#2a2a2a"))
        painter.drawRoundedRect(track_left, int(mid_y - 1), track_w, 2, 1, 1)
        played_w = max(0.0, x_on_track(self._position) - track_left)
        painter.setBrush(QColor("#c8c8c8"))
        painter.drawRoundedRect(
            track_left, int(mid_y - 1), int(min(played_w, track_w)), 2, 1, 1
        )

        # Soft A–B span when both exist.
        if (
            self._loop_a is not None
            and self._loop_b is not None
            and abs(self._loop_b - self._loop_a) >= 0.01
        ):
            a, b = sorted((self._loop_a, self._loop_b))
            x0 = x_on_track(a)
            x1 = x_on_track(b)
            painter.setBrush(QColor(61, 214, 140, 40))
            painter.drawRoundedRect(
                int(x0), int(mid_y - 3), max(2, int(x1 - x0)), 6, 2, 2
            )

        # A / B ticks (short, centered on the hairline).
        for label, t, col in (
            ("A", self._loop_a, QColor("#3dd68c")),
            ("B", self._loop_b, QColor("#f0c14a")),
        ):
            if t is None:
                continue
            ax = x_on_track(min(max(0.0, float(t)), self._duration))
            painter.setPen(QPen(col, 2))
            painter.drawLine(QPointF(ax, mid_y - 5), QPointF(ax, mid_y + 5))
            tiny = painter.font()
            tiny.setPointSize(max(7, tiny.pointSize() - 3))
            tiny.setBold(True)
            painter.setFont(tiny)
            painter.setPen(col)
            painter.drawText(int(ax + 2), int(mid_y - 6), label)

        # Short, slightly thicker white playhead (not full-height red).
        px = x_on_track(self._position)
        painter.setPen(QPen(QColor("#ffffff"), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(px, mid_y - 4), QPointF(px, mid_y + 4))

        if width >= 140:
            painter.setPen(QColor(TEXT_MUTED))
            font = painter.font()
            font.setPointSize(max(7, font.pointSize() - 3))
            font.setBold(False)
            painter.setFont(font)
            start = "0:00"
            end = self._format_time(self._duration)
            painter.drawText(track_left, top + height - 1, start)
            tw = painter.fontMetrics().horizontalAdvance(end)
            painter.drawText(track_left + track_w - tw, top + height - 1, end)

        painter.end()

    @staticmethod
    def _format_time(seconds: float) -> str:
        total = max(0, int(seconds))
        m, s = divmod(total, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"
