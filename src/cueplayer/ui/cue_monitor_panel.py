"""Right-side monitor: big clock, current cue(s), and scrolling cue list."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHeaderView,
    QLabel,
    QMenu,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cueplayer.domain.models import Mark, Song
from cueplayer.ui.transport_bar import format_time

_COL_TIME = 0
_COL_LANE = 1
_COL_NOTE = 2


def mark_now_text(song: Song, mark: Mark) -> str:
    note = mark.display_name.strip()
    if note:
        return note
    lane = song.lane_by_index(mark.lane_index)
    return lane.name if lane is not None else f"Mark {mark.lane_index}"


def _now_card_style(accent: str, *, secondary: bool = False) -> str:
    size = "18px" if secondary else "22px"
    min_h = "56px" if secondary else "72px"
    return (
        f"color: #e4e4e7; font-size: {size}; font-weight: 600; padding: 10px 12px;"
        f"background: #141416; border-radius: 6px; border-left: 5px solid {accent};"
        f"min-height: {min_h};"
    )


def mark_now_body(song: Song, mark: Mark) -> str:
    lane = song.lane_by_index(mark.lane_index)
    lane_bit = lane.name if lane is not None else f"Mark {mark.lane_index}"
    note = mark.display_name.strip()
    if note:
        return f"{note}\n{lane_bit}"
    return lane_bit



class CueMonitorPanel(QWidget):
    """Cue list: click Time/Mark to seek; Note edits; Shift/Ctrl multi-select + Del."""

    seek_requested = Signal(float)
    delete_requested = Signal(list)  # list[str] mark ids
    selection_changed = Signal(list)  # list[str] mark ids
    note_changed = Signal(str, str, str)  # mark_id, old_name, new_name
    now_visibility_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._song: Song | None = None
        self._position = 0.0
        self._current_mark_ids: set[str] = set()
        self._updating_table = False
        self._syncing_selection = False
        self._secondary_hold_mark_id: str | None = None
        self._secondary_cleared = False
        self._secondary_clear_timer = QTimer(self)
        self._secondary_clear_timer.setSingleShot(True)
        self._secondary_clear_timer.timeout.connect(self._on_secondary_auto_clear)

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
        # Explicit px so the global QWidget font-size cannot shrink the clock.
        # background: transparent — avoid a darker strip vs the frame chrome.
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

        # Primary: one Main Sequence card. Secondary: all Buttons compressed into one card.
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

        list_title = QLabel("Cue List (Shift/Ctrl to multi-select · Del to delete · click time to jump)")
        list_title.setStyleSheet("font-weight: 600; color: #a1a1aa;")

        self.cue_table = QTableWidget(0, 3)
        self.cue_table.setHorizontalHeaderLabels(["Time", "Mark", "Note"])
        self.cue_table.verticalHeader().setVisible(False)
        self.cue_table.setShowGrid(False)
        self.cue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.cue_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.cue_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.cue_table.horizontalHeader().setSectionResizeMode(_COL_TIME, QHeaderView.ResizeMode.ResizeToContents)
        self.cue_table.horizontalHeader().setSectionResizeMode(_COL_LANE, QHeaderView.ResizeMode.ResizeToContents)
        self.cue_table.horizontalHeader().setSectionResizeMode(_COL_NOTE, QHeaderView.ResizeMode.Stretch)
        self.cue_table.setStyleSheet("QTableWidget::item { padding: 6px 8px; }")
        self.cue_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.cue_table.cellClicked.connect(self._on_cell_clicked)
        self.cue_table.itemChanged.connect(self._on_item_changed)
        self.cue_table.itemSelectionChanged.connect(self._on_selection_changed)

        layout.addWidget(clock_frame)
        layout.addWidget(self._now_section)
        layout.addWidget(list_title)
        layout.addWidget(self.cue_table, stretch=1)

    def set_song(self, song: Song | None) -> None:
        self._song = song
        self.refresh_list()
        self._apply_now_panel_visibility()
        self.set_position(self._position, getattr(song, "duration_seconds", 0.0) if song else 0.0)

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
        sender = self.sender()
        if isinstance(sender, QWidget):
            menu.exec(sender.mapToGlobal(pos))
        else:
            menu.exec(self._now_section.mapToGlobal(pos))

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
        if self._song is not None:
            for mark in self._song.marks:
                lane = self._song.lane_by_index(mark.lane_index)
                if lane is not None and not lane.visible:
                    continue
                row = self.cue_table.rowCount()
                self.cue_table.insertRow(row)

                time_item = QTableWidgetItem(format_time(mark.time_seconds))
                time_item.setFlags(time_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                time_item.setData(Qt.ItemDataRole.UserRole, mark.id)
                self.cue_table.setItem(row, _COL_TIME, time_item)

                lane_name = lane.name if lane is not None else f"Mark {mark.lane_index}"
                lane_item = QTableWidgetItem(lane_name)
                lane_item.setFlags(lane_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if lane is not None:
                    lane_item.setForeground(QColor(lane.color))
                self.cue_table.setItem(row, _COL_LANE, lane_item)

                note_item = QTableWidgetItem(mark.display_name)
                note_item.setFlags(
                    note_item.flags()
                    | Qt.ItemFlag.ItemIsEditable
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsEnabled
                )
                note_item.setToolTip("Click to type a Note directly (e.g. Verse / Chorus)")
                self.cue_table.setItem(row, _COL_NOTE, note_item)
        self._updating_table = False
        self._apply_now_highlight()
        if selected:
            self.set_selected_mark_ids(selected)
        self._sync_current()

    def selected_mark_ids(self) -> list[str]:
        ids: list[str] = []
        for index in self.cue_table.selectionModel().selectedRows():
            item = self.cue_table.item(index.row(), _COL_TIME)
            if item is None:
                continue
            mark_id = item.data(Qt.ItemDataRole.UserRole)
            if mark_id:
                ids.append(str(mark_id))
        return ids

    def set_selected_mark_ids(self, mark_ids: set[str] | list[str]) -> None:
        wanted = set(mark_ids)
        self._syncing_selection = True
        self.cue_table.clearSelection()
        model = self.cue_table.selectionModel()
        for row in range(self.cue_table.rowCount()):
            item = self.cue_table.item(row, _COL_TIME)
            if item is None:
                continue
            if item.data(Qt.ItemDataRole.UserRole) in wanted:
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
        time_item = self.cue_table.item(row, _COL_TIME)
        if time_item is None:
            return
        mark_id = time_item.data(Qt.ItemDataRole.UserRole)
        mark = self._song.mark_by_id(str(mark_id)) if mark_id else None
        if mark is None:
            return
        if column == _COL_NOTE:
            if not multi:
                note_item = self.cue_table.item(row, _COL_NOTE)
                if note_item is not None:
                    self.cue_table.editItem(note_item)
            return
        if not multi:
            self.seek_requested.emit(mark.time_seconds)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_table or self._song is None:
            return
        if item.column() != _COL_NOTE:
            return
        time_item = self.cue_table.item(item.row(), _COL_TIME)
        if time_item is None:
            return
        mark_id = time_item.data(Qt.ItemDataRole.UserRole)
        mark = self._song.mark_by_id(str(mark_id)) if mark_id else None
        if mark is None:
            return
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

    def _apply_now_highlight(self) -> None:
        """Tint rows that are currently active in NOW slots."""
        clear = QColor(0, 0, 0, 0)
        for row in range(self.cue_table.rowCount()):
            time_item = self.cue_table.item(row, _COL_TIME)
            mark_id = time_item.data(Qt.ItemDataRole.UserRole) if time_item else None
            is_now = mark_id in self._current_mark_ids
            bg = QColor("#243044") if is_now else clear
            if is_now and self._song is not None and mark_id:
                mark = self._song.mark_by_id(str(mark_id))
                lane = self._song.lane_by_index(mark.lane_index) if mark else None
                if lane is not None:
                    c = QColor(lane.color)
                    bg = QColor(c.red(), c.green(), c.blue(), 40)
            for col in range(3):
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
        cue.setText(mark_now_body(self._song, active))
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
        if changed and scroll_id is not None:
            for row in range(self.cue_table.rowCount()):
                time_item = self.cue_table.item(row, _COL_TIME)
                if time_item is None:
                    continue
                if time_item.data(Qt.ItemDataRole.UserRole) == scroll_id:
                    self.cue_table.scrollToItem(
                        time_item,
                        QAbstractItemView.ScrollHint.PositionAtCenter,
                    )
                    break
