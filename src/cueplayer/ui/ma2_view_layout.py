"""Interactive fixed 16 x 8 grandMA2 Screen 3 layout editor."""

from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QWidget


DEFAULT_VIEW_LAYOUT: list[dict[str, object]] = [
    {"type": "sequence", "mode": "perSong", "x": 0, "y": 0, "w": 10, "h": 1, "start": 1, "stride": 20},
    {"type": "macros", "mode": "fixed", "x": 10, "y": 0, "w": 6, "h": 1, "start": 101, "stride": 1},
    {"type": "effects", "mode": "perSong", "x": 0, "y": 1, "w": 16, "h": 5, "start": 201, "stride": 100},
    {"type": "effects", "mode": "fixed", "x": 0, "y": 6, "w": 16, "h": 2, "start": 1, "stride": 1},
]

TIMECODE_POOL_TOTAL_CELLS = 3

POOL_LABELS = {
    "camera": "Camera Pool",
    "effects": "Effects",
    "filters": "Filters",
    "forms": "Forms",
    "groups": "Groups",
    "images": "Images",
    "layout": "Layout Pool",
    "macros": "Macros",
    "masks": "Masks",
    "matricks": "MAtricks",
    "pagesChannel": "Pages Channel",
    "pagesExec": "Pages Exec",
    "sequence": "Sequence",
    "timecode": "Timecode Pool",
    "timecodeSlots": "Timecode Slots Pool",
    "timer": "Timer",
    "views": "Views",
    "universes": "Universes",
    "worlds": "Worlds",
}


def default_view_layout() -> list[dict[str, object]]:
    return deepcopy(DEFAULT_VIEW_LAYOUT)


class Ma2ViewLayoutStage(QWidget):
    """Paint and directly drag/resize Pool windows on the permanent 16 x 8 grid."""

    selection_changed = Signal(int)
    layout_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.widgets: list[dict[str, object]] = default_view_layout()
        self.selected_index = 0
        self.song_index = 0
        self.locked = False
        self._drag_mode = ""
        self._drag_origin = QPoint()
        self._drag_snapshot: dict[str, object] | None = None
        self.setMinimumSize(720, 360)
        self.setMouseTracking(True)

    def set_layout(self, widgets: list[dict[str, object]]) -> None:
        self.widgets = deepcopy(widgets or DEFAULT_VIEW_LAYOUT)
        for widget in self.widgets:
            if widget.get("type") == "timecode":
                widget["w"] = TIMECODE_POOL_TOTAL_CELLS
                widget["h"] = 1
                widget["x"] = min(int(widget.get("x", 0)), 16 - TIMECODE_POOL_TOTAL_CELLS)
        self.selected_index = min(self.selected_index, len(self.widgets) - 1)
        self.update()

    def _cell_size(self) -> tuple[float, float]:
        return self.width() / 16.0, self.height() / 8.0

    def _rect(self, widget: dict[str, object]) -> QRectF:
        cw, ch = self._cell_size()
        return QRectF(float(widget["x"]) * cw, float(widget["y"]) * ch, float(widget["w"]) * cw, float(widget["h"]) * ch)

    def paintEvent(self, _event) -> None:  # noqa: N802, ANN001
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#11151a"))
        cw, ch = self._cell_size()
        painter.setPen(QPen(QColor("#2a3038"), 1))
        for column in range(17):
            painter.drawLine(int(column * cw), 0, int(column * cw), self.height())
        for row in range(9):
            painter.drawLine(0, int(row * ch), self.width(), int(row * ch))
        for index, widget in enumerate(self.widgets):
            rect = self._rect(widget).adjusted(1, 1, -1, -1)
            selected = index == self.selected_index
            border = QColor("#3b82f6") if selected else QColor("#5d6875")
            fill = QColor("#172554") if widget.get("mode") == "perSong" else QColor("#4a1635")
            painter.fillRect(rect, QColor("#1b2026"))
            painter.setPen(QPen(border, 3 if selected else 2))
            painter.drawRect(rect)
            title = QRectF(rect.left(), rect.top(), cw, ch).adjusted(2, 2, -2, -2)
            painter.fillRect(title, fill)
            painter.setPen(QColor("#f8fafc"))
            painter.drawText(title, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, POOL_LABELS.get(str(widget.get("type")), str(widget.get("type", "Pool"))))
            start = int(widget.get("start", 1))
            if widget.get("mode") == "perSong":
                start += self.song_index * int(widget.get("stride", 1))
            slots = int(widget["w"]) * int(widget["h"]) - 1
            # MA2's Timecode Pool window consumes three Screen 3 cells in
            # total: one title cell plus its two built-in slots.
            builtin_slots = TIMECODE_POOL_TOTAL_CELLS - 1 if widget.get("type") == "timecode" else 0
            for offset in range(max(0, slots)):
                cell = offset + 1
                column = cell % int(widget["w"])
                row = cell // int(widget["w"])
                cell_rect = QRectF(rect.left() + column * cw, rect.top() + row * ch, cw, ch)
                painter.setPen(QColor("#b9c2ce"))
                text = (
                    f"Built-in\nSlot {offset + 1}"
                    if offset < builtin_slots
                    else str(start + offset - builtin_slots)
                )
                painter.drawText(
                    cell_rect.adjusted(5, 3, -2, -2),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                    text,
                )
            if selected and not self.locked:
                painter.fillRect(QRectF(rect.right() - 12, rect.bottom() - 12, 10, 10), QColor("#3b82f6"))

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = event.position()
        for index in range(len(self.widgets) - 1, -1, -1):
            rect = self._rect(self.widgets[index])
            if rect.contains(point):
                self.selected_index = index
                self.selection_changed.emit(index)
                self.update()
                if not self.locked:
                    self._drag_origin = event.position().toPoint()
                    self._drag_snapshot = deepcopy(self.widgets[index])
                    resizable = self.widgets[index].get("type") != "timecode"
                    self._drag_mode = "resize" if resizable and point.x() > rect.right() - 18 and point.y() > rect.bottom() - 18 else "move"
                return

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self._drag_mode or self._drag_snapshot is None or self.selected_index < 0:
            return
        cw, ch = self._cell_size()
        dx = round((event.position().x() - self._drag_origin.x()) / cw)
        dy = round((event.position().y() - self._drag_origin.y()) / ch)
        widget = self.widgets[self.selected_index]
        source = self._drag_snapshot
        if self._drag_mode == "move":
            widget["x"] = max(0, min(16 - int(source["w"]), int(source["x"]) + dx))
            widget["y"] = max(0, min(8 - int(source["h"]), int(source["y"]) + dy))
        else:
            widget["w"] = max(1, min(16 - int(source["x"]), int(source["w"]) + dx))
            widget["h"] = max(1, min(8 - int(source["y"]), int(source["h"]) + dy))
        self.update()

    def mouseReleaseEvent(self, _event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_mode:
            self._drag_mode = ""
            self._drag_snapshot = None
            self.layout_changed.emit()
