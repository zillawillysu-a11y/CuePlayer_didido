"""Setlist row delegate: row colors plus striped-LTC badge on the right."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QStyleOptionViewItem

from cueplayer.ui.row_color import RowColorDelegate
from cueplayer.ui.theme import TEXT_DISABLED, WARNING

# Item-data role: ``None`` = no striped LTC, ``0`` = LTC left, ``1`` = LTC right.
ROLE_LTC_CHANNEL = int(Qt.ItemDataRole.UserRole) + 12

_COL_LTC = 4
# Must stay in sync with SetlistWidget._LTC_COLUMN_WIDTH.
# Tight fit for ``LTC L R`` (small bold font); Song column stretches the rest.
_LTC_COLUMN_WIDTH = 54


class SetlistRowDelegate(RowColorDelegate):
    """Paint ``ROLE_ROW_COLOR`` rows and an LTC/L/R badge in the LTC column."""

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:  # noqa: N802
        hint = super().sizeHint(option, index)
        if index.column() == _COL_LTC:
            return QSize(max(hint.width(), _LTC_COLUMN_WIDTH), hint.height())
        return hint

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # noqa: N802
        if index.column() != _COL_LTC:
            super().paint(painter, option, index)
            return
        self._paint_ltc_cell(painter, option, index)

    def _paint_ltc_cell(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        channel = index.data(ROLE_LTC_CHANNEL)
        if channel is None:
            # Still paint selection / row-color chrome so the column matches the row.
            opt = QStyleOptionViewItem(option)
            self.initStyleOption(opt, index)
            opt.text = ""
            super().paint(painter, opt, index)
            return

        try:
            ltc_side = int(channel)
        except (TypeError, ValueError):
            ltc_side = -1
        if ltc_side not in (0, 1):
            return

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        super().paint(painter, opt, index)

        rect = option.rect.adjusted(2, 0, -4, 0)
        lit = QColor(WARNING)
        dim = QColor(TEXT_DISABLED)

        font = QFont(opt.font)
        font.setPointSize(max(8, font.pointSize() - 1))
        font.setBold(True)
        painter.save()
        painter.setClipRect(option.rect)
        painter.setFont(font)
        fm = painter.fontMetrics()

        parts = [
            ("LTC", lit),
            ("L", lit if ltc_side == 0 else dim),
            ("R", lit if ltc_side == 1 else dim),
        ]
        gap = 3
        widths = [fm.horizontalAdvance(text) for text, _ in parts]
        total = sum(widths) + gap * (len(parts) - 1)
        # Right-align when there is room; otherwise start at left so nothing is clipped off.
        x = rect.right() - total if total <= rect.width() else rect.left()
        y = rect.center().y() + (fm.ascent() - fm.descent()) // 2 - 1
        for (text, color), w in zip(parts, widths, strict=True):
            painter.setPen(color)
            painter.drawText(x, y, text)
            x += w + gap
        painter.restore()
