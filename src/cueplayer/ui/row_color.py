"""Shared Song.row_color painting for setlist / export song lists.

Keeps selection treatment on the same accent-blue family as the rest of the
app (see ``theme.py``), including when a custom-colored row is selected.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import (
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)

from cueplayer.ui.theme import ACCENT, BG_SELECTED, contrast_text_color, with_alpha

# Custom item-data role: optional "#RRGGBB" (or "") for Song.row_color.
ROLE_ROW_COLOR = int(Qt.ItemDataRole.UserRole) + 50


class RowColorDelegate(QStyledItemDelegate):
    """Paint optional ``ROLE_ROW_COLOR`` background + accent selection chrome."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # noqa: N802
        color_hex = str(index.data(ROLE_ROW_COLOR) or "").strip()
        base = QColor(color_hex) if color_hex else None
        if base is not None and not base.isValid():
            base = None
        selected = bool(option.state & QStyle.StateFlag.State_Selected)

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.textElideMode = Qt.TextElideMode.ElideNone

        if base is None and not selected:
            super().paint(painter, opt, index)
            return
        opt.features = opt.features & ~QStyleOptionViewItem.ViewItemFeature.Alternate
        opt.state = opt.state & ~QStyle.StateFlag.State_Selected

        rect = option.rect
        painter.save()
        if base is not None:
            painter.fillRect(rect, base)
            if selected:
                painter.fillRect(rect, with_alpha(ACCENT, 90))
            text_hex = contrast_text_color(base.name())
        else:
            painter.fillRect(rect, QColor(BG_SELECTED))
            text_hex = "#ffffff"
        if selected:
            painter.fillRect(
                int(rect.left()), int(rect.top()), 3, int(rect.height()), QColor(ACCENT)
            )
        painter.restore()

        text_color = QColor(text_hex)
        opt.palette.setColor(QPalette.ColorRole.Text, text_color)
        opt.palette.setColor(QPalette.ColorRole.HighlightedText, text_color)
        super().paint(painter, opt, index)
