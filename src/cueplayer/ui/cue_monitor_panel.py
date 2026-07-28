"""Right-side monitor: big clock, current cue(s), and scrolling cue list."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal, QEvent
from PySide6.QtGui import QAction, QColor, QFont, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHeaderView,
    QLabel,
    QMenu,
    QSizePolicy,
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


def _now_card_style(accent: str, *, secondary: bool = False) -> str:
    size = "18px" if secondary else "22px"
    min_h = "64px" if secondary else "84px"
    return (
        f"color: #e4e4e7; font-size: {size}; font-weight: 600;"
        f"padding: 14px 12px; line-height: 1.35;"
        f"background: #141416; border-radius: 6px; border-left: 5px solid {accent};"
        f"min-height: {min_h};"
    )


def mark_now_body(song: Song, mark: Mark, *, show_cue_id: bool = False) -> str:
    lines: list[str] = []
    if show_cue_id:
        main_index = song.main_lane_index()
        if main_index is not None and mark.lane_index == main_index:
            cue_id = mark.main_cue_id.strip()
            if cue_id:
                lines.append(f"Cue {cue_id}")
    lane = song.lane_by_index(mark.lane_index)
    lane_bit = lane.name if lane is not None else f"Type {mark.lane_index}"
    note = mark.display_name.strip()
    if note:
        lines.append(lane_bit)
        lines.append(note)
    elif not lines:
        lines.append(lane_bit)
    else:
        lines.append(lane_bit)
    return "\n".join(lines)


class CueMonitorPanel(QWidget):
    """Cue list: click Time/Type to seek; Note edits; Shift/Ctrl multi-select + Del."""

    seek_requested = Signal(float)
    delete_requested = Signal(list)  # list[str] mark ids
    selection_changed = Signal(list)  # list[str] mark ids
    note_changed = Signal(str, str, str)  # mark_id, old_name, new_name
    cue_id_changed = Signal(str, str, str)  # mark_id, old_id, new_id
    cue_id_edit_failed = Signal(str)  # user-facing reason
    cue_list_layout_changed = Signal()
    renumber_cue_ids_requested = Signal()
    now_visibility_changed = Signal()
    cue_list_visibility_changed = Signal()

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

        self.setMinimumWidth(280)
        self.setMaximumWidth(440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        clock_frame = QFrame()
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

        now_title = QLabel("NOW")
        now_title.setStyleSheet("color: #a1a1aa; font-size: 11px; letter-spacing: 1px;")

        self.primary_track = QLabel("PRIMARY")
        self.primary_track.setStyleSheet("color: #a1a1aa; font-size: 11px; font-weight: 600;")
        self.primary_cue = QLabel("—")
        self.primary_cue.setWordWrap(True)
        self.primary_cue.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.primary_cue.setStyleSheet(_now_card_style("#ff5a5f"))

        self.secondary_track = QLabel("SECONDARY")
        self.secondary_track.setStyleSheet("color: #a1a1aa; font-size: 11px; font-weight: 600;")
        self.secondary_cue = QLabel("—")
        self.secondary_cue.setWordWrap(True)
        self.secondary_cue.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.secondary_cue.setStyleSheet(_now_card_style("#52525b", secondary=True))

        self._now_section = QWidget()
        now_layout = QVBoxLayout(self._now_section)
        now_layout.setContentsMargins(0, 0, 0, 0)
        now_layout.setSpacing(6)
        now_layout.addWidget(now_title)
        now_layout.addWidget(self.primary_track)
        now_layout.addWidget(self.primary_cue)
        now_layout.addWidget(self.secondary_track)
        now_layout.addWidget(self.secondary_cue)
        self._now_section.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._now_section.customContextMenuRequested.connect(self._show_now_context_menu)
        for widget in (
            now_title,
            self.primary_track,
            self.primary_cue,
            self.secondary_track,
            self.secondary_cue,
        ):
            widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            widget.customContextMenuRequested.connect(self._show_now_context_menu)

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

        layout.addWidget(clock_frame)
        layout.addWidget(self._now_section)
        layout.addWidget(self._list_title)
        layout.addWidget(self._list_collapsed)
        layout.addWidget(self.cue_table, stretch=1)

    def set_song(self, song: Song | None) -> None:
        self._song = song
        self._playhead_list_mark_id = None
        self._apply_column_order()
        self.refresh_list()
        self._apply_now_panel_visibility()
        self._apply_cue_list_visibility()
        self.set_position(self._position, getattr(song, "duration_seconds", 0.0) if song else 0.0)

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
        self.secondary_track.setVisible(show_secondary)
        if not show_secondary:
            self.secondary_cue.setVisible(False)
            self._secondary_clear_timer.stop()

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
        from cueplayer.domain.main_cue_id import capture_main_cue_ids

        renumber = QAction("Renumber Cue IDs (1, 2, 3…)", self)
        renumber.setEnabled(bool(capture_main_cue_ids(self._song)))
        renumber.triggered.connect(self.renumber_cue_ids_requested.emit)
        menu.addSeparator()
        menu.addAction(renumber)

    def eventFilter(self, obj, event) -> bool:  # noqa: ANN001, N802
        if obj is self.cue_table and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                if self.cue_table.state() != QAbstractItemView.State.EditingState:
                    ids = self.selected_mark_ids()
                    if ids:
                        self.delete_requested.emit(ids)
                        return True
        return super().eventFilter(obj, event)

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
        main_index = self._song.main_lane_index() if self._song is not None else None
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
                if main_index is not None and mark.lane_index == main_index:
                    cue_id_item.setFlags(
                        cue_id_item.flags()
                        | Qt.ItemFlag.ItemIsEditable
                        | Qt.ItemFlag.ItemIsSelectable
                        | Qt.ItemFlag.ItemIsEnabled
                    )
                    cue_id_item.setToolTip("Click to edit Cue ID (Main lane)")
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
            if main_cue_id_taken(self._song, new_id, exclude_mark_id=mark.id):
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
            self.secondary_track.hide()
            self.secondary_cue.hide()
            self._apply_now_highlight()
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
