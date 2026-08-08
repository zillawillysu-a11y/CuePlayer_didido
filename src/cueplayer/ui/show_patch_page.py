"""MA Show Patch page — Sequence chain + Fader assignment for the whole show."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QStandardPaths, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
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
    QFrame,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from cueplayer.domain.models import MaExportSettings, Project
from cueplayer.exporters.common import parse_page_executor, sanitize_ma_name
from cueplayer.exporters.ma2 import Ma2Exporter
from cueplayer.exporters.ma2_telnet import Ma2TelnetError, Ma2TelnetScanner
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
    pool_collisions,
)
from cueplayer.ui.dnd_mime import EXPORT_SONG_IDS_MIME
from cueplayer.ui.row_color import ROLE_ROW_COLOR, RowColorDelegate
from cueplayer.ui.ma2_view_layout import (
    TIMECODE_POOL_TOTAL_CELLS,
    Ma2ViewLayoutStage,
    default_view_layout,
)
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
_EXPORT_SONG_IDS_MIME = EXPORT_SONG_IDS_MIME

# Fixed order/labels for the "Export Content Check" checkbox set, shared by
# Console Setup's Export Options (the real, functional checkboxes), Review &
# Export's read/write mirror (self.review_macro_checks, synced by index —
# see _on_review_export_option_toggled), and the Export confirm dialog.
# Keep all three in this exact order if it ever changes.
_EXPORT_CONTENT_CHECK_LABELS = (
    "Song List Sequence",
    "Fixed control Macros",
    "Song Macro",
    "Song View",
    "Add Main Cue named Preset",
)

# Manual Pool Starts (Review & Export): every one of the 7 Pool Start
# spinboxes ends up this tall — the shared QSS rule for QSpinBox
# ("min-height: 32px; padding: 2px 8px; border: 1px solid ...") computes
# 32 + 4 (padding) + 2 (border) = 38px, and that CSS-driven minimum wins
# over any smaller setFixedHeight()/setMaximumHeight() call in code, so
# fighting it produces exactly the unstable squeeze this page used to have.
_MANUAL_POOL_FIELD_HEIGHT = 38
# Each grid row reserves the field height plus this gap, as ONE combined
# hard-floor row minimum (see the QGridLayout comment below for why the
# gap is folded in rather than left as separate, squeezable spacing).
_MANUAL_POOL_ROW_SPACING = 8
_MANUAL_POOL_ROW_HEIGHT = _MANUAL_POOL_FIELD_HEIGHT + _MANUAL_POOL_ROW_SPACING

# View Layout Pool Types with a matching per-song Pool Start in Console
# Setup — only these can "Follow Console Setup's per-song Pool Start".
_FOLLOWABLE_POOL_TYPES = {"sequence", "effects", "groups", "timecode", "macros"}

# Display labels for the manual per-song Pool override keys used in
# MaExportSettings.ma2_pool_overrides / SongPatchSlot / pool_collisions().
POOL_COLLISION_LABELS = {
    "sequence": "Sequence",
    "effects": "Effects",
    "groups": "Groups",
    "timecode": "Timecode",
    "view": "View",
    "page": "Page",
    "song_macro": "Song Macro",
}


class ExportQueueList(QListWidget):
    """Drop target for Set List songs; the queue order is the export order."""

    song_ids_dropped = Signal(list)

    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:  # noqa: ANN001
        if event.mimeData().hasFormat(_EXPORT_SONG_IDS_MIME):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: ANN001
        if event.mimeData().hasFormat(_EXPORT_SONG_IDS_MIME):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: ANN001
        if event.mimeData().hasFormat(_EXPORT_SONG_IDS_MIME):
            payload = bytes(event.mimeData().data(_EXPORT_SONG_IDS_MIME)).decode("utf-8")
            self.song_ids_dropped.emit([song_id for song_id in payload.splitlines() if song_id])
            event.acceptProposedAction()
            return
        super().dropEvent(event)


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
        self._review_table_refreshing = False
        self._expanded_content_song_ids: set[str] = set()
        self._ma2_discovery = Ma2Discovery((), None)
        # Set by MainWindow so the CSV Save As dialog can default to the
        # folder holding the current CuePlayer Project file. None (unsaved
        # project) falls back to a Documents-style location.
        self.project_file_path_provider: Callable[[], Path | None] | None = None

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
        # Console Setup only: a few px back from margins/gaps between its
        # 3 stacked sections (settings_row / opt_row / setup_nav) — every
        # px here is one this page doesn't need a whole-page scroll for at
        # a maximized 1920x1080. Other tabs keep the shared 16/14 above.
        self.setup_page_layout.setContentsMargins(16, 10, 16, 10)
        self.setup_page_layout.setSpacing(8)
        def _scrollable(page: QWidget) -> QScrollArea:
            """Tab content that scrolls instead of clipping.

            Console Setup and View Layout are naturally wider than a small
            laptop window and have no internal auto-scrolling widget of their
            own, so without this their overflowing controls (the Pool Start
            fields, Group included) were simply unreachable — no scrollbar,
            just cut off.

            Songs & Pools / Export Registry / Review & Export are deliberately
            NOT wrapped this way: each already has its own large QTableWidget,
            which is itself a scrolling widget. Wrapping the whole page would
            let that table's layout claim unlimited height instead of the
            tab's actual viewport height, so the *entire page* scrolled
            instead of just the table — exactly the behaviour this must avoid.
            """
            area = QScrollArea()
            area.setWidget(page)
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            return area

        self.workflow_tabs.addTab(self.songs_page, "1  Songs & Pools")
        self.workflow_tabs.addTab(self.registry_page, "2  Export Registry")
        self.workflow_tabs.addTab(_scrollable(self.setup_page), "3  Console Setup")
        self.workflow_tabs.addTab(_scrollable(self.view_page), "4  View Layout")
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
            # Windows' native groupbox chrome paints the title sub-control
            # with an opaque theme background unless a stylesheet says
            # otherwise — without this, group titles like "MA2 Live Pool
            # Scan" show a dark rectangle that doesn't match the panel
            # behind them.
            "QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; "
            "background: transparent; }"
            "QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { background: #101318; color: #eef2f7; "
            "border: 1px solid #38414d; border-radius: 6px; min-height: 32px; padding: 2px 8px; }"
            "QPushButton { background: #1b1f25; color: #eef2f7; border: 1px solid #2b313a; "
            "border-radius: 7px; min-height: 32px; padding: 0 13px; }"
            "QPushButton:hover { border-color: #4a5565; }"
            "QTableWidget, QListWidget { background: #15181d; alternate-background-color: #191d23; "
            "color: #eef2f7; border: 1px solid #2b313a; border-radius: 7px; gridline-color: #2b313a; }"
            "QHeaderView::section { background: #1b1f25; color: #99a3b1; border: none; "
            "border-right: 1px solid #2b313a; border-bottom: 1px solid #2b313a; padding: 8px; }"
            "QLabel { color: #eef2f7; background: transparent; border: none; }"
            "QCheckBox { background: transparent; }"
            "#maExportOptions QCheckBox { background: transparent; }"
            "#reviewExportContent QCheckBox { background: transparent; padding: 3px 6px; }"
            "#reviewExportContent { background: #15181d; border: 1px solid #2b313a; border-radius: 6px; }"
        )

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
        # Placeholder only — set_project() -> _detect_ma2_versions() clears
        # and repopulates this from the real detected installations before
        # the page is ever shown to a user. Never mix a real detected
        # version with a made-up generic one in the same list.
        self.ma2_version.addItem(MA2_MINIMUM_VERSION)
        # Holds a short version string like "3.9.63.6" — no need for the
        # ~348px its longest item would otherwise reserve.
        self.ma2_version.setMaximumWidth(150)
        self.ma2_detect_btn = QPushButton("Detect MA2")
        self.ma2_detect_status = QLabel("Not detected")
        # This label holds a long line ("Running … · Installed 3.1.2, 3.3.4,
        # 3.9.60, …"). Unconstrained it demanded ~816px, which alone forced
        # the Console box to 1400px and the whole page to a 2824px minimum
        # width — so the Pool Start fields (Group included) ended up outside
        # a normal window and could not be clicked at all.
        self.ma2_detect_status.setWordWrap(True)
        self.ma2_detect_status.setMaximumWidth(300)
        self.ma2_detect_status.setMinimumHeight(40)
        self.ma2_detect_status.setStyleSheet("color: #8b949e;")
        console_layout.addWidget(self.ma2_version)
        console_layout.addWidget(self.ma2_detect_btn)
        console_layout.addWidget(self.ma2_detect_status)
        settings_row.addWidget(console_box)

        pool_box = QGroupBox("Pool Start")
        pool_form = QGridLayout(pool_box)
        pool_form.setHorizontalSpacing(14)
        pool_form.setVerticalSpacing(6)
        self.seq_start = NoWheelSpinBox()
        self.seq_start.setRange(1, 9999)
        self.seq_start.setValue(1)
        self.tc_start = NoWheelSpinBox()
        self.tc_start.setRange(1, 9999)
        self.tc_start.setValue(201)
        self.ma2_effect_pool_start = NoWheelSpinBox()
        self.ma2_effect_pool_start.setRange(1, 9999)
        self.ma2_effect_pool_start.setValue(201)
        self.ma2_group_pool_start = NoWheelSpinBox()
        self.ma2_group_pool_start.setRange(1, 9999)
        self.ma2_group_pool_start.setValue(1)
        self.ma2_view_pool_start = NoWheelSpinBox()
        self.ma2_view_pool_start.setRange(1, 9999)
        self.ma2_view_pool_start.setValue(201)
        self.ma2_song_macro_start = NoWheelSpinBox()
        self.ma2_song_macro_start.setRange(1, 9999)
        self.ma2_song_macro_start.setValue(201)
        self.ma2_fixed_macro_start = NoWheelSpinBox()
        self.ma2_fixed_macro_start.setRange(1, 9999)
        self.ma2_fixed_macro_start.setValue(101)
        # Every "first Pool number for X" field lives here, not scattered
        # into Export Options — matches the Sequence/Effects/Groups/
        # Timecode/View/Song Macro ordering used throughout the app.
        pool_start_fields = (
            ("Sequence", self.seq_start),
            ("Effect", self.ma2_effect_pool_start),
            ("Group", self.ma2_group_pool_start),
            ("Timecode", self.tc_start),
            ("View", self.ma2_view_pool_start),
            ("Song Macro", self.ma2_song_macro_start),
            ("Fixed Macro", self.ma2_fixed_macro_start),
        )
        # 4 label/value pairs per row (was 2): at a maximized desktop width
        # this box has plenty of horizontal room, and halving the row count
        # (4 rows -> 2) is real, measurable vertical space back for Console
        # Setup to fit at 1920x1080 without the whole page needing to
        # scroll — see the _scrollable() note near workflow_tabs.addTab.
        _POOL_START_COLS = 4
        for index, (label_text, widget) in enumerate(pool_start_fields):
            row, col = divmod(index, _POOL_START_COLS)
            label = QLabel(label_text)
            label.setStyleSheet("color: #99a3b1; font-size: 11px;")
            # These only ever hold a 1-9999 Pool number. Left free to expand
            # they grew to ~270px each, which pushed later columns off the
            # visible area so those fields could not be clicked at all.
            widget.setMaximumWidth(110)
            pool_form.addWidget(label, row, col * 2)
            pool_form.addWidget(widget, row, col * 2 + 1)
        for col in range(_POOL_START_COLS):
            pool_form.setColumnStretch(col * 2 + 1, 1)
        settings_row.addWidget(pool_box, stretch=2)

        fader_box = QGroupBox("Fader (Executor)")
        # 2 label/value pairs per row (was QFormLayout's 1 per row) — same
        # row-count reduction as Pool Start above, same reason.
        fader_form = QGridLayout(fader_box)
        fader_form.setHorizontalSpacing(14)
        fader_form.setVerticalSpacing(6)
        self.executor_page = NoWheelSpinBox()
        self.executor_page.setRange(1, 9999)
        self.executor_page.setValue(201)
        self.main_executor_number = NoWheelSpinBox()
        self.main_executor_number.setRange(1, 999)
        self.main_executor_number.setValue(130)
        self.button_executor_number = NoWheelSpinBox()
        self.button_executor_number.setRange(1, 999)
        self.button_executor_number.setValue(101)
        self.page_per_song = QCheckBox("Next Page per song (201 → 202 → …)")
        self.page_per_song.setChecked(True)
        self.page_per_song.setToolTip(
            "Each song advances to the next Page. Main stays at .130 and Buttons start at .101."
        )
        for index, (label_text, widget) in enumerate((
            ("Page", self.executor_page),
            ("Main", self.main_executor_number),
            ("Button Start", self.button_executor_number),
        )):
            row, col = divmod(index, 2)
            label = QLabel(label_text)
            label.setStyleSheet("color: #99a3b1; font-size: 11px;")
            widget.setMaximumWidth(110)
            fader_form.addWidget(label, row, col * 2)
            fader_form.addWidget(widget, row, col * 2 + 1)
        fader_form.addWidget(self.page_per_song, 2, 0, 1, 4)
        fader_form.setColumnStretch(1, 1)
        fader_form.setColumnStretch(3, 1)
        settings_row.addWidget(fader_box, stretch=1)
        self.setup_page_layout.addLayout(settings_row)

        opt_row = QHBoxLayout()
        opt_box = QGroupBox("Export Options")
        opt_box.setObjectName("maExportOptions")
        opt_form = QGridLayout(opt_box)
        opt_form.setHorizontalSpacing(14)
        opt_form.setVerticalSpacing(8)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Full (Sequence + Timecode)", "full")
        self.mode_combo.addItem("Timecode Only", "timecode_only")
        self.latency_ms = NoWheelDoubleSpinBox()
        self.latency_ms.setRange(-500.0, 500.0)
        self.latency_ms.setDecimals(1)
        self.latency_ms.setSuffix(" ms")
        self.data_pool = QLineEdit("Default")
        self.show_macro_name = QLineEdit(_DEFAULT_SHOW_MACRO)
        self.show_name = QLineEdit("CuePlayer")
        self.show_name.setPlaceholderText("CuePlayer")
        self.song_viewbutton = QLineEdit("1.20")
        self.song_viewbutton.setPlaceholderText("1.20")
        self.ma2_fixed_macros = QCheckBox("Fixed control Macros")
        self.ma2_song_macros = QCheckBox("Song Macro")
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
        self.ma2_add_preset_cue = QCheckBox("Add Main Cue named Preset")
        self.ma2_preset_cue_id = NoWheelDoubleSpinBox()
        self.ma2_preset_cue_id.setRange(0.001, 9999.999)
        self.ma2_preset_cue_id.setDecimals(3)
        self.ma2_preset_cue_id.setValue(0.5)
        self.ma2_song_views = QCheckBox("Song View")
        self.ma2_song_views.setChecked(True)
        self.ma2_effect_slots = NoWheelSpinBox()
        self.ma2_effect_slots.setRange(1, 9999)
        self.ma2_effect_slots.setValue(100)
        self.ma2_sequence_slots = NoWheelSpinBox()
        self.ma2_sequence_slots.setRange(1, 9999)
        self.ma2_sequence_slots.setValue(20)
        self.ma2_group_slots = NoWheelSpinBox()
        self.ma2_group_slots.setRange(1, 9999)
        self.ma2_group_slots.setValue(20)
        self.show_macro_name.setPlaceholderText(_DEFAULT_SHOW_MACRO)
        self.show_macro_name.setToolTip(
            "Show-wide Install file name (MA3 = Macro; MA2 = Plugin primarily; .xml can be omitted)"
        )
        option_fields = (
            ("Mode", self.mode_combo), ("Show Name", self.show_name), ("Install Name", self.show_macro_name), ("Template Page", self.ma2_template_page),
            ("Sequence Slots Per Song", self.ma2_sequence_slots), ("Group Slots Per Song", self.ma2_group_slots), ("Effect Slots Per Song", self.ma2_effect_slots),
            ("Song ViewButton", self.song_viewbutton), ("Preset Cue ID", self.ma2_preset_cue_id), ("Latency", self.latency_ms),
            ("MA3 Data Pool", self.data_pool),
        )
        # 3 field pairs per row (was 2): this box gets generous width at a
        # maximized desktop (stretch=3 of opt_row's 5), and cutting the row
        # count (11 fields: 6 rows -> 4; 5 checkboxes: 3 rows -> 2) is real
        # vertical space back for Console Setup to fit at 1920x1080 without
        # the whole page needing to scroll.
        _OPTION_COLS = 3
        for index, (label_text, widget) in enumerate(option_fields):
            group_column = (index % _OPTION_COLS) * 2
            group_row = index // _OPTION_COLS
            label = QLabel(label_text)
            label.setStyleSheet("color: #99a3b1; font-size: 11px;")
            opt_form.addWidget(label, group_row, group_column)
            opt_form.addWidget(widget, group_row, group_column + 1)
        checks_row = (len(option_fields) + _OPTION_COLS - 1) // _OPTION_COLS
        # Fixed order/labels shared with Review & Export's "Export Content
        # Check" mirror (see _EXPORT_CONTENT_CHECK_LABELS) and the Export
        # confirm dialog — keep all three in sync if this ever changes.
        for column, checkbox in enumerate((self.ma2_song_list, self.ma2_fixed_macros, self.ma2_song_macros, self.ma2_song_views, self.ma2_add_preset_cue)):
            opt_form.addWidget(checkbox, checks_row + column // _OPTION_COLS, (column % _OPTION_COLS) * 2, 1, 2)
        opt_row.addWidget(opt_box, stretch=3)

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
        # Long single-line hint: unconstrained it demanded ~1620px, which
        # forced Console Setup (and therefore the whole page) to a ~2800px
        # minimum width, pushing the Pool Start fields off any normal window.
        self.out_hint.setWordWrap(True)
        self.out_hint.setMinimumHeight(36)
        self.out_hint.setStyleSheet("color: #8b949e;")
        out_layout.addWidget(self.out_hint)
        opt_row.addWidget(out_box, stretch=2)
        opt_row.setAlignment(out_box, Qt.AlignmentFlag.AlignTop)
        self.setup_page_layout.addLayout(opt_row)
        self.setup_page_layout.addStretch(1)

        songs_content_row = QHBoxLayout()

        song_box = QGroupBox("Export Queue")
        song_box.setMaximumWidth(340)
        song_layout = QVBoxLayout(song_box)
        song_layout.addWidget(
            QLabel("Drag songs — or a whole folder — from the Setlist panel; drop order = export order")
        )
        self.song_pick = ExportQueueList()
        self.song_pick.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.song_pick.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.song_pick.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.song_pick.setItemDelegate(RowColorDelegate(self.song_pick))
        song_layout.addWidget(self.song_pick, stretch=1)
        pick_btns = QHBoxLayout()
        self.song_all_btn = QPushButton("Check All")
        self.song_none_btn = QPushButton("Clear Queue")
        pick_btns.addWidget(self.song_all_btn)
        pick_btns.addWidget(self.song_none_btn)
        song_layout.addLayout(pick_btns)
        songs_content_row.addWidget(song_box)

        self.playlist_table = QTableWidget(0, 11)
        self.playlist_table.setObjectName("maExportPlaylistTable")
        self.playlist_table.setHorizontalHeaderLabels(
            ["Export", "Song Order", "Song", "Export Name", "Sequence", "Effects", "Groups", "Timecode", "Page", "Marks", "Content"]
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
        self.playlist_table.setColumnWidth(6, 105)
        self.playlist_table.setColumnWidth(7, 82)
        self.playlist_table.setColumnWidth(8, 70)
        self.playlist_table.setColumnWidth(9, 82)
        self.playlist_table.setColumnWidth(10, 130)
        songs_content_row.addWidget(self.playlist_table, stretch=1)
        self.songs_page_layout.addLayout(songs_content_row, stretch=1)

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
        # registry_left_widget already caps this column's width below — this
        # box just fills it, matching every other box in that column instead
        # of double-constraining its own width.
        live_scan_layout = QVBoxLayout(live_scan_box)
        live_scan_fields = QGridLayout()
        live_scan_fields.setContentsMargins(0, 0, 0, 0)
        live_scan_fields.setHorizontalSpacing(12)
        live_scan_fields.setVerticalSpacing(6)
        self.registry_host = QLineEdit("127.0.0.1")
        self.registry_version = QLineEdit(MA2_MINIMUM_VERSION)
        self.registry_version.setReadOnly(True)
        self.registry_command_port = NoWheelSpinBox()
        self.registry_command_port.setRange(1, 65535)
        self.registry_command_port.setValue(30000)
        self.registry_monitor_port = NoWheelSpinBox()
        self.registry_monitor_port.setRange(1, 65535)
        self.registry_monitor_port.setValue(30001)
        self.registry_user = QLineEdit("administrator")
        # grandMA2's own stock login default — a convenience starting point,
        # not persisted (see MaExportSettings.ma2_telnet_user docstring).
        self.registry_password = QLineEdit("admin")
        self.registry_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.registry_plugin_pool = NoWheelSpinBox()
        self.registry_plugin_pool.setRange(2, 9999)
        self.registry_plugin_pool.setValue(9999)
        self.registry_plugin_import_path = QLineEdit()
        for index, (label_text, widget) in enumerate((
            ("MA2 Host", self.registry_host),
            ("Target Version", self.registry_version),
            ("Command", self.registry_command_port),
            ("Monitor", self.registry_monitor_port),
            ("MA2 Show User", self.registry_user),
            ("Password", self.registry_password),
            ("Plugin Pool", self.registry_plugin_pool),
        )):
            field_widget = QWidget()
            field_widget.setObjectName("maLiveScanField")
            field = QVBoxLayout(field_widget)
            field.setContentsMargins(0, 0, 0, 0)
            field.setSpacing(2)
            label = QLabel(label_text)
            label.setStyleSheet("color: #99a3b1; font-size: 11px; background: transparent;")
            field.addWidget(label)
            field.addWidget(widget)
            row, col = divmod(index, 2)
            live_scan_fields.addWidget(field_widget, row, col)
        live_scan_layout.addLayout(live_scan_fields)
        plugin_path_row = QHBoxLayout()
        plugin_path_row.setContentsMargins(0, 0, 0, 0)
        plugin_path_label = QLabel("MA2 Plugin Import Path (optional)")
        plugin_path_label.setStyleSheet("color: #99a3b1; font-size: 11px;")
        self.registry_plugin_import_path.setPlaceholderText(
            "Leave blank for local MA2 onPC; use only for a remote console"
        )
        plugin_path_row.addWidget(plugin_path_label)
        plugin_path_row.addWidget(self.registry_plugin_import_path, stretch=1)
        live_scan_layout.addLayout(plugin_path_row)
        self.registry_telnet_lights = QLabel()
        self._set_telnet_status("idle")
        live_scan_layout.addWidget(self.registry_telnet_lights)
        self.registry_scan_status = QLabel(
            "Ready · write and import the read-only scanner Plugin before scanning"
        )
        self.registry_scan_status.setWordWrap(True)
        self.registry_scan_status.setStyleSheet(
            "background: #101318; color: #99a3b1; border-radius: 6px; padding: 9px;"
        )
        live_scan_layout.addWidget(self.registry_scan_status)
        self.registry_write_scan_plugin = QPushButton("Write Scan Plugin")
        self.registry_import_and_scan = QPushButton("Import Plugin & Scan")
        self.registry_test_connection = QPushButton("Test Connection")
        self.registry_scan_show = QPushButton("Scan Current Show")
        self.registry_write_scan_plugin.setToolTip(
            "Write the read-only CuePlayer Live Scan Plugin to the MA2 plugins folder"
        )
        self.registry_test_connection.setToolTip(
            "Connect to the MA2 Command Telnet port without changing the show"
        )
        self.registry_import_and_scan.setToolTip(
            "Import the scanner at the chosen Plugin Pool, then run it. This can overwrite that Pool ID."
        )
        self.registry_scan_show.setToolTip(
            "Run the installed read-only scanner Plugin and read its System Monitor frame"
        )
        self.registry_write_scan_plugin.clicked.connect(self._write_live_scan_plugin)
        self.registry_import_and_scan.clicked.connect(self._import_scan_plugin_and_scan)
        self.registry_test_connection.clicked.connect(self._test_ma2_telnet_connection)
        self.registry_scan_show.clicked.connect(self._scan_ma2_show)
        # 2x2 grid instead of one packed row — the narrower Telnet box no
        # longer has room to show all four button labels on one line.
        live_scan_actions = QGridLayout()
        live_scan_actions.setContentsMargins(0, 0, 0, 0)
        live_scan_actions.setHorizontalSpacing(8)
        live_scan_actions.setVerticalSpacing(6)
        for index, button in enumerate((
            self.registry_write_scan_plugin,
            self.registry_import_and_scan,
            self.registry_test_connection,
            self.registry_scan_show,
        )):
            row, col = divmod(index, 2)
            live_scan_actions.addWidget(button, row, col)
        live_scan_layout.addLayout(live_scan_actions)

        self.registry_start_after_scanned = QCheckBox("Start after scanned Pools")
        self.registry_start_after_scanned.setToolTip(
            "Push every Pool start (Sequence, Effects, Groups, Timecode, View, "
            "Song Macro) past the highest number the last scan found on the "
            "console, so this export cannot overwrite existing show objects.\n"
            "While this is on, manual per-song Pool overrides are ignored so "
            "the numbers can actually move. Turn it off for a normal export "
            "from the configured starts."
        )
        self.registry_start_after_scanned.toggled.connect(self._on_start_after_scanned_toggled)
        live_scan_layout.addWidget(self.registry_start_after_scanned)

        registry_content_row = QHBoxLayout()
        registry_left_widget = QWidget()
        registry_left_widget.setMaximumWidth(360)
        registry_left_column = QVBoxLayout(registry_left_widget)
        registry_left_column.setContentsMargins(0, 0, 0, 0)
        registry_left_column.addWidget(live_scan_box)
        registry_left_column.addStretch(1)
        registry_content_row.addWidget(registry_left_widget)

        registry_middle_widget = QWidget()
        registry_middle_widget.setMaximumWidth(200)
        registry_middle_column = QVBoxLayout(registry_middle_widget)
        registry_middle_column.setContentsMargins(0, 0, 0, 0)
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
            registry_middle_column.addWidget(label)
        self.registry_status = QLabel("Registry preview · based on the current export selection")
        self.registry_status.setWordWrap(True)
        self.registry_status.setStyleSheet(
            "background: #111113; border: 1px solid #27272a; border-radius: 6px; "
            "padding: 10px; color: #a1a1aa;"
        )
        registry_middle_column.addWidget(self.registry_status)
        registry_middle_column.addStretch(1)
        registry_content_row.addWidget(registry_middle_widget)

        self.registry_table = QTableWidget(0, 11)
        self.registry_table.setHorizontalHeaderLabels(
            ["Order", "Song", "Export Name", "Status", "Sequence", "Effects", "Groups", "Timecode", "View", "Page", "Song Macro"]
        )
        self.registry_table.verticalHeader().setVisible(False)
        self.registry_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.registry_table.setColumnWidth(0, 56)
        self.registry_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.registry_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        # Left/middle are capped by setMaximumWidth above — the Song List
        # (registry_table) absorbs all remaining width so it's fully visible.
        registry_content_row.addWidget(self.registry_table, stretch=1)
        self.registry_page_layout.addLayout(registry_content_row, stretch=1)

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
            "Design the Screen 3 template. Drag Pool windows, resize from the lower-right "
            "corner, or enter exact values in the Inspector."
        )
        view_intro.setWordWrap(True)
        view_intro.setStyleSheet("color: #8b949e; padding: 4px;")
        self.view_page_layout.addWidget(view_intro)
        view_content = QHBoxLayout()
        view_stage_card = QGroupBox("Screen 3 Template")
        view_stage_layout = QVBoxLayout(view_stage_card)
        view_toolbar = QHBoxLayout()
        self.view_preview_song = QComboBox()
        self.view_preview_song.setMinimumWidth(230)
        self.view_add_pool = QPushButton("Add Pool")
        self.view_duplicate_pool = QPushButton("Duplicate")
        self.view_delete_pool = QPushButton("Delete")
        self.view_lock_layout = QCheckBox("Lock layout")
        self.view_reset_layout = QPushButton("Reset")
        for widget in (self.view_preview_song, self.view_add_pool, self.view_duplicate_pool, self.view_delete_pool):
            view_toolbar.addWidget(widget)
        view_toolbar.addStretch(1)
        view_toolbar.addWidget(QLabel("Required 16 × 8 grid"))
        view_toolbar.addWidget(self.view_lock_layout)
        view_toolbar.addWidget(self.view_reset_layout)
        view_stage_layout.addLayout(view_toolbar)
        self.view_stage = Ma2ViewLayoutStage()
        view_stage_layout.addWidget(self.view_stage, stretch=1)
        legend = QLabel("Fixed Pool range   |   Per Song unique Pool range   |   One shared layout for every song")
        legend.setWordWrap(True)
        legend.setStyleSheet("color: #99a3b1; padding: 5px;")
        view_stage_layout.addWidget(legend)
        view_content.addWidget(view_stage_card, stretch=1)

        view_inspector = QGroupBox("Pool Inspector")
        inspector_form = QFormLayout(view_inspector)
        self.view_pool_type = QComboBox()
        for key, label in (
            ("camera", "Camera Pool"),
            ("effects", "Effects"),
            ("filters", "Filters"),
            ("forms", "Forms"),
            ("groups", "Groups"),
            ("images", "Images"),
            ("layout", "Layout Pool"),
            ("macros", "Macros"),
            ("masks", "Masks"),
            ("matricks", "MAtricks"),
            ("pagesChannel", "Pages Channel"),
            ("pagesExec", "Pages Exec"),
            ("sequence", "Sequence"),
            ("timecode", "Timecode Pool"),
            ("timecodeSlots", "Timecode Slots Pool"),
            ("timer", "Timer"),
            ("views", "Views"),
            ("universes", "Universes"),
            ("worlds", "Worlds"),
        ):
            self.view_pool_type.addItem(label, key)
        self.view_pool_mode = QComboBox()
        self.view_pool_mode.addItem("Fixed · same numbers", "fixed")
        self.view_pool_mode.addItem("Per Song · unique numbers", "perSong")
        self.view_pool_follow = QCheckBox("Follow Console Setup's per-song Pool Start")
        self.view_pool_follow.setToolTip(
            "Pool Start / Reserved Slots Per Song mirror Console Setup's Pool "
            "Start for this Pool Type, and update live as you switch Preview Song."
        )
        self.view_pool_number_start = NoWheelSpinBox()
        self.view_pool_stride = NoWheelSpinBox()
        self.view_pool_x = NoWheelSpinBox()
        self.view_pool_y = NoWheelSpinBox()
        self.view_pool_width = NoWheelSpinBox()
        self.view_pool_height = NoWheelSpinBox()
        for spin in (self.view_pool_number_start, self.view_pool_stride):
            spin.setRange(1, 9999)
        self.view_pool_x.setRange(0, 15)
        self.view_pool_y.setRange(0, 7)
        self.view_pool_width.setRange(1, 16)
        self.view_pool_height.setRange(1, 8)
        inspector_form.addRow("Pool Type", self.view_pool_type)
        inspector_form.addRow("Pool Allocation", self.view_pool_mode)
        inspector_form.addRow(self.view_pool_follow)
        inspector_form.addRow("Pool Start", self.view_pool_number_start)
        inspector_form.addRow("Reserved Slots Per Song", self.view_pool_stride)
        # Screen 3 geometry is edited directly by dragging/resizing the Pool
        # window on the 16 x 8 stage; keep these values out of the inspector.
        self.view_allocation_status = QLabel("")
        self.view_allocation_status.setWordWrap(True)
        inspector_form.addRow("Status", self.view_allocation_status)
        view_inspector.setMaximumWidth(330)
        view_content.addWidget(view_inspector)
        self.view_page_layout.addLayout(view_content, stretch=1)

        review_intro = QLabel(
            "Review the selected songs, Pool allocation, Console target, and output folder "
            "before generating the MA files."
        )
        review_intro.setWordWrap(True)
        review_intro.setStyleSheet("color: #8b949e; padding: 4px;")
        self.review_page_layout.addWidget(review_intro)

        review_content_row = QHBoxLayout()
        review_left_widget = QWidget()
        review_left_widget.setMaximumWidth(340)
        review_left_column = QVBoxLayout(review_left_widget)
        review_left_column.setContentsMargins(0, 0, 0, 0)

        macro_review_box = QGroupBox("Export Content Check")
        macro_review_box.setObjectName("reviewExportContent")
        macro_review_layout = QVBoxLayout(macro_review_box)
        self.review_macro_checks = []
        for index, label in enumerate(_EXPORT_CONTENT_CHECK_LABELS):
            check = QCheckBox(label)
            check.toggled.connect(
                lambda checked, check_index=index: self._on_review_export_option_toggled(check_index, checked)
            )
            self.review_macro_checks.append(check)
            macro_review_layout.addWidget(check)
        review_left_column.addWidget(macro_review_box)

        manual_box = QGroupBox("Manual Pool Starts")
        # The explanation lives in a tooltip, NOT a word-wrapped QLabel above
        # the fields: a wrapped QLabel under-reports its sizeHint height, so
        # the parent under-allocates and the rows below get crushed.
        manual_box.setToolTip(
            "Leave a field blank to leave that Pool alone. Fill only Timecode, "
            "for example, and Auto-Fill renumbers just the Timecode column.\n"
            "Or double-click any cell in the table to pin one song's own "
            "starting number; collisions with another song are highlighted."
        )
        # Fixed vertical policy: this box always requests exactly its
        # sizeHint, so a sibling that grows (the wrapped summary label below
        # it gets longer after Auto-Fill) can never squeeze these rows into
        # each other. In a window too short for every widget's preferred
        # size, Qt's shrink pass can still take a few px back from this box
        # (there is no scroll fallback on this tab — see the QScrollArea
        # note near workflow_tabs.addTab), which shows up as slightly
        # tighter row spacing (never overlap: setRowMinimumHeight below is
        # a genuine floor for each row's field, confirmed by measurement
        # down to a 1280x700 window). Every field's own fixed size is what
        # is actually unbreakable; see the geometry regression test.
        manual_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        manual_layout = QVBoxLayout(manual_box)
        # Same setting as the Export Registry copy, mirrored here so it can be
        # reached without leaving the page you actually export from.
        self.review_start_after_scanned = QCheckBox("Start after scanned Pools")
        self.review_start_after_scanned.setToolTip(
            "Push every Pool start past the highest number the last scan found "
            "on the console. Ticking it clears existing per-song pins so the "
            "numbers can move; anything you pin or Auto-Fill afterwards wins."
        )
        self.review_start_after_scanned.toggled.connect(self._on_start_after_scanned_toggled)
        manual_layout.addWidget(self.review_start_after_scanned)
        manual_hint = QLabel("Blank = leave that Pool unchanged")
        manual_hint.setStyleSheet("background: transparent; color: #8b949e; font-size: 11px;")
        manual_layout.addWidget(manual_hint)
        # A QGridLayout with an explicit per-row minimum height, not
        # QFormLayout: QFormLayout sizes each row from the label/field
        # sizeHint, which is a heuristic that can under-report by a few
        # pixels per row on real Windows font metrics — with 7 rows that
        # heuristic error accumulates into visible squeeze/overlap even
        # though every field already has a fixed size.
        #
        # The inter-row gap is folded into each row's own minimum height
        # (_MANUAL_POOL_ROW_HEIGHT already includes it) instead of using
        # QGridLayout's separate setVerticalSpacing(): a row's minimum
        # height is a genuine hard floor Qt's layout engine will not shrink
        # below even when this box is squeezed for space in a short window,
        # but *inter-row spacing* set via setVerticalSpacing is only a
        # preference and gets squeezed first — which produced inconsistent
        # row pitch (46px at a tall window, 42-43px at a short one) even
        # though no row ever actually overlapped. Zero explicit spacing +
        # every row already tall enough to include its own gap makes the
        # pitch between rows exactly _MANUAL_POOL_ROW_HEIGHT, always.
        manual_fields_form = QGridLayout()
        manual_fields_form.setContentsMargins(0, 0, 0, 0)
        manual_fields_form.setHorizontalSpacing(12)
        manual_fields_form.setVerticalSpacing(0)
        self.review_pool_start_fields = {}
        for row, (label_text, attr) in enumerate((
            ("Sequence", "seq_start"),
            ("Effect", "effect_start"),
            ("Timecode", "timecode_start"),
            ("Group", "group_start"),
            ("Macro", "macro_start"),
            ("View", "view_start"),
            ("Page", "page_start"),
        )):
            field = NoWheelSpinBox()
            # 0 renders blank (Qt shows specialValueText at the minimum) and
            # means "don't touch this Pool" — see _auto_fill_pool_overrides.
            field.setRange(0, 9999)
            field.setSpecialValueText(" ")
            field.setValue(0)
            # Width is only ever set here (QSS has no min-width rule for
            # QSpinBox), but height matches _MANUAL_POOL_FIELD_HEIGHT — the
            # actual height the shared QSS min-height/padding/border already
            # forces, so this doesn't fight the stylesheet, just pins width
            # too and blocks the grid from ever stretching either dimension.
            field.setFixedSize(90, _MANUAL_POOL_FIELD_HEIGHT)
            field.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            field.setToolTip(
                f"Auto-Fill start for the {label_text} column. Leave blank to "
                f"leave {label_text} untouched."
            )
            self.review_pool_start_fields[attr] = field
            manual_fields_form.setRowMinimumHeight(row, _MANUAL_POOL_ROW_HEIGHT)
            label = QLabel(label_text)
            label.setStyleSheet("color: #99a3b1; background: transparent;")
            manual_fields_form.addWidget(
                label, row, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            manual_fields_form.addWidget(
                field, row, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
        manual_layout.addLayout(manual_fields_form)
        # A guaranteed gap between the Page row and the buttons below, so the
        # last field row can never read as touching/overlapping them.
        manual_layout.addSpacing(10)
        autofill_row = QHBoxLayout()
        autofill_row.setContentsMargins(0, 0, 0, 0)
        self.review_autofill_btn = QPushButton("Auto-Fill && Sequence")
        self.review_autofill_btn.setToolTip(
            "Write a per-song override for every song in the queue, starting "
            "from the numbers above and advancing by each Pool's configured "
            "slots/song (Timecode, View, and Song Macro advance by 1)."
        )
        self.review_clear_overrides_btn = QPushButton("Clear All Overrides")
        autofill_row.addWidget(self.review_autofill_btn)
        autofill_row.addWidget(self.review_clear_overrides_btn)
        autofill_row.addStretch(1)
        manual_layout.addLayout(autofill_row)
        self.review_autofill_btn.clicked.connect(self._auto_fill_pool_overrides)
        self.review_clear_overrides_btn.clicked.connect(self._clear_pool_overrides)
        review_left_column.addWidget(manual_box)

        # One compact line — Console/song count/Output Folder only. The
        # longer detail (Groups reserved, Show scan max IDs, manual-override
        # pin count) that used to fill this box as several paragraphs is now
        # a tooltip on this same label, so the left column stays short enough
        # to fit a normal window without needing the whole page to scroll.
        self.review_summary = QLabel("")
        self.review_summary.setWordWrap(True)
        self.review_summary.setStyleSheet(
            "background: #111113; border: 1px solid #27272a; border-radius: 8px; "
            "padding: 8px 12px; color: #e5e7eb;"
        )
        review_left_column.addWidget(self.review_summary)
        review_left_column.addStretch(1)
        review_content_row.addWidget(review_left_widget)

        self.review_table = QTableWidget(0, 11)
        self.review_table.setHorizontalHeaderLabels(
            ["Order", "Song", "Export Name", "Sequence", "Effects", "Groups", "Timecode", "View", "Page", "Song Macro", "Marks"]
        )
        self.review_table.verticalHeader().setVisible(False)
        self.review_table.setColumnWidth(0, 56)
        # Order/Chinese/Song/Marks stay read-only; the six Pool columns (3-8)
        # accept a manual per-song start via double-click — see
        # _on_review_table_item_edited.
        self.review_table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.EditKeyPressed
        )
        self.review_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.review_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.review_table.itemChanged.connect(self._on_review_table_item_edited)
        # review_left_widget is capped by setMaximumWidth above — the table
        # absorbs all remaining width so it's fully visible.
        review_content_row.addWidget(self.review_table, stretch=1)
        self.review_page_layout.addLayout(review_content_row, stretch=1)

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
        self.export_csv_btn = QPushButton("Export Allocation Report (CSV)…")
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
        action_row.addWidget(self.export_csv_btn)
        action_row.addStretch(1)
        action_row.addWidget(self.export_btn)
        self.review_page_layout.addLayout(action_row)

        for widget in (
            self.seq_start,
            self.tc_start,
            self.executor_page,
            self.main_executor_number,
            self.button_executor_number,
            self.page_per_song,
            self.mode_combo,
            self.latency_ms,
            self.data_pool,
            self.show_macro_name,
            self.show_name,
            self.song_viewbutton,
            self.ma2_template_page,
            self.ma2_fixed_macro_start,
            self.ma2_song_macro_start,
            self.ma2_add_preset_cue,
            self.ma2_preset_cue_id,
            self.ma2_song_views,
            self.ma2_view_pool_start,
            self.ma2_effect_pool_start,
            self.ma2_effect_slots,
            self.ma2_sequence_slots,
            self.ma2_group_slots,
            self.ma2_group_pool_start,
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

        self.view_preview_song.currentIndexChanged.connect(self._on_view_song_changed)
        self.view_stage.selection_changed.connect(self._load_view_inspector)
        self.view_stage.layout_changed.connect(self._on_view_layout_changed)
        self.view_add_pool.clicked.connect(self._add_view_pool)
        self.view_duplicate_pool.clicked.connect(self._duplicate_view_pool)
        self.view_delete_pool.clicked.connect(self._delete_view_pool)
        self.view_reset_layout.clicked.connect(self._reset_view_layout)
        self.view_lock_layout.toggled.connect(self._set_view_layout_locked)
        for widget in (self.view_pool_type, self.view_pool_mode):
            widget.currentIndexChanged.connect(self._update_selected_view_pool)
        self.view_pool_follow.toggled.connect(self._update_selected_view_pool)
        for widget in (
            self.view_pool_number_start,
            self.view_pool_stride,
            self.view_pool_x,
            self.view_pool_y,
            self.view_pool_width,
            self.view_pool_height,
        ):
            widget.valueChanged.connect(self._update_selected_view_pool)

        self.out_dir.textChanged.connect(self._on_out_dir_edited)
        self.playlist_table.itemChanged.connect(self._on_playlist_item_changed)
        self.song_pick.song_ids_dropped.connect(self._add_songs_to_export_queue)
        self.song_pick.model().rowsMoved.connect(lambda *_args: self._on_song_pick_changed())
        self.ma2_version.currentTextChanged.connect(self._on_ma2_version_changed)
        self.ma2_detect_btn.clicked.connect(self._detect_ma2_versions)
        self.ma2_radio.toggled.connect(self._on_console_toggled)
        self.ma3_radio.toggled.connect(self._on_console_toggled)
        self.song_pick.itemChanged.connect(self._on_song_pick_changed)
        self.song_all_btn.clicked.connect(lambda: self._set_all_songs(True))
        self.song_none_btn.clicked.connect(lambda: self._set_all_songs(False))
        self.refresh_btn.clicked.connect(self.refresh)
        self.export_csv_btn.clicked.connect(self._export_allocation_report_csv)
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
            return
        self._write_ui_to_settings()
        songs = self._checked_songs()
        self._slots = build_show_patch(songs, self._project.ma_export)
        # Now that the real allocation exists, pull any "Follow Console Setup"
        # View Layout Pool onto it — that is what makes the View track a
        # manual per-song edit, Auto-Fill, or Start after scanned Pools.
        if self._sync_following_view_pools():
            self._project.ma_export.ma2_view_layout = [
                dict(widget) for widget in self.view_stage.widgets
            ]
        self._rebuild_playlist_table()
        self._rebuild_table()
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
        queued_songs = self._checked_songs()
        checked_ids = {song.id for song in queued_songs}
        settings = self._project.ma_export
        seq_slots = max(1, int(settings.ma2_sequence_slots_per_song))
        effect_slots = max(1, int(settings.ma2_effect_slots_per_song))
        group_slots = max(1, int(settings.ma2_group_slots_per_song))
        # self._slots was just (re)built from this same queued_songs list in
        # refresh() — reuse it so overrides are reflected everywhere at once.
        slots_by_song_id = {slot.song.id: slot for slot in self._slots}
        self._playlist_refreshing = True
        self.playlist_table.setRowCount(len(queued_songs) * 2)
        for row, song in enumerate(queued_songs):
            main_row = row * 2
            content_row = main_row + 1
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
            self.playlist_table.setItem(main_row, 0, export_item)
            slot = slots_by_song_id.get(song.id)
            if slot is not None:
                sequence_start = int(slot.main_sequence)
                effect_start = int(slot.effect_start)
                group_start = int(slot.group_start)
                timecode_start = int(slot.timecode_pool)
                page = int(slot.page)
            else:
                sequence_start = int(settings.sequence_pool_start) + row * seq_slots
                effect_start = int(settings.ma2_effect_pool_start) + row * effect_slots
                group_start = int(settings.ma2_group_pool_start) + row * group_slots
                timecode_start = int(settings.timecode_pool_start) + row
                fallback_page0, _fallback_exec = parse_page_executor(settings.main_executor or "1.101")
                page = fallback_page0 + row if bool(settings.page_per_song) else fallback_page0
            ma_name = sanitize_ma_name(song.ma_export_name or song.name, fallback="Song")
            values = (
                str(row + 1),
                song.name,
                ma_name,
                f"{sequence_start}–{sequence_start + seq_slots - 1}",
                f"{effect_start}–{effect_start + effect_slots - 1}",
                f"{group_start}–{group_start + group_slots - 1}",
                str(timecode_start),
                str(page),
                str(len(song.marks)),
                self._content_summary(song),
            )
            for column, value in enumerate(values, start=1):
                if column == 10:
                    button = QPushButton(value)
                    button.setObjectName("maExportContentButton")
                    button.setToolTip("Show or hide Main and Button export options")
                    button.clicked.connect(
                        lambda _checked=False, song_id=song.id:
                        self._toggle_content_details(song_id)
                    )
                    self.playlist_table.setCellWidget(main_row, column, button)
                    continue
                item = QTableWidgetItem(value)
                if column in (1, 4, 5, 6, 7, 8, 9):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if column == 2:
                    item.setToolTip(song.name)
                self.playlist_table.setItem(main_row, column, item)
            self.playlist_table.setRowHeight(main_row, 38)
            self.playlist_table.setSpan(content_row, 0, 1, 11)
            self.playlist_table.setCellWidget(
                content_row, 0, self._build_content_detail(song)
            )
            expanded = song.id in self._expanded_content_song_ids
            self.playlist_table.setRowHidden(content_row, not expanded)
            self.playlist_table.setRowHeight(content_row, 66 if expanded else 0)
        self._playlist_refreshing = False

    def _content_selection(self, song_id: str) -> tuple[bool, set[int] | None]:
        """Return one song's selection; missing Button data means every Button."""
        if self._project is None:
            return True, None
        raw = self._project.ma_export.export_content_by_song.get(song_id, {})
        include_main = bool(raw.get("main", True))
        buttons = raw.get("buttons")
        return (
            include_main,
            {int(value) for value in buttons} if isinstance(buttons, list) else None,
        )

    def _available_button_lanes(self, song):
        return [
            lane for lane in sorted(song.mark_lanes, key=lambda item: item.index)
            if not lane.cue_id_enabled and lane.export_enabled
            and any(mark.lane_index == lane.index for mark in song.marks)
        ]

    def _content_summary(self, song) -> str:
        include_main, selected_buttons = self._content_selection(song.id)
        available = self._available_button_lanes(song)
        selected_count = len(available) if selected_buttons is None else sum(
            lane.index in selected_buttons for lane in available
        )
        total = 1 + len(available)
        selected = int(include_main) + selected_count
        return f"{selected}/{total} selected"

    def _toggle_content_details(self, song_id: str) -> None:
        if song_id in self._expanded_content_song_ids:
            self._expanded_content_song_ids.remove(song_id)
        else:
            self._expanded_content_song_ids.add(song_id)
        self._rebuild_playlist_table()

    def _build_content_detail(self, song) -> QWidget:
        include_main, selected_buttons = self._content_selection(song.id)
        panel = QWidget()
        panel.setObjectName("maExportContentDetail")
        panel.setStyleSheet(
            "#maExportContentDetail { background: #14171b; border-top: 1px solid #2b3138; }"
        )
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(42, 5, 12, 5)
        layout.setSpacing(3)
        title_row = QHBoxLayout()
        title = QLabel("Export Content")
        title.setStyleSheet("font-weight: 700;")
        title_row.addWidget(title)
        hint = QLabel("Export only the required Main/Button Sequences and matching Timecode tracks for this song.")
        hint.setObjectName("maExportHint")
        title_row.addWidget(hint)
        title_row.addStretch(1)
        select_all_button = QPushButton("Select All")
        select_all_button.setObjectName("maExportSelectAllContentButton")
        select_all_button.setToolTip("Check Main and every Button for this song")
        select_all_button.clicked.connect(
            lambda _checked=False, song_id=song.id: self._select_all_content(song_id)
        )
        title_row.addWidget(select_all_button)
        clear_button = QPushButton("Clear Selection")
        clear_button.setObjectName("maExportClearContentButton")
        clear_button.setToolTip("Uncheck Main and every Button for this song")
        clear_button.clicked.connect(
            lambda _checked=False, song_id=song.id: self._clear_content_selection(song_id)
        )
        title_row.addWidget(clear_button)
        layout.addLayout(title_row)
        checks = QHBoxLayout()
        checks.setSpacing(18)
        main_check = QCheckBox("Main")
        main_check.setChecked(include_main)
        main_check.toggled.connect(
            lambda checked, song_id=song.id: self._set_content_main(song_id, checked)
        )
        checks.addWidget(main_check)
        for lane in self._available_button_lanes(song):
            check = QCheckBox(lane.name or f"Mark {lane.index}")
            check.setChecked(selected_buttons is None or lane.index in selected_buttons)
            check.toggled.connect(
                lambda checked, song_id=song.id, lane_index=lane.index:
                self._set_content_button(song_id, lane_index, checked)
            )
            checks.addWidget(check)
        checks.addStretch(1)
        layout.addLayout(checks)
        return panel

    def _select_all_content(self, song_id: str) -> None:
        """Select all exportable Main/Button content for one song."""
        if self._project is None:
            return
        song = next((item for item in self._project.songs if item.id == song_id), None)
        if song is None:
            return
        self._project.ma_export.export_content_by_song[song_id] = {
            "main": True,
            "buttons": [lane.index for lane in self._available_button_lanes(song)],
        }
        self.refresh()
        self.settings_changed.emit()

    def _clear_content_selection(self, song_id: str) -> None:
        """Unselect all exportable content for one song without unchecking the song."""
        if self._project is None:
            return
        self._project.ma_export.export_content_by_song[song_id] = {
            "main": False,
            "buttons": [],
        }
        self.refresh()
        self.settings_changed.emit()

    def _set_content_main(self, song_id: str, checked: bool) -> None:
        if self._project is None:
            return
        setting = self._project.ma_export.export_content_by_song.setdefault(song_id, {})
        setting["main"] = bool(checked)
        self.refresh()
        self.settings_changed.emit()

    def _set_content_button(self, song_id: str, lane_index: int, checked: bool) -> None:
        if self._project is None:
            return
        include_main, selected = self._content_selection(song_id)
        song = next((item for item in self._project.songs if item.id == song_id), None)
        if selected is None and song is not None:
            selected = {lane.index for lane in self._available_button_lanes(song)}
        selected = selected or set()
        if checked:
            selected.add(lane_index)
        else:
            selected.discard(lane_index)
        setting = self._project.ma_export.export_content_by_song.setdefault(song_id, {})
        setting["main"] = include_main
        setting["buttons"] = sorted(selected)
        self.refresh()
        self.settings_changed.emit()

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
            self.view_preview_song.clear()
            return
        selected_ids = [
            song_id for song_id in self._project.ma_export.export_song_ids
            if any(song.id == song_id for song in self._project.songs)
        ]
        songs_by_id = {song.id: song for song in self._project.songs}
        self.song_pick.blockSignals(True)
        self.song_pick.clear()
        for song_id in selected_ids:
            song = songs_by_id[song_id]
            en = sanitize_ma_name(song.ma_export_name or song.name, fallback="Song")
            label = en if not song.name or song.name == en else f"{song.name}  ·  {en}"
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, song.id)
            item.setData(ROLE_ROW_COLOR, song.row_color or "")
            self.song_pick.addItem(item)
        self.song_pick.blockSignals(False)
        preview_index = max(0, self.view_preview_song.currentIndex())
        self.view_preview_song.blockSignals(True)
        self.view_preview_song.clear()
        for position, song in enumerate(self._project.songs, start=1):
            self.view_preview_song.addItem(f"{position}. {song.name}", song.id)
        if self.view_preview_song.count():
            self.view_preview_song.setCurrentIndex(
                min(preview_index, self.view_preview_song.count() - 1)
            )
        self.view_preview_song.blockSignals(False)

    def _add_songs_to_export_queue(self, song_ids: list[str]) -> None:
        if self._project is None:
            return
        current = [
            str(self.song_pick.item(row).data(Qt.ItemDataRole.UserRole) or "")
            for row in range(self.song_pick.count())
            if self.song_pick.item(row) is not None
        ]
        valid = {song.id for song in self._project.songs}
        for song_id in song_ids:
            if song_id in valid and song_id not in current:
                current.append(song_id)
        self._project.ma_export.export_song_ids = current
        self._rebuild_song_pick()
        self.refresh()
        self.settings_changed.emit()

    def _set_all_songs(self, checked: bool) -> None:
        if not checked:
            if self._project is not None:
                self._project.ma_export.export_song_ids = []
                # Rebuild the queue widget itself (empty), not just the setting —
                # otherwise the still-checked items survive and
                # _write_ui_to_settings() re-derives export_song_ids from them
                # on the very next refresh(), silently undoing the clear.
                self._rebuild_song_pick()
                self.refresh()
                self.settings_changed.emit()
            return
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
        # installed_versions already IS the full, deduplicated, real-machine
        # list (Windows uninstall registry + Start Menu/Desktop shortcut
        # targets, each read via the actual .exe's FileVersion so multi-
        # segment builds like 3.9.60.91 survive; the ProgramData library
        # folder scan is only folded in as a per-family fallback there — see
        # merge_installed_ma2_versions). Nothing here re-adds a hardcoded
        # generic/truncated placeholder (that mixing — e.g. a fake "3.9.60"
        # sitting next to the real "3.9.60.91" — was the original bug).
        versions = set(self._ma2_discovery.installed_versions)
        if self._ma2_discovery.running_version:
            versions.add(self._ma2_discovery.running_version)
        if self._project and self._project.ma_export.ma2_target_version:
            versions.add(self._project.ma_export.ma2_target_version)
        if not versions:
            # Nothing detected at all (no MA2 on this machine, or running
            # off-Windows) — a single, clearly-generic fallback so the
            # dropdown isn't empty, never mixed in alongside real versions.
            versions.add(MA2_MINIMUM_VERSION)
        selected = (
            self._project.ma_export.ma2_target_version
            if self._project and self._project.ma_export.ma2_target_version
            else self._ma2_discovery.recommended_version or MA2_MINIMUM_VERSION
        )
        versions.add(selected)
        self.ma2_version.blockSignals(True)
        self.ma2_version.clear()
        self.ma2_version.addItems(
            sorted(versions, key=lambda value: tuple(int(n) for n in re.findall(r"\d+", value)))
        )
        self.ma2_version.setCurrentText(selected)
        self.ma2_version.blockSignals(False)
        self.registry_version.setText(selected)
        # The "Running X · Installed Y, Z, ..." summary was removed here —
        # this label is still used for the unsupported-version warning
        # below (and by _on_ma2_version_changed / apply_registry_scan_result
        # for their own status messages), just not for a version-list dump.
        if not ma2_version_supported(selected):
            self.ma2_detect_status.setText(
                f"Unsupported {selected} · minimum {MA2_MINIMUM_VERSION}"
            )
            self.ma2_detect_status.setStyleSheet("color: #f87171;")
        else:
            self.ma2_detect_status.setText("")
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
        group_start: int | None = None,
        page_start: int | None = None,
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
        # Groups was previously left out entirely, so a scan silently left
        # the Group Pool pointing at numbers the console was already using.
        if group_start is not None:
            self.ma2_group_pool_start.setValue(max(1, group_start))
        if page_start is not None:
            self.executor_page.setValue(max(1, page_start))
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

    def _ma2_telnet_scanner(self) -> Ma2TelnetScanner:
        return Ma2TelnetScanner(
            self.registry_host.text(),
            command_port=int(self.registry_command_port.value()),
            monitor_port=int(self.registry_monitor_port.value()),
        )

    def _set_telnet_status(self, state: str) -> None:
        """Render the three independently useful stages of the MA2 connection."""
        colors = {
            "idle": ("#6e7681", "#6e7681", "#6e7681"),
            "command": ("#3fb950", "#6e7681", "#6e7681"),
            "scanning": ("#3fb950", "#d29922", "#d29922"),
            "ready": ("#3fb950", "#3fb950", "#3fb950"),
            "error": ("#f85149", "#f85149", "#f85149"),
        }
        command, monitor, plugin = colors.get(state, colors["idle"])
        self.registry_telnet_lights.setText(
            "<span style='color:%s'>●</span> Command &nbsp; "
            "<span style='color:%s'>●</span> System Monitor &nbsp; "
            "<span style='color:%s'>●</span> Plugin / Scan" % (command, monitor, plugin)
        )
        self.registry_telnet_lights.setStyleSheet(
            "background: #171b22; color: #c9d1d9; border-radius: 6px; padding: 7px;"
        )

    def _write_live_scan_plugin(self, _checked: bool = False) -> None:
        raw_directory = self.out_dir.text().strip()
        if not raw_directory:
            self.registry_scan_status.setText("Choose an MA2 Output Folder before writing the scanner Plugin")
            return
        directory = Path(raw_directory)
        try:
            paths = Ma2Exporter().write_live_scan_plugin(directory)
        except OSError as exc:
            self.registry_scan_status.setText(f"Could not write scanner Plugin: {exc}")
            return
        local_plugin_folder = str(paths["plugin_xml"].parent)
        if self.registry_plugin_import_path.text().strip() == local_plugin_folder:
            self.registry_plugin_import_path.clear()
        self.registry_scan_status.setText(
            f"Scanner Plugin written: {paths['plugin_xml'].name}. Ready to import at Plugin Pool {self.registry_plugin_pool.value()}."
        )
        self._set_telnet_status("idle")

    def _test_ma2_telnet_connection(self, _checked: bool = False) -> None:
        try:
            feedback = self._ma2_telnet_scanner().test_connection(
                user=self.registry_user.text(), password=self.registry_password.text()
            )
        except Ma2TelnetError as exc:
            self.registry_scan_status.setText(str(exc))
            self._set_telnet_status("error")
            return
        text = (
            f"Connected to {self.registry_host.text().strip()}:{self.registry_command_port.value()} · Login command sent"
        )
        if feedback.strip():
            compact_feedback = " ".join(feedback.split())[:120]
            text += f" · MA2: {compact_feedback}"
        self.registry_scan_status.setText(text)
        self._set_telnet_status("command")

    def _scan_ma2_show(self, _checked: bool = False) -> None:
        try:
            self._set_telnet_status("scanning")
            snapshot = self._ma2_telnet_scanner().scan(
                user=self.registry_user.text(),
                password=self.registry_password.text(),
                plugin_pool=int(self.registry_plugin_pool.value()),
            )
        except Ma2TelnetError as exc:
            self.registry_scan_status.setText(str(exc))
            self._set_telnet_status("error")
            return
        applied = self.apply_registry_scan_result(
            remote_version=snapshot.version,
            sequence_start=snapshot.next_free("sequence"),
            effect_start=snapshot.next_free("effect"),
            timecode_start=snapshot.next_free("timecode"),
            song_macro_start=snapshot.next_free("macro"),
            view_start=snapshot.next_free("view"),
            group_start=snapshot.next_free("group"),
            page_start=snapshot.next_free("page"),
            host=self.registry_host.text().strip(),
        )
        if not applied:
            self.registry_scan_status.setText(
                f"Scan received MA2 {snapshot.version}, which is outside the supported range; settings were not changed."
            )
            self._set_telnet_status("error")
            return
        self._project.ma_export.ma2_scanned_pool_max = {
            "sequence": max(snapshot.sequence, default=0),
            "effect": max(snapshot.effect, default=0),
            "timecode": max(snapshot.timecode, default=0),
            "macro": max(snapshot.macro, default=0),
            "view": max(snapshot.view, default=0),
            "group": max(snapshot.group, default=0),
            "page": max(snapshot.page, default=0),
        }
        self.refresh()
        self.settings_changed.emit()
        self.registry_scan_status.setText(
            f"Scan completed: MA2 {snapshot.version}; "
            f"Groups detected: {len(snapshot.group)}."
        )
        self._set_telnet_status("ready")

    def _import_scan_plugin_and_scan(self, _checked: bool = False) -> None:
        plugin_pool = int(self.registry_plugin_pool.value())
        raw_directory = self.out_dir.text().strip()
        if not raw_directory:
            self.registry_scan_status.setText(
                "Choose an MA2 Output Folder before installing the scanner Plugin."
            )
            return
        try:
            paths = Ma2Exporter().write_live_scan_plugin(Path(raw_directory))
        except OSError as exc:
            self.registry_scan_status.setText(f"Could not write scanner Plugin: {exc}")
            return
        import_path = self.registry_plugin_import_path.text().strip()
        answer = QMessageBox.warning(
            self,
            "Install scanner Plugin",
            f"MA2 Import can overwrite Plugin {plugin_pool}.\n\n"
            "Continue only when you have chosen an empty Plugin Pool number.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        scanner = self._ma2_telnet_scanner()
        try:
            self._set_telnet_status("scanning")
            import_feedback = scanner.import_plugin(
                plugin_pool=plugin_pool,
                import_path=import_path,
                user=self.registry_user.text(),
                password=self.registry_password.text(),
            )
            snapshot = scanner.scan(
                user=self.registry_user.text(),
                password=self.registry_password.text(),
                plugin_pool=plugin_pool,
            )
        except Ma2TelnetError as exc:
            self.registry_scan_status.setText(f"Install/scan failed: {exc}")
            self._set_telnet_status("error")
            return
        applied = self.apply_registry_scan_result(
            remote_version=snapshot.version,
            sequence_start=snapshot.next_free("sequence"),
            effect_start=snapshot.next_free("effect"),
            timecode_start=snapshot.next_free("timecode"),
            song_macro_start=snapshot.next_free("macro"),
            view_start=snapshot.next_free("view"),
            group_start=snapshot.next_free("group"),
            page_start=snapshot.next_free("page"),
            host=self.registry_host.text().strip(),
        )
        if not applied:
            self.registry_scan_status.setText(
                f"Plugin installed, but MA2 {snapshot.version} is unsupported; settings were not changed."
            )
            self._set_telnet_status("error")
            return
        self._project.ma_export.ma2_scanned_pool_max = {
            "sequence": max(snapshot.sequence, default=0),
            "effect": max(snapshot.effect, default=0),
            "timecode": max(snapshot.timecode, default=0),
            "macro": max(snapshot.macro, default=0),
            "view": max(snapshot.view, default=0),
            "group": max(snapshot.group, default=0),
            "page": max(snapshot.page, default=0),
        }
        self.refresh()
        self.settings_changed.emit()
        status_text = (
            f"Plugin {plugin_pool} installed and scan completed successfully. "
            f"Groups detected: {len(snapshot.group)}."
        )
        if import_feedback.strip():
            compact_import_feedback = " ".join(import_feedback.split())[:120]
            status_text += f" MA2: {compact_import_feedback}"
        self.registry_scan_status.setText(status_text)
        self._set_telnet_status("ready")

    def _load_settings_into_ui(self) -> None:
        if self._project is None:
            return
        s = self._project.ma_export
        self._suppress = True
        self.ma3_radio.setChecked(s.console == "ma3")
        self.ma2_radio.setChecked(s.console != "ma3")
        self.seq_start.setValue(int(s.sequence_pool_start))
        self.tc_start.setValue(int(s.timecode_pool_start))
        try:
            page, main_executor = parse_page_executor(s.main_executor or "201.130")
        except ValueError:
            page, main_executor = 201, 130
        try:
            _button_page, button_executor = parse_page_executor(
                s.button_executor_start or "201.101"
            )
        except ValueError:
            button_executor = 101
        self.executor_page.setValue(page)
        self.main_executor_number.setValue(main_executor)
        self.button_executor_number.setValue(button_executor)
        self.page_per_song.setChecked(bool(s.page_per_song))
        idx = self.mode_combo.findData(s.export_mode)
        self.mode_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.latency_ms.setValue(float(s.latency_ms))
        self.data_pool.setText(s.data_pool or "Default")
        self.show_macro_name.setText(
            s.show_install_macro_name or _DEFAULT_SHOW_MACRO
        )
        self.show_name.setText(s.ma2_show_name or "CuePlayer")
        self.song_viewbutton.setText(s.ma2_song_viewbutton or "1.20")
        self.ma2_template_page.setValue(int(s.ma2_template_page or 200))
        self.ma2_fixed_macro_start.setValue(int(s.ma2_fixed_macro_start or 101))
        self.ma2_song_macro_start.setValue(int(s.ma2_song_macro_start or 201))
        self.ma2_add_preset_cue.setChecked(bool(s.ma2_add_main_preset_cue))
        self.ma2_preset_cue_id.setValue(float(s.ma2_main_preset_cue_id or 0.5))
        self.ma2_song_views.setChecked(bool(s.ma2_include_song_views))
        self.ma2_view_pool_start.setValue(int(s.ma2_view_pool_start or 201))
        self.ma2_effect_pool_start.setValue(int(s.ma2_effect_pool_start or 201))
        self.ma2_effect_slots.setValue(int(s.ma2_effect_slots_per_song or 100))
        self.ma2_sequence_slots.setValue(int(s.ma2_sequence_slots_per_song or 20))
        self.ma2_group_slots.setValue(int(s.ma2_group_slots_per_song or 20))
        self.ma2_group_pool_start.setValue(int(s.ma2_group_pool_start or 1))
        self.registry_host.setText(s.ma2_telnet_host or "127.0.0.1")
        self.registry_command_port.setValue(int(s.ma2_telnet_command_port or 30000))
        self.registry_monitor_port.setValue(int(s.ma2_telnet_monitor_port or 30001))
        self.registry_user.setText(s.ma2_telnet_user or "administrator")
        self.registry_plugin_pool.setValue(int(s.ma2_telnet_plugin_pool or 9999))
        self.registry_plugin_import_path.setText(s.ma2_telnet_plugin_import_path or "")
        self._sync_start_after_scanned_checkboxes(bool(s.ma2_start_after_scanned))
        self.view_stage.set_layout(s.ma2_view_layout or self._default_view_layout_for_settings())
        self._load_view_inspector(self.view_stage.selected_index)
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
            self.ma2_effect_slots,
            self.ma2_sequence_slots,
            self.ma2_group_slots,
            self.ma2_group_pool_start,
            self.ma2_fixed_macros,
            self.ma2_song_macros,
            self.ma2_song_list,
            self.registry_host,
            self.registry_command_port,
            self.registry_monitor_port,
            self.registry_user,
            self.registry_plugin_pool,
            self.registry_plugin_import_path,
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
        page = int(self.executor_page.value())
        s.main_executor = f"{page}.{int(self.main_executor_number.value())}"
        s.button_executor_start = f"{page}.{int(self.button_executor_number.value())}"
        s.page_per_song = self.page_per_song.isChecked()
        s.latency_ms = float(self.latency_ms.value())
        s.data_pool = self.data_pool.text().strip() or "Default"
        s.show_install_macro_name = normalize_show_macro_basename(
            self.show_macro_name.text()
        )
        s.ma2_show_name = self.show_name.text().strip() or "CuePlayer"
        s.ma2_song_viewbutton = self.song_viewbutton.text().strip() or "1.20"
        s.ma2_template_page = int(self.ma2_template_page.value())
        s.ma2_fixed_macro_start = int(self.ma2_fixed_macro_start.value())
        s.ma2_song_macro_start = int(self.ma2_song_macro_start.value())
        s.ma2_add_main_preset_cue = self.ma2_add_preset_cue.isChecked()
        s.ma2_main_preset_cue_id = float(self.ma2_preset_cue_id.value())
        s.ma2_include_song_views = self.ma2_song_views.isChecked()
        s.ma2_view_pool_start = int(self.ma2_view_pool_start.value())
        s.ma2_effect_pool_start = int(self.ma2_effect_pool_start.value())
        s.ma2_effect_slots_per_song = int(self.ma2_effect_slots.value())
        s.ma2_sequence_slots_per_song = int(self.ma2_sequence_slots.value())
        s.ma2_group_slots_per_song = int(self.ma2_group_slots.value())
        s.ma2_group_pool_start = int(self.ma2_group_pool_start.value())
        # Following View Layout Pools are synced in refresh(), after the
        # allocation exists — doing it here would read last cycle's slots.
        s.ma2_view_layout = [dict(widget) for widget in self.view_stage.widgets]
        s.ma2_include_fixed_macros = self.ma2_fixed_macros.isChecked()
        s.ma2_include_song_macros = self.ma2_song_macros.isChecked()
        s.ma2_include_song_list = self.ma2_song_list.isChecked()
        s.ma2_telnet_host = self.registry_host.text().strip() or "127.0.0.1"
        s.ma2_telnet_command_port = int(self.registry_command_port.value())
        s.ma2_telnet_monitor_port = int(self.registry_monitor_port.value())
        s.ma2_telnet_user = self.registry_user.text().strip() or "administrator"
        s.ma2_telnet_plugin_pool = int(self.registry_plugin_pool.value())
        s.ma2_telnet_plugin_import_path = self.registry_plugin_import_path.text().strip()
        s.ma2_start_after_scanned = self.registry_start_after_scanned.isChecked()
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

    def _auto_fill_pool_overrides(self) -> None:
        """Renumber the queue from the Manual Pool Starts seeds.

        Only Pools with a value are touched — a blank field (0, shown empty)
        leaves that whole column exactly as it is, so filling just Timecode
        renumbers only the Timecode column.
        """
        if self._project is None or not self._slots:
            return
        settings = self._project.ma_export
        seq_slots = max(1, int(settings.ma2_sequence_slots_per_song))
        effect_slots = max(1, int(settings.ma2_effect_slots_per_song))
        group_slots = max(1, int(settings.ma2_group_slots_per_song))
        seeds = {
            "sequence": (self.review_pool_start_fields["seq_start"].value(), seq_slots),
            "effects": (self.review_pool_start_fields["effect_start"].value(), effect_slots),
            "groups": (self.review_pool_start_fields["group_start"].value(), group_slots),
            "timecode": (self.review_pool_start_fields["timecode_start"].value(), 1),
            "view": (self.review_pool_start_fields["view_start"].value(), 1),
            "song_macro": (self.review_pool_start_fields["macro_start"].value(), 1),
            "page": (self.review_pool_start_fields["page_start"].value(), 1),
        }
        seeds = {pool: value for pool, value in seeds.items() if value[0] > 0}
        if not seeds:
            self.registry_scan_status.setText(
                "Auto-Fill did nothing — every Manual Pool Start is blank. "
                "Fill the Pools you want renumbered."
            )
            return
        for row, slot in enumerate(self._slots):
            overrides = settings.ma2_pool_overrides.setdefault(slot.song.id, {})
            for pool, (start, stride) in seeds.items():
                overrides[pool] = int(start) + row * stride
        # Auto-Fill is an explicit instruction, so it wins: switch off
        # "Start after scanned Pools" rather than leaving two bulk rules
        # fighting over the same numbers.
        if settings.ma2_start_after_scanned:
            settings.ma2_start_after_scanned = False
            self._sync_start_after_scanned_checkboxes(False)
            self.registry_scan_status.setText(
                "Auto-Fill applied · Start after scanned Pools switched off so "
                "these numbers are used exactly as entered."
            )
        self.refresh()
        self.settings_changed.emit()

    def _clear_pool_overrides(self) -> None:
        if self._project is None:
            return
        self._project.ma_export.ma2_pool_overrides = {}
        self.refresh()
        self.settings_changed.emit()

    def _on_review_table_item_edited(self, item: QTableWidgetItem) -> None:
        if self._review_table_refreshing or self._suppress or self._project is None:
            return
        pool_by_column = {
            3: "sequence",
            4: "effects",
            5: "groups",
            6: "timecode",
            7: "view",
            8: "page",
            9: "song_macro",
        }
        pool = pool_by_column.get(item.column())
        row = item.row()
        if pool is None or not (0 <= row < len(self._slots)):
            return
        song_id = self._slots[row].song.id
        settings = self._project.ma_export
        match = re.search(r"\d+", item.text())
        if match:
            value = max(1, int(match.group()))
            settings.ma2_pool_overrides.setdefault(song_id, {})[pool] = value
        else:
            # Blanked the cell — drop back to the computed default.
            settings.ma2_pool_overrides.get(song_id, {}).pop(pool, None)
        self.refresh()
        self.settings_changed.emit()

    def _sync_start_after_scanned_checkboxes(self, checked: bool) -> None:
        """Keep the Export Registry and Review & Export copies in step."""
        for box in (self.registry_start_after_scanned, self.review_start_after_scanned):
            box.blockSignals(True)
            box.setChecked(bool(checked))
            box.blockSignals(False)

    def _on_start_after_scanned_toggled(self, checked: bool) -> None:
        if self._suppress or self._project is None:
            return
        self._sync_start_after_scanned_checkboxes(checked)
        settings = self._project.ma_export
        settings.ma2_start_after_scanned = bool(checked)
        if checked:
            if not settings.ma2_scanned_pool_max:
                self.registry_scan_status.setText(
                    "Start after scanned Pools is on, but nothing has been scanned "
                    "yet — run Scan Current Show to detect the Pools already in use."
                )
            elif settings.ma2_pool_overrides:
                # Existing pins would hold songs behind the scanned range and
                # make the toggle look broken, so this bulk action clears them.
                # Say so plainly rather than dropping the numbers silently.
                cleared = len(settings.ma2_pool_overrides)
                settings.ma2_pool_overrides = {}
                self.registry_scan_status.setText(
                    f"Start after scanned Pools is on · cleared {cleared} pinned "
                    "song(s) so every Pool could move past the scanned range."
                )
        self.refresh()
        self.settings_changed.emit()

    def _on_review_export_option_toggled(self, index: int, checked: bool) -> None:
        """Keep Review & Export's final checks bidirectionally synced with setup."""
        # Order must match _EXPORT_CONTENT_CHECK_LABELS / self.review_macro_checks.
        console_checks = (
            self.ma2_song_list,
            self.ma2_fixed_macros,
            self.ma2_song_macros,
            self.ma2_song_views,
            self.ma2_add_preset_cue,
        )
        source = console_checks[index]
        if source.isChecked() != checked:
            source.setChecked(checked)

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
            self.ma2_effect_slots,
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

    @staticmethod
    def _scanned_max_text(settings: MaExportSettings) -> str:
        """Highest Pool number actually found by the last Live Scan (Test
        Connection / Scan Current Show) — distinct from "Next safe start",
        which is only what CuePlayer itself plans to use next."""
        scanned = settings.ma2_scanned_pool_max
        if not scanned:
            return "Show scan max IDs: not scanned yet — run Scan Current Show"
        text = (
            f"Show scan max IDs: Seq {scanned.get('sequence', '—')} / "
            f"Effect {scanned.get('effect', '—')} / "
            f"TC {scanned.get('timecode', '—')} / "
            f"Group {scanned.get('group', '—')} / "
            f"Macro {scanned.get('macro', '—')} / "
            f"View {scanned.get('view', '—')} / "
            f"Page {scanned.get('page', '—')}"
        )
        if settings.ma2_start_after_scanned:
            # Manual pins always win over this toggle (see build_show_patch) —
            # it only clears pre-existing ones once, at the moment it's
            # ticked, so any pinned afterwards stay put.
            text += " · Starting after these where not manually pinned"
        elif settings.ma2_pool_overrides:
            # Overrides outrank the scanned starts, which is exactly why
            # numbers can look "stuck" after a scan — say so explicitly.
            pinned = len(settings.ma2_pool_overrides)
            text += (
                f" · {pinned} song(s) pinned by manual overrides — these ignore "
                "the scan until you enable Start after scanned Pools or use "
                "Clear All Overrides"
            )
        return text

    def _rebuild_workflow_pages(self) -> None:
        if self._project is None:
            return
        settings = self._project.ma_export
        # The Auto-Fill seeds are deliberately NOT mirrored from Console Setup
        # on every refresh: they are the user's own input, and rewriting them
        # here made a deliberately blank ("leave this Pool alone") field
        # impossible to keep.
        slots_per_song = max(1, int(settings.ma2_sequence_slots_per_song))
        group_slots = max(1, int(settings.ma2_group_slots_per_song))
        effect_slots = max(1, int(settings.ma2_effect_slots_per_song))
        collisions = pool_collisions(self._slots, settings)
        pool_by_review_column = {
            3: "sequence",
            4: "effects",
            5: "groups",
            6: "timecode",
            7: "view",
            8: "page",
            9: "song_macro",
        }
        collision_brush = QBrush(QColor("#7f1d1d"))
        self.registry_table.setRowCount(len(self._slots))
        self.review_table.setRowCount(len(self._slots))
        self._review_table_refreshing = True
        for row, slot in enumerate(self._slots):
            seq_start = int(slot.main_sequence)
            seq_end = seq_start + slots_per_song - 1
            effect_start = int(slot.effect_start)
            effect_end = effect_start + effect_slots - 1
            group_start = int(slot.group_start)
            group_end = group_start + group_slots - 1
            macro = int(slot.song_macro_pool)
            view = int(slot.view_pool)
            song = slot.song
            # "Song" shows the Setlist name as-is (Chinese or otherwise) so it
            # can be cross-checked against the Setlist panel; never blank —
            # songs named only in English (88Bars) still show their name here.
            # Display-only: the exporter always uses Export Name.
            song_name = song.name or slot.display_name
            registry_values = (
                f"{song.setlist_number:g}",
                song_name,
                slot.display_name,
                "Planned",
                f"{seq_start}–{seq_end}",
                f"{effect_start}–{effect_end}",
                f"{group_start}–{group_end}",
                str(slot.timecode_pool),
                str(view),
                str(slot.page),
                str(macro),
            )
            for column, value in enumerate(registry_values):
                if column == 3:
                    status = QLabel("●  Planned")
                    status.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    status.setToolTip("Planned allocation — not yet verified by an MA2 show scan")
                    status.setStyleSheet(
                        "color: #86efac; font-weight: 650; background: transparent; "
                        "padding: 2px 8px;"
                    )
                    self.registry_table.setCellWidget(row, column, status)
                else:
                    self.registry_table.setItem(row, column, QTableWidgetItem(value))
            review_values = (
                str(row + 1),
                song_name,
                slot.display_name,
                f"{seq_start}–{seq_end}",
                f"{effect_start}–{effect_end}",
                f"{group_start}–{group_end}",
                str(slot.timecode_pool),
                str(view),
                str(slot.page),
                str(macro),
                f"{slot.main_cue_count} Main · {slot.button_mark_count} Button",
            )
            for column, value in enumerate(review_values):
                item = QTableWidgetItem(value)
                pool = pool_by_review_column.get(column)
                if pool is None:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                elif slot.song.id in collisions.get(pool, ()):
                    item.setBackground(collision_brush)
                    item.setToolTip(
                        f"{POOL_COLLISION_LABELS.get(pool, pool)} Pool overlaps another "
                        "song — pick a different start."
                    )
                self.review_table.setItem(row, column, item)
        self._review_table_refreshing = False
        if self._slots:
            last_row = len(self._slots) - 1
            next_sequence = int(self._slots[last_row].main_sequence) + slots_per_song
            next_effect = int(settings.ma2_effect_pool_start) + len(self._slots) * effect_slots
            next_timecode = int(self._slots[last_row].timecode_pool) + 1
            next_group = int(settings.ma2_group_pool_start) + len(self._slots) * group_slots
            self.registry_status.setText(
                f"{len(self._slots)} planned song(s) · Next safe starts: Sequence {next_sequence}, "
                f"Effects {next_effect}, Groups {next_group}, Timecode {next_timecode}, "
                f"Song Macro {int(settings.ma2_song_macro_start) + len(self._slots)}, "
                f"View {int(settings.ma2_view_pool_start) + len(self._slots)}, "
                f"Groups reserve {group_slots}/song\n"
                f"{self._scanned_max_text(settings)}"
            )
            self.registry_summary_labels[0].setText(
                f"Registered Songs\n{len(self._slots)}"
            )
            self.registry_summary_labels[1].setText(f"Next Sequence\n{next_sequence}")
            self.registry_summary_labels[2].setText(f"Next Effects\n{next_effect}")
            self.registry_summary_labels[3].setText(f"Next Groups\n{next_group}")
        else:
            self.registry_status.setText(
                f"No songs selected · no Registry allocation proposed\n"
                f"{self._scanned_max_text(settings)}"
            )
            self.registry_summary_labels[0].setText("Registered Songs\n0")
            self.registry_summary_labels[1].setText(
                f"Next Sequence\n{int(settings.sequence_pool_start)}"
            )
            self.registry_summary_labels[2].setText(
                f"Next Effects\n{int(settings.ma2_effect_pool_start)}"
            )
            self.registry_summary_labels[3].setText(f"Next Groups\n{int(settings.ma2_group_pool_start)}")
        target = self.ma2_version.currentText().strip() if self._console() == "ma2" else "grandMA3"
        out_folder = self.out_dir.text().strip() or "(not selected)"
        self.review_summary.setText(
            f"{target}  ·  {len(self._slots)} song(s)  ·  Output: {out_folder}"
        )
        self.review_summary.setToolTip(
            f"Groups reserved per song: {int(settings.ma2_group_slots_per_song)}\n"
            f"{self._scanned_max_text(settings)}"
        )
        # Order must match _EXPORT_CONTENT_CHECK_LABELS / self.review_macro_checks.
        values = (
            settings.ma2_include_song_list,
            settings.ma2_include_fixed_macros,
            settings.ma2_include_song_macros,
            settings.ma2_include_song_views,
            settings.ma2_add_main_preset_cue,
        )
        for check, value in zip(self.review_macro_checks, values):
            check.blockSignals(True)
            check.setChecked(bool(value))
            check.blockSignals(False)
        preview_id = self.view_preview_song.currentData()
        self.view_preview_song.blockSignals(True)
        self.view_preview_song.clear()
        for row, slot in enumerate(self._slots, start=1):
            self.view_preview_song.addItem(f"{row}. {slot.display_name}", slot.song.id)
        preview_row = self.view_preview_song.findData(preview_id)
        if self.view_preview_song.count():
            self.view_preview_song.setCurrentIndex(max(0, preview_row))
        self.view_preview_song.blockSignals(False)
        self._refresh_view_stage()

    def _refresh_view_stage(self) -> None:
        if self._project is None:
            return
        self.view_stage.song_index = max(0, self.view_preview_song.currentIndex())
        self.view_stage.update()
        self._load_view_inspector(self.view_stage.selected_index)

    def _default_view_layout_for_settings(self) -> list[dict[str, object]]:
        layout = default_view_layout()
        if self._project is None:
            return layout
        settings = self._project.ma_export
        layout[0].update(start=int(settings.sequence_pool_start), stride=int(settings.ma2_sequence_slots_per_song))
        layout[2].update(start=int(settings.ma2_effect_pool_start), stride=int(settings.ma2_effect_slots_per_song))
        return layout

    def _on_view_song_changed(self, index: int) -> None:
        self.view_stage.song_index = max(0, index)
        self.view_stage.update()
        self._load_view_inspector(self.view_stage.selected_index)

    def _load_view_inspector(self, index: int) -> None:
        if not (0 <= index < len(self.view_stage.widgets)):
            self.view_allocation_status.setText("Select or add a Pool window.")
            return
        widget = self.view_stage.widgets[index]
        controls = (self.view_pool_type, self.view_pool_mode, self.view_pool_follow, self.view_pool_number_start, self.view_pool_stride, self.view_pool_x, self.view_pool_y, self.view_pool_width, self.view_pool_height)
        for control in controls:
            control.blockSignals(True)
        self.view_pool_type.setCurrentIndex(max(0, self.view_pool_type.findData(widget.get("type"))))
        self.view_pool_mode.setCurrentIndex(max(0, self.view_pool_mode.findData(widget.get("mode"))))
        followable = str(widget.get("type")) in _FOLLOWABLE_POOL_TYPES
        follow = followable and bool(widget.get("follow"))
        self.view_pool_follow.setChecked(follow)
        self.view_pool_follow.setEnabled(followable)
        self.view_pool_number_start.setValue(int(widget.get("start", 1)))
        self.view_pool_stride.setValue(int(widget.get("stride", 1)))
        self.view_pool_x.setValue(int(widget.get("x", 0)))
        self.view_pool_y.setValue(int(widget.get("y", 0)))
        self.view_pool_width.setValue(int(widget.get("w", 1)))
        self.view_pool_height.setValue(int(widget.get("h", 1)))
        # Following derives Pool Start/Stride/Allocation from Console Setup —
        # editing them here directly would just be overwritten on the next sync.
        self.view_pool_mode.setEnabled(not follow)
        self.view_pool_number_start.setEnabled(not follow)
        self.view_pool_stride.setEnabled(not follow and widget.get("mode") == "perSong")
        for control in controls:
            control.blockSignals(False)
        start = int(widget.get("start", 1)) + (self.view_stage.song_index * int(widget.get("stride", 1)) if widget.get("mode") == "perSong" else 0)
        visible = int(widget.get("w", 1)) * int(widget.get("h", 1)) - 1
        # The full Timecode Pool window is three cells: title + two MA2 slots.
        builtin_slots = TIMECODE_POOL_TOTAL_CELLS - 1 if widget.get("type") == "timecode" else 0
        overlaps = False
        for left_index, left in enumerate(self.view_stage.widgets):
            left_rect = (int(left["x"]), int(left["y"]), int(left["x"]) + int(left["w"]), int(left["y"]) + int(left["h"]))
            for right in self.view_stage.widgets[left_index + 1 :]:
                right_rect = (int(right["x"]), int(right["y"]), int(right["x"]) + int(right["w"]), int(right["y"]) + int(right["h"]))
                if left_rect[0] < right_rect[2] and right_rect[0] < left_rect[2] and left_rect[1] < right_rect[3] and right_rect[1] < left_rect[3]:
                    overlaps = True
                    break
        stride_warning = widget.get("mode") == "perSong" and int(widget.get("stride", 1)) < max(0, visible - builtin_slots)
        if overlaps:
            self.view_allocation_status.setText("Layout overlap · move or resize a Pool window")
            self.view_allocation_status.setStyleSheet("color: #f87171;")
        elif stride_warning:
            self.view_allocation_status.setText(f"Reserved range too small · {visible - builtin_slots} numbered Pool slots")
            self.view_allocation_status.setStyleSheet("color: #f87171;")
        else:
            timecode_note = " · 2 built-in Timecode slots (3 cells total)" if builtin_slots else ""
            self.view_allocation_status.setText(f"Screen 3 · {visible - builtin_slots} numbered Pool slots · starts at {start}{timecode_note}")
            self.view_allocation_status.setStyleSheet("color: #99a3b1;")

    def _console_pool_start_stride(self, pool_type: str) -> tuple[int, int] | None:
        """Effective (start, stride) a following View Layout Pool should show.

        Derived from the built allocation (``self._slots``) rather than the
        raw Console Setup spinbox, so the View Layout also tracks anything
        that changes the numbers downstream of it — a manual per-song edit in
        Review & Export, Auto-Fill, or Start after scanned Pools. Falls back
        to the Console Setup fields when no songs are queued yet.
        """
        mapping: dict[str, tuple[object, object, str]] = {
            "sequence": (self.seq_start, self.ma2_sequence_slots, "main_sequence"),
            "effects": (self.ma2_effect_pool_start, self.ma2_effect_slots, "effect_start"),
            "groups": (self.ma2_group_pool_start, self.ma2_group_slots, "group_start"),
            "timecode": (self.tc_start, None, "timecode_pool"),
            "macros": (self.ma2_song_macro_start, None, "song_macro_pool"),
        }
        entry = mapping.get(pool_type)
        if entry is None:
            return None
        start_widget, stride_widget, slot_attr = entry
        start = int(start_widget.value())
        stride = int(stride_widget.value()) if stride_widget is not None else 1
        if self._slots:
            start = int(getattr(self._slots[0], slot_attr))
            if len(self._slots) >= 2:
                # Use the real gap between the first two songs so an
                # Auto-Fill with its own spacing is reflected exactly.
                actual = int(getattr(self._slots[1], slot_attr)) - start
                if actual > 0:
                    stride = actual
        return start, max(1, stride)

    def _sync_following_view_pools(self) -> bool:
        """Pull every "follow"-checked View Layout Pool onto the live
        allocation. Returns True when a widget actually moved."""
        changed = False
        for widget in self.view_stage.widgets:
            if not widget.get("follow"):
                continue
            values = self._console_pool_start_stride(str(widget.get("type")))
            if values is None:
                continue
            start, stride = values
            if (
                int(widget.get("start", 0)) != start
                or int(widget.get("stride", 0)) != stride
                or widget.get("mode") != "perSong"
            ):
                widget["start"] = start
                widget["stride"] = stride
                widget["mode"] = "perSong"
                changed = True
        if changed:
            self.view_stage.update()
            if self.view_stage.selected_index >= 0:
                self._load_view_inspector(self.view_stage.selected_index)
        return changed

    def _update_selected_view_pool(self, *_args) -> None:
        if self._suppress or not (0 <= self.view_stage.selected_index < len(self.view_stage.widgets)):
            return
        widget = self.view_stage.widgets[self.view_stage.selected_index]
        pool_type = self.view_pool_type.currentData()
        is_timecode = pool_type == "timecode"
        minimum_width = TIMECODE_POOL_TOTAL_CELLS if is_timecode else 1
        width = max(minimum_width, min(self.view_pool_width.value(), 16 - self.view_pool_x.value()))
        height = min(self.view_pool_height.value(), 8 - self.view_pool_y.value())
        follow = self.view_pool_follow.isChecked() and pool_type in _FOLLOWABLE_POOL_TYPES
        if follow:
            start, stride = self._console_pool_start_stride(pool_type) or (
                self.view_pool_number_start.value(), self.view_pool_stride.value()
            )
            mode = "perSong"
        else:
            start, stride = self.view_pool_number_start.value(), self.view_pool_stride.value()
            mode = self.view_pool_mode.currentData()
        widget.update(type=pool_type, mode=mode, follow=follow, start=start, stride=stride, x=min(self.view_pool_x.value(), 16 - width), y=self.view_pool_y.value(), w=width, h=height)
        if is_timecode:
            self.view_pool_width.setValue(width)
        self.view_stage.update()
        self._on_view_layout_changed()

    def _on_view_layout_changed(self) -> None:
        if self._project is None:
            return
        self._project.ma_export.ma2_view_layout = [dict(widget) for widget in self.view_stage.widgets]
        self._load_view_inspector(self.view_stage.selected_index)
        self.settings_changed.emit()

    def _add_view_pool(self) -> None:
        self.view_stage.widgets.append({"type": "effects", "mode": "fixed", "x": 0, "y": 0, "w": 4, "h": 2, "start": 1, "stride": 1})
        self.view_stage.selected_index = len(self.view_stage.widgets) - 1
        self._on_view_layout_changed()
        self.view_stage.update()

    def _duplicate_view_pool(self) -> None:
        if not self.view_stage.widgets:
            return
        widget = dict(self.view_stage.widgets[self.view_stage.selected_index])
        widget["x"] = min(16 - int(widget["w"]), int(widget["x"]) + 1)
        widget["y"] = min(8 - int(widget["h"]), int(widget["y"]) + 1)
        self.view_stage.widgets.append(widget)
        self.view_stage.selected_index = len(self.view_stage.widgets) - 1
        self._on_view_layout_changed()
        self.view_stage.update()

    def _delete_view_pool(self) -> None:
        if not self.view_stage.widgets:
            return
        self.view_stage.widgets.pop(self.view_stage.selected_index)
        self.view_stage.selected_index = min(self.view_stage.selected_index, len(self.view_stage.widgets) - 1)
        self._on_view_layout_changed()
        self.view_stage.update()

    def _reset_view_layout(self) -> None:
        self.view_stage.set_layout(self._default_view_layout_for_settings())
        self._on_view_layout_changed()

    def _set_view_layout_locked(self, locked: bool) -> None:
        self.view_stage.locked = locked
        self.view_stage.update()

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
        enabled_content = [
            name for name, enabled in (
                ("Song List Sequence", self.ma2_song_list.isChecked()),
                ("Fixed control Macros", self.ma2_fixed_macros.isChecked()),
                ("Song Macro", self.ma2_song_macros.isChecked()),
                ("Song View", self.ma2_song_views.isChecked()),
                ("Add Main Cue named Preset", self.ma2_add_preset_cue.isChecked()),
            ) if enabled
        ]
        # One item per line so the confirm dialog is easy to check at a glance.
        macro_flags = "\n".join(f"• {name}" for name in enabled_content) if enabled_content else "None"
        answer = QMessageBox.question(
            self,
            "Confirm Export",
            f"Export {len(self._slots)} song(s) to:\n{out}\n\nEnabled content:\n{macro_flags}\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
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
                    show_name=self._project.ma_export.ma2_show_name,
                )
            else:
                all_paths = Ma2Exporter().export_show_to_directory(
                    plans,
                    directory,
                    show_install_name=show_macro_basename,
                    show_name=self._project.ma_export.ma2_show_name,
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
                    effect_slots_per_song=self._project.ma_export.ma2_effect_slots_per_song,
                    sequence_slots_per_song=self._project.ma_export.ma2_sequence_slots_per_song,
                    view_layout=self._project.ma_export.ma2_view_layout or self._default_view_layout_for_settings(),
                    pool_overrides=self._project.ma_export.ma2_pool_overrides,
                )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Export Failed", str(exc))
            return

        try:
            all_paths.update(self._write_export_allocation_report(directory))
        except OSError as exc:
            QMessageBox.warning(
                self,
                "Export Report Not Written",
                f"MA files were created, but the allocation report could not be written:\n{exc}",
            )

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

    def _allocation_report_columns_and_rows(self) -> tuple[list[str], list[dict[str, str]]]:
        """Build the Order/Song/.../Song Macro rows shared by the TXT summary
        written alongside every MA export and the standalone CSV report.
        This is the single source for that table — every column value comes
        straight from ``self._slots``, the same allocation the real export
        uses, so the report can never drift from what MA2 actually receives.
        """
        if self._project is None:
            return [], []
        settings = self._project.ma_export
        seq_slots = max(1, int(settings.ma2_sequence_slots_per_song))
        effect_slots = max(1, int(settings.ma2_effect_slots_per_song))
        group_slots = max(1, int(settings.ma2_group_slots_per_song))
        columns = [
            "Order", "Song", "Export Name", "Sequence", "Effects", "Groups",
            "Timecode", "View", "Page", "Song Macro",
        ]
        rows: list[dict[str, str]] = []
        for order, slot in enumerate(self._slots, start=1):
            seq_start = int(slot.main_sequence)
            effect_start = int(slot.effect_start)
            group_start = int(slot.group_start)
            rows.append({
                "Order": str(order),
                "Song": slot.song.name,
                "Export Name": slot.display_name,
                "Sequence": f"{seq_start}–{seq_start + seq_slots - 1}",
                "Effects": f"{effect_start}–{effect_start + effect_slots - 1}",
                "Groups": f"{group_start}–{group_start + group_slots - 1}",
                "Timecode": str(slot.timecode_pool),
                "View": str(int(slot.view_pool)),
                "Page": str(int(slot.page)),
                "Song Macro": str(int(slot.song_macro_pool)),
            })
        return columns, rows

    def _write_export_allocation_report(self, directory: Path) -> dict[str, Path]:
        """Write a TXT record of this export's Pool allocation alongside the
        MA files. The CSV report is a separate, user-directed Save As action
        (see ``_export_allocation_report_csv``) — it is not written here so
        it never lands in the MA2 import/export folder without being asked.
        """
        if self._project is None:
            return {}
        settings = self._project.ma_export
        columns, rows = self._allocation_report_columns_and_rows()
        stem = sanitize_ma_name(settings.ma2_show_name or "CuePlayer", fallback="CuePlayer")
        text_path = directory / f"{stem}_Export_Allocation.txt"
        lines = [f"Show Name: {settings.ma2_show_name or 'CuePlayer'}", "", " | ".join(columns)]
        lines.extend(" | ".join(row[column] for column in columns) for row in rows)
        text_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return {"show:allocation_txt": text_path}

    def _default_allocation_report_directory(self) -> Path:
        """Where the CSV Save As dialog opens: the current Project file's
        folder, or a Documents-style fallback when the project has never
        been saved. Deliberately not the MA2 output folder."""
        provider = self.project_file_path_provider
        project_path = provider() if provider is not None else None
        if project_path is not None:
            return Path(project_path).parent
        documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        return Path(documents) if documents else Path.home()

    def _export_allocation_report_csv(self, _checked: bool = False) -> None:
        if self._project is None or not self._slots:
            QMessageBox.information(
                self, "Nothing to Export", "Add songs to the Export Queue first."
            )
            return
        settings = self._project.ma_export
        columns, rows = self._allocation_report_columns_and_rows()
        stem = sanitize_ma_name(settings.ma2_show_name or "CuePlayer", fallback="CuePlayer")
        default_path = self._default_allocation_report_directory() / f"{stem}_Export_Allocation.csv"
        chosen, _filter = QFileDialog.getSaveFileName(
            self, "Save Allocation Report", str(default_path), "CSV Files (*.csv)"
        )
        if not chosen:
            return
        csv_path = Path(chosen)
        if csv_path.suffix.lower() != ".csv":
            csv_path = csv_path.with_suffix(".csv")
        try:
            with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=columns)
                writer.writeheader()
                writer.writerows(rows)
        except OSError as exc:
            QMessageBox.warning(self, "Export Report Not Written", f"Could not write CSV: {exc}")
            return
        QMessageBox.information(
            self, "Allocation Report Saved", f"Allocation Report saved to:\n{csv_path}"
        )
