"""Mark Manager: names, colors, shortcuts, shapes, visibility; add/remove marks."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cueplayer.domain.models import MARKER_SHAPE_LABELS, MarkLane, Project, Song
from cueplayer.persistence.mark_template import (
    apply_lanes_to_song,
    build_template,
    clone_lanes,
    dicts_to_lanes,
    load_mark_template,
    save_mark_template,
)
from cueplayer.playback.midi_cue_notes import default_note_for_lane
from cueplayer.ui.color_presets import (
    BUILTIN_PRESETS,
    add_user_preset,
    all_presets,
    get_color,
    remove_user_preset,
)
from cueplayer.ui.spinboxes import NoWheelComboBox
from cueplayer.ui.marker_draw import draw_marker_shape

_COL_INDEX = 0
_COL_NAME = 1
_COL_KEY = 2
_COL_SHAPE = 3
_COL_COLOR = 4
_COL_VISIBLE = 5
_COL_CUE_LIST = 6
_COL_CUE_ID = 7
_COL_MIDI = 8
_COL_MIDI_NOTE = 9
_COL_PAUSE = 10
_COL_ASK_NOTE = 11
_COL_WAVE_NOTE = 12
_COL_WAVE_CUE = 13
_COL_NOW = 14
_COL_COUNT = 15

_HEADER_LABELS = (
    "#",
    "Name",
    "Shortcut",
    "Shape",
    "Color",
    "Visible",
    "Cue List",
    "Cue ID",
    "MIDI On",
    "Note",
    "Pause",
    "Ask Note",
    "Wave Note",
    "Wave Cue",
    "NOW",
)

# Floors so headers and combo text (Secondary / auto (36)) are not clipped.
_COLUMN_MIN_WIDTHS = {
    _COL_INDEX: 44,
    _COL_NAME: 140,
    _COL_KEY: 80,
    _COL_SHAPE: 140,
    _COL_COLOR: 72,
    _COL_VISIBLE: 78,
    _COL_CUE_LIST: 86,
    _COL_CUE_ID: 78,
    _COL_MIDI: 82,
    _COL_MIDI_NOTE: 128,
    _COL_PAUSE: 72,
    _COL_ASK_NOTE: 96,
    _COL_WAVE_NOTE: 104,
    _COL_WAVE_CUE: 100,
    _COL_NOW: 128,
}

# Extra room for combo arrow + padding when sizing from sample cell text.
_COMBO_CELL_SAMPLES = {
    _COL_SHAPE: "Triangle ▲",
    _COL_MIDI_NOTE: "auto (127)",
    _COL_NOW: "Secondary",
}
_COMBO_CHROME_PX = 36

_TABLE_COMBO_QSS = (
    "QComboBox {"
    "  padding: 2px 6px;"
    "  min-height: 1.2em;"
    "}"
)


def _style_table_combo(combo: QComboBox) -> None:
    combo.setStyleSheet(_TABLE_COMBO_QSS)


class ShapePreview(QWidget):
    """Live preview of the currently selected Mark shape / color."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(72)
        self.setMinimumWidth(220)
        self._shape = "circle"
        self._color = QColor("#E74C3C")
        self._name = "Preview"
        self.setStyleSheet("background: #14161c; border: 1px solid #2a2f3a; border-radius: 6px;")

    def set_preview(self, *, shape: str, color: str, name: str) -> None:
        self._shape = shape or "circle"
        self._color = QColor(color)
        self._name = name or "Preview"
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ANN001
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#14161c"))
        painter.setPen(QColor("#8b949e"))
        painter.drawText(12, 22, f"Shape preview · {self._name}")
        mid_y = self.height() * 0.62
        painter.setPen(self._color)
        painter.drawLine(24, int(mid_y), self.width() - 24, int(mid_y))
        draw_marker_shape(painter, self.width() * 0.5, mid_y, self._color, self._shape, size=12)


