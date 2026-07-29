"""Right-side monitor: big clock, current cue(s), and scrolling cue list."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QMimeData, QPoint, Qt, QTimer, Signal, QEvent
from PySide6.QtGui import QAction, QColor, QDrag, QFont, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHeaderView,
    QLabel,
    QMenu,
    QSizePolicy,
    QSplitter,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cueplayer.domain.main_cue_id import (
    is_valid_main_cue_id_text,
    main_cue_id_fits_order,
    main_cue_id_map,
    main_cue_id_order_hint,
    main_cue_id_taken,
    normalize_main_cue_id_text,
)
from cueplayer.domain.models import Mark, Song
from cueplayer.ui.cue_list_columns import (
    CUE_LIST_FIELD_LABELS,
    CUE_LIST_FIELDS,
    DEFAULT_CUE_LIST_COLUMN_ORDER,
    LOGICAL_INDEX_BY_FIELD,
    normalize_cue_list_column_order,
)
from cueplayer.ui.transport_bar import format_time

_COL_COUNT = len(CUE_LIST_FIELDS)
_ROW_HEIGHT = 34


class _RevealLabel(QLabel):
    """Small affordance when the Cue List is collapsed."""

    clicked = Signal()

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("color: #71717a; font-size: 11px; padding: 4px 0;")
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class _PaddedItemDelegate(QStyledItemDelegate):
    """Extra vertical padding so edited text is not clipped."""

    def paint(self, painter, option, index) -> None:  # noqa: ANN001
        opt = QStyleOptionViewItem(option)
        opt.rect = opt.rect.adjusted(0, 2, 0, -2)
        super().paint(painter, opt, index)

    def createEditor(self, parent, option, index):  # noqa: ANN001
        editor = super().createEditor(parent, option, index)
        if editor is not None:
            editor.setStyleSheet(
                "padding: 4px 6px; margin: 0; min-height: 1.4em;"
            )
        return editor


def mark_now_text(song: Song, mark: Mark) -> str:
    note = mark.display_name.strip()
    if note:
        return note
    lane = song.lane_by_index(mark.lane_index)
    return lane.name if lane is not None else f"Type {mark.lane_index}"


_MIME_NOW_SECONDARY = "application/x-cueplayer-now-secondary"
_NOW_CARD_MIN_H = 72
_NOW_CARD_MIN_H_BELOW = 52
_NOW_PRIMARY_COL_MIN = 72
_NOW_SECONDARY_COL_MIN = 64
_CUE_LIST_BODY_MIN = 80
_NOW_TITLE_CHROME = 30  # NOW label + layout spacing/margins


def _now_card_style(accent: str, *, secondary: bool = False) -> str:
    """Card chrome. Full border + radius so top *and* bottom corners round cleanly."""
    size = "16px" if secondary else "20px"
    pad = "10px 10px" if secondary else "12px 12px"
    return (
        f"color: #e4e4e7; font-size: {size}; font-weight: 600;"
        f"padding: {pad}; line-height: 1.3;"
        f"background-color: #141416;"
        # Qt only rounds reliably when all sides are set (not border-left alone).
        f"border: 1px solid #1f1f22;"
        f"border-left: 5px solid {accent};"
        f"border-radius: 8px;"
    )


def mark_now_body(song: Song, mark: Mark, *, show_cue_id: bool = False) -> str:
    lane = song.lane_by_index(mark.lane_index)
    lane_bit = lane.name if lane is not None else f"Type {mark.lane_index}"
    note = mark.display_name.strip()

    if show_cue_id:
        detail_lines: list[str] = []
        if lane is not None and lane.cue_id_enabled:
            cue_id = mark.main_cue_id.strip()
            if cue_id:
                detail_lines.append(f"Cue {cue_id}")
        if note:
            detail_lines.append(note)
        if detail_lines:
            return f"{lane_bit}\n-\n" + "\n".join(detail_lines)
        return lane_bit

    if note:
        return f"{lane_bit}\n{note}"
    return lane_bit


class CueMonitorPanel(QWidget):
    """Cue list: click Time/Type to seek; Note edits; Shift/Ctrl multi-select + Del."""

    seek_requested = Signal(float)
    delete_requested = Signal(list)  # list[str] mark ids
    selection_changed = Signal(list)  # list[str] mark ids
    note_changed = Signal(str, str, str)  # mark_id, old_name, new_name
    cue_id_changed = Signal(str, str, str)  # mark_id, old_id, new_id
    cue_id_edit_failed = Signal(str)  # user-facing reason
    cue_list_layout_changed = Signal()
    renumber_cue_ids_requested = Signal(object)  # lane_index: int | None (None = all)
    now_visibility_changed = Signal()
    cue_list_visibility_changed = Signal()
    now_layout_changed = Signal()
    output_timecode_clock_changed = Signal()  # secondary right/below or splitter sizes

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._song: Song | None = None
        self._position = 0.0
        self._current_mark_ids: set[str] = set()
        self._playhead_list_mark_id: str | None = None
        self._updating_table = False
        self._syncing_selection = False
        self._secondary_hold_mark_id: str | None = None
        self._secondary_cleared = False
        self._secondary_clear_timer = QTimer(self)
        self._secondary_clear_timer.setSingleShot(True)
        self._secondary_clear_timer.timeout.connect(self._on_secondary_auto_clear)
        self._column_order: list[str] = list(DEFAULT_CUE_LIST_COLUMN_ORDER)
        self._reordering_header = False
        self._now_placement = "right"  # "right" | "below"
        self._splitter_state_right: QByteArray | None = None
        self._splitter_state_below: QByteArray | None = None
        self._body_splitter_state: QByteArray | None = None
        self._secondary_drag_origin: QPoint | None = None

        self.setMinimumWidth(280)
        self.setMaximumWidth(440)
        # Prefer shrinking children over forcing the main window taller.
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        clock_frame = QFrame()
        self._clock_frame = clock_frame
        clock_frame.setObjectName("clockFrame")
        clock_frame.setStyleSheet(
            "#clockFrame {"
            "  background: #111113;"
            "  border: 1px solid #27272a;"
            "  border-radius: 8px;"
            "}"
            "#clockFrame QLabel {"
            "  background: transparent;"
            "}"
        )
        clock_layout = QVBoxLayout(clock_frame)
        clock_layout.setContentsMargins(12, 16, 12, 16)
        clock_layout.setSpacing(6)

        self.clock_label = QLabel("00:00.000")
        self.clock_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        clock_font = QFont("Consolas")
        if not clock_font.exactMatch():
            clock_font = QFont("Cascadia Mono")
        clock_font.setPointSize(48)
        clock_font.setBold(True)
        self.clock_label.setFont(clock_font)
        self.clock_label.setStyleSheet(
            "color: #e4e4e7; background: transparent; font-size: 48px; font-weight: 700;"
            "font-family: Consolas, 'Cascadia Mono', monospace;"
        )

        self.duration_label = QLabel("/ 00:00.000")
        self.duration_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.duration_label.setStyleSheet(
            "color: #a1a1aa; background: transparent; font-size: 16px;"
        )

        clock_layout.addWidget(self.clock_label)
        clock_layout.addWidget(self.duration_label)

        self._tc_output_block = QWidget()
        self._tc_output_block.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._tc_output_block.setStyleSheet("background: transparent;")
        tc_out_layout = QVBoxLayout(self._tc_output_block)
        tc_out_layout.setContentsMargins(0, 8, 0, 4)
        tc_out_layout.setSpacing(2)

        self.tc_output_status = QLabel("TC off")
        self.tc_output_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tc_output_status.setStyleSheet(
            "color: #71717a; background: transparent; font-size: 11px; font-weight: 600;"
            "letter-spacing: 0.5px;"
        )

        self.tc_output_value = QLabel("01:00:00:00")
        self.tc_output_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tc_font = QFont("Consolas")
        if not tc_font.exactMatch():
            tc_font = QFont("Cascadia Mono")
        tc_font.setPointSize(22)
        tc_font.setBold(True)
        self.tc_output_value.setFont(tc_font)
        self._tc_clock_color = "#3dd68c"
        self._show_output_tc_clock = True
        self._apply_output_timecode_style()

        tc_out_layout.addWidget(self.tc_output_status)
        tc_out_layout.addWidget(self.tc_output_value)
        clock_layout.addWidget(self._tc_output_block)

        clock_frame.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        clock_frame.customContextMenuRequested.connect(self._show_clock_context_menu)

        now_title = QLabel("NOW")
        now_title.setStyleSheet("color: #a1a1aa; font-size: 11px; letter-spacing: 1px;")

        self.primary_track = QLabel("PRIMARY")
        self.primary_track.setStyleSheet("color: #a1a1aa; font-size: 11px; font-weight: 600;")
        self.primary_cue = QLabel("—")
        self.primary_cue.setWordWrap(True)
        self.primary_cue.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.primary_cue.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.primary_cue.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.primary_cue.setMinimumHeight(_NOW_CARD_MIN_H)
        self.primary_cue.setStyleSheet(_now_card_style("#ff5a5f"))

        self.secondary_track = QLabel("SECONDARY")
        self.secondary_track.setStyleSheet("color: #a1a1aa; font-size: 11px; font-weight: 600;")
        self.secondary_track.setToolTip("Drag to place Secondary on the right or below Primary")
        self.secondary_track.setCursor(Qt.CursorShape.OpenHandCursor)
        self.secondary_cue = QLabel("—")
        self.secondary_cue.setWordWrap(True)
        # Secondary copy sits vertically centered in the card.
        self.secondary_cue.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.secondary_cue.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.secondary_cue.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.secondary_cue.setMinimumHeight(_NOW_CARD_MIN_H)
        self.secondary_cue.setStyleSheet(_now_card_style("#52525b", secondary=True))

        self._now_section = QWidget()
        self._now_section.setAcceptDrops(True)
        self._now_section.setMinimumHeight(
            _NOW_TITLE_CHROME + _NOW_PRIMARY_COL_MIN
        )
        self._now_section.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        now_layout = QVBoxLayout(self._now_section)
        now_layout.setContentsMargins(0, 0, 0, 4)
        now_layout.setSpacing(6)
        now_layout.addWidget(now_title)

        self._primary_now_column = QWidget()
        self._primary_now_column.setMinimumWidth(120)
        self._primary_now_column.setMinimumHeight(_NOW_PRIMARY_COL_MIN)
        self._primary_now_column.setAcceptDrops(True)
        primary_col_layout = QVBoxLayout(self._primary_now_column)
        primary_col_layout.setContentsMargins(0, 0, 0, 0)
        primary_col_layout.setSpacing(4)
        primary_col_layout.addWidget(self.primary_track)
        primary_col_layout.addWidget(self.primary_cue, stretch=1)

        self._secondary_now_column = QWidget()
        self._secondary_now_column.setMinimumWidth(72)
        self._secondary_now_column.setMinimumHeight(_NOW_SECONDARY_COL_MIN)
        secondary_col_layout = QVBoxLayout(self._secondary_now_column)
        secondary_col_layout.setContentsMargins(0, 0, 0, 0)
        secondary_col_layout.setSpacing(4)
        secondary_col_layout.addWidget(self.secondary_track)
        secondary_col_layout.addWidget(self.secondary_cue, stretch=1)

        self._now_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._now_splitter.setObjectName("nowSplitter")
        self._now_splitter.setChildrenCollapsible(False)
        self._now_splitter.setHandleWidth(8)
        self._now_splitter.setOpaqueResize(True)
        self._now_splitter.setAcceptDrops(True)
        self._now_splitter.setStyleSheet(
            "#nowSplitter::handle {"
            "  background: transparent;"
            "  border: none;"
            "  margin: 0;"
            "  padding: 0;"
            "}"
            "#nowSplitter::handle:hover {"
            "  background: rgba(74, 158, 255, 0.35);"
            "}"
        )
        self._now_splitter.addWidget(self._primary_now_column)
        self._now_splitter.addWidget(self._secondary_now_column)
        self._now_splitter.setStretchFactor(0, 3)
        self._now_splitter.setStretchFactor(1, 1)
        self._now_splitter.setSizes([260, 100])
        self._now_splitter.splitterMoved.connect(self._on_now_splitter_moved)
        now_layout.addWidget(self._now_splitter, stretch=1)
        self._now_section.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._now_section.customContextMenuRequested.connect(self._show_now_context_menu)
        for widget in (
            now_title,
            self.primary_track,
            self.primary_cue,
            self.secondary_track,
            self.secondary_cue,
            self._primary_now_column,
            self._secondary_now_column,
            self._now_splitter,
            self._now_section,
        ):
            widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            widget.customContextMenuRequested.connect(self._show_now_context_menu)
        self.secondary_track.installEventFilter(self)
        self._secondary_now_column.installEventFilter(self)
        self._now_section.installEventFilter(self)
        self._now_splitter.installEventFilter(self)
        self._primary_now_column.installEventFilter(self)

        self._list_title = QLabel(
            "Cue List (Shift/Ctrl to multi-select · Del to delete · click time to jump)"
        )
        self._list_title.setStyleSheet("font-weight: 600; color: #a1a1aa;")
        self._list_title.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list_title.customContextMenuRequested.connect(self._show_cue_list_context_menu)

        self._list_collapsed = _RevealLabel("▸ Cue List hidden — click to show")
        self._list_collapsed.clicked.connect(self._show_cue_list)
        self._list_collapsed.customContextMenuRequested.connect(self._show_cue_list_context_menu)

        self.cue_table = QTableWidget(0, _COL_COUNT)
        self.cue_table.setHorizontalHeaderLabels(
            [CUE_LIST_FIELD_LABELS[field] for field in CUE_LIST_FIELDS]
        )
        self.cue_table.setItemDelegate(_PaddedItemDelegate(self.cue_table))
        self.cue_table.verticalHeader().setVisible(False)
        self.cue_table.verticalHeader().setDefaultSectionSize(_ROW_HEIGHT)
        self.cue_table.setShowGrid(False)
        self.cue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.cue_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.cue_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.cue_table.horizontalHeader()
        header.setSectionsMovable(True)
        header.setFirstSectionMovable(True)
        header.sectionMoved.connect(self._on_header_section_moved)
        self._apply_column_resize_modes()
        self.cue_table.setStyleSheet(
            "QTableWidget::item { padding: 8px 8px; }"
            "QTableWidget QLineEdit { padding: 4px 6px; min-height: 1.4em; }"
        )
        self.cue_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.cue_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.cue_table.customContextMenuRequested.connect(self._show_cue_list_context_menu)
        self.cue_table.cellClicked.connect(self._on_cell_clicked)
        self.cue_table.itemChanged.connect(self._on_item_changed)
        self.cue_table.itemSelectionChanged.connect(self._on_selection_changed)
        self.cue_table.installEventFilter(self)

        # Cue List block — lives in a body splitter under NOW so raising NOW
        # height compresses Cue List instead of painting over it.
        self._cue_list_block = QWidget()
        self._cue_list_block.setMinimumHeight(_CUE_LIST_BODY_MIN)
        self._cue_list_block.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        cue_list_layout = QVBoxLayout(self._cue_list_block)
        cue_list_layout.setContentsMargins(0, 0, 0, 0)
        cue_list_layout.setSpacing(6)
        cue_list_layout.addWidget(self._list_title)
        cue_list_layout.addWidget(self._list_collapsed)
        cue_list_layout.addWidget(self.cue_table, stretch=1)

        self._body_splitter = QSplitter(Qt.Orientation.Vertical)
        self._body_splitter.setObjectName("nowBodySplitter")
        self._body_splitter.setChildrenCollapsible(False)
        self._body_splitter.setHandleWidth(8)
        self._body_splitter.setOpaqueResize(True)
        self._body_splitter.setStyleSheet(
            "#nowBodySplitter::handle {"
            "  background: transparent;"
            "  border: none;"
            "  margin: 0;"
            "  padding: 0;"
            "}"
            "#nowBodySplitter::handle:hover {"
            "  background: rgba(74, 158, 255, 0.35);"
            "}"
        )
        self._body_splitter.addWidget(self._now_section)
        self._body_splitter.addWidget(self._cue_list_block)
        self._body_splitter.setStretchFactor(0, 0)
        self._body_splitter.setStretchFactor(1, 1)
        self._body_splitter.setSizes([240, 420])
        self._body_splitter.splitterMoved.connect(self._on_body_splitter_moved)
        body_handle = self._body_splitter.handle(1)
        body_handle.setCursor(Qt.CursorShape.SizeVerCursor)
        body_handle.setToolTip("Drag to resize Secondary vs Cue List")

        layout.addWidget(clock_frame)
        layout.addWidget(self._body_splitter, stretch=1)
        QTimer.singleShot(0, self.ensure_now_splitter_ready)

    def set_song(self, song: Song | None) -> None:
        self._song = song
        self._playhead_list_mark_id = None
        self._apply_column_order()
        self._apply_cue_list_column_visibility()
        self.refresh_list()
        self._apply_now_panel_visibility()
        self._apply_cue_list_visibility()
        self.set_position(self._position, getattr(song, "duration_seconds", 0.0) if song else 0.0)
        QTimer.singleShot(0, self.ensure_now_splitter_ready)

    def _col_for_field(self, field: str) -> int:
        return self._column_order.index(field)

    def _field_at_col(self, col: int) -> str:
        return self._column_order[col]

    def _time_col(self) -> int:
        return self._col_for_field("time")

    def _apply_column_resize_modes(self) -> None:
        header = self.cue_table.horizontalHeader()
        for field in self._column_order:
            col = self._col_for_field(field)
            if field == "note":
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
            else:
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

    def _apply_column_order(self, order: list[str] | None = None) -> None:
        if order is None:
            if self._song is not None:
                order = normalize_cue_list_column_order(self._song.cue_list_column_order)
            else:
                order = list(DEFAULT_CUE_LIST_COLUMN_ORDER)
        else:
            order = normalize_cue_list_column_order(order)
        self._column_order = order
        header = self.cue_table.horizontalHeader()
        self._reordering_header = True
        for visual_pos, field in enumerate(order):
            logical = LOGICAL_INDEX_BY_FIELD[field]
            current_visual = header.visualIndex(logical)
            if current_visual != visual_pos:
                header.moveSection(current_visual, visual_pos)
        self._apply_column_resize_modes()
        self._reordering_header = False
        self._apply_cue_list_column_visibility()

    def _on_header_section_moved(self, logical_index: int, old_visual: int, new_visual: int) -> None:
        del logical_index, old_visual, new_visual
        if self._reordering_header or self._song is None:
            return
        header = self.cue_table.horizontalHeader()
        order: list[str] = []
        for visual in range(_COL_COUNT):
            logical = header.logicalIndex(visual)
            order.append(CUE_LIST_FIELDS[logical])
        self._column_order = order
        self._song.cue_list_column_order = list(order)
        self._apply_column_resize_modes()
        self.cue_list_layout_changed.emit()

    def _mark_id_at_row(self, row: int) -> str | None:
        time_item = self.cue_table.item(row, self._time_col())
        if time_item is None:
            return None
        mark_id = time_item.data(Qt.ItemDataRole.UserRole)
        return str(mark_id) if mark_id else None

    def apply_now_display_settings(self) -> None:
        """Reload NOW lane slots after Display dialog changes."""
        self._secondary_cleared = False
        self._secondary_hold_mark_id = None
        self._secondary_clear_timer.stop()
        self._apply_now_panel_visibility()
        self._sync_current(force_now=True)

    def _apply_now_panel_visibility(self) -> None:
        if self._song is None:
            show_primary = True
            show_secondary = True
        else:
            show_primary = bool(self._song.now_primary_visible)
            show_secondary = bool(self._song.now_secondary_visible)
        self.primary_track.setVisible(show_primary)
        self.primary_cue.setVisible(show_primary)
        self._primary_now_column.setVisible(show_primary)
        self.secondary_track.setVisible(show_secondary)
        self._secondary_now_column.setVisible(show_secondary)
        if not show_secondary:
            self.secondary_cue.setVisible(False)
            self._secondary_clear_timer.stop()
        self._sync_now_splitter_visibility()

    def _on_now_splitter_moved(self, *_args) -> None:
        self._schedule_now_card_fit()
        # Redistribute inside the current panel only — never grow the window.
        self._fit_body_within_panel()
        self.now_layout_changed.emit()

    def _on_body_splitter_moved(self, *_args) -> None:
        # Body handle = Secondary vs Cue List (Primary height stays in below mode).
        if self._now_placement == "below" and self._secondary_now_column.isVisible():
            self._apply_below_body_to_secondary()
        else:
            self._fit_body_within_panel()
        self.now_layout_changed.emit()

    def _primary_col_min(self) -> int:
        # Constant floor only — do not follow card minimumHeight (that feedback
        # loop grows the main window off-screen when width wraps text).
        return _NOW_PRIMARY_COL_MIN

    def _secondary_col_min(self) -> int:
        return _NOW_SECONDARY_COL_MIN

    def _now_chrome_height(self) -> int:
        return _NOW_TITLE_CHROME

    def _body_total_height(self) -> int:
        if not hasattr(self, "_body_splitter"):
            return 0
        sizes = self._body_splitter.sizes()
        total = sum(sizes) if sizes else 0
        if total > 0:
            return total
        return max(0, self._body_splitter.height())

    def _below_now_floor(self, primary_h: int) -> int:
        handle = max(8, self._now_splitter.handleWidth())
        return (
            self._now_chrome_height()
            + max(primary_h, self._primary_col_min())
            + handle
            + self._secondary_col_min()
        )

    def _fit_body_within_panel(self) -> None:
        """Keep NOW/Cue List split inside the current panel height (no window grow)."""
        if not hasattr(self, "_body_splitter"):
            return
        sizes = self._body_splitter.sizes()
        if len(sizes) != 2:
            return
        total = self._body_total_height()
        if total <= 0:
            return
        max_now = max(40, total - max(40, _CUE_LIST_BODY_MIN // 2))
        preferred = min(self._now_content_min_height(), max_now)
        now_h = sizes[0]
        if now_h < preferred:
            now_h = preferred
        now_h = min(max(40, now_h), max_now)
        self._body_splitter.setSizes([now_h, max(0, total - now_h)])
        # Constant floor only — never content-driven window expansion.
        self._now_section.setMinimumHeight(_NOW_TITLE_CHROME + _NOW_PRIMARY_COL_MIN)

    def _apply_below_body_to_secondary(self) -> None:
        """
        When Secondary is below Primary, dragging NOW↔Cue List resizes Secondary
        (Primary stays) and squeezes Cue List — Secondary never disappears.
        All math stays inside the current body total (window cannot grow).
        """
        body = self._body_splitter.sizes()
        if len(body) != 2:
            return
        total = self._body_total_height()
        if total <= 0:
            return
        inner = self._now_splitter.sizes()
        primary = inner[0] if len(inner) == 2 else 180
        primary = max(self._primary_col_min(), min(primary, total))
        handle = max(8, self._now_splitter.handleWidth())
        sec_min = self._secondary_col_min()
        now_floor = self._below_now_floor(primary)

        # Ideal NOW height from the drag, clamped so Cue List keeps a sliver
        # and Secondary keeps its floor — never increase `total`.
        max_now = max(sec_min + self._now_chrome_height(), total - max(40, _CUE_LIST_BODY_MIN // 2))
        now_h = min(max(body[0], min(now_floor, max_now)), max_now)
        if now_h < now_floor and now_floor <= max_now:
            now_h = now_floor
        # If the panel is too short for full floors, shrink Primary so Secondary lives.
        avail = max(0, now_h - self._now_chrome_height())
        if primary + handle + sec_min > avail:
            primary = max(40, avail - handle - sec_min)
        secondary = max(sec_min, avail - primary - handle)
        if primary + handle + secondary > avail:
            secondary = max(sec_min, avail - primary - handle)
            primary = max(40, avail - handle - secondary)

        cue_h = max(0, total - now_h)
        self._body_splitter.setSizes([now_h, cue_h])
        self._now_splitter.setStretchFactor(0, 0)
        self._now_splitter.setStretchFactor(1, 0)
        self._now_splitter.setMinimumHeight(0)
        self._now_splitter.setMaximumHeight(16777215)
        self._now_splitter.setSizes([max(1, primary), max(1, secondary)])
        self._now_section.setMinimumHeight(_NOW_TITLE_CHROME + _NOW_PRIMARY_COL_MIN)

    def now_secondary_placement(self) -> str:
        return self._now_placement

    def set_now_secondary_placement(self, placement: str, *, emit: bool = True) -> None:
        if placement not in ("right", "below"):
            return
        if placement == self._now_placement and self._now_splitter.orientation() == (
            Qt.Orientation.Horizontal if placement == "right" else Qt.Orientation.Vertical
        ):
            return
        self._stash_current_splitter_state()
        self._now_placement = placement
        self._apply_now_placement()
        if emit:
            self.now_layout_changed.emit()

    def _stash_current_splitter_state(self) -> None:
        state = QByteArray(self._now_splitter.saveState())
        if self._now_placement == "below":
            self._splitter_state_below = state
        else:
            self._splitter_state_right = state
        if hasattr(self, "_body_splitter"):
            self._body_splitter_state = QByteArray(self._body_splitter.saveState())

    def _apply_now_placement(self) -> None:
        # Clear any leftover fixed-height pin from older builds.
        self._now_splitter.setMinimumHeight(0)
        self._now_splitter.setMaximumHeight(16777215)
        if self._now_placement == "below":
            self._now_splitter.setOrientation(Qt.Orientation.Vertical)
            self._now_splitter.setStretchFactor(0, 0)
            self._now_splitter.setStretchFactor(1, 0)
            stashed = self._splitter_state_below
            default_sizes = [180, 88]
        else:
            self._now_splitter.setOrientation(Qt.Orientation.Horizontal)
            self._now_splitter.setStretchFactor(0, 3)
            self._now_splitter.setStretchFactor(1, 1)
            stashed = self._splitter_state_right
            default_sizes = [260, 100]
        restored = False
        if stashed is not None and len(stashed) > 0:
            restored = bool(self._now_splitter.restoreState(stashed))
        if not restored:
            self._now_splitter.setSizes(default_sizes)
        if self._now_placement == "below":
            self._now_splitter.setStretchFactor(0, 0)
            self._now_splitter.setStretchFactor(1, 0)
            sizes = self._now_splitter.sizes()
            if len(sizes) == 2 and sizes[1] < self._secondary_col_min():
                primary = max(self._primary_col_min(), sizes[0])
                self._now_splitter.setSizes([primary, self._secondary_col_min()])
        else:
            self._now_splitter.setStretchFactor(0, 3)
            self._now_splitter.setStretchFactor(1, 1)
        self._sync_now_splitter_visibility()
        self._refresh_splitter_handles()
        self._schedule_now_card_fit()
        if self._now_placement == "below" and self._secondary_now_column.isVisible():
            self._apply_below_body_to_secondary()
        else:
            self._fit_body_within_panel()
    def _sync_now_splitter_visibility(self) -> None:
        show_secondary = self._secondary_now_column.isVisible()
        handle = self._now_splitter.handle(1)
        below = self._now_placement == "below"
        handle.setCursor(
            Qt.CursorShape.SizeVerCursor if below else Qt.CursorShape.SizeHorCursor
        )
        handle.setToolTip(
            "Drag to resize Secondary height"
            if below
            else "Drag to resize Secondary width"
        )
        if show_secondary:
            handle.setEnabled(True)
            sizes = self._now_splitter.sizes()
            if below:
                total = max(sum(sizes), self._now_splitter.height(), 220)
                if len(sizes) != 2 or sizes[1] < 36:
                    self._now_splitter.setSizes([int(total * 0.68), int(total * 0.32)])
            else:
                total = max(sum(sizes), self._now_splitter.width(), 320)
                if len(sizes) != 2 or sizes[1] < 40:
                    self._now_splitter.setSizes([int(total * 0.72), int(total * 0.28)])
        else:
            handle.setEnabled(False)
            if below:
                total = max(self._now_splitter.height(), sum(self._now_splitter.sizes()), 1)
            else:
                total = max(self._now_splitter.width(), sum(self._now_splitter.sizes()), 1)
            self._now_splitter.setSizes([total, 0])

    def _refresh_splitter_handles(self) -> None:
        """Re-enable drag handles after first layout / session restore."""
        for splitter in (self._now_splitter, getattr(self, "_body_splitter", None)):
            if splitter is None:
                continue
            splitter.setEnabled(True)
            splitter.setOpaqueResize(True)
            handle = splitter.handle(1)
            handle.setEnabled(True)
            handle.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            handle.raise_()
        # Secondary-hidden: only the Primary↔Secondary handle should stay disabled.
        if not self._secondary_now_column.isVisible():
            self._now_splitter.handle(1).setEnabled(False)

    def ensure_now_splitter_ready(self) -> None:
        """Fix handles after startup layout restore (before first song switch)."""
        if not hasattr(self, "_now_splitter"):
            return
        self._apply_now_placement()
        if (
            hasattr(self, "_body_splitter")
            and self._body_splitter_state is not None
            and len(self._body_splitter_state) > 0
        ):
            self._body_splitter.restoreState(self._body_splitter_state)
        self._refresh_splitter_handles()
        self._fit_body_within_panel()
        # Second pass after sizes settle (common cold-start failure mode).
        QTimer.singleShot(50, self._refresh_splitter_handles)
        QTimer.singleShot(150, self._refresh_splitter_handles)

    def showEvent(self, event) -> None:  # noqa: ANN001, N802
        super().showEvent(event)
        QTimer.singleShot(0, self.ensure_now_splitter_ready)

    def save_now_splitter_state(self):
        self._stash_current_splitter_state()
        return {
            "placement": self._now_placement,
            "right": bytes(self._splitter_state_right or b""),
            "below": bytes(self._splitter_state_below or b""),
            "current": bytes(self._now_splitter.saveState()),
            "body": bytes(self._body_splitter_state or self._body_splitter.saveState()),
        }

    def restore_now_splitter_state(self, raw) -> None:
        placement = "right"
        if isinstance(raw, dict):
            placement = str(raw.get("placement") or "right")
            right = raw.get("right")
            below = raw.get("below")
            body = raw.get("body")
            if isinstance(right, (bytes, bytearray, QByteArray)) and len(right) > 0:
                self._splitter_state_right = QByteArray(right)
            if isinstance(below, (bytes, bytearray, QByteArray)) and len(below) > 0:
                self._splitter_state_below = QByteArray(below)
            if isinstance(body, (bytes, bytearray, QByteArray)) and len(body) > 0:
                self._body_splitter_state = QByteArray(body)
            current = raw.get("current")
            if isinstance(current, (bytes, bytearray, QByteArray)) and len(current) > 0:
                if placement == "below":
                    self._splitter_state_below = QByteArray(current)
                else:
                    self._splitter_state_right = QByteArray(current)
        elif isinstance(raw, (bytes, bytearray, QByteArray)) and len(raw) > 0:
            # Legacy single-state restore (horizontal only).
            self._splitter_state_right = QByteArray(raw)
            placement = "right"
        self._now_placement = placement if placement in ("right", "below") else "right"
        self._apply_now_placement()
        if (
            self._body_splitter_state is not None
            and len(self._body_splitter_state) > 0
        ):
            self._body_splitter.restoreState(self._body_splitter_state)
        QTimer.singleShot(0, self.ensure_now_splitter_ready)
        QTimer.singleShot(50, self.ensure_now_splitter_ready)

    def _schedule_now_card_fit(self) -> None:
        QTimer.singleShot(0, self._fit_now_cards)

    def _fit_now_cards(self) -> None:
        """Keep a modest card floor; never raise mins enough to grow the window."""
        below = self._now_placement == "below"
        floor = _NOW_CARD_MIN_H_BELOW if below else _NOW_CARD_MIN_H
        # Cap by currently allocated card height so width-wrap cannot inflate
        # minimumHeight and push the main window off-screen.
        for card in (self.primary_cue, self.secondary_cue):
            if not card.isVisible():
                card.setMinimumHeight(floor)
                continue
            allocated = card.height()
            cap = allocated if allocated > floor else floor
            width = max(40, card.width())
            natural = card.heightForWidth(width)
            if natural <= 0:
                natural = card.sizeHint().height()
            card.setMinimumHeight(min(max(floor, natural), cap))
        self._fit_body_within_panel()

    def _now_content_min_height(self) -> int:
        """Preferred NOW height from constant floors (not escalating card mins)."""
        title_h = _NOW_TITLE_CHROME
        track_h = 16
        gaps = 8
        if self._now_placement == "below" and self._secondary_now_column.isVisible():
            handle = max(8, self._now_splitter.handleWidth())
            return (
                title_h
                + gaps
                + self._primary_col_min()
                + handle
                + self._secondary_col_min()
            )
        return title_h + gaps + max(self._primary_col_min(), _NOW_CARD_MIN_H)

    def _apply_cue_list_visibility(self) -> None:
        visible = self._song is None or bool(self._song.cue_list_visible)
        self._list_title.setVisible(visible)
        self.cue_table.setVisible(visible)
        self._list_collapsed.setVisible(not visible)

    def _set_cue_list_visible(self, visible: bool) -> None:
        if self._song is None:
            return
        self._song.cue_list_visible = bool(visible)
        self._apply_cue_list_visibility()
        self.cue_list_visibility_changed.emit()

    def _show_cue_list(self) -> None:
        self._set_cue_list_visible(True)

    def _append_cue_list_menu_action(self, menu: QMenu) -> None:
        if self._song is None:
            return
        show_list = QAction("Show Cue List", self)
        show_list.setCheckable(True)
        show_list.setChecked(bool(self._song.cue_list_visible))
        show_list.toggled.connect(self._set_cue_list_visible)
        menu.addAction(show_list)

        show_cue_id = QAction("Show Cue ID", self)
        show_cue_id.setCheckable(True)
        show_cue_id.setChecked(bool(self._song.cue_list_show_cue_id))
        show_cue_id.setToolTip("Show or hide the Cue ID column in Cue List")
        show_cue_id.toggled.connect(self._set_cue_list_show_cue_id)
        menu.addAction(show_cue_id)

        menu.addSeparator()
        from cueplayer.domain.main_cue_id import renumberable_cue_list_lanes

        lanes = renumberable_cue_list_lanes(self._song)
        renumber_menu = menu.addMenu("Renumber Cue IDs (1, 2, 3…)")
        renumber_menu.setEnabled(bool(lanes))
        if lanes:
            all_action = renumber_menu.addAction("All Cue List types")
            all_action.triggered.connect(lambda: self.renumber_cue_ids_requested.emit(None))
            if len(lanes) > 1:
                renumber_menu.addSeparator()
                for lane in lanes:
                    lane_action = renumber_menu.addAction(lane.name)
                    lane_action.triggered.connect(
                        lambda _checked=False, lane_index=lane.index: self.renumber_cue_ids_requested.emit(
                            lane_index
                        )
                    )

    def _set_cue_list_show_cue_id(self, visible: bool) -> None:
        if self._song is None:
            return
        self._song.cue_list_show_cue_id = bool(visible)
        self._apply_cue_list_column_visibility()
        self.cue_list_layout_changed.emit()

    def _apply_cue_list_column_visibility(self) -> None:
        """Show/hide Cue List columns from song preferences."""
        show_cue_id = True if self._song is None else bool(self._song.cue_list_show_cue_id)
        cue_id_logical = LOGICAL_INDEX_BY_FIELD["cue_id"]
        self.cue_table.setColumnHidden(cue_id_logical, not show_cue_id)

    def eventFilter(self, obj, event) -> bool:  # noqa: ANN001, N802
        if (
            getattr(self, "cue_table", None) is obj
            and event.type() == QEvent.Type.KeyPress
        ):
            if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                if self.cue_table.state() != QAbstractItemView.State.EditingState:
                    ids = self.selected_mark_ids()
                    if ids:
                        self.delete_requested.emit(ids)
                        return True

        if obj in (self.secondary_track, self._secondary_now_column):
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._secondary_drag_origin = event.position().toPoint()
            elif event.type() == QEvent.Type.MouseMove and self._secondary_drag_origin is not None:
                if event.buttons() & Qt.MouseButton.LeftButton:
                    delta = event.position().toPoint() - self._secondary_drag_origin
                    if abs(delta.x()) + abs(delta.y()) >= 8:
                        self._start_secondary_drag()
                        self._secondary_drag_origin = None
                        return True
            elif event.type() in (
                QEvent.Type.MouseButtonRelease,
                QEvent.Type.MouseButtonDblClick,
            ):
                self._secondary_drag_origin = None

        drop_targets = (
            self._now_section,
            self._now_splitter,
            self._primary_now_column,
            self.primary_track,
            self.primary_cue,
        )
        if obj in drop_targets:
            if event.type() == QEvent.Type.DragEnter:
                if event.mimeData().hasFormat(_MIME_NOW_SECONDARY):
                    event.acceptProposedAction()
                    return True
            elif event.type() == QEvent.Type.DragMove:
                if event.mimeData().hasFormat(_MIME_NOW_SECONDARY):
                    event.acceptProposedAction()
                    return True
            elif event.type() == QEvent.Type.Drop:
                if event.mimeData().hasFormat(_MIME_NOW_SECONDARY):
                    placement = self._placement_from_drop(event.position().toPoint(), obj)
                    self.set_now_secondary_placement(placement)
                    event.acceptProposedAction()
                    return True
        return super().eventFilter(obj, event)

    def _start_secondary_drag(self) -> None:
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(_MIME_NOW_SECONDARY, b"1")
        drag.setMimeData(mime)
        self.secondary_track.setCursor(Qt.CursorShape.ClosedHandCursor)
        drag.exec(Qt.DropAction.MoveAction)
        self.secondary_track.setCursor(Qt.CursorShape.OpenHandCursor)

    def _placement_from_drop(self, local_pos: QPoint, source: QWidget) -> str:
        """Map drop position to right/below relative to the NOW area."""
        # Convert to now-section coordinates for a stable decision.
        if source is self._now_section:
            pos = local_pos
        else:
            pos = self._now_section.mapFrom(source, local_pos)
        rect = self._now_section.rect()
        if rect.height() <= 0 or rect.width() <= 0:
            return self._now_placement
        # Prefer below when dropping in the lower band; otherwise right.
        if pos.y() >= int(rect.height() * 0.55):
            return "below"
        if pos.x() >= int(rect.width() * 0.55):
            return "right"
        # Near primary: if more horizontal travel from center → right, else below.
        if abs(pos.x() - rect.width() / 2) > abs(pos.y() - rect.height() / 2):
            return "right"
        return "below"

    def _show_now_context_menu(self, pos) -> None:  # noqa: ANN001
        if self._song is None:
            return
        menu = QMenu(self)
        show_primary = QAction("Show Primary display", self)
        show_primary.setCheckable(True)
        show_primary.setChecked(bool(self._song.now_primary_visible))
        show_secondary = QAction("Show Secondary display", self)
        show_secondary.setCheckable(True)
        show_secondary.setChecked(bool(self._song.now_secondary_visible))

        def _toggle_primary(checked: bool) -> None:
            self._song.now_primary_visible = bool(checked)
            self._apply_now_panel_visibility()
            self._sync_current(force_now=True)
            self.now_visibility_changed.emit()

        def _toggle_secondary(checked: bool) -> None:
            self._song.now_secondary_visible = bool(checked)
            self._apply_now_panel_visibility()
            self._sync_current(force_now=True)
            self.now_visibility_changed.emit()

        show_primary.toggled.connect(_toggle_primary)
        show_secondary.toggled.connect(_toggle_secondary)
        menu.addAction(show_primary)
        menu.addAction(show_secondary)
        menu.addSeparator()
        place_right = QAction("Secondary on the right", self)
        place_right.setCheckable(True)
        place_right.setChecked(self._now_placement == "right")
        place_below = QAction("Secondary below", self)
        place_below.setCheckable(True)
        place_below.setChecked(self._now_placement == "below")
        place_right.triggered.connect(lambda: self.set_now_secondary_placement("right"))
        place_below.triggered.connect(lambda: self.set_now_secondary_placement("below"))
        menu.addAction(place_right)
        menu.addAction(place_below)
        menu.addSeparator()
        self._append_cue_list_menu_action(menu)
        sender = self.sender()
        if isinstance(sender, QWidget):
            menu.exec(sender.mapToGlobal(pos))
        else:
            menu.exec(self._now_section.mapToGlobal(pos))

    def _show_cue_list_context_menu(self, pos) -> None:  # noqa: ANN001
        if self._song is None:
            return
        menu = QMenu(self)
        self._append_cue_list_menu_action(menu)
        sender = self.sender()
        if isinstance(sender, QWidget):
            menu.exec(sender.mapToGlobal(pos))
        else:
            menu.exec(self.cue_table.viewport().mapToGlobal(pos))

    def _on_secondary_auto_clear(self) -> None:
        self._secondary_cleared = True
        self._show_secondary_empty()
        if self._secondary_hold_mark_id and self._secondary_hold_mark_id in self._current_mark_ids:
            self._current_mark_ids.discard(self._secondary_hold_mark_id)
            self._apply_now_highlight()

    def _show_secondary_empty(self) -> None:
        self.secondary_track.setText("SECONDARY")
        self.secondary_track.setStyleSheet("color: #a1a1aa; font-size: 11px; font-weight: 600;")
        self.secondary_cue.setText("—")
        self.secondary_cue.setStyleSheet(_now_card_style("#3f3f46", secondary=True))

    def refresh_list(self) -> None:
        selected = set(self.selected_mark_ids())
        self._updating_table = True
        self.cue_table.setRowCount(0)
        cue_ids = main_cue_id_map(self._song) if self._song is not None else {}
        time_col = self._time_col()
        type_col = self._col_for_field("type")
        cue_id_col = self._col_for_field("cue_id")
        note_col = self._col_for_field("note")
        if self._song is not None:
            for mark in self._song.marks:
                lane = self._song.lane_by_index(mark.lane_index)
                if lane is not None and not lane.visible:
                    continue
                if lane is not None and not lane.cue_list_enabled:
                    continue
                row = self.cue_table.rowCount()
                self.cue_table.insertRow(row)
                self.cue_table.setRowHeight(row, _ROW_HEIGHT)

                time_item = QTableWidgetItem(format_time(mark.time_seconds))
                time_item.setFlags(time_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                time_item.setData(Qt.ItemDataRole.UserRole, mark.id)
                self.cue_table.setItem(row, time_col, time_item)

                cue_id_text = cue_ids.get(mark.id, "")
                cue_id_item = QTableWidgetItem(cue_id_text)
                lane_has_id = lane is not None and lane.cue_id_enabled
                if lane_has_id:
                    cue_id_item.setFlags(
                        cue_id_item.flags()
                        | Qt.ItemFlag.ItemIsEditable
                        | Qt.ItemFlag.ItemIsSelectable
                        | Qt.ItemFlag.ItemIsEnabled
                    )
                    cue_id_item.setToolTip("Click to edit Cue ID")
                else:
                    cue_id_item.setFlags(cue_id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                cue_id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.cue_table.setItem(row, cue_id_col, cue_id_item)

                lane_name = lane.name if lane is not None else f"Type {mark.lane_index}"
                lane_item = QTableWidgetItem(lane_name)
                lane_item.setFlags(lane_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if lane is not None:
                    lane_item.setForeground(QColor(lane.color))
                self.cue_table.setItem(row, type_col, lane_item)

                note_item = QTableWidgetItem(mark.display_name)
                note_item.setFlags(
                    note_item.flags()
                    | Qt.ItemFlag.ItemIsEditable
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsEnabled
                )
                note_item.setToolTip("Click to type a Note directly (e.g. Verse / Chorus)")
                self.cue_table.setItem(row, note_col, note_item)
        self._updating_table = False
        self._apply_now_highlight()
        if selected:
            self.set_selected_mark_ids(selected)
        self._sync_current()

    def selected_mark_ids(self) -> list[str]:
        ids: list[str] = []
        for index in self.cue_table.selectionModel().selectedRows():
            mark_id = self._mark_id_at_row(index.row())
            if mark_id:
                ids.append(mark_id)
        return ids

    def set_selected_mark_ids(self, mark_ids: set[str] | list[str]) -> None:
        wanted = set(mark_ids)
        self._syncing_selection = True
        self.cue_table.clearSelection()
        model = self.cue_table.selectionModel()
        for row in range(self.cue_table.rowCount()):
            mark_id = self._mark_id_at_row(row)
            if mark_id in wanted:
                model.select(
                    self.cue_table.model().index(row, 0),
                    model.SelectionFlag.Select | model.SelectionFlag.Rows,
                )
        self._syncing_selection = False

    def set_position(self, seconds: float, duration: float | None = None) -> None:
        self._position = max(0.0, seconds)
        self.clock_label.setText(format_time(self._position))
        if duration is not None:
            self.duration_label.setText(f"/ {format_time(duration)}")
        self._sync_current()

    @property
    def show_output_timecode_clock(self) -> bool:
        return self._show_output_tc_clock

    def configure_output_timecode_clock(self, *, visible: bool, color: str) -> None:
        self._show_output_tc_clock = bool(visible)
        q = QColor(color or "#3dd68c")
        self._tc_clock_color = q.name() if q.isValid() else "#3dd68c"
        self._tc_output_block.setVisible(self._show_output_tc_clock)
        self._apply_output_timecode_style()

    def set_output_timecode(
        self,
        *,
        timecode: str,
        outputs: tuple[str, ...] | list[str],
        sending: bool,
    ) -> None:
        if not self._show_output_tc_clock:
            return
        outs = tuple(outputs)
        if outs:
            self.tc_output_status.setText(" · ".join(outs))
            active_color = self._tc_clock_color if sending else "#71717a"
            self.tc_output_status.setStyleSheet(
                f"color: {active_color}; background: transparent; font-size: 11px;"
                "font-weight: 600; letter-spacing: 0.5px;"
            )
            self.tc_output_value.setText(timecode)
            value_color = self._tc_clock_color if sending else "#a1a1aa"
            self.tc_output_value.setStyleSheet(
                f"color: {value_color}; background: transparent; font-size: 22px;"
                "font-weight: 700; font-family: Consolas, 'Cascadia Mono', monospace;"
            )
        else:
            self.tc_output_status.setText("TC off")
            self.tc_output_status.setStyleSheet(
                "color: #52525b; background: transparent; font-size: 11px;"
                "font-weight: 600; letter-spacing: 0.5px;"
            )
            self.tc_output_value.setText("—")
            self.tc_output_value.setStyleSheet(
                "color: #52525b; background: transparent; font-size: 22px;"
                "font-weight: 700; font-family: Consolas, 'Cascadia Mono', monospace;"
            )

    def _apply_output_timecode_style(self) -> None:
        self._tc_output_block.setVisible(self._show_output_tc_clock)

    def _show_clock_context_menu(self, pos) -> None:  # noqa: ANN001
        menu = QMenu(self)
        show_action = menu.addAction("Show output timecode clock")
        show_action.setCheckable(True)
        show_action.setChecked(self._show_output_tc_clock)
        show_action.setToolTip("LTC / MTC output timecode under the seconds display (Notes-only shows status, not SMPTE)")
        chosen = menu.exec(self._clock_frame.mapToGlobal(pos))
        if chosen is show_action:
            self._show_output_tc_clock = show_action.isChecked()
            self._tc_output_block.setVisible(self._show_output_tc_clock)
            self.output_timecode_clock_changed.emit()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            ids = self.selected_mark_ids()
            if ids:
                self.delete_requested.emit(ids)
                event.accept()
                return
        super().keyPressEvent(event)

    def _on_selection_changed(self) -> None:
        if self._updating_table or self._syncing_selection:
            return
        self.selection_changed.emit(self.selected_mark_ids())

    def _on_cell_clicked(self, row: int, column: int) -> None:
        if self._song is None:
            return
        modifiers = QApplication.keyboardModifiers()
        multi = bool(
            modifiers
            & (
                Qt.KeyboardModifier.ShiftModifier
                | Qt.KeyboardModifier.ControlModifier
                | Qt.KeyboardModifier.MetaModifier
            )
        )
        mark_id = self._mark_id_at_row(row)
        mark = self._song.mark_by_id(mark_id) if mark_id else None
        if mark is None:
            return
        field = self._field_at_col(column)
        if field in ("note", "cue_id"):
            if not multi:
                cell_item = self.cue_table.item(row, column)
                if cell_item is not None and cell_item.flags() & Qt.ItemFlag.ItemIsEditable:
                    self.cue_table.editItem(cell_item)
            return
        if not multi:
            self.seek_requested.emit(mark.time_seconds)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_table or self._song is None:
            return
        field = self._field_at_col(item.column())
        if field not in ("note", "cue_id"):
            return
        mark_id = self._mark_id_at_row(item.row())
        mark = self._song.mark_by_id(mark_id) if mark_id else None
        if mark is None:
            return
        if field == "note":
            self._apply_note_edit(item, mark)
        else:
            self._apply_cue_id_edit(item, mark)

    def _apply_note_edit(self, item: QTableWidgetItem, mark: Mark) -> None:
        old_name = mark.display_name
        new_name = item.text().strip()
        if item.text() != new_name:
            self._updating_table = True
            item.setText(new_name)
            self._updating_table = False
        if new_name == old_name:
            return
        mark.display_name = new_name
        self.note_changed.emit(str(mark.id), old_name, new_name)
        self._sync_current(force_now=True)

    def _apply_cue_id_edit(self, item: QTableWidgetItem, mark: Mark) -> None:
        old_id = mark.main_cue_id
        raw = item.text().strip()
        if not is_valid_main_cue_id_text(raw):
            self._updating_table = True
            item.setText(old_id)
            self._updating_table = False
            self.cue_id_edit_failed.emit("Cue ID must be a positive number")
            return
        new_id = normalize_main_cue_id_text(raw)
        if not main_cue_id_fits_order(self._song, mark.id, new_id):
            self._updating_table = True
            item.setText(old_id)
            self._updating_table = False
            if main_cue_id_taken(
                self._song,
                new_id,
                exclude_mark_id=mark.id,
                lane_index=mark.lane_index,
            ):
                self.cue_id_edit_failed.emit(f"Cue ID {new_id!r} is already used")
            else:
                self.cue_id_edit_failed.emit(main_cue_id_order_hint(self._song, mark.id))
            return
        if item.text() != new_id:
            self._updating_table = True
            item.setText(new_id)
            self._updating_table = False
        if new_id == old_id:
            return
        mark.main_cue_id = new_id
        self.cue_id_changed.emit(str(mark.id), old_id, new_id)

    def _apply_now_highlight(self) -> None:
        """Tint rows that are currently active in NOW slots."""
        clear = QColor(0, 0, 0, 0)
        for row in range(self.cue_table.rowCount()):
            mark_id = self._mark_id_at_row(row)
            is_now = mark_id in self._current_mark_ids
            bg = QColor("#243044") if is_now else clear
            if is_now and self._song is not None and mark_id:
                mark = self._song.mark_by_id(mark_id)
                lane = self._song.lane_by_index(mark.lane_index) if mark else None
                if lane is not None:
                    c = QColor(lane.color)
                    bg = QColor(c.red(), c.green(), c.blue(), 40)
            for col in range(_COL_COUNT):
                item = self.cue_table.item(row, col)
                if item is None:
                    continue
                item.setBackground(bg)

    def _fill_now_slot(
        self,
        *,
        track: QLabel,
        cue: QLabel,
        lane_indices: list[int],
        title: str,
        secondary: bool,
        active_ids: set[str],
    ) -> str | None:
        """Update one NOW card. Returns mark id to scroll to, if any."""
        if not lane_indices:
            track.hide()
            cue.hide()
            if secondary:
                self._secondary_clear_timer.stop()
                self._secondary_hold_mark_id = None
                self._secondary_cleared = False
            return None
        if secondary and self._song is not None and not self._song.now_secondary_visible:
            track.hide()
            cue.hide()
            return None
        if not secondary and self._song is not None and not self._song.now_primary_visible:
            track.hide()
            cue.hide()
            return None
        track.show()
        cue.show()
        assert self._song is not None
        active = self._song.active_mark_among_lanes(lane_indices, self._position)

        if secondary:
            clear_s = max(0.0, float(self._song.now_secondary_clear_seconds))
            if active is None:
                self._secondary_clear_timer.stop()
                self._secondary_hold_mark_id = None
                self._secondary_cleared = False
            elif active.id != self._secondary_hold_mark_id:
                self._secondary_hold_mark_id = active.id
                self._secondary_cleared = False
                if clear_s > 0:
                    self._secondary_clear_timer.start(int(round(clear_s * 1000)))
                else:
                    self._secondary_clear_timer.stop()
            if self._secondary_cleared:
                self._show_secondary_empty()
                return None

        if active is None:
            track.setText(title)
            track.setStyleSheet("color: #a1a1aa; font-size: 11px; font-weight: 600;")
            cue.setText("—")
            cue.setStyleSheet(_now_card_style("#3f3f46", secondary=secondary))
            return None

        lane = self._song.lane_by_index(active.lane_index)
        accent = lane.color if lane is not None else "#ff5a5f"
        lane_name = lane.name if lane is not None else title
        track.setText(f"{title} · {lane_name}")
        track.setStyleSheet(f"color: {accent}; font-size: 11px; font-weight: 600;")
        cue.setText(mark_now_body(self._song, active, show_cue_id=not secondary))
        cue.setStyleSheet(_now_card_style(accent, secondary=secondary))
        active_ids.add(active.id)
        return active.id

    def _sync_current(self, *, force_now: bool = False) -> None:
        del force_now
        if self._song is None:
            self._current_mark_ids = set()
            self.primary_track.setText("PRIMARY")
            self.primary_track.setStyleSheet("color: #a1a1aa; font-size: 11px; font-weight: 600;")
            self.primary_cue.setText("—")
            self.primary_cue.setStyleSheet(_now_card_style("#ff5a5f"))
            self._primary_now_column.show()
            self.secondary_track.hide()
            self.secondary_cue.hide()
            self._secondary_now_column.hide()
            self._sync_now_splitter_visibility()
            self._apply_now_highlight()
            self._schedule_now_card_fit()
            return

        primary, secondary = self._song.resolve_now_groups()
        active_ids: set[str] = set()
        scroll_id = self._fill_now_slot(
            track=self.primary_track,
            cue=self.primary_cue,
            lane_indices=primary,
            title="PRIMARY",
            secondary=False,
            active_ids=active_ids,
        )
        sec_id = self._fill_now_slot(
            track=self.secondary_track,
            cue=self.secondary_cue,
            lane_indices=secondary,
            title="SECONDARY",
            secondary=True,
            active_ids=active_ids,
        )
        if scroll_id is None:
            scroll_id = sec_id

        changed = active_ids != self._current_mark_ids
        self._current_mark_ids = active_ids
        self._apply_now_highlight()
        del changed, scroll_id
        self._schedule_now_card_fit()
        self._follow_cue_list_to_playhead()

    def _follow_cue_list_to_playhead(self) -> None:
        """Scroll/select the cue row for the current playhead (independent of NOW hold)."""
        if self._song is None:
            return
        mark = self._song.last_mark_at_or_before(self._position)
        if mark is None:
            return
        if mark.id == self._playhead_list_mark_id:
            return
        self._playhead_list_mark_id = mark.id
        self._select_mark_row(mark.id, scroll=True, emit_selection=True)

    def _select_mark_row(self, mark_id: str, *, scroll: bool, emit_selection: bool) -> None:
        self._syncing_selection = True
        self.cue_table.clearSelection()
        model = self.cue_table.selectionModel()
        time_col = self._time_col()
        for row in range(self.cue_table.rowCount()):
            if self._mark_id_at_row(row) != mark_id:
                continue
            model.select(
                self.cue_table.model().index(row, 0),
                model.SelectionFlag.Select | model.SelectionFlag.Rows,
            )
            if scroll:
                time_item = self.cue_table.item(row, time_col)
                if time_item is not None:
                    self.cue_table.scrollToItem(
                        time_item,
                        QAbstractItemView.ScrollHint.PositionAtCenter,
                    )
            break
        self._syncing_selection = False
        if emit_selection:
            self.selection_changed.emit([mark_id])
