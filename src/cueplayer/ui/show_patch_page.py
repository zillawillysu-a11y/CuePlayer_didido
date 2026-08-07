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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from cueplayer.domain.models import MaExportSettings, Project
from cueplayer.exporters.common import sanitize_ma_name
from cueplayer.exporters.ma2 import Ma2Exporter
from cueplayer.exporters.ma3 import Ma3Exporter
from cueplayer.exporters.ma_default_dirs import (
    MA2_MINIMUM_VERSION,
    Ma2Discovery,
    discover_ma2_environment,
    ma2_export_dir_for_version,
    ma2_version_from_path,
    ma2_version_supported,
    resolve_export_dir,
)
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
        self._playlist_refreshing = False
        self._ma2_discovery = Ma2Discovery((), None)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(10)

        title = QLabel("Export · MA Playlist")
        title.setObjectName("maExportTitle")
        hint = QLabel(
            "Choose songs and Pool ranges, configure the console, then review and export."
        )
        hint.setWordWrap(True)
        hint.setObjectName("maExportHint")
        root.addWidget(title)
        root.addWidget(hint)

        self.workflow_tabs = QTabWidget()
        self.workflow_tabs.setObjectName("maExportWorkflowTabs")
        self.songs_page = QWidget()
        self.registry_page = QWidget()
        self.setup_page = QWidget()
        self.view_page = QWidget()
        self.review_page = QWidget()
        self.songs_page_layout = QVBoxLayout(self.songs_page)
        self.registry_page_layout = QVBoxLayout(self.registry_page)
        self.setup_page_layout = QVBoxLayout(self.setup_page)
        self.view_page_layout = QVBoxLayout(self.view_page)
        self.review_page_layout = QVBoxLayout(self.review_page)
        for layout in (
            self.songs_page_layout,
            self.registry_page_layout,
            self.setup_page_layout,
            self.view_page_layout,
            self.review_page_layout,
        ):
            layout.setContentsMargins(16, 16, 16, 16)
            layout.setSpacing(14)
        self.workflow_tabs.addTab(self.songs_page, "1  Songs & Pools")
        self.workflow_tabs.addTab(self.registry_page, "2  Export Registry")
        self.workflow_tabs.addTab(self.setup_page, "3  Console Setup")
        self.workflow_tabs.addTab(self.view_page, "4  View Layout")
        self.workflow_tabs.addTab(self.review_page, "5  Review & Export")
        root.addWidget(self.workflow_tabs, stretch=1)
        self.setStyleSheet(
            "ShowPatchPage { background: #0d0f12; color: #eef2f7; }"
            "#maExportTitle { font-size: 22px; font-weight: 700; color: #eef2f7; }"
            "#maExportHint { color: #99a3b1; }"
            "QTabWidget::pane { border: 1px solid #2b313a; background: #15181d; top: -1px; }"
            "QTabBar::tab { background: #0d0f12; color: #99a3b1; border: 1px solid transparent; "
            "padding: 9px 16px; min-width: 130px; }"
            "QTabBar::tab:selected { background: #15181d; color: #eef2f7; border-color: #2b313a; "
            "border-bottom-color: #15181d; }"
            "QGroupBox { background: #15181d; border: 1px solid #2b313a; border-radius: 8px; "
            "margin-top: 10px; padding: 14px 10px 10px; color: #eef2f7; font-weight: 600; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }"
            "QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { background: #101318; color: #eef2f7; "
            "border: 1px solid #38414d; border-radius: 6px; min-height: 32px; padding: 2px 8px; }"
            "QPushButton { background: #1b1f25; color: #eef2f7; border: 1px solid #2b313a; "
            "border-radius: 7px; min-height: 32px; padding: 0 13px; }"
            "QPushButton:hover { border-color: #4a5565; }"
            "QTableWidget, QListWidget { background: #15181d; alternate-background-color: #191d23; "
            "color: #eef2f7; border: 1px solid #2b313a; border-radius: 7px; gridline-color: #2b313a; }"
            "QHeaderView::section { background: #1b1f25; color: #99a3b1; border: none; "
            "border-right: 1px solid #2b313a; border-bottom: 1px solid #2b313a; padding: 8px; }"
            "QLabel { color: #eef2f7; }"
        )

        self.chain_label = QLabel("")
        self.chain_label.setWordWrap(True)
        self.chain_label.setStyleSheet(
            "background: #111113; border: 1px solid #27272a; border-radius: 8px;"
            "padding: 10px 12px; color: #a1a1aa; font-family: Consolas, 'Courier New', monospace;"
        )
        self.songs_page_layout.addWidget(self.chain_label)

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
        self.ma2_version = QComboBox()
        self.ma2_version.setEditable(True)
        self.ma2_version.addItems([MA2_MINIMUM_VERSION, "3.9.60", "3.9.61", "3.9.63.6"])
        self.ma2_detect_btn = QPushButton("Detect MA2")
        self.ma2_detect_status = QLabel("Not detected")
        self.ma2_detect_status.setStyleSheet("color: #8b949e;")
        console_layout.addWidget(self.ma2_version)
        console_layout.addWidget(self.ma2_detect_btn)
        console_layout.addWidget(self.ma2_detect_status)
        settings_row.addWidget(console_box)

        pool_box = QGroupBox("Pool Start")
        pool_form = QFormLayout(pool_box)
        self.seq_start = NoWheelSpinBox()
        self.seq_start.setRange(1, 9999)
        self.seq_start.setValue(1)
        self.tc_start = NoWheelSpinBox()
        self.tc_start.setRange(1, 9999)
        self.tc_start.setValue(201)
        pool_form.addRow("Sequence", self.seq_start)
        pool_form.addRow("Timecode", self.tc_start)
        settings_row.addWidget(pool_box)

        fader_box = QGroupBox("Fader (Executor)")
        fader_form = QFormLayout(fader_box)
        self.main_fader = QLineEdit("201.130")
        self.button_fader = QLineEdit("201.101")
        self.main_fader.setPlaceholderText("201.130")
        self.button_fader.setPlaceholderText("201.101")
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
        self.setup_page_layout.addLayout(settings_row)

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
        self.ma2_template_page.setValue(200)
        self.ma2_fixed_macro_start = NoWheelSpinBox()
        self.ma2_fixed_macro_start.setRange(1, 9999)
        self.ma2_fixed_macro_start.setValue(101)
        self.ma2_song_macro_start = NoWheelSpinBox()
        self.ma2_song_macro_start.setRange(1, 9999)
        self.ma2_song_macro_start.setValue(201)
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
        self.ma2_sequence_slots = NoWheelSpinBox()
        self.ma2_sequence_slots.setRange(1, 9999)
        self.ma2_sequence_slots.setValue(20)
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
        opt_form.addRow("MA2 Sequence Slots Per Song", self.ma2_sequence_slots)
        opt_form.addRow(self.ma2_fixed_macros)
        opt_form.addRow(self.ma2_song_macros)
        opt_form.addRow(self.ma2_song_list)
        opt_row.addWidget(opt_box)

        out_box = QGroupBox("Output Folder")
        out_layout = QVBoxLayout(out_box)
        out_row = QHBoxLayout()
        self.out_dir = QLineEdit()
        browse = QPushButton("Browse…")
        restore = QPushButton("Use Version Default")
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
        opt_row.setAlignment(out_box, Qt.AlignmentFlag.AlignTop)
        self.setup_page_layout.addLayout(opt_row)
        self.setup_page_layout.addStretch(1)

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
        self.songs_page_layout.addWidget(song_box)
        song_box.hide()

        self.playlist_table = QTableWidget(0, 9)
        self.playlist_table.setObjectName("maExportPlaylistTable")
        self.playlist_table.setHorizontalHeaderLabels(
            ["Export", "Song Order", "Song", "MA Export Name", "Sequence", "Effects", "Timecode", "Marks", "Content"]
        )
        self.playlist_table.verticalHeader().setVisible(False)
        self.playlist_table.setAlternatingRowColors(True)
        self.playlist_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.playlist_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.playlist_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.playlist_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.playlist_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.playlist_table.setColumnWidth(0, 58)
        self.playlist_table.setColumnWidth(1, 88)
        self.playlist_table.setColumnWidth(4, 105)
        self.playlist_table.setColumnWidth(5, 115)
        self.playlist_table.setColumnWidth(6, 82)
        self.playlist_table.setColumnWidth(7, 82)
        self.playlist_table.setColumnWidth(8, 130)
        self.songs_page_layout.addWidget(self.playlist_table, stretch=1)

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
        self.table.hide()
        songs_nav = QHBoxLayout()
        songs_nav.addWidget(self.song_all_btn)
        songs_nav.addWidget(self.song_none_btn)
        songs_nav.addStretch(1)
        songs_next = QPushButton("Export Registry  →")
        songs_next.clicked.connect(lambda: self.workflow_tabs.setCurrentIndex(1))
        songs_nav.addWidget(songs_next)
        self.songs_page_layout.addLayout(songs_nav)

        registry_intro = QLabel(
            "Existing allocations stay stable. Live MA2 scanning will feed this page through "
            "the validated Registry synchronization interface."
        )
        registry_intro.setWordWrap(True)
        registry_intro.setStyleSheet("color: #8b949e; padding: 4px;")
        self.registry_page_layout.addWidget(registry_intro)
        live_scan_box = QGroupBox("MA2 Live Pool Scan")
        live_scan_layout = QVBoxLayout(live_scan_box)
        live_scan_fields = QHBoxLayout()
        self.registry_host = QLineEdit("127.0.0.1")
        self.registry_version = QLineEdit(MA2_MINIMUM_VERSION)
        self.registry_version.setReadOnly(True)
        self.registry_command_port = NoWheelSpinBox()
        self.registry_command_port.setRange(1, 65535)
        self.registry_command_port.setValue(30000)
        self.registry_monitor_port = NoWheelSpinBox()
        self.registry_monitor_port.setRange(1, 65535)
        self.registry_monitor_port.setValue(30001)
        self.registry_user = QLineEdit("CuePlayerScan")
        self.registry_password = QLineEdit()
        self.registry_password.setEchoMode(QLineEdit.EchoMode.Password)
        for label_text, widget in (
            ("MA2 Host", self.registry_host),
            ("Target Version", self.registry_version),
            ("Command", self.registry_command_port),
            ("Monitor", self.registry_monitor_port),
            ("User", self.registry_user),
            ("Password", self.registry_password),
        ):
            field = QVBoxLayout()
            label = QLabel(label_text)
            label.setStyleSheet("color: #99a3b1; font-size: 11px;")
            field.addWidget(label)
            field.addWidget(widget)
            live_scan_fields.addLayout(
                field,
                stretch=2 if label_text in ("MA2 Host", "User", "Password") else 1,
            )
        live_scan_layout.addLayout(live_scan_fields)
        live_scan_actions = QHBoxLayout()
        self.registry_scan_status = QLabel(
            "Not connected · Telnet integration is not enabled yet"
        )
        self.registry_scan_status.setStyleSheet(
            "background: #101318; color: #99a3b1; border-radius: 6px; padding: 9px;"
        )
        test_connection = QPushButton("Test Connection")
        scan_show = QPushButton("Scan Current Show")
        for button in (test_connection, scan_show):
            button.setEnabled(False)
            button.setToolTip(
                "Telnet transport is planned after the interface workflow is approved"
            )
        live_scan_actions.addWidget(self.registry_scan_status, stretch=1)
        live_scan_actions.addWidget(test_connection)
        live_scan_actions.addWidget(scan_show)
        live_scan_layout.addLayout(live_scan_actions)
        self.registry_page_layout.addWidget(live_scan_box)

        registry_summary_layout = QHBoxLayout()
        self.registry_summary_labels: list[QLabel] = []
        for text in (
            "Registered Songs\n0",
            "Next Sequence\n1",
            "Next Effects\n201",
            "Next IDs\n201",
        ):
            label = QLabel(text)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet(
                "background: #15181d; border: 1px solid #2b313a; border-radius: 8px; "
                "padding: 10px; font-weight: 600;"
            )
            self.registry_summary_labels.append(label)
            registry_summary_layout.addWidget(label)
        self.registry_page_layout.addLayout(registry_summary_layout)
        self.registry_status = QLabel("Registry preview · based on the current export selection")
        self.registry_status.setStyleSheet(
            "background: #111113; border: 1px solid #27272a; border-radius: 6px; "
            "padding: 10px; color: #a1a1aa;"
        )
        self.registry_page_layout.addWidget(self.registry_status)
        self.registry_table = QTableWidget(0, 7)
        self.registry_table.setHorizontalHeaderLabels(
            ["Song", "Status", "Sequence", "Effects", "Timecode", "Song Macro", "View"]
        )
        self.registry_table.verticalHeader().setVisible(False)
        self.registry_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.registry_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.registry_page_layout.addWidget(self.registry_table, stretch=1)
        registry_nav = QHBoxLayout()
        registry_back = QPushButton("←  Songs & Pools")
        registry_next = QPushButton("Console Setup  →")
        registry_back.clicked.connect(lambda: self.workflow_tabs.setCurrentIndex(0))
        registry_next.clicked.connect(lambda: self.workflow_tabs.setCurrentIndex(2))
        registry_nav.addWidget(registry_back)
        registry_nav.addStretch(1)
        registry_nav.addWidget(registry_next)
        self.registry_page_layout.addLayout(registry_nav)

        view_intro = QLabel(
            "Screen 3 is fixed at 16 × 8. Each cell represents one MA Pool slot, and every "
            "Pool title consumes the first cell of its window."
        )
        view_intro.setWordWrap(True)
        view_intro.setStyleSheet("color: #8b949e; padding: 4px;")
        self.view_page_layout.addWidget(view_intro)
        self.view_grid = QTableWidget(8, 16)
        self.view_grid.setObjectName("ma2Screen3Grid")
        self.view_grid.horizontalHeader().setVisible(False)
        self.view_grid.verticalHeader().setVisible(False)
        self.view_grid.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.view_grid.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.view_grid.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.view_grid.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.view_page_layout.addWidget(self.view_grid, stretch=1)

        review_intro = QLabel(
            "Review the selected songs, Pool allocation, Console target, and output folder "
            "before generating the MA files."
        )
        review_intro.setWordWrap(True)
        review_intro.setStyleSheet("color: #8b949e; padding: 4px;")
        self.review_page_layout.addWidget(review_intro)
        self.review_summary = QLabel("")
        self.review_summary.setWordWrap(True)
        self.review_summary.setStyleSheet(
            "background: #111113; border: 1px solid #27272a; border-radius: 8px; "
            "padding: 12px; color: #e5e7eb;"
        )
        self.review_page_layout.addWidget(self.review_summary)
        self.review_table = QTableWidget(0, 6)
        self.review_table.setHorizontalHeaderLabels(
            ["Order", "Song", "Sequence", "Effects", "Timecode", "Marks"]
        )
        self.review_table.verticalHeader().setVisible(False)
        self.review_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.review_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.review_page_layout.addWidget(self.review_table, stretch=1)

        setup_nav = QHBoxLayout()
        setup_back = QPushButton("←  Export Registry")
        setup_next = QPushButton("View Layout  →")
        setup_back.clicked.connect(lambda: self.workflow_tabs.setCurrentIndex(1))
        setup_next.clicked.connect(lambda: self.workflow_tabs.setCurrentIndex(3))
        setup_nav.addWidget(setup_back)
        setup_nav.addStretch(1)
        setup_nav.addWidget(setup_next)
        self.setup_page_layout.addLayout(setup_nav)

        view_nav = QHBoxLayout()
        view_back = QPushButton("←  Console Setup")
        view_next = QPushButton("Review & Export  →")
        view_back.clicked.connect(lambda: self.workflow_tabs.setCurrentIndex(2))
        view_next.clicked.connect(lambda: self.workflow_tabs.setCurrentIndex(4))
        view_nav.addWidget(view_back)
        view_nav.addStretch(1)
        view_nav.addWidget(view_next)
        self.view_page_layout.addLayout(view_nav)

        action_row = QHBoxLayout()
        review_back = QPushButton("←  View Layout")
        self.refresh_btn = QPushButton("Refresh Patch")
        self.export_btn = QPushButton("Export Checked Songs…")
        self.export_btn.setStyleSheet(
            "QPushButton { height: 34px; padding: 0 16px; font-weight: 650;"
            " background: #3b82f6; border: 1px solid #3b82f6; border-radius: 7px; color: white; }"
            "QPushButton:hover { background: #2563eb; }"
            "QPushButton:pressed { background: #1d4ed8; }"
        )
        review_back.clicked.connect(lambda: self.workflow_tabs.setCurrentIndex(3))
        action_row.addWidget(review_back)
        action_row.addWidget(self.refresh_btn)
        action_row.addStretch(1)
        action_row.addWidget(self.export_btn)
        self.review_page_layout.addLayout(action_row)

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
            self.ma2_sequence_slots,
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
        self.playlist_table.itemChanged.connect(self._on_playlist_item_changed)
        self.ma2_version.currentTextChanged.connect(self._on_ma2_version_changed)
        self.ma2_detect_btn.clicked.connect(self._detect_ma2_versions)
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
        self._detect_ma2_versions(quiet=True)
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
        self._rebuild_playlist_table()
        self._rebuild_table()
        self._rebuild_chain()
        self._rebuild_workflow_pages()

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

    def _rebuild_playlist_table(self) -> None:
        if self._project is None:
            self.playlist_table.setRowCount(0)
            return
        checked_ids = {
            str(self.song_pick.item(row).data(Qt.ItemDataRole.UserRole) or "")
            for row in range(self.song_pick.count())
            if self.song_pick.item(row) is not None
            and self.song_pick.item(row).checkState() == Qt.CheckState.Checked
        }
        settings = self._project.ma_export
        seq_slots = max(1, int(settings.ma2_sequence_slots_per_song))
        self._playlist_refreshing = True
        self.playlist_table.setRowCount(len(self._project.songs))
        for row, song in enumerate(self._project.songs):
            export_item = QTableWidgetItem()
            export_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            export_item.setCheckState(
                Qt.CheckState.Checked if song.id in checked_ids else Qt.CheckState.Unchecked
            )
            export_item.setData(Qt.ItemDataRole.UserRole, song.id)
            export_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.playlist_table.setItem(row, 0, export_item)
            sequence_start = int(settings.sequence_pool_start) + row * seq_slots
            effect_start = int(settings.ma2_effect_pool_start) + row * 100
            main_marks = sum(1 for mark in song.marks if mark.lane_index == 1)
            button_marks = sum(1 for mark in song.marks if mark.lane_index != 1)
            ma_name = sanitize_ma_name(song.ma_export_name or song.name, fallback="Song")
            values = (
                str(row + 1),
                song.name,
                ma_name,
                f"{sequence_start}–{sequence_start + seq_slots - 1}",
                f"{effect_start}–{effect_start + 99}",
                str(int(settings.timecode_pool_start) + row),
                str(len(song.marks)),
                f"Main + {button_marks} Button" if button_marks else f"Main · {main_marks} cues",
            )
            for column, value in enumerate(values, start=1):
                item = QTableWidgetItem(value)
                if column in (1, 4, 5, 6, 7):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if column == 2:
                    item.setToolTip(song.name)
                self.playlist_table.setItem(row, column, item)
            self.playlist_table.setRowHeight(row, 54)
        self._playlist_refreshing = False

    def _on_playlist_item_changed(self, item: QTableWidgetItem) -> None:
        if self._playlist_refreshing or self._suppress or item.column() != 0:
            return
        song_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        for row in range(self.song_pick.count()):
            source = self.song_pick.item(row)
            if source is not None and str(source.data(Qt.ItemDataRole.UserRole) or "") == song_id:
                source.setCheckState(item.checkState())
                break

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

    def _detect_ma2_versions(self, _checked: bool = False, *, quiet: bool = False) -> None:
        self._ma2_discovery = discover_ma2_environment()
        versions = {item.version for item in self._ma2_discovery.installations}
        if self._ma2_discovery.running_version:
            versions.add(self._ma2_discovery.running_version)
        if self._project and self._project.ma_export.ma2_target_version:
            versions.add(self._project.ma_export.ma2_target_version)
        versions.update({MA2_MINIMUM_VERSION, "3.9.60", "3.9.61", "3.9.63.6"})
        selected = (
            self._project.ma_export.ma2_target_version
            if self._project and self._project.ma_export.ma2_target_version
            else self._ma2_discovery.recommended_version or MA2_MINIMUM_VERSION
        )
        self.ma2_version.blockSignals(True)
        self.ma2_version.clear()
        self.ma2_version.addItems(
            sorted(versions, key=lambda value: tuple(int(n) for n in value.split(".")))
        )
        self.ma2_version.setCurrentText(selected)
        self.ma2_version.blockSignals(False)
        self.registry_version.setText(selected)
        installed = ", ".join(item.version for item in self._ma2_discovery.installations) or "none"
        running = self._ma2_discovery.running_version or "not running"
        self.ma2_detect_status.setText(f"Running {running} · Installed {installed}")
        if not ma2_version_supported(selected):
            self.ma2_detect_status.setText(
                f"Unsupported {selected} · minimum {MA2_MINIMUM_VERSION}"
            )
            self.ma2_detect_status.setStyleSheet("color: #f87171;")
        else:
            self.ma2_detect_status.setStyleSheet("color: #8b949e;")
        if self._project:
            self._project.ma_export.ma2_target_version = selected
            if self._project.ma_export.ma2_output_dir_follows_version:
                self._apply_version_default_dir(selected, quiet=quiet)

    def _apply_version_default_dir(self, version: str, *, quiet: bool = False) -> bool:
        path = ma2_export_dir_for_version(version, self._ma2_discovery.installations)
        if path is None:
            if not quiet:
                QMessageBox.information(
                    self,
                    "Version Folder Not Found",
                    f"No installed gma2_V_* folder matches MA2 {version}. Choose a folder manually.",
                )
            return False
        self._suppress = True
        self.out_dir.setText(str(path))
        self._suppress = False
        if self._project:
            self._project.ma_export.output_dir_ma2 = str(path)
            self._project.ma_export.ma2_output_dir_follows_version = True
        self._update_out_hint()
        return True

    def _on_ma2_version_changed(self, version: str) -> None:
        if self._suppress or self._project is None:
            return
        version = version.strip()
        self._project.ma_export.ma2_target_version = version
        self.registry_version.setText(version)
        if not ma2_version_supported(version):
            self.ma2_detect_status.setText(
                f"Unsupported {version} · minimum {MA2_MINIMUM_VERSION}"
            )
            self.ma2_detect_status.setStyleSheet("color: #f87171;")
            return
        self.ma2_detect_status.setStyleSheet("color: #8b949e;")
        if self._project.ma_export.ma2_output_dir_follows_version:
            self._apply_version_default_dir(version, quiet=True)
        self.settings_changed.emit()

    def apply_registry_scan_result(
        self,
        *,
        remote_version: str,
        sequence_start: int,
        effect_start: int,
        timecode_start: int,
        song_macro_start: int,
        view_start: int,
        host: str = "MA2",
    ) -> bool:
        """Apply a validated scanner allocation without changing fixed controls."""
        if self._project is None or not ma2_version_supported(remote_version):
            return False
        self._suppress = True
        self.ma2_version.setCurrentText(remote_version)
        self.seq_start.setValue(max(1, sequence_start))
        self.ma2_effect_pool_start.setValue(max(1, effect_start))
        self.tc_start.setValue(max(1, timecode_start))
        self.ma2_song_macro_start.setValue(max(1, song_macro_start))
        self.ma2_view_pool_start.setValue(max(1, view_start))
        self._suppress = False
        self._project.ma_export.ma2_target_version = remote_version
        if self._project.ma_export.ma2_output_dir_follows_version:
            self._apply_version_default_dir(remote_version, quiet=True)
        self._write_ui_to_settings()
        self.ma2_detect_status.setText(
            f"Registry synchronized from {host} · MA2 {remote_version}"
        )
        self.registry_version.setText(remote_version)
        self.registry_scan_status.setText(
            f"Registry synchronized · {host} · Remote MA2 {remote_version}"
        )
        self.refresh()
        self.settings_changed.emit()
        return True

    def _load_settings_into_ui(self) -> None:
        if self._project is None:
            return
        s = self._project.ma_export
        self._suppress = True
        self.ma3_radio.setChecked(s.console == "ma3")
        self.ma2_radio.setChecked(s.console != "ma3")
        self.seq_start.setValue(int(s.sequence_pool_start))
        self.tc_start.setValue(int(s.timecode_pool_start))
        self.main_fader.setText(s.main_executor or "201.130")
        self.button_fader.setText(s.button_executor_start or "201.101")
        self.page_per_song.setChecked(bool(s.page_per_song))
        idx = self.mode_combo.findData(s.export_mode)
        self.mode_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.latency_ms.setValue(float(s.latency_ms))
        self.data_pool.setText(s.data_pool or "Default")
        self.show_macro_name.setText(
            s.show_install_macro_name or _DEFAULT_SHOW_MACRO
        )
        self.song_viewbutton.setText(s.ma2_song_viewbutton or "1.20")
        self.ma2_template_page.setValue(int(s.ma2_template_page or 200))
        self.ma2_fixed_macro_start.setValue(int(s.ma2_fixed_macro_start or 101))
        self.ma2_song_macro_start.setValue(int(s.ma2_song_macro_start or 201))
        self.ma2_add_preset_cue.setChecked(bool(s.ma2_add_main_preset_cue))
        self.ma2_preset_cue_id.setValue(float(s.ma2_main_preset_cue_id or 0.5))
        self.ma2_song_views.setChecked(bool(s.ma2_include_song_views))
        self.ma2_view_pool_start.setValue(int(s.ma2_view_pool_start or 201))
        self.ma2_effect_pool_start.setValue(int(s.ma2_effect_pool_start or 201))
        self.ma2_sequence_slots.setValue(int(s.ma2_sequence_slots_per_song or 20))
        self.ma2_fixed_macros.setChecked(bool(s.ma2_include_fixed_macros))
        self.ma2_song_macros.setChecked(bool(s.ma2_include_song_macros))
        self.ma2_song_list.setChecked(bool(s.ma2_include_song_list))
        self.ma2_version.setCurrentText(s.ma2_target_version or MA2_MINIMUM_VERSION)
        remembered = s.output_dir_ma3 if s.console == "ma3" else s.output_dir_ma2
        path = resolve_export_dir(s.console if s.console in ("ma2", "ma3") else "ma2", remembered or None)
        self.out_dir.setText(path)
        self.data_pool.setEnabled(s.console == "ma3")
        self.ma2_version.setEnabled(s.console != "ma3")
        self.ma2_detect_btn.setEnabled(s.console != "ma3")
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
            self.ma2_sequence_slots,
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
        s.main_executor = self.main_fader.text().strip() or "201.130"
        s.button_executor_start = self.button_fader.text().strip() or "201.101"
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
        s.ma2_sequence_slots_per_song = int(self.ma2_sequence_slots.value())
        s.ma2_include_fixed_macros = self.ma2_fixed_macros.isChecked()
        s.ma2_include_song_macros = self.ma2_song_macros.isChecked()
        s.ma2_include_song_list = self.ma2_song_list.isChecked()
        s.ma2_target_version = self.ma2_version.currentText().strip()
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
        if self._console() == "ma2":
            self._project.ma_export.ma2_output_dir_follows_version = False
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
        self.ma2_version.setEnabled(new_console != "ma3")
        self.ma2_detect_btn.setEnabled(new_console != "ma3")
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
            self.ma2_sequence_slots,
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
            mode = (
                "following Target Version"
                if self._project and self._project.ma_export.ma2_output_dir_follows_version
                else "custom folder"
            )
            self.out_hint.setText(
                "MA2: pick gma2_V_*/importexport — "
                "Seq/TC → importexport, Install Plugin → plugins (writes Timecode when run) · "
                + mode
            )
        else:
            self.out_hint.setText(
                "MA3: pick gma3_library (or datapools) — "
                "Sequence → sequences, Timecode → timecodes, Macro → macros"
            )

    def _browse_out(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose Export Folder", self.out_dir.text())
        if path:
            if self._project and self._console() == "ma2":
                self._project.ma_export.ma2_output_dir_follows_version = False
            self.out_dir.setText(path)

    def _restore_default_dir(self) -> None:
        if self._console() == "ma2":
            if self._project:
                self._project.ma_export.ma2_output_dir_follows_version = True
            if self._apply_version_default_dir(self.ma2_version.currentText().strip()):
                self.settings_changed.emit()
            return
        path = resolve_export_dir(self._console(), remembered=None)
        if not path:
            QMessageBox.information(self, "No Default Found", "No grandMA install path was detected on this computer.")
            return
        self.out_dir.setText(path)

    def _rebuild_workflow_pages(self) -> None:
        if self._project is None:
            return
        settings = self._project.ma_export
        slots_per_song = max(1, int(settings.ma2_sequence_slots_per_song))
        effect_slots = 100
        self.registry_table.setRowCount(len(self._slots))
        self.review_table.setRowCount(len(self._slots))
        for row, slot in enumerate(self._slots):
            seq_start = int(slot.main_sequence)
            seq_end = seq_start + slots_per_song - 1
            effect_start = int(settings.ma2_effect_pool_start) + row * effect_slots
            effect_end = effect_start + effect_slots - 1
            macro = int(settings.ma2_song_macro_start) + row
            view = int(settings.ma2_view_pool_start) + row
            registry_values = (
                slot.display_name,
                "Planned",
                f"{seq_start}–{seq_end}",
                f"{effect_start}–{effect_end}",
                str(slot.timecode_pool),
                str(macro),
                str(view),
            )
            for column, value in enumerate(registry_values):
                self.registry_table.setItem(row, column, QTableWidgetItem(value))
            review_values = (
                str(row + 1),
                slot.display_name,
                f"{seq_start}–{seq_end}",
                f"{effect_start}–{effect_end}",
                str(slot.timecode_pool),
                f"{slot.main_cue_count} Main · {slot.button_mark_count} Button",
            )
            for column, value in enumerate(review_values):
                self.review_table.setItem(row, column, QTableWidgetItem(value))
        if self._slots:
            last_row = len(self._slots) - 1
            next_sequence = int(self._slots[last_row].main_sequence) + slots_per_song
            next_effect = int(settings.ma2_effect_pool_start) + len(self._slots) * effect_slots
            next_timecode = int(self._slots[last_row].timecode_pool) + 1
            self.registry_status.setText(
                f"{len(self._slots)} planned song(s) · Next safe starts: Sequence {next_sequence}, "
                f"Effects {next_effect}, Timecode {next_timecode}, "
                f"Song Macro {int(settings.ma2_song_macro_start) + len(self._slots)}, "
                f"View {int(settings.ma2_view_pool_start) + len(self._slots)}"
            )
            self.registry_summary_labels[0].setText(
                f"Registered Songs\n{len(self._slots)}"
            )
            self.registry_summary_labels[1].setText(f"Next Sequence\n{next_sequence}")
            self.registry_summary_labels[2].setText(f"Next Effects\n{next_effect}")
            self.registry_summary_labels[3].setText(f"Next IDs\n{next_timecode}")
        else:
            self.registry_status.setText("No songs selected · no Registry allocation proposed")
            self.registry_summary_labels[0].setText("Registered Songs\n0")
            self.registry_summary_labels[1].setText(
                f"Next Sequence\n{int(settings.sequence_pool_start)}"
            )
            self.registry_summary_labels[2].setText(
                f"Next Effects\n{int(settings.ma2_effect_pool_start)}"
            )
            self.registry_summary_labels[3].setText(
                f"Next IDs\n{int(settings.timecode_pool_start)}"
            )
        target = self.ma2_version.currentText().strip() if self._console() == "ma2" else "grandMA3"
        self.review_summary.setText(
            f"Console: {target}    ·    Selected songs: {len(self._slots)}\n"
            f"Output Folder: {self.out_dir.text().strip() or '(not selected)'}"
        )
        self._rebuild_view_grid()

    def _rebuild_view_grid(self) -> None:
        settings = self._project.ma_export if self._project else MaExportSettings()
        sequence_start = int(self._slots[0].main_sequence) if self._slots else int(settings.sequence_pool_start)
        effect_start = int(settings.ma2_effect_pool_start)
        fixed_effect_start = 1
        for row in range(8):
            for column in range(16):
                item = QTableWidgetItem("")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if row == 0 and column == 0:
                    item.setText("Sequence")
                    item.setBackground(QBrush(QColor("#1e3a8a")))
                elif row == 0 and column < 10:
                    item.setText(str(sequence_start + column - 1))
                    item.setBackground(QBrush(QColor("#172554")))
                elif row == 0 and column == 10:
                    item.setText("Macros")
                    item.setBackground(QBrush(QColor("#6b214d")))
                elif row == 0:
                    item.setText(str(int(settings.ma2_fixed_macro_start) + column - 11))
                    item.setBackground(QBrush(QColor("#4a1635")))
                elif row == 1 and column == 0:
                    item.setText("Effects")
                    item.setBackground(QBrush(QColor("#1e3a8a")))
                elif 1 <= row <= 5:
                    offset = (row - 1) * 16 + column - 1
                    item.setText(str(effect_start + offset))
                    item.setBackground(QBrush(QColor("#172554")))
                elif row == 6 and column == 0:
                    item.setText("Effects")
                    item.setBackground(QBrush(QColor("#6b214d")))
                else:
                    offset = (row - 6) * 16 + column - 1
                    item.setText(str(fixed_effect_start + offset))
                    item.setBackground(QBrush(QColor("#4a1635")))
                item.setForeground(QBrush(QColor("#f8fafc")))
                self.view_grid.setItem(row, column, item)

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
        if self._console() == "ma2":
            target_version = self.ma2_version.currentText().strip()
            if not ma2_version_supported(target_version):
                QMessageBox.warning(
                    self,
                    "Unsupported grandMA2 Version",
                    f"grandMA2 {target_version} is below the supported minimum {MA2_MINIMUM_VERSION}.",
                )
                return
            folder_version = ma2_version_from_path(out)
            if folder_version and tuple(int(n) for n in folder_version.split("."))[:3] != tuple(
                int(n) for n in target_version.split(".")
            )[:3]:
                QMessageBox.warning(
                    self,
                    "MA2 Version / Folder Mismatch",
                    f"Target Version is {target_version}, but Output Folder belongs to {folder_version}.",
                )
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
                    sequence_slots_per_song=self._project.ma_export.ma2_sequence_slots_per_song,
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
