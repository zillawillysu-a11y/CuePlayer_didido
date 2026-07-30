"""Setlist row delegate: row colors plus Video / striped-LTC badges on the right."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QStyleOptionViewItem

from cueplayer.ui.row_color import ROLE_ROW_COLOR, RowColorDelegate
from cueplayer.ui.theme import (
    ACCENT,
    COLOR_VIDEO,
    badge_dim_on_background,
    badge_lit_on_background,
)

# Item-data roles for the media badge column.
ROLE_LTC_CHANNEL = int(Qt.ItemDataRole.UserRole) + 12
ROLE_HAS_VIDEO = int(Qt.ItemDataRole.UserRole) + 13

_COL_MEDIA = 4
# Must stay in sync with SetlistWidget._LTC_COLUMN_WIDTH.
# Tight fit for ``V LTC L R`` (small bold font); Song column stretches the rest.
_LTC_COLUMN_WIDTH = 68


class SetlistRowDelegate(RowColorDelegate):
    """Paint ``ROLE_ROW_COLOR`` rows and optional V / LTC/L/R badges."""

    def __init__(self, table) -> None:  # noqa: ANN001
        super().__init__(table)
        self._table = table

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:  # noqa: N802
        hint = super().sizeHint(option, index)
        if index.column() == _COL_MEDIA:
            return QSize(max(hint.width(), _LTC_COLUMN_WIDTH), hint.height())
        return hint

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # noqa: N802
        if index.column() != _COL_MEDIA:
            super().paint(painter, option, index)
            return
        self._paint_media_cell(painter, option, index)

    def _show_ltc_badge(self) -> bool:
        return bool(getattr(self._table, "_show_ltc_badge", True))

    def _show_video_badge(self) -> bool:
        return bool(getattr(self._table, "_show_video_badge", True))

    def _row_color_hex(self, index) -> str | None:  # noqa: ANN001
        raw = str(index.data(ROLE_ROW_COLOR) or "").strip()
        if not raw:
            return None
        return raw if QColor(raw).isValid() else None

    def _paint_media_cell(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # noqa: ANN001
        row_hex = self._row_color_hex(index)
        channel = index.data(ROLE_LTC_CHANNEL)
        has_video = bool(index.data(ROLE_HAS_VIDEO))
        show_ltc = self._show_ltc_badge()
        show_video = self._show_video_badge()

        ltc_side: int | None = None
        if show_ltc and channel is not None:
            try:
                side = int(channel)
            except (TypeError, ValueError):
                side = -1
            if side in (0, 1):
                ltc_side = side

        parts: list[tuple[str, str]] = []
        if show_video and has_video:
            parts.append(("V", badge_lit_on_background(row_hex, default=COLOR_VIDEO)))
        if ltc_side is not None:
            lit = badge_lit_on_background(row_hex)
            dim = badge_dim_on_background(row_hex)
            parts.extend(
                [
                    ("LTC", lit),
                    ("L", lit if ltc_side == 0 else dim),
                    ("R", lit if ltc_side == 1 else dim),
                ]
            )

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        super().paint(painter, opt, index)
        if not parts:
            return

        rect = option.rect.adjusted(2, 0, -4, 0)
        font = QFont(opt.font)
        font.setPointSize(max(8, font.pointSize() - 1))
        font.setBold(True)
        painter.save()
        painter.setClipRect(option.rect)
        painter.setFont(font)
        fm = painter.fontMetrics()

        gap = 3
        widths = [fm.horizontalAdvance(text) for text, _ in parts]
        total = sum(widths) + gap * (len(parts) - 1)
        x = rect.right() - total if total <= rect.width() else rect.left()
        y = rect.center().y() + (fm.ascent() - fm.descent()) // 2 - 1
        for (text, color_hex), w in zip(parts, widths, strict=True):
            painter.setPen(QColor(color_hex))
            painter.drawText(x, y, text)
            x += w + gap
        painter.restore()
