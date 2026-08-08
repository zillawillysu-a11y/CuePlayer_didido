"""Interactive Screen 3 layout editor — MA2 uses a fixed 16 x 8 grid,
MA3 an 18 x 10 grid (confirmed against a real onPC View export: widget
X/Y/W/H there are exactly 2x the grid-cell coordinates edited here, so a
36-wide/20-tall MA3 canvas is an 18x10 grid)."""

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

# Exact Screen 3 geometry and visible pool starts from Willy's real
# grandMA3 2.3.2 SONGVIEW.xml export. MA2 keeps its established default above.
DEFAULT_MA3_VIEW_LAYOUT: list[dict[str, object]] = [
    {"type": "sequence", "mode": "perSong", "x": 0, "y": 0, "w": 18, "h": 1, "start": 1018, "stride": 20},
    {"type": "groups", "mode": "perSong", "x": 0, "y": 1, "w": 18, "h": 1, "start": 1018, "stride": 20},
    {"type": "all3", "mode": "fixed", "x": 0, "y": 2, "w": 18, "h": 3, "start": 1, "stride": 1},
    {"type": "all5", "mode": "perSong", "x": 0, "y": 5, "w": 18, "h": 5, "start": 1091, "stride": 100},
]

TIMECODE_POOL_TOTAL_CELLS = 3

# (grid_w, grid_h) per console — MA2's Screen 3 is a fixed 16x8 grid; MA3's
# is 18x10 (real hardware: SONGVIEW.xml's raw X/Y/W/H are exactly 2x these
# grid-cell coordinates).
GRID_SIZE_BY_CONSOLE: dict[str, tuple[int, int]] = {
    "ma2": (16, 8),
    "ma3": (18, 10),
}

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

MA3_POOL_LABELS = {
    "sequence": "Sequence",
    "groups": "Groups",
    "macros": "Macros",
    "all1": "All 1",
    "all2": "All 2",
    "all3": "All 3\nTemplate EFX",
    "all4": "All 4",
    "all5": "All 5\nSong EFX",
}


def default_view_layout() -> list[dict[str, object]]:
    return deepcopy(DEFAULT_VIEW_LAYOUT)


def default_ma3_view_layout() -> list[dict[str, object]]:
    return deepcopy(DEFAULT_MA3_VIEW_LAYOUT)


class Ma2ViewLayoutStage(QWidget):
    """Paint and directly drag/resize Pool windows on a fixed grid whose
    size depends on the target console (see ``GRID_SIZE_BY_CONSOLE``)."""

    selection_changed = Signal(int)
    layout_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.grid_w = 16
        self.grid_h = 8
        self.widgets: list[dict[str, object]] = default_view_layout()
        self.selected_index = 0
        self.song_index = 0
        self.locked = False
        self._drag_mode = ""
        self._drag_origin = QPoint()
        self._drag_snapshot: dict[str, object] | None = None
        self.setMinimumSize(720, 360)
        self.setMouseTracking(True)

    def set_grid_size(self, grid_w: int, grid_h: int) -> None:
        if (grid_w, grid_h) == (self.grid_w, self.grid_h):
            return
        self.grid_w = int(grid_w)
        self.grid_h = int(grid_h)
        for widget in self.widgets:
            widget["x"] = max(0, min(self.grid_w - int(widget.get("w", 1)), int(widget.get("x", 0))))
            widget["y"] = max(0, min(self.grid_h - int(widget.get("h", 1)), int(widget.get("y", 0))))
        self.update()

    def set_layout(self, widgets: list[dict[str, object]]) -> None:
        self.widgets = deepcopy(widgets or DEFAULT_VIEW_LAYOUT)
        for widget in self.widgets:
            if widget.get("type") == "timecode":
                # Three cells is the Timecode Pool's minimum native footprint
                # (title + two built-ins); the user may extend it rightward.
                widget["w"] = min(self.grid_w, max(TIMECODE_POOL_TOTAL_CELLS, int(widget.get("w", 1))))
                widget["x"] = min(int(widget.get("x", 0)), self.grid_w - int(widget["w"]))
        self.selected_index = min(self.selected_index, len(self.widgets) - 1)
        self.update()

    def _cell_size(self) -> tuple[float, float]:
        return self.width() / float(self.grid_w), self.height() / float(self.grid_h)

    def _rect(self, widget: dict[str, object]) -> QRectF:
        cw, ch = self._cell_size()
        return QRectF(float(widget["x"]) * cw, float(widget["y"]) * ch, float(widget["w"]) * cw, float(widget["h"]) * ch)

    def paintEvent(self, _event) -> None:  # noqa: N802, ANN001
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#11151a"))
        cw, ch = self._cell_size()
        painter.setPen(QPen(QColor("#2a3038"), 1))
        for column in range(self.grid_w + 1):
            painter.drawLine(int(column * cw), 0, int(column * cw), self.height())
        for row in range(self.grid_h + 1):
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
            labels = MA3_POOL_LABELS if (self.grid_w, self.grid_h) == GRID_SIZE_BY_CONSOLE["ma3"] else POOL_LABELS
            title_text = labels.get(str(widget.get("type")), str(widget.get("type", "Pool")))
            title_flags = Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap
            painter.save()
            if labels is MA3_POOL_LABELS:
                # MA3's title cell is only 1/18 of the screen width. Keep the
                # two-line EFX labels inside that cell on real Windows font
                # metrics instead of clipping the second line at the bottom.
                title_font = painter.font()
                for pixel_size in range(12, 6, -1):
                    title_font.setPixelSize(pixel_size)
                    painter.setFont(title_font)
                    bounds = painter.boundingRect(title, title_flags, title_text)
                    if bounds.width() <= title.width() and bounds.height() <= title.height():
                        break
            painter.drawText(title, title_flags, title_text)
            painter.restore()
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
                    self._drag_mode = "resize" if point.x() > rect.right() - 18 and point.y() > rect.bottom() - 18 else "move"
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
            widget["x"] = max(0, min(self.grid_w - int(source["w"]), int(source["x"]) + dx))
            widget["y"] = max(0, min(self.grid_h - int(source["h"]), int(source["y"]) + dy))
        else:
            minimum_width = TIMECODE_POOL_TOTAL_CELLS if widget.get("type") == "timecode" else 1
            widget["w"] = max(minimum_width, min(self.grid_w - int(source["x"]), int(source["w"]) + dx))
            widget["h"] = max(1, min(self.grid_h - int(source["y"]), int(source["h"]) + dy))
        self.update()

    def mouseReleaseEvent(self, _event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_mode:
            self._drag_mode = ""
            self._drag_snapshot = None
            self.layout_changed.emit()
