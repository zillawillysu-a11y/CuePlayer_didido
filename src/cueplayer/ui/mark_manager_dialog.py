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
from cueplayer.ui.color_presets import (
    BUILTIN_PRESETS,
    add_user_preset,
    all_presets,
    get_color,
    remove_user_preset,
)
from cueplayer.ui.marker_draw import draw_marker_shape

_COL_INDEX = 0
_COL_NAME = 1
_COL_KEY = 2
_COL_SHAPE = 3
_COL_COLOR = 4
_COL_VISIBLE = 5
_COL_TYPE = 6


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
        self.resize(900, 560)
        self._song = song
        self._project = project
        self._suppress_key_prompt = False
        self._lane_snapshot = deepcopy(song.mark_lanes)

        layout = QVBoxLayout(self)
        hint = QLabel(
            "Set the name, shortcut, shape, and color for each Mark. "
            'Use "Save Settings" to write a file you can later load and apply to a song or as the show default.'
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8b949e;")
        layout.addWidget(hint)

        self.preview = ShapePreview()
        layout.addWidget(self.preview)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["#", "Name", "Shortcut", "Shape", "Color", "Visible", "Type"]
        )
        self.table.horizontalHeader().setSectionResizeMode(_COL_NAME, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(_COL_INDEX, 44)
        self.table.setColumnWidth(_COL_KEY, 100)
        self.table.setColumnWidth(_COL_SHAPE, 120)
        self.table.setColumnWidth(_COL_COLOR, 70)
        self.table.setColumnWidth(_COL_VISIBLE, 56)
        self.table.setColumnWidth(_COL_TYPE, 110)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        layout.addWidget(self.table, stretch=1)

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
        self.table.itemSelectionChanged.connect(self._refresh_preview)
        self._load_from_song()
        if self.table.rowCount() > 0:
            self.table.selectRow(0)
        self._refresh_preview()

    def _reject_restore(self) -> None:
        self._song.mark_lanes = deepcopy(self._lane_snapshot)
        self.preview_changed.emit()
        self.reject()

    def _load_from_song(self) -> None:
        self.table.setRowCount(0)
        for lane in sorted(self._song.mark_lanes, key=lambda item: item.index):
            self._append_row(lane)

    def _load_from_lanes(self, lanes: list[MarkLane]) -> None:
        self.table.setRowCount(0)
        for lane in sorted(lanes, key=lambda item: item.index):
            self._append_row(lane)
        if self.table.rowCount() > 0:
            self.table.selectRow(0)
        self._refresh_preview()
        self.preview_changed.emit()

    def _collect_draft_lanes(self) -> list[MarkLane] | None:
        """Build MarkLane list from the table; None if invalid."""
        rows = self.table.rowCount()
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
            type_widget = self.table.cellWidget(row, _COL_TYPE)
            if not all([index_item, name_edit, key_widget, shape_widget, visible_wrap, type_widget]):
                QMessageBox.warning(self, "Mark Manager", f"Row {row + 1} has incomplete data.")
                return None
            assert isinstance(name_edit, QLineEdit)
            assert isinstance(key_widget, QComboBox)
            assert isinstance(shape_widget, QComboBox)
            assert isinstance(type_widget, QComboBox)
            checkbox = visible_wrap.property("checkbox")
            if not isinstance(checkbox, QCheckBox):
                checkbox = visible_wrap.findChild(QCheckBox)
            if checkbox is None:
                QMessageBox.warning(self, "Mark Manager", f"Row {row + 1} is missing its visibility toggle.")
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
            lane_type = str(type_widget.currentData() or "top_button")
            if lane_type not in ("main", "top_button"):
                lane_type = "top_button"
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
                    marker_shape=shape,  # type: ignore[arg-type]
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
        template = build_template(
            draft,
            name=path.stem.replace(".cueplayer-marks", ""),
            now_primary_lanes=list(self._song.now_primary_lanes),
            now_secondary_lanes=list(self._song.now_secondary_lanes),
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
        row = self.table.rowCount()
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
            key.addItem(f"Shortcut {digit}", str(digit))
        idx = key.findData(lane.shortcut.strip())
        key.setCurrentIndex(idx if idx >= 0 else 0)
        key.setProperty("last_data", key.currentData())
        key.activated.connect(lambda _i, c=key: self._on_shortcut_activated(c))
        self.table.setCellWidget(row, _COL_KEY, key)

        shape = QComboBox()
        for shape_id, label in MARKER_SHAPE_LABELS.items():
            shape.addItem(label, shape_id)
        shape_idx = shape.findData(lane.marker_shape)
        shape.setCurrentIndex(shape_idx if shape_idx >= 0 else 0)
        shape.currentIndexChanged.connect(lambda _i, r=row: self._on_shape_or_color_changed(r))
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

        mark_type = QComboBox()
        mark_type.addItem("Main", "main")
        mark_type.addItem("Top Button", "top_button")
        type_idx = mark_type.findData(lane.lane_type)
        mark_type.setCurrentIndex(type_idx if type_idx >= 0 else 1)
        self.table.setCellWidget(row, _COL_TYPE, mark_type)

    def eventFilter(self, obj, event) -> bool:  # noqa: ANN001
        # Clicking a name field should also select that row for preview / delete.
        if isinstance(obj, QLineEdit) and event.type() == event.Type.MouseButtonPress:
            for row in range(self.table.rowCount()):
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
        for row in range(self.table.rowCount()):
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
            row = 0 if self.table.rowCount() else -1
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
        for r in range(self.table.rowCount()):
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
        for r in range(self.table.rowCount()):
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
        return rows[0].row() if rows else -1

    def _add_row(self) -> None:
        used = {
            int(self.table.item(r, _COL_INDEX).text())
            for r in range(self.table.rowCount())
            if self.table.item(r, _COL_INDEX) is not None
        }
        index = 1
        while index in used:
            index += 1
        color = BUILTIN_PRESETS[(index - 1) % len(BUILTIN_PRESETS)]
        taken_keys = set()
        for r in range(self.table.rowCount()):
            combo = self.table.cellWidget(r, _COL_KEY)
            if isinstance(combo, QComboBox) and combo.currentData():
                taken_keys.add(str(combo.currentData()))
        shortcut = next((str(d) for d in range(1, 10) if str(d) not in taken_keys), "")
        self._append_row(
            MarkLane(
                index=index,
                name=f"Mark {index}",
                lane_type="main" if index == 1 else "top_button",
                color=color,
                shortcut=shortcut,
                visible=True,
                marker_shape="circle",
            )
        )
        self.table.selectRow(self.table.rowCount() - 1)

    def _remove_row(self) -> None:
        row = self._selected_row()
        if row < 0:
            return
        if self.table.rowCount() <= 1:
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
        self.accept()


# Back-compat alias
LaneManagerDialog = MarkManagerDialog
