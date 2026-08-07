"""MA Show Patch page — Sequence chain + Fader assignment for the whole show."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cueplayer.domain.models import MaExportSettings, Project
from cueplayer.exporters.common import sanitize_ma_name
from cueplayer.exporters.ma2 import Ma2Exporter
from cueplayer.exporters.ma3 import Ma3Exporter
from cueplayer.exporters.ma_default_dirs import resolve_export_dir
from cueplayer.exporters.show_patch import (
    SongPatchSlot,
    build_show_patch,
    plans_from_show_patch,
    sequence_chain_labels,
)
from cueplayer.ui.row_color import ROLE_ROW_COLOR, RowColorDelegate
from cueplayer.ui.spinboxes import NoWheelDoubleSpinBox, NoWheelSpinBox
from cueplayer.ui.theme import contrast_text_color

_COL_ORDER = 0
_COL_SONG = 1
_COL_ROLE = 2
_COL_SEQ = 3
_COL_FADER = 4
_COL_TC = 5
_COL_MARKS = 6

_DEFAULT_SHOW_MACRO = "CuePlayer_Show_Install"


def _lane_color_for_main(song) -> str:  # noqa: ANN001
    lane = next((l for l in song.mark_lanes if l.cue_id_enabled), None)
    return (lane.color if lane and lane.color else "#E74C3C")


def _lane_color_for_button(song, lane_index: int) -> str:  # noqa: ANN001
    lane = next((l for l in song.mark_lanes if l.index == lane_index), None)
    return (lane.color if lane and lane.color else "#4C8BF5")


def _mark_cell_bg(hex_color: str) -> QColor:
    """Readable cell fill from a bright mark color (blend toward black)."""
    c = QColor(hex_color)
    if not c.isValid():
        return QColor("#27272a")
    return QColor(
        max(20, int(c.red() * 0.42)),
        max(20, int(c.green() * 0.42)),
        max(20, int(c.blue() * 0.42)),
    )


def normalize_show_macro_basename(raw: str) -> str:
    """User-facing macro name → safe file basename (no .xml)."""
    text = (raw or "").strip()
    if text.lower().endswith(".xml"):
        text = text[:-4].strip()
    cleaned = sanitize_ma_name(text, fallback=_DEFAULT_SHOW_MACRO)
    return cleaned or _DEFAULT_SHOW_MACRO


class ShowPatchPage(QWidget):
    """
    Show-wide MA patch map.

    Sequence order: Song1 Main → Song1 Button → Song2 Main → Song2 Button → …
    """

    settings_changed = Signal()
    export_finished = Signal(object)  # dict[str, Path]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project: Project | None = None
        self._slots: list[SongPatchSlot] = []
        self._suppress = False

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(10)

        title = QLabel("Export · Sequence / Fader")
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #e6edf3;")
        hint = QLabel(
            "Check the songs to export. MA2 Main: Song; MA3 Main: Song_Main; "
            "Button Sequence: Song_Hit (Mark name). "
            "Each song has one Timecode containing the Main Go+ and all Button Tops."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8b949e;")
        root.addWidget(title)
        root.addWidget(hint)

        self.chain_label = QLabel("")
        self.chain_label.setWordWrap(True)
        self.chain_label.setStyleSheet(
            "background: #111113; border: 1px solid #27272a; border-radius: 8px;"
            "padding: 10px 12px; color: #a1a1aa; font-family: Consolas, 'Courier New', monospace;"
        )
        root.addWidget(self.chain_label)

        settings_row = QHBoxLayout()
        console_box = QGroupBox("Console")
        console_layout = QHBoxLayout(console_box)
        self.ma2_radio = QRadioButton("grandMA2")
        self.ma3_radio = QRadioButton("grandMA3")
        self.ma2_radio.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.ma2_radio)
        group.addButton(self.ma3_radio)
        console_layout.addWidget(self.ma2_radio)
        console_layout.addWidget(self.ma3_radio)
        settings_row.addWidget(console_box)

        pool_box = QGroupBox("Pool Start")
        pool_form = QFormLayout(pool_box)
        self.seq_start = NoWheelSpinBox()
        self.seq_start.setRange(1, 9999)
        self.seq_start.setValue(1)
        self.tc_start = NoWheelSpinBox()
        self.tc_start.setRange(1, 9999)
        self.tc_start.setValue(1)
        pool_form.addRow("Sequence", self.seq_start)
        pool_form.addRow("Timecode", self.tc_start)
        settings_row.addWidget(pool_box)

        fader_box = QGroupBox("Fader (Executor)")
        fader_form = QFormLayout(fader_box)
        self.main_fader = QLineEdit("1.101")
        self.button_fader = QLineEdit("1.201")
        self.main_fader.setPlaceholderText("1.101")
        self.button_fader.setPlaceholderText("1.201")
        self.page_per_song = QCheckBox("New Page per song (1.201 → 2.201 → …)")
        self.page_per_song.setChecked(True)
        self.page_per_song.setToolTip(
            "Each song uses its own Page, with Main=101 and Buttons starting at 201; "
            "Install will label that Page with the song's English name"
        )
        fader_form.addRow("Main", self.main_fader)
        fader_form.addRow("Button Start", self.button_fader)
        fader_form.addRow(self.page_per_song)
        settings_row.addWidget(fader_box, stretch=1)
        root.addLayout(settings_row)

        opt_row = QHBoxLayout()
        opt_box = QGroupBox("Export Options")
        opt_form = QFormLayout(opt_box)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Full (Sequence + Timecode)", "full")
        self.mode_combo.addItem("Timecode Only", "timecode_only")
        self.latency_ms = NoWheelDoubleSpinBox()
        self.latency_ms.setRange(-500.0, 500.0)
        self.latency_ms.setDecimals(1)
        self.latency_ms.setSuffix(" ms")
        self.data_pool = QLineEdit("Default")
        self.show_macro_name = QLineEdit(_DEFAULT_SHOW_MACRO)
        self.song_viewbutton = QLineEdit("1.20")
        self.song_viewbutton.setPlaceholderText("1.20")
        self.ma2_fixed_macros = QCheckBox("Fixed control Macros")
        self.ma2_song_macros = QCheckBox("Song Macros")
        self.ma2_song_list = QCheckBox("Song List Sequence")
        for checkbox in (
            self.ma2_fixed_macros,
            self.ma2_song_macros,
            self.ma2_song_list,
        ):
            checkbox.setChecked(True)
        self.ma2_template_page = NoWheelSpinBox()
        self.ma2_template_page.setRange(1, 9999)
        self.ma2_template_page.setValue(100)
        self.ma2_fixed_macro_start = NoWheelSpinBox()
        self.ma2_fixed_macro_start.setRange(1, 9999)
        self.ma2_fixed_macro_start.setValue(1001)
        self.ma2_song_macro_start = NoWheelSpinBox()
        self.ma2_song_macro_start.setRange(1, 9999)
        self.ma2_song_macro_start.setValue(1009)
        self.ma2_add_preset_cue = QCheckBox("Add Main Cue named Preset")
        self.ma2_preset_cue_id = NoWheelDoubleSpinBox()
        self.ma2_preset_cue_id.setRange(0.001, 9999.999)
        self.ma2_preset_cue_id.setDecimals(3)
        self.ma2_preset_cue_id.setValue(0.5)
        self.ma2_song_views = QCheckBox("Song Views (Screen 3)")
        self.ma2_song_views.setChecked(True)
        self.ma2_view_pool_start = NoWheelSpinBox()
        self.ma2_view_pool_start.setRange(1, 9999)
        self.ma2_view_pool_start.setValue(201)
        self.ma2_effect_pool_start = NoWheelSpinBox()
        self.ma2_effect_pool_start.setRange(1, 9999)
        self.ma2_effect_pool_start.setValue(201)
        self.show_macro_name.setPlaceholderText(_DEFAULT_SHOW_MACRO)
        self.show_macro_name.setToolTip(
            "Show-wide Install file name (MA3 = Macro; MA2 = Plugin primarily; .xml can be omitted)"
        )
        opt_form.addRow("Mode", self.mode_combo)
        opt_form.addRow("Latency", self.latency_ms)
        opt_form.addRow("MA3 Data Pool", self.data_pool)
        opt_form.addRow("Install Name", self.show_macro_name)
        opt_form.addRow("MA2 Song ViewButton", self.song_viewbutton)
        opt_form.addRow("MA2 Template Page", self.ma2_template_page)
        opt_form.addRow("MA2 Fixed Macro Start", self.ma2_fixed_macro_start)
        opt_form.addRow("MA2 Song Macro Start", self.ma2_song_macro_start)
        opt_form.addRow(self.ma2_add_preset_cue)
        opt_form.addRow("MA2 Preset Cue ID", self.ma2_preset_cue_id)
        opt_form.addRow(self.ma2_song_views)
        opt_form.addRow("MA2 View Pool Start", self.ma2_view_pool_start)
        opt_form.addRow("MA2 Effect Pool Start", self.ma2_effect_pool_start)
        opt_form.addRow(self.ma2_fixed_macros)
        opt_form.addRow(self.ma2_song_macros)
        opt_form.addRow(self.ma2_song_list)
        opt_row.addWidget(opt_box)

        out_box = QGroupBox("Output Folder")
        out_layout = QVBoxLayout(out_box)
        out_row = QHBoxLayout()
        self.out_dir = QLineEdit()
        browse = QPushButton("Browse…")
        restore = QPushButton("Restore Default")
        browse.clicked.connect(self._browse_out)
        restore.clicked.connect(self._restore_default_dir)
        out_row.addWidget(self.out_dir, stretch=1)
        out_row.addWidget(browse)
        out_row.addWidget(restore)
        out_layout.addLayout(out_row)
        self.out_hint = QLabel("")
        self.out_hint.setStyleSheet("color: #8b949e;")
        out_layout.addWidget(self.out_hint)
        opt_row.addWidget(out_box, stretch=1)
        root.addLayout(opt_row)

        song_box = QGroupBox("Songs to Export")
        song_layout = QVBoxLayout(song_box)
        self.song_pick = QListWidget()
        self.song_pick.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.song_pick.setMaximumHeight(140)
        self.song_pick.setItemDelegate(RowColorDelegate(self.song_pick))
        song_layout.addWidget(self.song_pick)
        pick_btns = QHBoxLayout()
        self.song_all_btn = QPushButton("Select All")
        self.song_none_btn = QPushButton("Select None")
        pick_btns.addWidget(self.song_all_btn)
        pick_btns.addWidget(self.song_none_btn)
        pick_btns.addStretch(1)
        song_layout.addLayout(pick_btns)
        root.addWidget(song_box)

        self.table = QTableWidget(0, 7)
        self.table.setObjectName("exportPatchTable")
        self.table.setHorizontalHeaderLabels(
            ["#", "English", "Sequence Name", "Pool", "Fader", "Timecode", "Marks"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        # Local sheet so global QTableWidget styles don't wipe per-cell BackgroundRole.
        self.table.setStyleSheet(
            "#exportPatchTable {"
            "  background-color: #111113;"
            "  gridline-color: #27272a;"
            "  border: 1px solid #27272a;"
            "  border-radius: 6px;"
            "  outline: none;"
            "}"
            "#exportPatchTable::item:selected {"
            "  background-color: #1a3a5c;"
            "  color: #ffffff;"
            "}"
            "#exportPatchTable QHeaderView::section {"
            "  background-color: #18181b;"
            "  color: #a1a1aa;"
            "  border: none;"
            "  border-bottom: 1px solid #27272a;"
            "  border-right: 1px solid #27272a;"
            "  padding: 6px 8px;"
            "}"
        )
        self.table.horizontalHeader().setSectionResizeMode(_COL_SONG, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(_COL_ROLE, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(_COL_ORDER, 40)
        self.table.setColumnWidth(_COL_SEQ, 80)
        self.table.setColumnWidth(_COL_FADER, 90)
        self.table.setColumnWidth(_COL_TC, 120)
        self.table.setColumnWidth(_COL_MARKS, 100)
        root.addWidget(self.table, stretch=1)

        action_row = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh Patch")
        self.export_btn = QPushButton("Export Checked Songs…")
        self.export_btn.setStyleSheet(
            "QPushButton { height: 34px; padding: 0 16px; font-weight: 600;"
            " background: transparent; border: none; color: #ededed; }"
            "QPushButton:hover { background: #222222; }"
            "QPushButton:pressed { background: #2a2a2a; }"
        )
        action_row.addWidget(self.refresh_btn)
        action_row.addStretch(1)
        action_row.addWidget(self.export_btn)
        root.addLayout(action_row)

        for widget in (
            self.seq_start,
            self.tc_start,
            self.main_fader,
            self.button_fader,
            self.page_per_song,
            self.mode_combo,
            self.latency_ms,
            self.data_pool,
            self.show_macro_name,
            self.song_viewbutton,
            self.ma2_template_page,
            self.ma2_fixed_macro_start,
            self.ma2_song_macro_start,
            self.ma2_add_preset_cue,
            self.ma2_preset_cue_id,
            self.ma2_song_views,
            self.ma2_view_pool_start,
            self.ma2_effect_pool_start,
            self.ma2_fixed_macros,
            self.ma2_song_macros,
            self.ma2_song_list,
        ):
            if isinstance(widget, QCheckBox):
                widget.toggled.connect(self._on_settings_edited)
            elif isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self._on_settings_edited)
            elif isinstance(widget, (NoWheelSpinBox, NoWheelDoubleSpinBox)):
                widget.valueChanged.connect(self._on_settings_edited)
            elif isinstance(widget, QLineEdit):
                widget.textChanged.connect(self._on_settings_edited)

        self.out_dir.textChanged.connect(self._on_out_dir_edited)
        self.ma2_radio.toggled.connect(self._on_console_toggled)
        self.ma3_radio.toggled.connect(self._on_console_toggled)
        self.song_pick.itemChanged.connect(self._on_song_pick_changed)
        self.song_all_btn.clicked.connect(lambda: self._set_all_songs(True))
        self.song_none_btn.clicked.connect(lambda: self._set_all_songs(False))
        self.refresh_btn.clicked.connect(self.refresh)
        self.export_btn.clicked.connect(self._export)

    def set_project(self, project: Project) -> None:
        self._project = project
        self._load_settings_into_ui()
        self._rebuild_song_pick()
        self.refresh()

    def sync_songs(self) -> None:
        """Call when setlist membership changes."""
        self._rebuild_song_pick()
        self.refresh()

    def refresh(self) -> None:
        if self._project is None:
            self._slots = []
            self.table.setRowCount(0)
            self.chain_label.setText("(No project)")
            return
        self._write_ui_to_settings()
        songs = self._checked_songs()
        self._slots = build_show_patch(songs, self._project.ma_export)
        self._rebuild_table()
        self._rebuild_chain()

    def _checked_songs(self):
        if self._project is None:
            return []
        by_id = {song.id: song for song in self._project.songs}
        out = []
        for row in range(self.song_pick.count()):
            item = self.song_pick.item(row)
            if item is None or item.checkState() != Qt.CheckState.Checked:
                continue
            song_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
            song = by_id.get(song_id)
            if song is not None:
                out.append(song)
        return out

    def _rebuild_song_pick(self) -> None:
        if self._project is None:
            self.song_pick.clear()
            return
        selected = set(self._project.ma_export.export_song_ids)
        # Empty list means "all songs" (default / first open).
        default_all = not selected
        self.song_pick.blockSignals(True)
        self.song_pick.clear()
        for song in self._project.songs:
            en = sanitize_ma_name(song.ma_export_name or song.name, fallback="Song")
            label = en if not song.name or song.name == en else f"{en}  ·  {song.name}"
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            checked = default_all or song.id in selected
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, song.id)
            item.setData(ROLE_ROW_COLOR, song.row_color or "")
            self.song_pick.addItem(item)
        self.song_pick.blockSignals(False)

    def _set_all_songs(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.song_pick.blockSignals(True)
        for row in range(self.song_pick.count()):
            item = self.song_pick.item(row)
            if item is not None:
                item.setCheckState(state)
        self.song_pick.blockSignals(False)
        self._on_song_pick_changed()

    def _on_song_pick_changed(self, *_args) -> None:
        if self._suppress or self._project is None:
            return
        ids = []
        for row in range(self.song_pick.count()):
            item = self.song_pick.item(row)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                ids.append(str(item.data(Qt.ItemDataRole.UserRole) or ""))
        self._project.ma_export.export_song_ids = ids
        self.refresh()
        self.settings_changed.emit()

    def _console(self) -> str:
        return "ma3" if self.ma3_radio.isChecked() else "ma2"

    def _load_settings_into_ui(self) -> None:
        if self._project is None:
            return
        s = self._project.ma_export
        self._suppress = True
        self.ma3_radio.setChecked(s.console == "ma3")
        self.ma2_radio.setChecked(s.console != "ma3")
        self.seq_start.setValue(int(s.sequence_pool_start))
        self.tc_start.setValue(int(s.timecode_pool_start))
        self.main_fader.setText(s.main_executor or "1.101")
        self.button_fader.setText(s.button_executor_start or "1.201")
        self.page_per_song.setChecked(bool(s.page_per_song))
        idx = self.mode_combo.findData(s.export_mode)
        self.mode_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.latency_ms.setValue(float(s.latency_ms))
        self.data_pool.setText(s.data_pool or "Default")
        self.show_macro_name.setText(
            s.show_install_macro_name or _DEFAULT_SHOW_MACRO
        )
        self.song_viewbutton.setText(s.ma2_song_viewbutton or "1.20")
        self.ma2_template_page.setValue(int(s.ma2_template_page or 100))
        self.ma2_fixed_macro_start.setValue(int(s.ma2_fixed_macro_start or 1001))
        self.ma2_song_macro_start.setValue(int(s.ma2_song_macro_start or 1009))
        self.ma2_add_preset_cue.setChecked(bool(s.ma2_add_main_preset_cue))
        self.ma2_preset_cue_id.setValue(float(s.ma2_main_preset_cue_id or 0.5))
        self.ma2_song_views.setChecked(bool(s.ma2_include_song_views))
        self.ma2_view_pool_start.setValue(int(s.ma2_view_pool_start or 201))
        self.ma2_effect_pool_start.setValue(int(s.ma2_effect_pool_start or 201))
        self.ma2_fixed_macros.setChecked(bool(s.ma2_include_fixed_macros))
        self.ma2_song_macros.setChecked(bool(s.ma2_include_song_macros))
        self.ma2_song_list.setChecked(bool(s.ma2_include_song_list))
        remembered = s.output_dir_ma3 if s.console == "ma3" else s.output_dir_ma2
        path = resolve_export_dir(s.console if s.console in ("ma2", "ma3") else "ma2", remembered or None)
        self.out_dir.setText(path)
        self.data_pool.setEnabled(s.console == "ma3")
        self.show_macro_name.setEnabled(True)
        self.song_viewbutton.setEnabled(s.console != "ma3")
        for widget in (
            self.ma2_template_page,
            self.ma2_fixed_macro_start,
            self.ma2_song_macro_start,
            self.ma2_add_preset_cue,
            self.ma2_preset_cue_id,
            self.ma2_song_views,
            self.ma2_view_pool_start,
            self.ma2_effect_pool_start,
            self.ma2_fixed_macros,
            self.ma2_song_macros,
            self.ma2_song_list,
        ):
            widget.setEnabled(s.console != "ma3")
        self._update_out_hint()
        self._suppress = False

    def _write_ui_to_settings(self) -> None:
        if self._project is None:
            return
        s = self._project.ma_export
        s.console = self._console()
        s.export_mode = str(self.mode_combo.currentData() or "full")
        s.sequence_pool_start = int(self.seq_start.value())
        s.timecode_pool_start = int(self.tc_start.value())
        s.main_executor = self.main_fader.text().strip() or "1.101"
        s.button_executor_start = self.button_fader.text().strip() or "1.201"
        s.page_per_song = self.page_per_song.isChecked()
        s.latency_ms = float(self.latency_ms.value())
        s.data_pool = self.data_pool.text().strip() or "Default"
        s.show_install_macro_name = normalize_show_macro_basename(
            self.show_macro_name.text()
        )
        s.ma2_song_viewbutton = self.song_viewbutton.text().strip() or "1.20"
        s.ma2_template_page = int(self.ma2_template_page.value())
        s.ma2_fixed_macro_start = int(self.ma2_fixed_macro_start.value())
        s.ma2_song_macro_start = int(self.ma2_song_macro_start.value())
        s.ma2_add_main_preset_cue = self.ma2_add_preset_cue.isChecked()
        s.ma2_main_preset_cue_id = float(self.ma2_preset_cue_id.value())
        s.ma2_include_song_views = self.ma2_song_views.isChecked()
        s.ma2_view_pool_start = int(self.ma2_view_pool_start.value())
        s.ma2_effect_pool_start = int(self.ma2_effect_pool_start.value())
        s.ma2_include_fixed_macros = self.ma2_fixed_macros.isChecked()
        s.ma2_include_song_macros = self.ma2_song_macros.isChecked()
        s.ma2_include_song_list = self.ma2_song_list.isChecked()
        # Keep export_song_ids in sync with checklist.
        ids = []
        for row in range(self.song_pick.count()):
            item = self.song_pick.item(row)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                ids.append(str(item.data(Qt.ItemDataRole.UserRole) or ""))
        if self.song_pick.count() > 0:
            s.export_song_ids = ids
        out = self.out_dir.text().strip()
        if s.console == "ma3":
            s.output_dir_ma3 = out
        else:
            s.output_dir_ma2 = out

    def _on_settings_edited(self, *_args) -> None:
        if self._suppress or self._project is None:
            return
        self.refresh()
        self.settings_changed.emit()

    def _on_out_dir_edited(self, *_args) -> None:
        if self._suppress or self._project is None:
            return
        self._write_ui_to_settings()
        self._update_out_hint()
        self.settings_changed.emit()

    def _on_console_toggled(self, checked: bool) -> None:
        if not checked or self._suppress or self._project is None:
            return
        s = self._project.ma_export
        new_console = self._console()
        old_console = "ma2" if new_console == "ma3" else "ma3"
        # Keep the folder currently in the box for the console we're leaving.
        current_out = self.out_dir.text().strip()
        if old_console == "ma3":
            s.output_dir_ma3 = current_out
        else:
            s.output_dir_ma2 = current_out
        s.console = new_console

        remembered = s.output_dir_ma3 if new_console == "ma3" else s.output_dir_ma2
        path = resolve_export_dir(new_console, remembered or None)
        self._suppress = True
        self.out_dir.setText(path)
        self.data_pool.setEnabled(new_console == "ma3")
        self.show_macro_name.setEnabled(True)
        self.song_viewbutton.setEnabled(new_console != "ma3")
        for widget in (
            self.ma2_template_page,
            self.ma2_fixed_macro_start,
            self.ma2_song_macro_start,
            self.ma2_add_preset_cue,
            self.ma2_preset_cue_id,
            self.ma2_song_views,
            self.ma2_view_pool_start,
            self.ma2_effect_pool_start,
            self.ma2_fixed_macros,
            self.ma2_song_macros,
            self.ma2_song_list,
        ):
            widget.setEnabled(new_console != "ma3")
        self._suppress = False
        if new_console == "ma3":
            s.output_dir_ma3 = path
        else:
            s.output_dir_ma2 = path
        self._update_out_hint()
        self.refresh()
        self.settings_changed.emit()

    def _update_out_hint(self) -> None:
        console = self._console()
        if console == "ma2":
            self.out_hint.setText(
                "MA2: pick gma2_V_*/importexport — "
                "Seq/TC → importexport, Install Plugin → plugins (writes Timecode when run)"
            )
        else:
            self.out_hint.setText(
                "MA3: pick gma3_library (or datapools) — "
                "Sequence → sequences, Timecode → timecodes, Macro → macros"
            )

    def _browse_out(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose Export Folder", self.out_dir.text())
        if path:
            self.out_dir.setText(path)

    def _restore_default_dir(self) -> None:
        path = resolve_export_dir(self._console(), remembered=None)
        if not path:
            QMessageBox.information(self, "No Default Found", "No grandMA install path was detected on this computer.")
            return
        self.out_dir.setText(path)

    def _rebuild_chain(self) -> None:
        if not self._slots:
            self.chain_label.setText("(Setlist has no songs)")
            return
        labels = sequence_chain_labels(self._slots)
        self.chain_label.setText("  →  ".join(labels))

    def _rebuild_table(self) -> None:
        # ord, en, seq_name, pool, fader, tc, marks, is_main, tc_tip, color, row_color
        rows: list[tuple[str, str, str, str, str, str, str, bool, str, str, str]] = []
        order = 1
        for slot in self._slots:
            btn_n = slot.button_lane_count
            btn_marks = slot.button_mark_count
            tc_main = f"TC {slot.timecode_pool} · Main+{btn_n}Btn"
            tip_main = (
                f'Page {slot.page} → "{slot.display_name}"; '
                + (
                    f"Timecode includes Main Go+ and {btn_n} Button Top(s) ({btn_marks} total)"
                    if slot.buttons
                    else "Timecode (Main only)"
                )
            )
            main_color = _lane_color_for_main(slot.song)
            song_row_color = (slot.song.row_color or "").strip()
            rows.append(
                (
                    str(order),
                    slot.display_name,
                    slot.main_sequence_name,
                    f"Seq {slot.main_sequence}",
                    slot.main_executor,
                    tc_main,
                    f"{slot.main_cue_count} cues",
                    True,
                    tip_main,
                    main_color,
                    song_row_color,
                )
            )
            order += 1
            for button in slot.buttons:
                btn_color = _lane_color_for_button(slot.song, button.lane_index)
                rows.append(
                    (
                        str(order),
                        slot.display_name,
                        button.sequence_name,
                        f"Seq {button.sequence}",
                        button.executor,
                        f"→ TC {slot.timecode_pool} Top",
                        f"{button.mark_count} tops",
                        False,
                        "This Button's Top events are written into the same song's Timecode",
                        btn_color,
                        song_row_color,
                    )
                )
                order += 1
            if not slot.buttons:
                rows.append(
                    (
                        str(order),
                        slot.display_name,
                        "—",
                        "—",
                        "—",
                        f"TC {slot.timecode_pool}",
                        "(No Button marks for this song)",
                        False,
                        "",
                        "",
                        song_row_color,
                    )
                )
                order += 1

        self.table.setRowCount(len(rows))
        for r, (ord_s, en, seq_name, pool, fader, tc, marks, is_main, tc_tip, color, row_color) in enumerate(
            rows
        ):
            values = [ord_s, en, seq_name, pool, fader, tc, marks]
            lane_color = QColor(color) if color else None
            song_bg = QColor(row_color) if row_color else None
            if song_bg is not None and not song_bg.isValid():
                song_bg = None
            for c, text in enumerate(values):
                item = QTableWidgetItem(text)
                if is_main:
                    item.setForeground(QBrush(QColor("#e4e4e7")))
                else:
                    item.setForeground(QBrush(QColor("#a1a1aa")))
                # # + English columns carry the setlist Song.row_color so VIP /
                # problem songs stay recognizable from setlist → export.
                if c in (_COL_ORDER, _COL_SONG) and song_bg is not None:
                    item.setBackground(QBrush(song_bg))
                    item.setForeground(QBrush(QColor(contrast_text_color(song_bg.name()))))
                # Sequence Name + Pool + Fader follow Mark color.
                if (
                    c in (_COL_ROLE, _COL_SEQ, _COL_FADER)
                    and lane_color is not None
                    and lane_color.isValid()
                ):
                    item.setBackground(QBrush(_mark_cell_bg(color)))
                    item.setForeground(QBrush(QColor("#ffffff")))
                if c == _COL_ORDER:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == _COL_TC and tc_tip:
                    item.setToolTip(tc_tip)
                if c == _COL_FADER and is_main and en:
                    item.setToolTip(f'Install will label the Page as "{en}"')
                self.table.setItem(r, c, item)

    def _export(self) -> None:
        if self._project is None or not self._slots:
            QMessageBox.warning(self, "No Songs Selected", "Check at least one song to export.")
            return
        self._write_ui_to_settings()
        out = self.out_dir.text().strip()
        if not out:
            QMessageBox.warning(self, "Missing Folder", "Choose an output folder first.")
            return
        directory = Path(out)
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Unable to Create Folder", str(exc))
            return

        # Fresh MA Preflight every export — exporters never validate.
        from cueplayer.application.ma_preflight_export_gate import (
            evaluate_ma_preflight_for_export,
        )
        from cueplayer.ui.ma_preflight_dialog import present_export_preflight_gate

        navigate = None
        host = self.window()
        handler = getattr(host, "_on_preflight_navigate", None)
        if callable(handler):
            navigate = handler
        gate = evaluate_ma_preflight_for_export(self._project)
        if not present_export_preflight_gate(
            gate, self, on_navigate=navigate
        ):
            return

        empty = [s for s in self._slots if s.main_cue_count == 0]
        if empty and self._project.ma_export.export_mode == "full":
            names = ", ".join(s.display_name for s in empty[:5])
            more = "…" if len(empty) > 5 else ""
            answer = QMessageBox.question(
                self,
                "No Main Cues",
                f"These songs have no Main Marks: {names}{more}\nExport anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        console = self._console()
        mode = str(self.mode_combo.currentData() or "full")
        show_macro_basename = normalize_show_macro_basename(
            self.show_macro_name.text()
            or self._project.ma_export.show_install_macro_name
        )
        if mode == "full":
            label = (
                "Show-wide Macro file name (.xml optional):"
                if console == "ma3"
                else "Show-wide Install Plugin/Macro file name (.xml optional):"
            )
            typed, ok = QInputDialog.getText(
                self,
                "Install File Name",
                label,
                text=show_macro_basename,
            )
            if not ok:
                return
            show_macro_basename = normalize_show_macro_basename(typed)
            self.show_macro_name.setText(show_macro_basename)
            self._project.ma_export.show_install_macro_name = show_macro_basename

        try:
            plans = plans_from_show_patch(self._slots, self._project.ma_export)
            button_tracks = sum(len(p.button_lanes) for p in plans)
            if console == "ma3":
                all_paths = Ma3Exporter().export_show_to_directory(
                    plans,
                    directory,
                    show_macro_name=show_macro_basename,
                )
            else:
                all_paths = Ma2Exporter().export_show_to_directory(
                    plans,
                    directory,
                    show_install_name=show_macro_basename,
                    song_viewbutton=self._project.ma_export.ma2_song_viewbutton,
                    include_fixed_macros=self._project.ma_export.ma2_include_fixed_macros,
                    include_song_macros=self._project.ma_export.ma2_include_song_macros,
                    include_song_list=self._project.ma_export.ma2_include_song_list,
                    template_page=self._project.ma_export.ma2_template_page,
                    fixed_macro_start=self._project.ma_export.ma2_fixed_macro_start,
                    song_macro_start=self._project.ma_export.ma2_song_macro_start,
                    add_main_preset_cue=self._project.ma_export.ma2_add_main_preset_cue,
                    main_preset_cue_id=self._project.ma_export.ma2_main_preset_cue_id,
                    include_song_views=self._project.ma_export.ma2_include_song_views,
                    view_pool_start=self._project.ma_export.ma2_view_pool_start,
                    effect_pool_start=self._project.ma_export.ma2_effect_pool_start,
                )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Export Failed", str(exc))
            return

        names = "\n".join(f"· {p.name}" for p in list(all_paths.values())[:24])
        if len(all_paths) > 24:
            names += f"\n…{len(all_paths)} files total"
        show_plugin = all_paths.get("show:plugin_xml")
        show_macro = all_paths.get("show:macro") or all_paths.get("show:macro_xml")
        if show_macro is not None and console == "ma3":
            macro_hint = (
                f"\n\nShow-wide Install Macro: {show_macro.name}\n"
                "(Import into the MA3 Macro pool, then run it once)"
            )
        elif show_plugin is not None and console == "ma2":
            macro_hint = (
                f"\n\nShow-wide Install Plugin: {show_plugin.parent.name}/{show_plugin.name}\n"
                "(MA2 Plugin pool → Import the .xml in plugins/ → Go+ to run once)\n"
                "The Plugin will Store/Assign all Sequences, then write and Import Timecode when run\n"
                "(same flow as CuePoints; each song has its own Timecode pool; do not run SetupOnly Macro alone)"
            )
        elif show_macro is not None and console == "ma2":
            macro_hint = (
                f"\n\nShow-wide Setup Macro: {show_macro.parent.name}/{show_macro.name}\n"
                "(Store/Assign only, no Timecode — use the Plugin instead)"
            )
        else:
            macro_hint = ""
        QMessageBox.information(
            self,
            "Export Complete",
            f"Exported {len(self._slots)} song(s) "
            f"(Timecode includes {button_tracks} Button Top track(s)) →\n"
            f"{directory}\n\n{names}{macro_hint}",
        )
        self.export_finished.emit(all_paths)