class ColorPickPopup(QFrame):
    color_chosen = Signal(str)

    def __init__(self, current: str, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setStyleSheet(
            "ColorPickPopup {"
            "  background: #181b22;"
            "  border: 1px solid #3a4152;"
            "  border-radius: 8px;"
            "}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        title = QLabel("Quick Color Pick")
        title.setStyleSheet("color: #8b949e;")
        layout.addWidget(title)
        self._grid = QGridLayout()
        self._grid.setSpacing(6)
        layout.addLayout(self._grid)
        self._rebuild_grid(current)

        row = QHBoxLayout()
        custom = QPushButton("Custom Color…")
        custom.setToolTip("Open the full color dialog (custom slots are remembered)")
        custom.clicked.connect(self._custom)
        add_btn = QPushButton("Add to Presets…")
        add_btn.setToolTip("Pick a color and save it here for next time")
        add_btn.clicked.connect(self._add_preset)
        row.addWidget(custom)
        row.addWidget(add_btn)
        layout.addLayout(row)
        self._current = current

    def _rebuild_grid(self, current: str) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for i, hex_color in enumerate(all_presets()):
            btn = QPushButton()
            btn.setFixedSize(28, 28)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(hex_color)
            selected = hex_color.upper() == QColor(current).name().upper()
            border = "2px solid #ffffff" if selected else "1px solid #111"
            btn.setStyleSheet(
                f"QPushButton {{ background: {hex_color}; border: {border}; border-radius: 4px; }}"
                f"QPushButton:hover {{ border: 2px solid #ffffff; }}"
            )
            btn.clicked.connect(lambda _=False, c=hex_color: self._pick(c))
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda _pos, c=hex_color: self._maybe_remove_preset(c)
            )
            self._grid.addWidget(btn, i // 4, i % 4)

    def _pick(self, color: str) -> None:
        self.color_chosen.emit(color)
        self.close()

    def _custom(self) -> None:
        chosen = get_color(QColor(self._current), self, "Custom Mark Color")
        if chosen.isValid():
            self.color_chosen.emit(chosen.name())
        self.close()

    def _add_preset(self) -> None:
        chosen = get_color(QColor(self._current), self, "Add Color Preset")
        if not chosen.isValid():
            return
        add_user_preset(chosen.name())
        self._rebuild_grid(chosen.name())
        self._current = chosen.name()

    def _maybe_remove_preset(self, color: str) -> None:
        from cueplayer.ui.color_presets import BUILTIN_PRESETS, load_user_presets

        if color.lower() not in {c.lower() for c in load_user_presets()}:
            return
        if color.lower() in {c.lower() for c in BUILTIN_PRESETS}:
            return
        remove_user_preset(color)
        self._rebuild_grid(self._current)


class ColorSwatchButton(QPushButton):
    color_changed = Signal(str)

    def __init__(self, color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(52, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Click for preset colors, or choose a custom one (presets are saved)")
        self._color = "#4C8BF5"
        self.set_color(color)
        self.clicked.connect(self._open_picker)

    def color(self) -> str:
        return self._color

    def set_color(self, color: str) -> None:
        q = QColor(color)
        self._color = q.name() if q.isValid() else "#4C8BF5"
        self.setStyleSheet(
            f"QPushButton {{ background: {self._color}; border: 1px solid #2a2f3a; border-radius: 4px; }}"
            f"QPushButton:hover {{ border: 1px solid #ffffff; }}"
        )
        self.setText("")

    def _open_picker(self) -> None:
        popup = ColorPickPopup(self._color, self)
        popup.color_chosen.connect(self._on_chosen)
        popup.move(self.mapToGlobal(self.rect().bottomLeft()))
        popup.show()

    def _on_chosen(self, color: str) -> None:
        self.set_color(color)
        self.color_changed.emit(self._color)


class ApplyMarkSettingsDialog(QDialog):
    """Choose how to apply a loaded mark template (stacked buttons so labels stay readable)."""

    CURRENT = "current"
    ALL = "all"
    DEFAULT = "default"

    def __init__(self, mark_count: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Apply Mark Settings")
        self.resize(400, 280)
        self._choice: str | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        body = QLabel(
            f"Loaded {mark_count} Mark(s).\n\n"
            '"All Songs" will rewrite the Mark definitions for every song in the project '
            "(marks with no matching lane will be removed)."
        )
        body.setWordWrap(True)
        layout.addWidget(body)

        for key, label in (
            (self.CURRENT, "Current Song"),
            (self.ALL, "All Songs + Default"),
            (self.DEFAULT, "Set as Default Only"),
        ):
            btn = QPushButton(label)
            btn.setMinimumHeight(40)
            btn.clicked.connect(lambda _checked=False, k=key: self._pick(k))
            layout.addWidget(btn)

        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel)

    def _pick(self, key: str) -> None:
        self._choice = key
        self.accept()

    def choice(self) -> str | None:
        return self._choice


class MarkManagerDialog(QDialog):
    """Edits mark tracks. Shape/color changes preview live."""

    preview_changed = Signal()
    project_defaults_changed = Signal()

    def __init__(
        self,
        song: Song,
        parent: QWidget | None = None,
        *,
        project: Project | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Mark Manager")
        # Wide enough for every header + combos without squeezing columns.
        total_cols = sum(_COLUMN_MIN_WIDTHS.values()) + 48
        self.setMinimumWidth(max(1280, total_cols))
        self.resize(max(1480, total_cols + 40), 580)
        self._song = song
        self._project = project
        self._suppress_key_prompt = False
        self._lane_snapshot = deepcopy(song.mark_lanes)
        self._now_snapshot = (
            list(song.now_primary_lanes),
            list(song.now_secondary_lanes),
            bool(song.now_lanes_configured),
        )

        layout = QVBoxLayout(self)
        hint = QLabel(
            "Set the name, shortcut, shape, color, and NOW display (Off / Primary / Secondary) for each Mark. "
            "MIDI On + Note (auto or 1–127) control which note is sent when playback crosses marks. "
            "Pause stops playback when you place a mark of that type; Ask Note opens a Note dialog after placing; "
            "Wave Note / Wave Cue show the Note or Cue ID next to the mark line on the waveform. "
            'Use "Save Settings" to write a file you can later load and apply to a song or as the show default. '
            "Scroll horizontally if needed — columns keep their full labels."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8b949e;")
        layout.addWidget(hint)

        self.preview = ShapePreview()
        layout.addWidget(self.preview)

        self.table = QTableWidget(0, _COL_COUNT)
        self.table.setHorizontalHeaderLabels(list(_HEADER_LABELS))
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(44)
        header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
        )
        header.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        layout.addWidget(self.table, stretch=1)

        self._syncing_bulk = False
        self._bulk_checks: dict[int, QCheckBox] = {}
        self._bulk_footer_row: int | None = None

        row_btns = QHBoxLayout()
        self.add_btn = QPushButton("Add Mark")
        self.remove_btn = QPushButton("Delete Selected")
        self.save_template_btn = QPushButton("Save Settings…")
        self.load_template_btn = QPushButton("Load Settings…")
        self.save_template_btn.setToolTip("Save the current Mark setup to a file (.cueplayer-marks.json)")
        self.load_template_btn.setToolTip("Load a settings file and apply it to the current song / all songs / project default")
        row_btns.addWidget(self.add_btn)
        row_btns.addWidget(self.remove_btn)
        row_btns.addStretch(1)
        row_btns.addWidget(self.save_template_btn)
        row_btns.addWidget(self.load_template_btn)
        layout.addLayout(row_btns)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self._reject_restore)
        layout.addWidget(buttons)

        self.add_btn.clicked.connect(self._add_row)
        self.remove_btn.clicked.connect(self._remove_row)
        self.save_template_btn.clicked.connect(self._save_template)
        self.load_template_btn.clicked.connect(self._load_template)
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        self._load_from_song()
        self._apply_column_widths()
        if self._lane_row_count() > 0:
            self.table.selectRow(0)
        self._refresh_preview()
        self._refresh_bulk_toggle_states()

    def _apply_column_widths(self) -> None:
        """Size columns so headers and typical combo text are not clipped."""
        header = self.table.horizontalHeader()
        metrics = self.table.fontMetrics()
        for col, label in enumerate(_HEADER_LABELS):
            text_w = metrics.horizontalAdvance(label) + 28
            sample = _COMBO_CELL_SAMPLES.get(col)
            cell_w = (
                metrics.horizontalAdvance(sample) + _COMBO_CHROME_PX if sample else 0
            )
            width = max(_COLUMN_MIN_WIDTHS[col], text_w, cell_w)
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
            self.table.setColumnWidth(col, width)

    def _lane_row_count(self) -> int:
        count = self.table.rowCount()
        if self._bulk_footer_row is not None and 0 <= self._bulk_footer_row < count:
            return count - 1
        return count

    def _is_bulk_footer_row(self, row: int) -> bool:
        return self._bulk_footer_row is not None and row == self._bulk_footer_row

    def _ensure_bulk_footer_row(self) -> None:
        """Bottom table row: all-on / all-off toggles aligned with their columns."""
        bulk_specs = {
            _COL_VISIBLE: "All on/off for Visible",
            _COL_CUE_LIST: "All on/off for Cue List",
            _COL_CUE_ID: "All on/off for Cue ID",
            _COL_MIDI: "All on/off for MIDI On",
            _COL_PAUSE: "All on/off for Pause on mark",
            _COL_ASK_NOTE: "All on/off for Ask Note after mark",
            _COL_WAVE_NOTE: "All on/off for Wave Note labels",
            _COL_WAVE_CUE: "All on/off for Wave Cue ID labels",
        }
        row = self.table.rowCount()
        if self._bulk_footer_row is None:
            self.table.insertRow(row)
            self._bulk_footer_row = row
        else:
            row = self._bulk_footer_row
        self.table.setRowHeight(row, 32)
        self.table.setRowHidden(row, False)
        for col in range(_COL_COUNT):
            self.table.removeCellWidget(row, col)
            if col in bulk_specs:
                box = self._bulk_checks.get(col)
                if box is None:
                    box = QCheckBox()
                    box.setTristate(True)
                    box.setToolTip(bulk_specs[col])
                    box.stateChanged.connect(lambda _state, c=col: self._on_bulk_toggle_changed(c))
                    self._bulk_checks[col] = box
                wrap = QWidget()
                wrap_layout = QHBoxLayout(wrap)
                wrap_layout.setContentsMargins(0, 0, 0, 0)
                wrap_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                wrap_layout.addWidget(box)
                self.table.setCellWidget(row, col, wrap)
            else:
                filler = QTableWidgetItem("")
                filler.setFlags(Qt.ItemFlag.NoItemFlags)
                filler.setBackground(QColor("#12151a"))
                self.table.setItem(row, col, filler)

    def _on_table_selection_changed(self) -> None:
        row = self._selected_row()
        if row < 0 and self.table.selectionModel().hasSelection():
            self.table.blockSignals(True)
            self.table.clearSelection()
            self.table.blockSignals(False)
        self._refresh_preview()

    def _checkbox_at(self, row: int, col: int) -> QCheckBox | None:
        wrap = self.table.cellWidget(row, col)
        if wrap is None:
            return None
        checkbox = wrap.property("checkbox")
        if isinstance(checkbox, QCheckBox):
            return checkbox
        found = wrap.findChild(QCheckBox)
        return found if isinstance(found, QCheckBox) else None

    def _refresh_bulk_toggle_states(self) -> None:
        if not self._bulk_checks:
            return
        self._syncing_bulk = True
        try:
            for col, bulk in self._bulk_checks.items():
                boxes = [
                    box
                    for row in range(self._lane_row_count())
                    if (box := self._checkbox_at(row, col)) is not None
                ]
                if not boxes:
                    bulk.setCheckState(Qt.CheckState.Unchecked)
                    continue
                checked = sum(1 for box in boxes if box.isChecked())
                if checked == len(boxes):
                    bulk.setCheckState(Qt.CheckState.Checked)
                elif checked == 0:
                    bulk.setCheckState(Qt.CheckState.Unchecked)
                else:
                    bulk.setCheckState(Qt.CheckState.PartiallyChecked)
        finally:
            self._syncing_bulk = False

    def _on_bulk_toggle_changed(self, col: int) -> None:
        if self._syncing_bulk:
            return
        bulk = self._bulk_checks.get(col)
        if bulk is None:
            return
        state = bulk.checkState()
        target = state != Qt.CheckState.Unchecked
        if state == Qt.CheckState.PartiallyChecked:
            target = True
        self._syncing_bulk = True
        try:
            for row in range(self._lane_row_count()):
                box = self._checkbox_at(row, col)
                if box is not None:
                    box.setChecked(target)
            bulk.setCheckState(
                Qt.CheckState.Checked if target else Qt.CheckState.Unchecked
            )
        finally:
            self._syncing_bulk = False

    def _connect_row_bulk_sync(self, *checkboxes: QCheckBox) -> None:
        for box in checkboxes:
            box.stateChanged.connect(self._refresh_bulk_toggle_states)

    def _reject_restore(self) -> None:
        self._song.mark_lanes = deepcopy(self._lane_snapshot)
        primary, secondary, configured = self._now_snapshot
        self._song.now_primary_lanes = list(primary)
        self._song.now_secondary_lanes = list(secondary)
        self._song.now_lanes_configured = bool(configured)
        self.preview_changed.emit()
        self.reject()

    def _now_role_for_index(self, lane_index: int) -> int:
        primary, secondary = self._song.configured_now_groups()
        if lane_index in primary:
            return 1
        if lane_index in secondary:
            return 2
        return 0

    def _collect_now_lanes(self) -> tuple[list[int], list[int]]:
        primary: list[int] = []
        secondary: list[int] = []
        for row in range(self._lane_row_count()):
            index_item = self.table.item(row, _COL_INDEX)
            combo = self.table.cellWidget(row, _COL_NOW)
            if index_item is None or not isinstance(combo, QComboBox):
                continue
            role = int(combo.currentData() or 0)
            lane_index = int(index_item.text())
            if role == 1:
                primary.append(lane_index)
            elif role == 2:
                secondary.append(lane_index)
        return primary, secondary

    def _apply_now_lanes_to_song(self) -> None:
        primary, secondary = self._collect_now_lanes()
        self._song.now_lanes_configured = True
        self._song.now_primary_lanes = primary
        self._song.now_secondary_lanes = secondary

    def _load_from_song(self) -> None:
        self.table.setRowCount(0)
        self._bulk_footer_row = None
        for lane in sorted(self._song.mark_lanes, key=lambda item: item.index):
            self._append_row(lane)
        self._ensure_bulk_footer_row()

    def _load_from_lanes(self, lanes: list[MarkLane]) -> None:
        self.table.setRowCount(0)
        self._bulk_footer_row = None
        for lane in sorted(lanes, key=lambda item: item.index):
            self._append_row(lane)
        self._ensure_bulk_footer_row()
        if self._lane_row_count() > 0:
            self.table.selectRow(0)
        self._refresh_preview()
        self.preview_changed.emit()

    def _collect_draft_lanes(self) -> list[MarkLane] | None:
        """Build MarkLane list from the table; None if invalid."""
        rows = self._lane_row_count()
        if rows == 0:
            QMessageBox.warning(self, "Mark Manager", "At least one Mark is required.")
            return None
        draft: list[MarkLane] = []
        used_keys: dict[str, int] = {}
        for row in range(rows):
            index_item = self.table.item(row, _COL_INDEX)
            name_edit = self._name_edit_at(row)
            key_widget = self.table.cellWidget(row, _COL_KEY)
            shape_widget = self.table.cellWidget(row, _COL_SHAPE)
            visible_wrap = self.table.cellWidget(row, _COL_VISIBLE)
            cue_id_wrap = self.table.cellWidget(row, _COL_CUE_ID)
            cue_list_wrap = self.table.cellWidget(row, _COL_CUE_LIST)
            midi_wrap = self.table.cellWidget(row, _COL_MIDI)
            midi_note_widget = self.table.cellWidget(row, _COL_MIDI_NOTE)
            pause_wrap = self.table.cellWidget(row, _COL_PAUSE)
            ask_note_wrap = self.table.cellWidget(row, _COL_ASK_NOTE)
            wave_note_wrap = self.table.cellWidget(row, _COL_WAVE_NOTE)
            wave_cue_wrap = self.table.cellWidget(row, _COL_WAVE_CUE)
            if not all(
                [
                    index_item,
                    name_edit,
                    key_widget,
                    shape_widget,
                    visible_wrap,
                    cue_id_wrap,
                    cue_list_wrap,
                    midi_wrap,
                    midi_note_widget,
                    pause_wrap,
                    ask_note_wrap,
                    wave_note_wrap,
                    wave_cue_wrap,
                ]
            ):
                QMessageBox.warning(self, "Mark Manager", f"Row {row + 1} has incomplete data.")
                return None
            assert isinstance(name_edit, QLineEdit)
            assert isinstance(key_widget, QComboBox)
            assert isinstance(shape_widget, QComboBox)
            checkbox = visible_wrap.property("checkbox")
            if not isinstance(checkbox, QCheckBox):
                checkbox = visible_wrap.findChild(QCheckBox)
            if checkbox is None:
                QMessageBox.warning(self, "Mark Manager", f"Row {row + 1} is missing its visibility toggle.")
                return None
            cue_list_box = cue_list_wrap.property("checkbox")
            if not isinstance(cue_list_box, QCheckBox):
                cue_list_box = cue_list_wrap.findChild(QCheckBox)
            if cue_list_box is None:
                QMessageBox.warning(self, "Mark Manager", f"Row {row + 1} is missing its Cue List toggle.")
                return None
            cue_id_box = cue_id_wrap.property("checkbox")
            if not isinstance(cue_id_box, QCheckBox):
                cue_id_box = cue_id_wrap.findChild(QCheckBox)
            if cue_id_box is None:
                QMessageBox.warning(self, "Mark Manager", f"Row {row + 1} is missing its Cue ID toggle.")
                return None
            midi_box = midi_wrap.property("checkbox")
            if not isinstance(midi_box, QCheckBox):
                midi_box = midi_wrap.findChild(QCheckBox)
            if midi_box is None:
                QMessageBox.warning(self, "Mark Manager", f"Row {row + 1} is missing its MIDI toggle.")
                return None
            pause_box = pause_wrap.property("checkbox")
            if not isinstance(pause_box, QCheckBox):
                pause_box = pause_wrap.findChild(QCheckBox)
            if pause_box is None:
                QMessageBox.warning(self, "Mark Manager", f"Row {row + 1} is missing its Pause toggle.")
                return None
            ask_note_box = ask_note_wrap.property("checkbox")
            if not isinstance(ask_note_box, QCheckBox):
                ask_note_box = ask_note_wrap.findChild(QCheckBox)
            if ask_note_box is None:
                QMessageBox.warning(self, "Mark Manager", f"Row {row + 1} is missing its Ask Note toggle.")
                return None
            wave_note_box = wave_note_wrap.property("checkbox")
            if not isinstance(wave_note_box, QCheckBox):
                wave_note_box = wave_note_wrap.findChild(QCheckBox)
            if wave_note_box is None:
                QMessageBox.warning(self, "Mark Manager", f"Row {row + 1} is missing its Wave Note toggle.")
                return None
            wave_cue_box = wave_cue_wrap.property("checkbox")
            if not isinstance(wave_cue_box, QCheckBox):
                wave_cue_box = wave_cue_wrap.findChild(QCheckBox)
            if wave_cue_box is None:
                QMessageBox.warning(self, "Mark Manager", f"Row {row + 1} is missing its Wave Cue toggle.")
                return None
            if not isinstance(midi_note_widget, NoWheelComboBox):
                QMessageBox.warning(self, "Mark Manager", f"Row {row + 1} is missing its MIDI note.")
                return None
            midi_note = self._midi_note_from_widget(midi_note_widget)
            if midi_note is None:
                QMessageBox.warning(
                    self,
                    "Mark Manager",
                    f"Row {row + 1}: enter auto or a MIDI note from 1 to 127.",
                )
                return None
            shortcut = str(key_widget.currentData() or "")
            if shortcut:
                if shortcut in used_keys:
                    QMessageBox.warning(self, "Mark Manager", f"Shortcut {shortcut} is used by more than one Mark.")
                    return None
                used_keys[shortcut] = row
            shape = str(shape_widget.currentData() or "circle")
            if shape not in MARKER_SHAPE_LABELS:
                shape = "circle"
            cue_id_enabled = cue_id_box.isChecked()
            lane_type = "main" if cue_id_enabled else "top_button"
            index = int(index_item.text())
            previous = self._song.lane_by_index(index)
            draft.append(
                MarkLane(
                    index=index,
                    name=name_edit.text().strip() or f"Mark {index}",
                    lane_type=lane_type,  # type: ignore[arg-type]
                    color=self._color_at(row),
                    shortcut=shortcut,
                    visible=checkbox.isChecked(),
                    locked=previous.locked if previous else False,
                    export_enabled=previous.export_enabled if previous else True,
                    cue_id_enabled=cue_id_enabled,
                    cue_list_enabled=cue_list_box.isChecked(),
                    midi_note_enabled=midi_box.isChecked(),
                    midi_note=midi_note,
                    pause_on_mark=pause_box.isChecked(),
                    prompt_note_on_mark=ask_note_box.isChecked(),
                    show_note_on_wave=wave_note_box.isChecked(),
                    show_cue_id_on_wave=wave_cue_box.isChecked(),
                    marker_shape=shape,  # type: ignore[arg-type]
                    show_row_color=previous.show_row_color if previous else True,
                )
            )
        return sorted(draft, key=lambda lane: lane.index)

    def _template_filter(self) -> str:
        return "CuePlayer Mark Settings (*.cueplayer-marks.json);;JSON (*.json);;All Files (*.*)"

    def _save_template(self) -> None:
        draft = self._collect_draft_lanes()
        if draft is None:
            return
        suggested = "mark_setup.cueplayer-marks.json"
        path_str, _ = QFileDialog.getSaveFileName(
            self,
            "Save Mark Settings",
            suggested,
            self._template_filter(),
        )
        if not path_str:
            return
        path = Path(path_str)
        if not path.name.lower().endswith(".json"):
            path = path.with_name(f"{path.name}.cueplayer-marks.json")
        elif not path.name.endswith(".cueplayer-marks.json") and path.suffix.lower() == ".json":
            path = path.with_name(f"{path.stem}.cueplayer-marks.json")
        primary, secondary = self._collect_now_lanes()
        template = build_template(
            draft,
            name=path.stem.replace(".cueplayer-marks", ""),
            now_primary_lanes=list(primary),
            now_secondary_lanes=list(secondary),
        )
        try:
            save_mark_template(path, template)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Unable to Save", str(exc))
            return
        QMessageBox.information(self, "Saved", f"Written to:\n{path}")

    def _load_template(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Load Mark Settings",
            "",
            self._template_filter(),
        )
        if not path_str:
            return
        try:
            data = load_mark_template(Path(path_str))
            lanes = dicts_to_lanes(data.get("mark_lanes") or [])
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Unable to Load", str(exc))
            return
        if not lanes:
            QMessageBox.warning(self, "Empty Settings File", "The settings file has no Marks.")
            return

        msg = ApplyMarkSettingsDialog(len(lanes), self)
        if msg.exec() != QDialog.DialogCode.Accepted or msg.choice() is None:
            return
        choice = msg.choice()

        now_primary = data.get("now_primary_lanes")
        now_secondary = data.get("now_secondary_lanes")
        if not isinstance(now_primary, list):
            now_primary = None
        if not isinstance(now_secondary, list):
            now_secondary = None

        if choice == ApplyMarkSettingsDialog.CURRENT:
            dropped = apply_lanes_to_song(
                self._song,
                lanes,
                now_primary_lanes=now_primary,
                now_secondary_lanes=now_secondary,
            )
            self._lane_snapshot = deepcopy(self._song.mark_lanes)
            self._load_from_lanes(self._song.mark_lanes)
            self.project_defaults_changed.emit()
            extra = f" ({dropped} unmatched mark(s) removed)" if dropped else ""
            QMessageBox.information(self, "Applied", f"Applied to the current song{extra}. Fine-tune and press OK.")
        elif choice == ApplyMarkSettingsDialog.DEFAULT:
            if self._project is None:
                QMessageBox.information(self, "Unable to Set", "No project object available to write the default to.")
                return
            self._project.default_mark_lanes = clone_lanes(lanes)
            self.project_defaults_changed.emit()
            QMessageBox.information(
                self,
                "Set as Default",
                'New songs added later will use this Mark layout. The current song is unchanged.',
            )
        elif choice == ApplyMarkSettingsDialog.ALL:
            if self._project is None:
                QMessageBox.information(self, "Unable to Apply", "No project object available.")
                return
            total_dropped = 0
            for song in self._project.songs:
                total_dropped += apply_lanes_to_song(
                    song,
                    lanes,
                    now_primary_lanes=now_primary,
                    now_secondary_lanes=now_secondary,
                )
            self._project.default_mark_lanes = clone_lanes(lanes)
            self._lane_snapshot = deepcopy(self._song.mark_lanes)
            self._load_from_lanes(self._song.mark_lanes)
            self.project_defaults_changed.emit()
            extra = f"\n{total_dropped} unmatched mark(s) removed in total." if total_dropped else ""
            QMessageBox.information(
                self,
                "Applied",
                f"Applied to all {len(self._project.songs)} song(s) and set as the project default.{extra}",
            )

    def _mark_name_at(self, row: int) -> str:
        edit = self.table.cellWidget(row, _COL_NAME)
        index_item = self.table.item(row, _COL_INDEX)
        if isinstance(edit, QLineEdit) and edit.text().strip():
            return edit.text().strip()
        if index_item:
            return f"Mark {index_item.text()}"
        return f"Row {row + 1}"

    def _name_edit_at(self, row: int) -> QLineEdit | None:
        edit = self.table.cellWidget(row, _COL_NAME)
        return edit if isinstance(edit, QLineEdit) else None

    def _append_row(self, lane: MarkLane) -> None:
        row = self._lane_row_count()
        self.table.insertRow(row)

        index_item = QTableWidgetItem(str(lane.index))
        index_item.setFlags(index_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        index_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, _COL_INDEX, index_item)

        # Real line edit so drag-selecting characters works (table cell editors don't).
        name_edit = QLineEdit(lane.name)
        name_edit.setFrame(False)
        name_edit.setStyleSheet(
            "QLineEdit {"
            "  background: transparent;"
            "  color: #d7dde8;"
            "  padding: 4px 6px;"
            "  selection-background-color: #3a6ea5;"
            "  selection-color: #ffffff;"
            "}"
            "QLineEdit:focus {"
            "  background: #1c2433;"
            "  border: 1px solid #4a6a94;"
            "  border-radius: 3px;"
            "}"
        )
        name_edit.setPlaceholderText("Enter name…")
        name_edit.setCursorPosition(0)
        name_edit.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        name_edit.textChanged.connect(self._on_name_text_changed)
        name_edit.installEventFilter(self)
        self.table.setCellWidget(row, _COL_NAME, name_edit)

        key = QComboBox()
        key.addItem("(None)", "")
        for digit in range(1, 10):
            key.addItem(str(digit), str(digit))
        idx = key.findData(lane.shortcut.strip())
        key.setCurrentIndex(idx if idx >= 0 else 0)
        key.setProperty("last_data", key.currentData())
        key.activated.connect(lambda _i, c=key: self._on_shortcut_activated(c))
        _style_table_combo(key)
        self.table.setCellWidget(row, _COL_KEY, key)

        shape = QComboBox()
        for shape_id, label in MARKER_SHAPE_LABELS.items():
            shape.addItem(label, shape_id)
        shape_idx = shape.findData(lane.marker_shape)
        shape.setCurrentIndex(shape_idx if shape_idx >= 0 else 0)
        shape.currentIndexChanged.connect(lambda _i, r=row: self._on_shape_or_color_changed(r))
        shape.setMinimumWidth(_COLUMN_MIN_WIDTHS[_COL_SHAPE] - 8)
        _style_table_combo(shape)
        self.table.setCellWidget(row, _COL_SHAPE, shape)

        swatch = ColorSwatchButton(lane.color)
        swatch.color_changed.connect(lambda _c, r=row: self._on_shape_or_color_changed(r))
        wrap = QWidget()
        wrap_layout = QHBoxLayout(wrap)
        wrap_layout.setContentsMargins(4, 0, 4, 0)
        wrap_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wrap_layout.addWidget(swatch)
        wrap.setProperty("swatch", swatch)
        self.table.setCellWidget(row, _COL_COLOR, wrap)

        visible = QCheckBox()
        visible.setChecked(lane.visible)
        visible_wrap = QWidget()
        visible_layout = QHBoxLayout(visible_wrap)
        visible_layout.setContentsMargins(0, 0, 0, 0)
        visible_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        visible_layout.addWidget(visible)
        visible_wrap.setProperty("checkbox", visible)
        self.table.setCellWidget(row, _COL_VISIBLE, visible_wrap)

        cue_id = QCheckBox()
        cue_id.setChecked(lane.cue_id_enabled)
        cue_id.setToolTip("Numbered Cue IDs (1, 2, 3…). Unchecked = Button lane.")
        cue_id_wrap = QWidget()
        cue_id_layout = QHBoxLayout(cue_id_wrap)
        cue_id_layout.setContentsMargins(0, 0, 0, 0)
        cue_id_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cue_id_layout.addWidget(cue_id)
        cue_id_wrap.setProperty("checkbox", cue_id)
        self.table.setCellWidget(row, _COL_CUE_ID, cue_id_wrap)

        cue_list = QCheckBox()
        cue_list.setChecked(lane.cue_list_enabled)
        cue_list.setToolTip("Show marks on this lane in the scrolling Cue List")
        cue_list_wrap = QWidget()
        cue_list_layout = QHBoxLayout(cue_list_wrap)
        cue_list_layout.setContentsMargins(0, 0, 0, 0)
        cue_list_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cue_list_layout.addWidget(cue_list)
        cue_list_wrap.setProperty("checkbox", cue_list)
        self.table.setCellWidget(row, _COL_CUE_LIST, cue_list_wrap)

        midi = QCheckBox()
        midi.setChecked(bool(getattr(lane, "midi_note_enabled", False)))
        midi.setToolTip(
            "Send a MIDI note when playback crosses marks on this lane "
            "(enable globally in Audio / Midi / Timecode → Send MIDI Cue Notes)"
        )
        midi_wrap = QWidget()
        midi_layout = QHBoxLayout(midi_wrap)
        midi_layout.setContentsMargins(0, 0, 0, 0)
        midi_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        midi_layout.addWidget(midi)
        midi_wrap.setProperty("checkbox", midi)
        self.table.setCellWidget(row, _COL_MIDI, midi_wrap)

        default_note = self._default_note_for_lane(lane)
        note_combo = self._make_note_combo(lane, default_note)
        note_combo.setMinimumWidth(_COLUMN_MIN_WIDTHS[_COL_MIDI_NOTE] - 8)
        _style_table_combo(note_combo)
        self.table.setCellWidget(row, _COL_MIDI_NOTE, note_combo)

        pause = QCheckBox()
        pause.setChecked(bool(getattr(lane, "pause_on_mark", False)))
        pause.setToolTip(
            "Pause playback when you place a mark of this type (shortcut or click)"
        )
        pause_wrap = QWidget()
        pause_layout = QHBoxLayout(pause_wrap)
        pause_layout.setContentsMargins(0, 0, 0, 0)
        pause_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pause_layout.addWidget(pause)
        pause_wrap.setProperty("checkbox", pause)
        self.table.setCellWidget(row, _COL_PAUSE, pause_wrap)

        ask_note = QCheckBox()
        ask_note.setChecked(bool(getattr(lane, "prompt_note_on_mark", False)))
        ask_note.setToolTip(
            "After placing a mark of this type, open a dialog to type the Note "
            "(works well with Pause)"
        )
        ask_note_wrap = QWidget()
        ask_note_layout = QHBoxLayout(ask_note_wrap)
        ask_note_layout.setContentsMargins(0, 0, 0, 0)
        ask_note_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ask_note_layout.addWidget(ask_note)
        ask_note_wrap.setProperty("checkbox", ask_note)
        self.table.setCellWidget(row, _COL_ASK_NOTE, ask_note_wrap)

        wave_note = QCheckBox()
        wave_note.setChecked(bool(getattr(lane, "show_note_on_wave", False)))
        wave_note.setToolTip(
            "Show the Note text next to the mark line on the waveform (top of the stem)"
        )
        wave_note_wrap = QWidget()
        wave_note_layout = QHBoxLayout(wave_note_wrap)
        wave_note_layout.setContentsMargins(0, 0, 0, 0)
        wave_note_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wave_note_layout.addWidget(wave_note)
        wave_note_wrap.setProperty("checkbox", wave_note)
        self.table.setCellWidget(row, _COL_WAVE_NOTE, wave_note_wrap)

        wave_cue = QCheckBox()
        wave_cue.setChecked(bool(getattr(lane, "show_cue_id_on_wave", False)))
        wave_cue.setToolTip(
            "Show the Cue ID next to the mark line on the waveform "
            "(requires Cue ID enabled for this type)"
        )
        wave_cue_wrap = QWidget()
        wave_cue_layout = QHBoxLayout(wave_cue_wrap)
        wave_cue_layout.setContentsMargins(0, 0, 0, 0)
        wave_cue_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wave_cue_layout.addWidget(wave_cue)
        wave_cue_wrap.setProperty("checkbox", wave_cue)
        self.table.setCellWidget(row, _COL_WAVE_CUE, wave_cue_wrap)

        now_combo = NoWheelComboBox()
        now_combo.addItem("Off", 0)
        now_combo.addItem("Primary", 1)
        now_combo.addItem("Secondary", 2)
        role = self._now_role_for_index(lane.index)
        role_idx = now_combo.findData(role)
        now_combo.setCurrentIndex(role_idx if role_idx >= 0 else 0)
        now_combo.setToolTip(
            "NOW monitor assignment: Off screen, Primary display, or Secondary display"
        )
        now_combo.setMinimumWidth(_COLUMN_MIN_WIDTHS[_COL_NOW] - 8)
        _style_table_combo(now_combo)
        now_combo.currentIndexChanged.connect(lambda _i: self._on_now_display_changed())
        self.table.setCellWidget(row, _COL_NOW, now_combo)

        self._connect_row_bulk_sync(
            visible, cue_id, cue_list, midi, pause, ask_note, wave_note, wave_cue
        )
        self._refresh_bulk_toggle_states()

    def _on_now_display_changed(self) -> None:
        self._apply_now_lanes_to_song()
        self.preview_changed.emit()

    def _make_note_combo(self, lane: MarkLane, default_note: int) -> NoWheelComboBox:
        combo = NoWheelComboBox()
        combo.setEditable(True)
        combo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        combo.addItem(f"auto ({default_note})", 0)
        for n in range(1, 128):
            combo.addItem(str(n), n)
        stored = int(getattr(lane, "midi_note", 0) or 0)
        if stored == 0:
            combo.setCurrentIndex(0)
        else:
            idx = combo.findData(stored)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            if idx < 0:
                combo.setEditText(str(stored))
        combo.setToolTip(
            f"Type auto or pick auto ({default_note}) for the default note on this lane. "
            "Or enter any number from 1 to 127."
        )
        return combo

    def _midi_note_from_widget(self, widget: NoWheelComboBox) -> int | None:
        text = widget.currentText().strip().lower()
        if not text or text.startswith("auto"):
            return 0
        try:
            value = int(text)
        except ValueError:
            return None
        if 1 <= value <= 127:
            return value
        return None

    def _midi_bases(self) -> tuple[int, int]:
        if self._project is not None:
            ao = self._project.audio_output
            return int(ao.midi_main_base_note), int(ao.midi_button_base_note)
        return 36, 48

    def _default_note_for_lane(self, lane: MarkLane) -> int:
        main_base, button_base = self._midi_bases()
        return default_note_for_lane(lane, main_base=main_base, button_base=button_base)

    def showEvent(self, event) -> None:  # noqa: ANN001
        super().showEvent(event)
        # Re-measure after the dialog is shown (font metrics can differ offscreen).
        self._apply_column_widths()

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)

    def eventFilter(self, obj, event) -> bool:  # noqa: ANN001
        # Clicking a name field should also select that row for preview / delete.
        if isinstance(obj, QLineEdit) and event.type() == event.Type.MouseButtonPress:
            for row in range(self._lane_row_count()):
                if self.table.cellWidget(row, _COL_NAME) is obj:
                    self.table.selectRow(row)
                    break
        return super().eventFilter(obj, event)

    def _on_name_changed(self, row: int) -> None:
        self._push_live_row(row)
        self._refresh_preview()

    def _on_name_text_changed(self, _text: str = "") -> None:
        edit = self.sender()
        if not isinstance(edit, QLineEdit):
            return
        for row in range(self._lane_row_count()):
            if self.table.cellWidget(row, _COL_NAME) is edit:
                self._on_name_changed(row)
                return

    def _on_shape_or_color_changed(self, row: int) -> None:
        self._push_live_row(row)
        self._refresh_preview()

    def _push_live_row(self, row: int) -> None:
        index_item = self.table.item(row, _COL_INDEX)
        shape_widget = self.table.cellWidget(row, _COL_SHAPE)
        if index_item is None or not isinstance(shape_widget, QComboBox):
            return
        lane = self._song.lane_by_index(int(index_item.text()))
        if lane is None:
            return
        shape = str(shape_widget.currentData() or "circle")
        if shape in MARKER_SHAPE_LABELS:
            lane.marker_shape = shape  # type: ignore[assignment]
        lane.color = self._color_at(row)
        name_edit = self._name_edit_at(row)
        if name_edit is not None and name_edit.text().strip():
            lane.name = name_edit.text().strip()
        self.preview_changed.emit()

    def _refresh_preview(self) -> None:
        row = self._selected_row()
        if row < 0:
            row = 0 if self._lane_row_count() else -1
        if row < 0:
            self.preview.set_preview(shape="circle", color="#888888", name="(None)")
            return
        shape_widget = self.table.cellWidget(row, _COL_SHAPE)
        shape = "circle"
        if isinstance(shape_widget, QComboBox):
            shape = str(shape_widget.currentData() or "circle")
        self.preview.set_preview(
            shape=shape,
            color=self._color_at(row),
            name=self._mark_name_at(row),
        )

    def _on_shortcut_activated(self, combo: QComboBox) -> None:
        if self._suppress_key_prompt:
            combo.setProperty("last_data", combo.currentData())
            return
        row = -1
        for r in range(self._lane_row_count()):
            if self.table.cellWidget(r, _COL_KEY) is combo:
                row = r
                break
        if row < 0:
            return
        new_key = str(combo.currentData() or "")
        old_key = str(combo.property("last_data") or "")
        if not new_key or new_key == old_key:
            combo.setProperty("last_data", new_key)
            return
        conflict_row = -1
        for r in range(self._lane_row_count()):
            if r == row:
                continue
            other = self.table.cellWidget(r, _COL_KEY)
            if isinstance(other, QComboBox) and str(other.currentData() or "") == new_key:
                conflict_row = r
                break
        if conflict_row < 0:
            combo.setProperty("last_data", new_key)
            return
        answer = QMessageBox.question(
            self,
            "Shortcut Already in Use",
            f'Shortcut {new_key} is currently bound to "{self._mark_name_at(conflict_row)}".\n'
            f'Rebind it to "{self._mark_name_at(row)}" instead?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            other = self.table.cellWidget(conflict_row, _COL_KEY)
            if isinstance(other, QComboBox):
                self._suppress_key_prompt = True
                other.blockSignals(True)
                other.setCurrentIndex(0)
                other.setProperty("last_data", "")
                other.blockSignals(False)
                self._suppress_key_prompt = False
            combo.setProperty("last_data", new_key)
        else:
            revert = combo.findData(old_key)
            combo.blockSignals(True)
            combo.setCurrentIndex(revert if revert >= 0 else 0)
            combo.blockSignals(False)

    def _selected_row(self) -> int:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return -1
        row = rows[0].row()
        if self._is_bulk_footer_row(row):
            return -1
        return row

    def _add_row(self) -> None:
        used = {
            int(self.table.item(r, _COL_INDEX).text())
            for r in range(self._lane_row_count())
            if self.table.item(r, _COL_INDEX) is not None
        }
        index = 1
        while index in used:
            index += 1
        color = BUILTIN_PRESETS[(index - 1) % len(BUILTIN_PRESETS)]
        taken_keys = set()
        for r in range(self._lane_row_count()):
            combo = self.table.cellWidget(r, _COL_KEY)
            if isinstance(combo, QComboBox) and combo.currentData():
                taken_keys.add(str(combo.currentData()))
        shortcut = next((str(d) for d in range(1, 10) if str(d) not in taken_keys), "")
        self._append_row(
            MarkLane(
                index=index,
                name=f"Mark {index}" if index != 1 else "Main",
                lane_type="main" if index == 1 else "top_button",
                color=color,
                shortcut=shortcut,
                visible=True,
                cue_id_enabled=(index == 1),
                cue_list_enabled=True,
                midi_note_enabled=(index != 1),
                marker_shape="triangle_up",
            )
        )
        self._ensure_bulk_footer_row()
        self.table.selectRow(self._lane_row_count() - 1)

    def _remove_row(self) -> None:
        row = self._selected_row()
        if row < 0:
            return
        if self._lane_row_count() <= 1:
            QMessageBox.information(self, "Mark Manager", "At least one Mark must remain.")
            return
        index_item = self.table.item(row, _COL_INDEX)
        mark_index = int(index_item.text()) if index_item else -1
        mark_count = len(self._song.marks_for_lane(mark_index))
        if mark_count:
            answer = QMessageBox.question(
                self,
                "Delete Mark",
                f"Mark #{mark_index} has {mark_count} cue(s), which will also be removed. Continue?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.table.removeRow(row)
        if self._bulk_footer_row is not None and row < self._bulk_footer_row:
            self._bulk_footer_row -= 1
        self._ensure_bulk_footer_row()
        self._refresh_bulk_toggle_states()

    def _color_at(self, row: int) -> str:
        wrap = self.table.cellWidget(row, _COL_COLOR)
        if wrap is None:
            return BUILTIN_PRESETS[0]
        swatch = wrap.property("swatch")
        if isinstance(swatch, ColorSwatchButton):
            return swatch.color()
        found = wrap.findChild(ColorSwatchButton)
        return found.color() if found is not None else BUILTIN_PRESETS[0]

    def _accept(self) -> None:
        draft = self._collect_draft_lanes()
        if draft is None:
            return
        keep = {lane.index for lane in draft}
        self._song.marks = [m for m in self._song.marks if m.lane_index in keep]
        self._song.mark_lanes = draft
        self._apply_now_lanes_to_song()
        from cueplayer.domain.main_cue_id import sync_lane_cue_ids

        sync_lane_cue_ids(self._song)
        self.accept()


# Back-compat alias
LaneManagerDialog = MarkManagerDialog
