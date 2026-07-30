"""Slim full-song overview scrubber (transport-integrated)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from cueplayer.ui.theme import TEXT, TEXT_MUTED, with_alpha


class TimelineOverviewBar(QWidget):
    """
    Full-width navigator: whole song on one thin strip.

    Drag / click to seek. Soft window = main Timeline visible range.
    Borderless dark bed — sits above Play / Pause / Stop.
    Idle: near-black. Hover: lifted grey (no blue accent).
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
        self._bar_height = 36
        self.setFixedHeight(self._bar_height + 4)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Overview — drag to jump in the song")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)

    def set_title(self, title: str) -> None:
        text = (title or "").strip()
        if text == self._title:
            return
        self._title = text
        self.update()

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
            self._bar_height,
        )

    def _time_for_x(self, x: float) -> float:
        left, _top, width, _h = self._track_rect()
        inset = 12
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

        # Borderless bed — black idle, soft grey on hover (no blue chrome).
        bed = QColor("#222222") if (self._hover or self._dragging) else QColor("#121212")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bed)
        painter.drawRoundedRect(left, top, width, height, 8, 8)

        # Title above the hairline (centered).
        title_band = 14 if (self._title and width >= 200) else 0
        mid_y = top + (title_band + 10 if title_band else height / 2.0)
        inset = 12
        track_left = left + inset
        track_w = max(1, width - inset * 2)

        if title_band:
            painter.setPen(QColor(TEXT))
            font = painter.font()
            font.setPointSize(max(9, font.pointSize() - 1))
            painter.setFont(font)
            elided = painter.fontMetrics().elidedText(
                self._title, Qt.TextElideMode.ElideMiddle, width - 100
            )
            painter.drawText(
                left,
                top + 1,
                width,
                title_band,
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                elided,
            )

        def x_on_track(t: float) -> float:
            return track_left + (t / self._duration) * track_w

        # Progress hairline — unplayed dark, played white.
        painter.setBrush(QColor("#2a2a2a"))
        painter.drawRoundedRect(track_left, int(mid_y - 1), track_w, 2, 1, 1)
        played_w = max(0.0, x_on_track(self._position) - track_left)
        painter.setBrush(QColor("#f0f0f0"))
        painter.drawRoundedRect(
            track_left, int(mid_y - 1), int(min(played_w, track_w)), 2, 1, 1
        )

        # Visible window on the main Timeline (subtle).
        x0 = x_on_track(self._view_start)
        x1 = x_on_track(self._view_end)
        win_w = max(3.0, x1 - x0)
        painter.setBrush(with_alpha("#ffffff", 16))
        painter.drawRoundedRect(int(x0), top + 2, int(win_w), height - 4, 4, 4)

        # A / B loop markers (always visible on the overview strip).
        for label, t, col in (
            ("A", self._loop_a, QColor("#3dd68c")),
            ("B", self._loop_b, QColor("#f0c14a")),
        ):
            if t is None:
                continue
            ax = x_on_track(min(max(0.0, float(t)), self._duration))
            painter.setPen(QPen(col, 2))
            painter.drawLine(QPointF(ax, top + 2), QPointF(ax, top + height - 2))
            painter.setPen(col)
            tiny = painter.font()
            tiny.setPointSize(max(8, tiny.pointSize() - 2))
            tiny.setBold(True)
            painter.setFont(tiny)
            painter.drawText(int(ax + 3), top + 12, label)

        # Playhead tick
        px = x_on_track(self._position)
        painter.setPen(QPen(QColor("#ff5a5f"), 1.5))
        painter.drawLine(QPointF(px, top + 3), QPointF(px, top + height - 3))

        # End labels: 0:00 … duration
        if width >= 140:
            painter.setPen(QColor(TEXT_MUTED))
            font = painter.font()
            font.setPointSize(max(8, font.pointSize() - 2))
            painter.setFont(font)
            start = "0:00"
            end = self._format_time(self._duration)
            painter.drawText(track_left, top + height - 3, start)
            tw = painter.fontMetrics().horizontalAdvance(end)
            painter.drawText(track_left + track_w - tw, top + height - 3, end)

        painter.end()

    @staticmethod
    def _format_time(seconds: float) -> str:
        total = max(0, int(seconds))
        m, s = divmod(total, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"
