"""Slim full-song overview scrubber (transport-integrated)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from cueplayer.ui.theme import TEXT_MUTED


class TimelineOverviewBar(QWidget):
    """
    Centered, horizontally shortened time bar above Play / Pause / Stop.

    Drag / click to seek. Progress + A/B + short white playhead.
    Time labels sit in side gutters so the white line never covers them.
    """

    seek_requested = Signal(float)

    # Side gutters for "0:00" / duration — keep hairline clear of the text.
    _LABEL_GUTTER = 56

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
        self._bar_height = 26
        self.setFixedHeight(self._bar_height)
        # Prefer a shorter horizontal span; transport centers us with stretches.
        self.setMinimumWidth(280)
        self.setMaximumWidth(720)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Overview — drag to jump in the song")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)

    def set_title(self, title: str) -> None:
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
        """Inner bed between time-label gutters."""
        gutter = self._LABEL_GUTTER
        margin_y = 2
        return (
            gutter,
            margin_y,
            max(1, self.width() - gutter * 2),
            max(1, self._bar_height - margin_y * 2),
        )

    def _time_for_x(self, x: float) -> float:
        left, _top, width, _h = self._track_rect()
        inset = 6
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
        inset = 6
        track_left = left + inset
        track_w = max(1, width - inset * 2)

        def x_on_track(t: float) -> float:
            return track_left + (t / self._duration) * track_w

        # Progress hairline — stays inside the bed, clear of side time labels.
        painter.setBrush(QColor("#2a2a2a"))
        painter.drawRoundedRect(track_left, int(mid_y - 1), track_w, 2, 1, 1)
        played_w = max(0.0, x_on_track(self._position) - track_left)
        painter.setBrush(QColor("#f0f0f0"))
        painter.drawRoundedRect(
            track_left, int(mid_y - 1), int(min(played_w, track_w)), 2, 1, 1
        )

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

        px = x_on_track(self._position)
        painter.setPen(
            QPen(QColor("#ffffff"), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        )
        painter.drawLine(QPointF(px, mid_y - 5), QPointF(px, mid_y + 5))

        # Time labels in gutters — never under the white progress line.
        painter.setPen(QColor(TEXT_MUTED))
        font = painter.font()
        # Slightly larger than body muted text so ends stay readable at a glance.
        font.setPointSize(max(11, font.pointSize() + 1))
        font.setBold(True)
        painter.setFont(font)
        start = "0:00"
        end = self._format_time(self._duration)
        painter.drawText(
            4,
            0,
            self._LABEL_GUTTER - 6,
            self.height(),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight),
            start,
        )
        painter.drawText(
            self.width() - self._LABEL_GUTTER + 2,
            0,
            self._LABEL_GUTTER - 6,
            self.height(),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            end,
        )

        # A/B last so ticks + letters stay above playhead / time gutters.
        mark_font = painter.font()
        mark_font.setPointSize(max(9, mark_font.pointSize() - 1))
        mark_font.setBold(True)
        painter.setFont(mark_font)
        fm = painter.fontMetrics()
        for label, t, col in (
            ("A", self._loop_a, QColor("#3dd68c")),
            ("B", self._loop_b, QColor("#f0c14a")),
        ):
            if t is None:
                continue
            ax = x_on_track(min(max(0.0, float(t)), self._duration))
            painter.setPen(QPen(col, 2))
            painter.drawLine(QPointF(ax, mid_y - 7), QPointF(ax, mid_y + 7))
            painter.setPen(col)
            text_w = fm.horizontalAdvance(label)
            # Keep the letter inside the track bed, not under side time labels.
            tx = int(ax + 3)
            if tx + text_w > left + width - 2:
                tx = int(ax - text_w - 3)
            tx = max(left + 2, min(tx, left + width - text_w - 2))
            painter.drawText(tx, int(mid_y - 2), label)

        painter.end()

    @staticmethod
    def _format_time(seconds: float) -> str:
        total = max(0, int(seconds))
        m, s = divmod(total, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"
