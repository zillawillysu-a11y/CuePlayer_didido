"""Main application window with waveform timeline and marking."""

from __future__ import annotations

import time
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from PySide6.QtCore import QByteArray, QEvent, QMimeData, QModelIndex, QPoint, QRect, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QColor,
    QDrag,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QFontMetrics,
    QKeyEvent,
    QKeySequence,
    QPainter,
    QPen,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from cueplayer.domain.models import (
    DEFAULT_STILL_CLIP_DURATION_SECONDS,
    AudioTrack,
    Project,
    SetlistCategory,
    Song,
    VideoClip,
)
from cueplayer.application.playback_service import PlaybackService
from cueplayer.application.project_service import (
    AUTOSAVE_INTERVAL_MINUTES as _AUTOSAVE_INTERVAL_MINUTES,
    DEFAULT_AUTOSAVE_INTERVAL_SEC as _DEFAULT_AUTOSAVE_INTERVAL_SEC,
    KEY_AUTOSAVE_ENABLED as _KEY_AUTOSAVE_ENABLED,
    KEY_AUTOSAVE_INTERVAL_SEC as _KEY_AUTOSAVE_INTERVAL_SEC,
    KEY_BACKUP_KEEP as _KEY_BACKUP_KEEP,
    KEY_LAST_PROJECT as _KEY_LAST_PROJECT,
    KEY_LAST_SONG_ID as _KEY_LAST_SONG_ID,
    ProjectService,
)
from cueplayer.application.settings_service import (
    KEY_CLEAN_OUTPUT_GEOMETRY as _KEY_CLEAN_OUTPUT_GEOMETRY,
    KEY_CLEAN_OUTPUT_WAS_OPEN as _KEY_CLEAN_OUTPUT_WAS_OPEN,
    KEY_CUE_LIST_COLUMN_ORDER as _KEY_CUE_LIST_COLUMN_ORDER,
    KEY_CUE_LIST_HEADER as _KEY_CUE_LIST_HEADER,
    KEY_CUE_LIST_SHOW_CUE_ID as _KEY_CUE_LIST_SHOW_CUE_ID,
    KEY_CUE_LIST_VISIBLE as _KEY_CUE_LIST_VISIBLE,
    KEY_MAIN_GEOMETRY as _KEY_MAIN_GEOMETRY,
    KEY_MAIN_SPLITTER as _KEY_MAIN_SPLITTER,
    KEY_MAIN_STATE as _KEY_MAIN_STATE,
    KEY_NOW_BODY_SPLITTER as _KEY_NOW_BODY_SPLITTER,
    KEY_NOW_PRIMARY_SHOW_CUE_ID as _KEY_NOW_PRIMARY_SHOW_CUE_ID,
    KEY_NOW_PRIMARY_SINGLE_LINE as _KEY_NOW_PRIMARY_SINGLE_LINE,
    KEY_NOW_PRIMARY_VISIBLE as _KEY_NOW_PRIMARY_VISIBLE,
    KEY_NOW_SECONDARY_PLACEMENT as _KEY_NOW_SECONDARY_PLACEMENT,
    KEY_NOW_SECONDARY_VISIBLE as _KEY_NOW_SECONDARY_VISIBLE,
    KEY_NOW_SPLITTER as _KEY_NOW_SPLITTER,
    KEY_NOW_SPLITTER_BELOW as _KEY_NOW_SPLITTER_BELOW,
    KEY_NOW_SPLITTER_RIGHT as _KEY_NOW_SPLITTER_RIGHT,
    KEY_SETLIST_VISIBLE as _KEY_SETLIST_VISIBLE,
    KEY_SETLIST_WIDTH as _KEY_SETLIST_WIDTH,
    KEY_TIMELINE_HEADER_WIDTH as _KEY_TIMELINE_HEADER_WIDTH,
    KEY_TIMELINE_PREVIEW_SPLITTER as _KEY_TIMELINE_PREVIEW_SPLITTER,
    KEY_TIMELINE_SPLITTER as _KEY_TIMELINE_SPLITTER,
    KEY_VIEW_MODE as _KEY_VIEW_MODE,
    SETTINGS_APP as _SETTINGS_APP,
    SETTINGS_ORG as _SETTINGS_ORG,
    SettingsService,
)
from cueplayer.application.show_session_service import ShowSessionService
from cueplayer.domain.song_session import SongSession
from cueplayer.persistence.backup import (
    list_backups,
)
from cueplayer.persistence.project_store import load_project
from cueplayer.persistence.media_layout import (
    DEFAULT_MEDIA_SUBDIR,
    heal_stale_media_paths,
    ingest_external_media_into_project,
    scan_external_media,
    sync_all_songs_media_to_setlist_folders,
)
from cueplayer.persistence.project_bundle import BundleResult, collect_project_bundle
from cueplayer.domain.media_relink import scan_missing_media
from cueplayer.media.ltc_detect import detect_ltc_channel
from cueplayer.ui.row_color import ROLE_ROW_COLOR
from cueplayer.ui.setlist_delegate import ROLE_HAS_VIDEO, ROLE_LTC_CHANNEL, SetlistRowDelegate
from cueplayer.ui.missing_media_dialog import MissingMediaRelinkDialog
from cueplayer.domain.undo import (
    AddMarksCommand,
    AddVideoClipsCommand,
    ChangeMarkLanesCommand,
    DeleteMarksCommand,
    DeleteVideoClipsCommand,
    EditMainCueIdCommand,
    EditVideoClipsCommand,
    MarkSnapshot,
    MoveMarksCommand,
    RenumberMainCueIdsCommand,
    RenameMarkCommand,
    SetlistEditCommand,
    SetlistStateSnapshot,
    SetVariantAnchorOffsetCommand,
    UndoContext,
    UndoStack,
    VideoClipSnapshot,
)
from cueplayer.media.audio_disk_cache import (
    load_audio_cached,
    load_all_ltc_channels,
    load_cached_waveform_peaks,
    save_cached_audio,
    save_ltc_channel,
)
from cueplayer.media.audio_loader import (
    AudioBuffer,
    ltc_waveform_display_buffer,
    probe_audio_duration,
    waveform_display_buffer,
)
from cueplayer.media.video_loader import VideoInfo, probe_media
from cueplayer.media.video_audio_loader import MAX_VIDEO_AUDIO_DECODE_SECONDS
from cueplayer.media.video_limits import (
    HEAVY_VIDEO_AUDIO_DECODE_SECONDS,
    source_needs_long_video_warning,
)
from cueplayer.media.video_music_standin import build_music_standin_from_video
from cueplayer.playback.audio_engine import AudioEngine
from cueplayer.playback.jog import hold_step_frames
from cueplayer.playback.ndi_output import (
    NdiVideoOutput,
    ndi_failure_kind,
    ndi_install_required,
)
from cueplayer.playback.video_sync import VideoSyncController
from cueplayer.ui.audio_timecode_dialog import AudioTimecodeDialog
from cueplayer.ui.align_anchors_dialog import AlignAnchorsDialog
from cueplayer.ui.ma_preflight_dialog import MaPreflightDialog
from cueplayer.domain.validation import build_preflight_report_for_project
from cueplayer.diagnostics import perf as perf_diag
from cueplayer.features import ENABLE_EXPERIMENTAL_FEATURES
from cueplayer.ui.cue_monitor_panel import CueMonitorPanel
from cueplayer.web_remote.bridge import WebRemoteBridge
from cueplayer.web_remote.main_window_remote_host import MainWindowRemoteHost
from cueplayer.web_remote.dialog import WebRemoteDialog
from cueplayer.web_remote.prefs import load_web_remote_prefs, save_web_remote_prefs
from cueplayer.ui.mark_display_dialog import MarkDisplayDialog
from cueplayer.ui.mark_manager_dialog import MarkManagerDialog
from cueplayer.ui.ndi_install_dialog import show_ndi_install_dialog
from cueplayer.ui.setlist_sheet_page import SetlistSheetPage
from cueplayer.ui.show_patch_page import ShowPatchPage
from cueplayer.ui.song_edit_dialog import (
    SongDraft,
    SongEditDialog,
    format_setlist_number,
    parse_setlist_number,
    suggest_ma_export_name,
)
from cueplayer.ui.drag_drop import (
    AUDIO_SUFFIXES,
    VIDEO_SUFFIXES,
    accept_file_drag,
    accept_file_drop,
    audio_paths_from_mime,
    mime_looks_like_file_drop,
    rejected_file_drop_reason,
    rejected_setlist_drop_reason,
    setlist_import_paths_from_mime,
    video_paths_from_mime,
)
from cueplayer.ui.theme import ACCENT, BG_SELECTED, contrast_text_color, with_alpha
from cueplayer.ui.timeline_widget import TimelineWidget
from cueplayer.ui.transport_bar import BottomTransportBar, TopToolBar
from cueplayer.ui.video_clip_edit import clip_start_after_body_drag, default_video_clip_duration
from cueplayer.ui.video_output_window import CleanVideoOutputWindow
from cueplayer.ui.video_preview import VideoPreviewWidget, rgb_frame_to_qimage

_MEDIA_DIALOG_FILTER = (
    "Video & Images (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.png *.jpg *.jpeg *.webp);;"
    "All Files (*.*)"
)
MAIN_WINDOW_TITLE_PREFIX = "CuePlayer Main"
# Floor so the Video Preview splitter cannot be dragged shut (View menu still hides).
_VIDEO_PREVIEW_SPLIT_MIN_HEIGHT = 96
# Machine settings keys / org aliases: see application.settings_service (+ ProjectService).


@dataclass
class _SetlistDisplayRow:
    kind: Literal["song", "category"]
    song_index: int | None = None
    category_id: str | None = None


def _text_input_has_focus() -> bool:
    """True when a widget that owns typing shortcuts is focused."""
    widget = QApplication.focusWidget()
    return isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox))


def _song_list_has_keyboard_focus(song_list: QTableWidget) -> bool:
    """True when keyboard focus is on the Setlist table (not Add/Edit buttons)."""
    widget = QApplication.focusWidget()
    if widget is None:
        return False
    return (
        widget is song_list
        or widget is song_list.viewport()
        or song_list.isAncestorOf(widget)
    )


def _warmup_bpm_analyzer_safe() -> None:
    try:
        from cueplayer.media.bpm_analyzer import warmup_bpm_analyzer

        warmup_bpm_analyzer()
    except Exception:  # noqa: BLE001
        pass


class SetlistWidget(QTableWidget):
    """Setlist: click No. to edit, drag rows to reorder, drop audio/video to add songs."""

    _TRIANGLE_HIT_MIN_PX = 28
    _MIME_FOLDER = "application/x-cueplayer-setlist-folder"
    # Wide enough for bold "V LTC L R" badge; Fixed so Song/BPM never squeeze it.
    _LTC_COLUMN_WIDTH = 68

    COL_NUM = 0
    COL_TITLE = 1
    COL_EN = 2
    COL_BPM = 3
    COL_LTC = 4
    COL_COUNT = 5

    # Shared with export/show-patch song lists (see cueplayer.ui.row_color).
    ROLE_ROW_COLOR = ROLE_ROW_COLOR
    ROLE_KIND = Qt.ItemDataRole.UserRole + 10
    ROLE_SONG_INDEX = Qt.ItemDataRole.UserRole + 11
    ROLE_LTC_CHANNEL = ROLE_LTC_CHANNEL
    ROLE_HAS_VIDEO = ROLE_HAS_VIDEO

    audio_files_dropped = Signal(list)
    audio_drop_rejected = Signal(str)
    rows_reordered = Signal(list, int)  # song ids in drag order, insert-before table row
    songs_moved_to_category = Signal(list, str)  # song ids, category id
    categories_reordered = Signal(str, int)  # category id, insert-before folder index
    category_clicked = Signal(str)  # triangle: toggle collapse
    category_rename_requested = Signal(str)  # folder label double-click
    setlist_number_edited = Signal(int, float)  # table row, new number
    setlist_number_edit_failed = Signal(int)  # table row
    song_title_edited = Signal(int, str)  # table row, display title for column 1
    song_ma_name_edited = Signal(int, str)  # table row, English / MA name (column 2)
    song_bpm_edited = Signal(int, object)  # table row, float | None
    song_bpm_edit_failed = Signal(int)  # table row

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, self.COL_COUNT, parent)
        self.setStyleSheet(
            "QTableWidget::item:focus { border: 0px; outline: none; }"
            "QTableWidget::item:selected { border: 0px; outline: none; }"
        )
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDropIndicatorShown(False)  # custom insert lines instead
        self.setDragDropOverwriteMode(False)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # Rename only via a deliberate double-click (or F2 / EditKeyPressed).
        # SelectedClicked is intentionally excluded: a single click on an
        # already-selected row (e.g. re-clicking a song after using a
        # transport control elsewhere) must only (re)select it, never open
        # inline rename — that was the source of accidental renames.
        self.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.setShowGrid(False)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setVisible(True)
        self.setHorizontalHeaderLabels(["No.", "Song", "English", "BPM", ""])
        header = self.horizontalHeader()
        # No./Song/English are Interactive so the user can drag widths; when the
        # panel is narrow, ScrollBarAsNeeded shows a horizontal scrollbar
        # instead of crushing Song to a few letters. LTC stays Fixed.
        header.setSectionsMovable(False)
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(36)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(self.COL_NUM, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(self.COL_TITLE, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(self.COL_BPM, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(self.COL_LTC, QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(self.COL_NUM, 48)
        self.setColumnWidth(self.COL_TITLE, 160)
        self.setColumnWidth(self.COL_EN, 110)
        self.setColumnWidth(self.COL_BPM, 64)
        self.setColumnWidth(self.COL_LTC, self._LTC_COLUMN_WIDTH)
        ltc_header = self.horizontalHeaderItem(self.COL_LTC)
        if ltc_header is not None:
            ltc_header.setToolTip(
                "Media badges: V = video clips; LTC L/R = striped timecode side"
            )
        self.setColumnHidden(2, True)
        self.setColumnHidden(3, False)
        self.verticalHeader().setDefaultSectionSize(28)
        self._show_ltc_badge = True
        self._show_video_badge = True
        self._sync_media_column_visibility()
        self.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # Pixel scrolling — column-step mode felt like notches, and selectRow /
        # setCurrentCell would yank the thumb to mid-range during playback.
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.horizontalScrollBar().setSingleStep(12)
        self._block_number_signal = False
        self._drag_song_ids: list[str] = []
        self._drag_category_id: str | None = None
        self._press_category_id: str | None = None
        self._folder_press_pos: QPoint | None = None
        self._saved_song_selection_rows: list[int] = []
        self._insert_indicator_row: int | None = None
        self._name_mode = "zh"
        self._show_bpm = True
        self.itemChanged.connect(self._on_item_changed)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.viewport().setAcceptDrops(True)

    def scrollTo(  # noqa: N802
        self,
        index: QModelIndex,
        hint: QAbstractItemView.ScrollHint = QAbstractItemView.ScrollHint.EnsureVisible,
    ) -> None:
        """Scroll vertically as usual; never nudge the horizontal bar.

        Selection / current-cell updates (rebuild, song switch, LTC refresh
        paths that reselect) must not yank Song/BPM into view and leave the
        thumb stuck mid-track while the user is playing.
        """
        bar = self.horizontalScrollBar()
        x = bar.value() if bar is not None else 0
        super().scrollTo(index, hint)
        if bar is not None:
            bar.setValue(x)

    def horizontal_scroll_value(self) -> int:
        bar = self.horizontalScrollBar()
        return int(bar.value()) if bar is not None else 0

    def set_horizontal_scroll_value(self, value: int) -> None:
        bar = self.horizontalScrollBar()
        if bar is not None:
            bar.setValue(value)

    def set_name_mode(self, mode: str) -> None:
        """zh = Chinese · both = Chinese + English · en = English."""
        if mode not in ("zh", "both", "en"):
            mode = "zh"
        self._name_mode = mode
        header = self.horizontalHeader()
        if mode == "both":
            self.setHorizontalHeaderLabels(["No.", "Song", "English", "BPM", ""])
            self.setColumnHidden(self.COL_EN, False)
            header.setSectionResizeMode(self.COL_EN, QHeaderView.ResizeMode.Interactive)
            header.setSectionResizeMode(self.COL_TITLE, QHeaderView.ResizeMode.Interactive)
        elif mode == "en":
            self.setHorizontalHeaderLabels(["No.", "English", "English", "BPM", ""])
            self.setColumnHidden(self.COL_EN, True)
            header.setSectionResizeMode(self.COL_TITLE, QHeaderView.ResizeMode.Interactive)
        else:
            self.setHorizontalHeaderLabels(["No.", "Song", "English", "BPM", ""])
            self.setColumnHidden(self.COL_EN, True)
            header.setSectionResizeMode(self.COL_TITLE, QHeaderView.ResizeMode.Interactive)
        self.setColumnHidden(self.COL_BPM, not self._show_bpm)
        self._sync_media_column_width()

    def _sync_media_column_width(self) -> None:
        header = self.horizontalHeader()
        header.setSectionResizeMode(self.COL_LTC, QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(self.COL_LTC, self._LTC_COLUMN_WIDTH)

    def _sync_media_column_visibility(self) -> None:
        visible = self._show_ltc_badge or self._show_video_badge
        self.setColumnHidden(self.COL_LTC, not visible)
        self._sync_media_column_width()

    def set_show_media_badges(self, *, show_ltc: bool, show_video: bool) -> None:
        self._show_ltc_badge = bool(show_ltc)
        self._show_video_badge = bool(show_video)
        self._sync_media_column_visibility()
        self.viewport().update()

    def set_show_bpm(self, visible: bool) -> None:
        self._show_bpm = bool(visible)
        self.setColumnHidden(self.COL_BPM, not self._show_bpm)
        self._sync_media_column_width()

    def set_ma_column_visible(self, visible: bool) -> None:
        # Back-compat for older callers.
        self.set_name_mode("both" if visible else "zh")

    def row_kind(self, row: int) -> str:
        item = self.item(row, 0)
        if item is None:
            return ""
        return str(item.data(self.ROLE_KIND) or "")

    def row_song_index(self, row: int) -> int | None:
        if self.row_kind(row) != "song":
            return None
        item = self.item(row, 0)
        if item is None:
            return None
        raw = item.data(self.ROLE_SONG_INDEX)
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    def row_category_id(self, row: int) -> str | None:
        if self.row_kind(row) != "category":
            return None
        item = self.item(row, 0)
        if item is None:
            return None
        raw = item.data(Qt.ItemDataRole.UserRole)
        return str(raw) if raw else None

    def _row_visual_rect(self, row: int) -> QRect:
        """Full-row viewport rect — ``visualRect`` is wrong for spanned folder rows."""
        if row < 0 or row >= self.rowCount():
            return QRect()
        return QRect(
            self.columnViewportPosition(0),
            self.rowViewportPosition(row),
            self.viewport().width(),
            self.rowHeight(row),
        )

    def _viewport_pos_from_event(self, event) -> QPoint:  # noqa: ANN001
        return self.viewport().mapFromGlobal(event.globalPosition().toPoint())

    def _category_triangle_hit(self, row: int, viewport_x: int, viewport_y: int) -> bool:
        """True when the click is on the ▸/▾ affordance (not the folder name)."""
        if self.row_category_id(row) is None:
            return False
        rect = self._row_visual_rect(row)
        if not rect.contains(viewport_x, viewport_y):
            return False
        item = self.item(row, self.COL_NUM)
        if item is None:
            return False
        local_x = viewport_x - rect.left()
        text = item.text()
        if not text or text[0] not in ("▸", "▾"):
            return False
        fm = QFontMetrics(item.font())
        tri_w = max(self._TRIANGLE_HIT_MIN_PX, fm.horizontalAdvance(f"{text[0]} ") + 4)
        return local_x <= tri_w

    def edit(
        self,
        index: QModelIndex,
        trigger: QAbstractItemView.EditTrigger,
        event,  # noqa: ANN001
    ) -> bool:
        if not index.isValid():
            return False
        if index.column() not in (self.COL_NUM, self.COL_TITLE, self.COL_EN, self.COL_BPM):
            return False
        # Belt-and-suspenders: SelectedClicked is not in setEditTriggers()
        # above, but guard against it explicitly here too so a single click
        # on an already-selected row can never start a rename.
        if trigger == QAbstractItemView.EditTrigger.SelectedClicked:
            return False
        return super().edit(index, trigger, event)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._block_number_signal or item is None:
            return
        if self.row_kind(item.row()) != "song":
            return
        col = item.column()
        if col == self.COL_NUM:
            parsed = parse_setlist_number(item.text())
            if parsed is None:
                self.setlist_number_edit_failed.emit(item.row())
                return
            self.setlist_number_edited.emit(item.row(), parsed)
        elif col == self.COL_TITLE:
            self.song_title_edited.emit(item.row(), item.text().strip())
        elif col == self.COL_EN:
            self.song_ma_name_edited.emit(item.row(), item.text().strip())
        elif col == self.COL_BPM:
            from cueplayer.media.bpm_analyzer import is_bpm_progress_text, parse_bpm_cell

            # Programmatic detect progress (… / 67%) must not open Invalid BPM.
            if is_bpm_progress_text(item.text()):
                return
            parsed = parse_bpm_cell(item.text())
            if parsed is False:
                self.song_bpm_edit_failed.emit(item.row())
                return
            self.song_bpm_edited.emit(item.row(), parsed)

    def startDrag(self, supportedActions) -> None:  # noqa: N802, ANN001
        # Folder drags are started from mouseMoveEvent via _start_folder_drag —
        # never hitchhike on selected song rows.
        if self._press_category_id:
            self._start_folder_drag()
            return
        self._drag_category_id = None
        ids: list[str] = []
        for row in sorted({idx.row() for idx in self.selectedIndexes()}):
            if self.row_kind(row) != "song":
                continue
            item = self.item(row, 0)
            if item is None:
                continue
            song_id = item.data(Qt.ItemDataRole.UserRole)
            if song_id:
                ids.append(str(song_id))
        self._drag_song_ids = ids
        super().startDrag(supportedActions)

    def _start_folder_drag(self) -> None:
        """Drag only this folder (+ songs stay in it); ignore other song selection."""
        cat_id = self._press_category_id
        if not cat_id:
            return
        self._drag_category_id = cat_id
        self._drag_song_ids = []
        self._saved_song_selection_rows = []
        # Keep UI selection on the folder title alone so the drag pixmap
        # does not look like a multi-song move.
        folder_row = next(
            (
                row
                for row in range(self.rowCount())
                if self.row_category_id(row) == cat_id
            ),
            None,
        )
        self.clearSelection()
        if folder_row is not None:
            item = self.item(folder_row, self.COL_NUM)
            if item is not None:
                item.setSelected(True)
                self.setCurrentItem(item)

        mime = QMimeData()
        mime.setData(self._MIME_FOLDER, QByteArray(cat_id.encode("utf-8")))
        drag = QDrag(self)
        drag.setMimeData(mime)
        if folder_row is not None:
            rect = self._row_visual_rect(folder_row)
            if rect.isValid() and rect.width() > 0 and rect.height() > 0:
                pixmap = self.viewport().grab(rect)
                drag.setPixmap(pixmap)
                drag.setHotSpot(QPoint(min(24, rect.width() // 4), rect.height() // 2))
        # CopyAction: drop handler must not delete the source folder row.
        drag.exec(Qt.DropAction.CopyAction)
        self._press_category_id = None
        self._folder_press_pos = None
        # dropEvent clears this on success; also clear on cancel so the next
        # song drag cannot inherit a stale folder id.
        self._drag_category_id = None

    def _selected_song_rows(self) -> list[int]:
        rows: list[int] = []
        for row in sorted({idx.row() for idx in self.selectedIndexes()}):
            if self.row_kind(row) == "song":
                rows.append(row)
        return rows

    def _restore_song_selection(self, rows: list[int]) -> None:
        self.clearSelection()
        for row in rows:
            if 0 <= row < self.rowCount() and self.row_kind(row) == "song":
                item = self.item(row, self.COL_NUM)
                if item is not None:
                    item.setSelected(True)

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        self._press_category_id = None
        self._folder_press_pos = None
        self._saved_song_selection_rows = []
        if event.button() == Qt.MouseButton.LeftButton:
            viewport_pos = self._viewport_pos_from_event(event)
            row = self.rowAt(viewport_pos.y())
            if row >= 0:
                cat_id = self.row_category_id(row)
                if cat_id is not None:
                    if self._category_triangle_hit(
                        row, viewport_pos.x(), viewport_pos.y()
                    ):
                        self.category_clicked.emit(cat_id)
                        event.accept()
                        return
                    # Title area: exclusive folder drag — drop unrelated song selection.
                    self._press_category_id = cat_id
                    self._folder_press_pos = QPoint(viewport_pos)
                    self._saved_song_selection_rows = self._selected_song_rows()
                    self.clearSelection()
                    item = self.item(row, self.COL_NUM)
                    if item is not None:
                        item.setSelected(True)
                        self.setCurrentItem(item)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001
        if (
            self._press_category_id
            and self._folder_press_pos is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            viewport_pos = self._viewport_pos_from_event(event)
            if (
                viewport_pos - self._folder_press_pos
            ).manhattanLength() >= QApplication.startDragDistance():
                self._start_folder_drag()
                return
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton and self._press_category_id:
            saved = list(self._saved_song_selection_rows)
            self._press_category_id = None
            self._folder_press_pos = None
            self._saved_song_selection_rows = []
            if saved:
                self._restore_song_selection(saved)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            viewport_pos = self._viewport_pos_from_event(event)
            row = self.rowAt(viewport_pos.y())
            if row >= 0:
                cat_id = self.row_category_id(row)
                if cat_id is not None:
                    if not self._category_triangle_hit(
                        row, viewport_pos.x(), viewport_pos.y()
                    ):
                        self.category_rename_requested.emit(cat_id)
                    return
        super().mouseDoubleClickEvent(event)

    def _category_row_at(self, row: int) -> str | None:
        if 0 <= row < self.rowCount():
            cat_id = self.row_category_id(row)
            if cat_id is not None:
                return cat_id
        if 0 <= row - 1 < self.rowCount():
            return self.row_category_id(row - 1)
        return None

    def _insert_row_at(self, pos) -> int:  # noqa: ANN001
        drop_index = self.indexAt(pos)
        if drop_index.isValid():
            drop_row = drop_index.row()
            rect = self.visualRect(drop_index)
            if pos.y() > rect.center().y():
                drop_row += 1
            return drop_row
        return self.rowCount()

    def _category_drop_target(self, pos) -> str | None:  # noqa: ANN001
        """Folder id when the pointer is on (or just under) a folder title row.

        Dropping selected songs onto a folder header must assign them to that
        folder — never dump them into the main (uncategorized) list.
        """
        for row in range(self.rowCount()):
            if self.row_kind(row) != "category":
                continue
            rect = self._row_visual_rect(row)
            # Slightly extend below the header so a drop near the title counts.
            if rect.adjusted(0, -1, 0, 8).contains(pos):
                return self.row_category_id(row)
        index = self.indexAt(pos)
        if index.isValid() and self.row_kind(index.row()) == "category":
            return self.row_category_id(index.row())
        return None

    def _set_insert_indicator(self, row: int | None) -> None:
        if self._insert_indicator_row == row:
            return
        self._insert_indicator_row = row
        self.viewport().update()

    def _clear_insert_indicator(self) -> None:
        self._set_insert_indicator(None)

    def viewportEvent(self, event: QEvent) -> bool:  # noqa: N802
        et = event.type()
        if et in (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop):
            if event.source() is self:
                return super().viewportEvent(event)
            mime = event.mimeData()
            if et in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
                if mime_looks_like_file_drop(mime):
                    accept_file_drag(event)
                    return True
            elif et == QEvent.Type.Drop:
                paths = setlist_import_paths_from_mime(mime)
                if paths:
                    self._clear_insert_indicator()
                    accept_file_drop(event)
                    self.audio_files_dropped.emit(paths)
                    return True
                self._clear_insert_indicator()
                self.audio_drop_rejected.emit(rejected_setlist_drop_reason(mime))
                event.ignore()
                return True
        ok = super().viewportEvent(event)
        if et == QEvent.Type.Paint and self._insert_indicator_row is not None:
            self._paint_insert_indicator()
        return ok

    def _paint_insert_indicator(self) -> None:
        """Draw lines under the song above and above the song below the gap."""
        row = self._insert_indicator_row
        if row is None:
            return
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        width = self.viewport().width()
        # Same accent-blue family as the rest of the app's selection/accent
        # styling (theme ACCENT), not a one-off mismatched color.
        color = QColor(ACCENT)
        fill = with_alpha(ACCENT, 70)
        pen = QPen(color, 2)
        painter.setPen(pen)

        y_top: int | None = None
        y_bottom: int | None = None
        if self.rowCount() <= 0:
            y_top = 2
            y_bottom = 6
        elif row <= 0:
            below = self.visualRect(self.model().index(0, 0))
            y_top = below.top()
            y_bottom = min(below.top() + 5, below.center().y())
        elif row >= self.rowCount():
            above = self.visualRect(self.model().index(self.rowCount() - 1, 0))
            y_bottom = above.bottom()
            y_top = max(above.bottom() - 5, above.center().y())
        else:
            above = self.visualRect(self.model().index(row - 1, 0))
            below = self.visualRect(self.model().index(row, 0))
            y_top = above.bottom()
            y_bottom = below.top()
            if y_bottom - y_top < 4:
                mid = (y_top + y_bottom) // 2
                y_top = mid - 2
                y_bottom = mid + 2

        if y_top is None or y_bottom is None:
            painter.end()
            return
        if y_bottom > y_top:
            painter.fillRect(0, y_top, width, y_bottom - y_top, fill)
        painter.drawLine(0, y_top, width, y_top)
        painter.drawLine(0, y_bottom, width, y_bottom)
        # Small side ticks so the gap reads as an insert slot.
        tick = 8
        painter.drawLine(0, y_top, 0, y_top + tick)
        painter.drawLine(0, y_bottom - tick, 0, y_bottom)
        painter.drawLine(width - 1, y_top, width - 1, y_top + tick)
        painter.drawLine(width - 1, y_bottom - tick, width - 1, y_bottom)
        painter.end()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        # Accept Explorer file drags optimistically (Windows may omit URLs
        # until drop); still accept internal row reorders.
        if event.source() is self:
            accept_file_drag(event)
            self._set_insert_indicator(self._folder_or_song_insert_row(event))
            return
        if mime_looks_like_file_drop(event.mimeData()):
            accept_file_drag(event)
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        if event.source() is self:
            accept_file_drag(event)
            self._set_insert_indicator(self._folder_or_song_insert_row(event))
            return
        if mime_looks_like_file_drop(event.mimeData()):
            accept_file_drag(event)
            self._clear_insert_indicator()
        else:
            self._clear_insert_indicator()
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802, ANN001
        self._clear_insert_indicator()
        super().dragLeaveEvent(event)

    def _is_folder_drag(self, event=None) -> bool:  # noqa: ANN001
        if self._drag_category_id:
            return True
        if event is not None:
            mime = event.mimeData()
            if mime is not None and mime.hasFormat(self._MIME_FOLDER):
                return True
        return False

    def _folder_or_song_insert_row(self, event) -> int:  # noqa: ANN001
        """Insert-before table row; folder drags snap to folder boundaries only."""
        pos = event.position().toPoint()
        if self._is_folder_drag(event):
            return self._folder_boundary_insert_row(pos)
        return self._insert_row_at(pos)

    def _folder_boundary_insert_row(self, pos) -> int:  # noqa: ANN001
        """Map pointer to an insert-before row at a folder header edge."""
        folder_rows = [
            row for row in range(self.rowCount()) if self.row_kind(row) == "category"
        ]
        if not folder_rows:
            return 0
        y = pos.y()
        for row in folder_rows:
            rect = self._row_visual_rect(row)
            if not rect.isValid():
                continue
            if y < rect.center().y():
                return row
        # Below the midpoint of the last folder header → after that folder's block.
        last = folder_rows[-1]
        end = last + 1
        while end < self.rowCount() and self.row_kind(end) == "song":
            end += 1
        return end

    def _folder_insert_index_at(self, drop_row: int) -> int:
        """Map a table insert-before row to an index among folder headers."""
        count = 0
        limit = max(0, min(int(drop_row), self.rowCount()))
        for row in range(limit):
            if self.row_kind(row) == "category":
                count += 1
        return count

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self._clear_insert_indicator()
        if event.source() is not self:
            paths = setlist_import_paths_from_mime(event.mimeData())
            if paths:
                accept_file_drop(event)
                self.audio_files_dropped.emit(paths)
                return
            self.audio_drop_rejected.emit(rejected_setlist_drop_reason(event.mimeData()))
            event.ignore()
            return
        pos = event.position().toPoint()
        mime = event.mimeData()
        category_id = self._drag_category_id
        if not category_id and mime is not None and mime.hasFormat(self._MIME_FOLDER):
            raw = bytes(mime.data(self._MIME_FOLDER)).decode("utf-8", errors="ignore")
            category_id = raw or None
        self._drag_category_id = None
        self._press_category_id = None
        self._folder_press_pos = None
        if category_id:
            drop_row = self._folder_boundary_insert_row(pos)
            # CopyAction: Qt must not delete the source folder row.
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            self.categories_reordered.emit(category_id, self._folder_insert_index_at(drop_row))
            return
        drop_row = self._insert_row_at(pos)
        ids = list(self._drag_song_ids)
        self._drag_song_ids = []
        if not ids:
            event.ignore()
            return
        # CopyAction: Qt must not delete source rows (MoveAction clears the list).
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        cat_id = self._category_drop_target(pos)
        if cat_id:
            self.songs_moved_to_category.emit(ids, cat_id)
            return
        # Insert slot immediately under a folder header → into that folder.
        if drop_row > 0 and drop_row - 1 < self.rowCount():
            if self.row_kind(drop_row - 1) == "category":
                under = self.row_category_id(drop_row - 1)
                if under:
                    self.songs_moved_to_category.emit(ids, under)
                    return
        self.rows_reordered.emit(ids, drop_row)


class MainWindow(QMainWindow):
    _setlist_ltc_cache_updated = Signal()
    _ltc_detect_finished = Signal(object, object, bool)  # cache_key, channel, ok
    _audio_prefetch_finished = Signal(object, object)  # path, buffer | Exception
    # Cold decode: PCM ready before peak pyramid — Play can start early.
    _audio_pcm_ready = Signal(object, object)  # path, AudioBuffer
    _bpm_detected = Signal(str, object)  # song_id, float | None
    _bpm_job_finished = Signal()  # pump next queued BPM job on the UI thread
    _bpm_progress_changed = Signal(str, int)  # song_id, percent (-1=queued, 0..100)
    _media_warm_progress = Signal()  # waveform / LTC batch progress on UI thread
    _video_standin_finished = Signal(int, object)  # token, AudioBuffer | None | Exception
    _video_probe_finished = Signal(object)  # background probe result bundle
    startup_ready = Signal()

    def __init__(self, project: Project | None = None) -> None:
        super().__init__()
        self.startup_session_ready = False
        self.project = project or Project.create("Untitled Project", with_song=False)
        # Workspace stand-in when Setlist is empty — never listed as a song.
        self._blank_song = Song.create("Untitled Song")
        self._song_session = SongSession()
        if self.project.songs:
            self.current_song = self.project.songs[0]
        else:
            self.current_song = self._blank_song
        self.settings = SettingsService(QSettings(_SETTINGS_ORG, _SETTINGS_APP))
        # Alias kept for existing tests / call sites that read ``_settings``.
        self._settings = self.settings
        self._project_service = ProjectService(self.settings)
        self._digit_shortcuts: list[QShortcut] = []
        # Latch digit keys between press and release so held keys add one mark.
        self._mark_shortcut_latch: set[str] = set()
        self._syncing_selection = False
        self._switching_song = False
        self._undo = UndoStack()
        self._undo_ctx = UndoContext(self.project, self.current_song.id)
        # Internal clipboard for Ctrl+C/Ctrl+V on timeline video clips
        # (Delete/Backspace reuse the existing _delete_video_clips path).
        self._video_clip_clipboard: list[VideoClipSnapshot] = []
        # Left/Right arrow-key jog: elapsed-hold-time bookkeeping per
        # direction, used to accelerate the seek step (see _nudge_frames()).
        self._nudge_hold_start: dict[int, float] = {}
        self._nudge_last_time: dict[int, float] = {}
        self._audio_load_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ui-audio-load")
        self._video_probe_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="ui-video-probe"
        )
        self._audio_prefetch_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ui-audio-prefetch")
        self._audio_load_token = 0
        self._video_standin_token = 0
        # Display-only Music waveforms built from video audio (survive song switch).
        self._video_standin_cache: dict[str, AudioBuffer] = {}
        self._song_activate_gen = 0
        self._pending_audio_load: tuple | None = None
        self._audio_buffer_cache: dict[tuple[str, int, int], AudioBuffer] = {}
        self._display_waveform_cache: dict[tuple[tuple[str, int, int] | None, int | None], AudioBuffer] = {}
        self._audio_ltc_cache: dict[tuple[str, int, int], int | None] = {}
        self._ltc_idle_timer: QTimer = QTimer(self)
        self._ltc_idle_timer.setSingleShot(True)
        self._ltc_idle_timer.setInterval(2000)
        self._ltc_idle_timer.timeout.connect(self._schedule_idle_ltc_detect)
        self._cue_list_refresh_timer = QTimer(self)
        self._cue_list_refresh_timer.setSingleShot(True)
        self._cue_list_refresh_timer.setInterval(150)
        self._cue_list_refresh_timer.timeout.connect(self._flush_cue_list_refresh)
        self._audio_ltc_inflight: dict[tuple[str, int, int], object] = {}
        self._timeline_ltc_exclude: int | None = None
        self._audio_inflight: dict[tuple[str, int, int], object] = {}
        self._ltc_detect_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="ui-ltc-detect"
        )
        # Waveform + LTC warm after setlist import / prefetch (status-bar %).
        self._media_warm_active = False
        self._media_warm_units: dict[tuple[str, int, int], dict[str, bool]] = {}
        # BPM is intentionally separate + single-threaded: each job reads PCM
        # and runs numpy corr — never stampede the machine on project open.
        self._bpm_detect_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="ui-bpm-detect"
        )
        # JIT-warm librosa onset path so the first real detect is not a hitch.
        self._bpm_detect_executor.submit(_warmup_bpm_analyzer_safe)
        self._setlist_ltc_cache_updated.connect(self._refresh_setlist_ltc_cells)
        self._ltc_detect_finished.connect(self._on_ltc_detect_finished)
        self._audio_prefetch_finished.connect(self._on_audio_prefetch_finished)
        self._audio_pcm_ready.connect(self._on_audio_pcm_ready)
        self._video_standin_finished.connect(self._on_video_standin_finished)
        self._video_probe_finished.connect(self._on_video_probe_finished)
        self._audio_ltc_cache.update(load_all_ltc_channels())
        self._media_warm_progress.connect(self._refresh_media_warm_status)
        self._bpm_detect_inflight: set[str] = set()
        # Song ids whose in-flight detect was user-forced (may overwrite typed BPM).
        self._bpm_force_ids: set[str] = set()
        self._bpm_detect_queue: list[tuple[str, Path, int | None, bool]] = []
        self._bpm_detect_running = False
        # UI progress: -1 = queued, 0..100 = active job percent.
        self._bpm_ui_progress: dict[str, int] = {}
        self._bpm_active_song_id: str | None = None
        self._bpm_detected.connect(self._on_bpm_detected)
        self._bpm_job_finished.connect(self._pump_bpm_detect_queue)
        self._bpm_progress_changed.connect(self._on_bpm_progress_changed)
        self._audio_load_timer = QTimer(self)
        self._audio_load_timer.setInterval(25)
        self._audio_load_timer.timeout.connect(self._poll_pending_audio_load)
        self._block_clean_output_visibility_persist = False
        self._pending_restore_geometry = None

        self.engine = AudioEngine(self)
        self.playback = PlaybackService(self.engine, self._song_session)
        self.show_session = ShowSessionService(self, self.playback)
        self.engine.set_duration(self.current_song.duration_seconds)
        self.engine.set_song_timebase(
            self.current_song.start_timecode, self.current_song.fps
        )
        # Machine-global audio prefs (survive New / Load Project).
        self.settings.apply_audio_to_project(self.project)
        self.engine.apply_audio_settings(self.project.audio_output)
        self.playback.sync_from_engine()

        # Video clips are driven by the audio sample clock (AudioEngine) —
        # no independent video timer (AGENTS.md non-negotiable).
        self.video_sync = VideoSyncController(self)
        self.video_sync.set_decode_quality(self.project.video_decode_quality)
        self.video_sync.set_timeline_video_heavy(bool(self.project.show_video_track))
        # Video frame decode must never be deferred merely because Video Audio
        # is decoding — that reverse priority caused Video stutter. Cache-miss
        # Video Audio may be temporary silence; it must not stall presentation.
        self.video_sync.set_defer_live_decode(None)
        self.video_sync.set_pipeline_state_listener(self._on_video_pipeline_state)
        self.video_sync.set_song(self.current_song)
        self.engine.set_song(self.current_song)
        self.video_preview = VideoPreviewWidget(context_menu=True, smooth_scale=False)
        self.video_preview.set_decode_quality(self.project.video_decode_quality)
        self.video_preview.decode_quality_changed.connect(self._set_video_decode_quality)
        # Parented to MainWindow for object lifetime, but Qt.Window still makes
        # this a separate top-level capture target for OBS. Its X button only
        # hides (see CleanVideoOutputWindow.closeEvent); MainWindow.closeEvent()
        # must force-close it so the process can exit.
        self.clean_output_window = CleanVideoOutputWindow(self)
        self.clean_output_window.apply_settings(self.project.clean_video_output)
        self._ndi_output = NdiVideoOutput()

        self.setWindowTitle(f"{MAIN_WINDOW_TITLE_PREFIX} — {self.project.name}")
        self.resize(1600, 900)
        # Compact enough to share a screen with grandMA / Depence; timeline
        # content scrolls instead of forcing this floor upward.
        self.setMinimumSize(720, 420)

        root = QWidget(self)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.toolbar = TopToolBar()
        self.transport = BottomTransportBar()
        self.timeline = TimelineWidget()
        self.timeline.set_song(self.current_song)
        self._apply_project_mark_line_settings()
        self.timeline.set_position(0.0)
        self.monitor = CueMonitorPanel()
        self.monitor.set_song(self.current_song)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._main_splitter = splitter
        left = QWidget()
        left.setObjectName("setlistPanel")
        # Whole left chrome accepts Explorer audio drops (not only the table
        # cells) — title / empty margins / button row used to swallow them.
        left.setAcceptDrops(True)
        left.installEventFilter(self)
        self._setlist_panel = left
        self._setlist_saved_width = 240
        self._setlist_visible = True
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_title = QLabel("Setlist")
        left_title.setStyleSheet("font-weight: 600;")
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.addWidget(left_title)
        title_row.addStretch(1)
        self.song_list = SetlistWidget()
        self.song_list.setItemDelegate(SetlistRowDelegate(self.song_list))
        self.song_list.set_name_mode(self.project.setlist_name_mode)
        self._sync_setlist_column_prefs()
        self._rebuild_song_list(
            select_indexes=[0] if self.project.songs else []
        )
        if not self.project.songs:
            # Match New Project: empty Setlist, blank timeline (no phantom song).
            self.timeline.set_song(None)
            self.timeline.set_audio(None)
            self.monitor.set_song(None)
            self.video_sync.set_song(None)
            self.engine.set_song(None)
        self.add_song_button = QPushButton("Add")
        self.edit_song_button = QPushButton("Edit")
        self.delete_song_button = QPushButton("Delete")
        self.add_song_button.setToolTip("Add a new song")
        self.edit_song_button.setToolTip(
            "Full edit: number / name / English MA / BPM / Timecode / FPS (or right-click → Edit)"
        )
        self.delete_song_button.setToolTip("Delete selected song(s)")
        self.move_up_button = QPushButton("↑")
        self.move_down_button = QPushButton("↓")
        self.sort_by_number_button = QPushButton("Sort by Number")
        self.renumber_button = QPushButton("Renumber")
        self.move_up_button.setToolTip("Move selected song(s) up")
        self.move_down_button.setToolTip("Move selected song(s) down")
        self.sort_by_number_button.setToolTip(
            "Sort songs by # within Main list, a folder, or All"
        )
        self.renumber_button.setToolTip(
            "Renumber to 1, 2, 3… within Main list, a folder, or All"
        )
        # Footer reflows / shortens labels when Setlist is narrow so Add/Edit/Delete
        # and Sort/Renumber are not clipped (e.g. "elet", "un").
        self._setlist_footer = QWidget()
        self._setlist_footer.setObjectName("setlistFooter")
        self._setlist_footer_layout = QGridLayout(self._setlist_footer)
        self._setlist_footer_layout.setContentsMargins(0, 0, 0, 0)
        self._setlist_footer_layout.setHorizontalSpacing(4)
        self._setlist_footer_layout.setVerticalSpacing(4)
        for button in (
            self.add_song_button,
            self.edit_song_button,
            self.delete_song_button,
            self.sort_by_number_button,
            self.renumber_button,
        ):
            button.setMinimumWidth(0)
            button.setSizePolicy(
                QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed
            )
        self.move_up_button.setFixedWidth(32)
        self.move_down_button.setFixedWidth(32)
        self._setlist_footer_compact: bool | None = None
        self._layout_setlist_footer(compact=False)

        left_layout.addLayout(title_row)
        left_layout.addWidget(self.song_list, stretch=1)
        left_layout.addWidget(self._setlist_footer)

        center = QWidget()
        center.setAcceptDrops(True)
        center.installEventFilter(self)
        self._timeline_center = center
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        self._timeline_scroll = QScrollArea()
        self._timeline_scroll.setWidgetResizable(False)
        self._timeline_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._timeline_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._timeline_scroll.setMinimumHeight(120)
        self._timeline_scroll.setWidget(self.timeline)
        self.timeline.content_geometry_changed.connect(self._sync_timeline_geometry)
        self._timeline_scroll.viewport().installEventFilter(self)
        center_layout.addWidget(self._timeline_scroll, stretch=1)

        # Center column: Timeline (Music → Video → LTC → Marks) on top,
        # Video Preview directly underneath — not stacked under the Cue list.
        self.video_preview_panel = QWidget()
        self.video_preview_panel.setObjectName("videoPreviewPanel")
        self.video_preview_panel.setMinimumHeight(_VIDEO_PREVIEW_SPLIT_MIN_HEIGHT)
        video_panel_layout = QVBoxLayout(self.video_preview_panel)
        video_panel_layout.setContentsMargins(0, 8, 0, 0)
        video_panel_layout.setSpacing(6)
        video_title = QLabel("Video Preview")
        video_title.setStyleSheet("font-weight: 600; color: #a1a1aa;")
        video_panel_layout.addWidget(video_title)
        video_panel_layout.addWidget(self.video_preview, stretch=1)

        timeline_preview_split = QSplitter(Qt.Orientation.Vertical)
        timeline_preview_split.setObjectName("timelinePreviewSplitter")
        timeline_preview_split.addWidget(center)
        timeline_preview_split.addWidget(self.video_preview_panel)
        timeline_preview_split.setStretchFactor(0, 3)
        timeline_preview_split.setStretchFactor(1, 2)
        timeline_preview_split.setSizes([560, 280])
        timeline_preview_split.setChildrenCollapsible(False)
        timeline_preview_split.setCollapsible(0, False)
        # Dragging shut used to hide Preview entirely; View menu still toggles it.
        timeline_preview_split.setCollapsible(1, False)
        self._timeline_preview_split = timeline_preview_split

        # Right column is Cue list only (clock + scrolling marks).
        timeline_split = QSplitter(Qt.Orientation.Horizontal)
        self._timeline_split = timeline_split
        timeline_split.setObjectName("timelineSplit")
        timeline_split.addWidget(timeline_preview_split)
        timeline_split.addWidget(self.monitor)
        timeline_split.setStretchFactor(0, 1)
        timeline_split.setStretchFactor(1, 0)
        timeline_split.setSizes([1020, 320])

        self.show_patch_page = ShowPatchPage()
        self.show_patch_page.set_project(self.project)
        self.setlist_sheet_page = SetlistSheetPage()
        self.setlist_sheet_page.set_project(self.project)
        self.view_stack = QStackedWidget()
        self.view_stack.addWidget(timeline_split)  # 0 = timeline
        self.view_stack.addWidget(self.show_patch_page)  # 1 = MA patch
        self.view_stack.addWidget(self.setlist_sheet_page)  # 2 = setlist sheet
        self.view_stack.setAcceptDrops(True)
        self.view_stack.installEventFilter(self)

        self._main_content_column = QWidget()
        main_content_layout = QVBoxLayout(self._main_content_column)
        main_content_layout.setContentsMargins(0, 0, 0, 0)
        main_content_layout.setSpacing(0)
        main_content_layout.addWidget(self.view_stack, stretch=1)
        main_content_layout.addWidget(self.transport)
        # Explicit floor beats transport / Export-page sizeHints (~1000px+).
        # Without this, QSplitter (non-collapsible) treats the hint as the
        # pane minimum and Setlist cannot drag wider until the window grows.
        self._main_content_column.setMinimumWidth(280)

        splitter.addWidget(left)
        splitter.addWidget(self._main_content_column)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        # Keep Setlist visible when the window is tiny — collapsing to zero
        # made the panel disappear into the left edge on one drag.
        splitter.setChildrenCollapsible(False)
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setSizes([240, 1340])
        left.setMinimumWidth(160)

        root_layout.addWidget(self.toolbar)
        root_layout.addWidget(splitter, stretch=1)
        self.transport.set_center_anchor(self.timeline)
        for split in (self._main_splitter, self._timeline_split, self._timeline_preview_split):
            split.splitterMoved.connect(self._sync_transport_layout)
        self.setCentralWidget(root)

        self.status = QStatusBar(self)
        self.setStatusBar(self.status)
        self._build_file_menu()
        self._setup_autosave()
        self._refresh_window_title()
        self._refresh_status()
        self._web_remote = WebRemoteBridge(MainWindowRemoteHost(self), parent=self)
        self._web_remote.status_changed.connect(
            lambda msg: self.status.showMessage(msg, 4000)
        )
        saved_remote = load_web_remote_prefs()
        err = self._web_remote.apply_prefs(saved_remote, restart=True)
        if err:
            self.status.showMessage(f"Web Remote failed: {err}", 6000)

        self.setAcceptDrops(True)

        self.add_song_button.clicked.connect(self._add_song)
        self.edit_song_button.clicked.connect(self._edit_song)
        self.delete_song_button.clicked.connect(self._delete_song)
        self.move_up_button.clicked.connect(lambda: self._move_selected_songs(-1))
        self.move_down_button.clicked.connect(lambda: self._move_selected_songs(1))
        self.sort_by_number_button.clicked.connect(self._show_sort_section_menu)
        self.renumber_button.clicked.connect(self._show_renumber_section_menu)
        self.song_list.currentCellChanged.connect(self._on_song_cell_changed)
        self.song_list.audio_files_dropped.connect(self._add_songs_from_media_paths)
        self.song_list.audio_drop_rejected.connect(
            lambda msg: self.status.showMessage(msg, 5000)
        )
        self.song_list.rows_reordered.connect(self._on_setlist_rows_reordered)
        self.song_list.songs_moved_to_category.connect(self._on_songs_moved_to_category)
        self.song_list.categories_reordered.connect(self._on_setlist_categories_reordered)
        self.song_list.category_clicked.connect(self._toggle_setlist_category)
        self.song_list.category_rename_requested.connect(self._rename_setlist_category)
        self.song_list.setlist_number_edited.connect(self._on_setlist_number_edited)
        self.song_list.setlist_number_edit_failed.connect(self._on_setlist_number_edit_failed)
        self.song_list.song_title_edited.connect(self._on_song_title_edited)
        self.song_list.song_ma_name_edited.connect(self._on_song_ma_name_edited)
        self.song_list.song_bpm_edited.connect(self._on_song_bpm_edited)
        self.song_list.song_bpm_edit_failed.connect(self._on_song_bpm_edit_failed)
        self.song_list.customContextMenuRequested.connect(self._on_setlist_context_menu)
        self.song_list.horizontalHeader().customContextMenuRequested.connect(
            self._on_setlist_header_context_menu
        )
        self.transport.play_clicked.connect(self.playback.play)
        self.transport.pause_clicked.connect(self.playback.pause)
        self.transport.stop_clicked.connect(self.playback.stop)
        self.toolbar.view_mode_changed.connect(self._set_view_mode)
        self.show_patch_page.settings_changed.connect(self._mark_dirty)
        self.show_patch_page.export_finished.connect(self._on_ma_export_finished)
        self.setlist_sheet_page.song_field_changed.connect(self._on_setlist_sheet_changed)
        self.setlist_sheet_page.sheet_layout_changed.connect(self._mark_dirty)
        self.transport.set_loop_a_clicked.connect(self._set_loop_a)
        self.transport.set_loop_b_clicked.connect(self._set_loop_b)
        self.transport.clear_loop_clicked.connect(self._clear_loop)
        self.transport.loop_toggled.connect(self._set_loop_enabled)
        self.transport.volume_changed.connect(self.playback.set_volume)
        self.transport.music_mute_toggled.connect(self._set_music_muted_from_ui)
        self.engine.music_muted_changed.connect(self.transport.set_music_muted)
        self.timeline.seek_requested.connect(self._on_timeline_seek_requested)
        self.transport.seek_requested.connect(
            lambda t: self._canonical_seek(float(t), input_source="overview")
        )
        self.timeline.view_changed.connect(self._sync_timeline_overview)
        self.timeline.content_geometry_changed.connect(self._sync_timeline_overview)
        self.timeline.scrub_started.connect(self._on_timeline_scrub_started)
        self.timeline.scrub_ended.connect(self._on_timeline_scrub_ended)
        # Unthrottled target → video scrub scheduler (latest-wins, ~16 Hz decode).
        self.timeline.scrub_target_changed.connect(
            lambda t: self.video_sync.update_position(t, source="scrub")
        )
        # Throttled chrome only (transport / cue list / clock).
        self.timeline.scrub_preview_requested.connect(self._on_scrub_preview)
        self.timeline.selection_changed.connect(self._on_timeline_selection)
        self.timeline.delete_requested.connect(self._delete_marks)
        self.timeline.note_rename_requested.connect(self._on_note_changed)
        self.timeline.cue_id_edit_requested.connect(self._on_cue_id_changed)
        self.timeline.change_type_requested.connect(self._change_mark_types)
        self.timeline.marks_changed.connect(self._on_marks_changed)
        self.timeline.marks_moved.connect(self._on_marks_moved)
        self.timeline.offset_requested.connect(self._offset_marks)
        self.timeline.loop_changed.connect(self._on_loop_region_dragged)
        self.timeline.video_clips_changed.connect(self._on_video_clips_changed)
        self.timeline.video_clip_edited.connect(self._on_video_clip_edited)
        self.timeline.video_clips_batch_edited.connect(self._on_video_clips_batch_edited)
        self.timeline.delete_video_clips_requested.connect(self._delete_video_clips)
        self.timeline.add_video_clip_requested.connect(self._add_video_clip_at)
        self.timeline.split_video_clip_requested.connect(self._split_video_clip)
        self.timeline.duplicate_video_clip_requested.connect(self._duplicate_video_clip)
        self.timeline.video_files_dropped.connect(self._add_video_clips_from_paths)
        self.timeline.video_track_mute_toggled.connect(self._on_video_track_mute_toggled)
        self.timeline.video_track_visibility_changed.connect(self._on_video_track_visibility_changed)
        self.timeline.ltc_track_visibility_changed.connect(self._on_ltc_track_visibility_changed)
        self.timeline.wave_gain_line_visibility_changed.connect(self._on_wave_gain_line_visibility_changed)
        self.timeline.ltc_gain_line_visibility_changed.connect(self._on_ltc_gain_line_visibility_changed)
        self.timeline.video_clip_volume_changed.connect(self._on_video_clip_volume_changed)
        self.timeline.music_volume_changed.connect(self._on_music_volume_changed)
        self.timeline.audio_gain_changed.connect(self._on_audio_gain_changed)
        self.timeline.lane_name_changed.connect(self._on_mark_lane_renamed)
        self.timeline.mark_manager_requested.connect(self._open_mark_manager)
        self.timeline.mark_lane_height_changed.connect(self._on_mark_lane_height_changed)
        self.timeline.mark_track_colors_changed.connect(self._on_mark_track_colors_changed)
        self.timeline.add_mark_requested.connect(self._add_mark)
        # Video decode must not run ahead of timeline paint, and must not pile
        # QueuedConnection backlog while the UI is busy. Single canonical path:
        # position fan-out → timeline first → then video_sync.update_position.
        # Scrub uses scrub_preview_requested only (engine forward skipped).
        self.engine.playing_changed.connect(self.video_sync.set_playing)
        # One RGB→QImage conversion shared by Preview + Clean Output (avoids
        # double memcpy when Clean Output is open with a video track).
        self.video_sync.frame_changed.connect(self._on_video_frame)
        self.video_sync.activation_loading.connect(self._on_video_activation_loading)
        self.video_sync.overlap_warning.connect(lambda msg: self.status.showMessage(msg, 4000))
        self.clean_output_window.visibility_changed.connect(self._clean_output_action.setChecked)
        self.clean_output_window.visibility_changed.connect(self._sync_video_output_active)
        self.clean_output_window.visibility_changed.connect(self._persist_clean_output_was_open)
        self.clean_output_window.decode_quality_changed.connect(self._set_video_decode_quality)
        self.clean_output_window.ndi_toggled.connect(self._toggle_ndi_output)
        self.clean_output_window.ndi_name_changed.connect(self._on_ndi_name_changed)
        self.clean_output_window.ndi_frame_mode_changed.connect(self._on_ndi_frame_mode_changed)
        self.clean_output_window.settings_changed.connect(self._on_clean_output_settings_changed)
        self._apply_ndi_from_project(show_errors=False)
        self.monitor.seek_requested.connect(self._seek_from_cue_list)
        self.monitor.selection_changed.connect(self._on_monitor_selection)
        self.monitor.delete_requested.connect(self._delete_marks)
        self.monitor.note_changed.connect(self._on_note_changed)
        self.monitor.cue_id_changed.connect(self._on_cue_id_changed)
        self.monitor.cue_id_edit_failed.connect(
            lambda msg: self.status.showMessage(msg, 3000)
        )
        self.monitor.now_visibility_changed.connect(self._on_monitor_ui_prefs_changed)
        self.monitor.cue_list_visibility_changed.connect(self._on_monitor_ui_prefs_changed)
        self.monitor.output_timecode_clock_changed.connect(
            self._on_output_timecode_clock_changed
        )
        self.monitor.output_quick_toggles_visibility_changed.connect(
            self._on_output_quick_toggles_visibility_changed
        )
        self.monitor.output_toggle_changed.connect(self._on_output_quick_toggle)
        self.monitor.audio_settings_requested.connect(self._open_audio_timecode)
        self.monitor.cue_list_layout_changed.connect(self._on_monitor_ui_prefs_changed)
        self.monitor.now_layout_changed.connect(self._on_now_layout_changed)
        self.monitor.renumber_cue_ids_requested.connect(self._renumber_main_cue_ids)
        self.engine.position_changed.connect(self._on_position_changed)
        self.engine.playing_changed.connect(lambda _playing=False: self.playback.sync_from_engine())
        self.engine.playing_changed.connect(self.transport.set_playing)
        self.engine.playing_changed.connect(self.timeline.set_playing)
        self.engine.timecode_status_changed.connect(self._refresh_timecode_status)
        self.engine.timecode_status_changed.connect(self._refresh_setlist_ltc_cells)
        self.engine.timecode_status_changed.connect(self._refresh_output_timecode_clock)
        self.engine.playing_changed.connect(
            lambda _playing: self._refresh_output_timecode_clock()
        )
        self.engine.playing_changed.connect(self._on_playing_changed_video_standin)
        self._refresh_timecode_status()
        self._sync_output_timecode_clock_ui()
        self._refresh_output_timecode_clock()

        QShortcut(QKeySequence(Qt.Key.Key_Space), self, activated=self.playback.toggle)
        QShortcut(QKeySequence(Qt.Key.Key_Left), self, activated=lambda: self._nudge_frames(-1))
        QShortcut(QKeySequence(Qt.Key.Key_Right), self, activated=lambda: self._nudge_frames(1))
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self, activated=self._delete_current_selection)
        QShortcut(QKeySequence(Qt.Key.Key_Backspace), self, activated=self._delete_current_selection)
        QShortcut(QKeySequence.StandardKey.Undo, self, activated=self._undo_action)
        QShortcut(QKeySequence.StandardKey.Redo, self, activated=self._redo_action)
        QShortcut(QKeySequence.StandardKey.Copy, self, activated=self._copy_video_clips)
        QShortcut(QKeySequence.StandardKey.Paste, self, activated=self._paste_video_clips)
        self._rebuild_digit_shortcuts()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        self.transport.set_times(0.0, self.engine.duration)
        self.monitor.set_position(0.0, self.engine.duration)

        self._restoring_session = False
        QTimer.singleShot(0, self._sync_timeline_geometry)
        QTimer.singleShot(0, self._restore_startup_session)

    def _restore_startup_session(self) -> None:
        """Restore window layout, last project, and demo fixture fallback."""
        self._restoring_session = True
        try:
            try:
                self._restore_ui_layout()
                self._restore_clean_output_visibility()
                self._restore_clean_output_geometry()
                self._sync_video_output_active()
                if not self._try_restore_last_project():
                    self._maybe_load_demo_fixture()
                self._sync_timeline_geometry()
                self._sync_transport_layout()
                self.monitor.ensure_now_splitter_ready()
                QTimer.singleShot(0, self.monitor.ensure_now_splitter_ready)
                QTimer.singleShot(100, self.monitor.ensure_now_splitter_ready)
            except Exception:  # noqa: BLE001
                import traceback

                traceback.print_exc()
        finally:
            self._restoring_session = False
            # Layout/splitter sizes settle after restore — Preview visibility
            # (and thus decode arming) can be wrong on the first tick.
            QTimer.singleShot(0, self._ensure_video_preview_frame)
            QTimer.singleShot(80, self._ensure_video_preview_frame)
            # Let queued splitter/layout timers settle, then tell the splash we are ready.
            def _emit_ready() -> None:
                self.startup_session_ready = True
                self.startup_ready.emit()

            QTimer.singleShot(0, _emit_ready)

    @property
    def _project_path(self) -> Path | None:
        return self._project_service.path

    @_project_path.setter
    def _project_path(self, value: Path | None) -> None:
        self._project_service.set_path(value)

    @property
    def _dirty(self) -> bool:
        return self._project_service.is_dirty

    @_dirty.setter
    def _dirty(self, value: bool) -> None:
        if value:
            self._project_service.mark_dirty()
        else:
            self._project_service.mark_clean()

    @property
    def current_song(self) -> Song:
        song = self._song_session.song
        return song if song is not None else self._blank_song

    @current_song.setter
    def current_song(self, song: Song) -> None:
        self._song_session.set_song(song)

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        self._sync_transport_layout()

    def _sync_transport_layout(self) -> None:
        if getattr(self, "_syncing_transport_layout", False):
            return
        self._syncing_transport_layout = True
        try:
            self._balance_timeline_monitor_split()
            self._fit_setlist_footer()
            transport = getattr(self, "transport", None)
            if transport is not None:
                transport.sync_geometry()
        finally:
            self._syncing_transport_layout = False

    def _layout_setlist_footer(self, *, compact: bool) -> None:
        """Place Setlist action buttons; compact = short labels + tighter grid."""
        layout = getattr(self, "_setlist_footer_layout", None)
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            if item is not None:
                item.widget()  # keep ownership on buttons; only detach from grid
        if compact:
            self.delete_song_button.setText("Del")
            self.sort_by_number_button.setText("Sort #")
            self.renumber_button.setText("Re#")
            # 3×2-ish: actions wrap so nothing is clipped at ~160px.
            layout.addWidget(self.add_song_button, 0, 0)
            layout.addWidget(self.edit_song_button, 0, 1)
            layout.addWidget(self.delete_song_button, 0, 2)
            layout.addWidget(self.move_up_button, 1, 0)
            layout.addWidget(self.move_down_button, 1, 1)
            layout.addWidget(self.sort_by_number_button, 1, 2)
            layout.addWidget(self.renumber_button, 2, 0, 1, 3)
        else:
            self.delete_song_button.setText("Delete")
            self.sort_by_number_button.setText("Sort by Number")
            self.renumber_button.setText("Renumber")
            layout.addWidget(self.add_song_button, 0, 0)
            layout.addWidget(self.edit_song_button, 0, 1)
            layout.addWidget(self.delete_song_button, 0, 2)
            layout.addWidget(self.move_up_button, 1, 0)
            layout.addWidget(self.move_down_button, 1, 1)
            layout.addWidget(self.sort_by_number_button, 1, 2)
            layout.addWidget(self.renumber_button, 1, 3)
        for col in range(4):
            layout.setColumnStretch(col, 1 if col < 3 else (0 if compact else 1))
        self._setlist_footer_compact = compact

    def _fit_setlist_footer(self) -> None:
        panel = getattr(self, "_setlist_panel", None)
        if panel is None or not hasattr(self, "_setlist_footer"):
            return
        # Margins 8+8; use inner width so labels match the visible chrome.
        inner = max(0, panel.width() - 16)
        compact = inner < 240
        if compact != self._setlist_footer_compact:
            self._layout_setlist_footer(compact=compact)

    def _balance_timeline_monitor_split(self) -> None:
        """Prefer shrinking the Cue monitor before starving the timeline column.

        ``timeline_split`` uses stretch (1, 0), so Qt shrinks the timeline first
        when the content pane narrows (e.g. Setlist dragged wider). Reclaim width
        from the monitor down to its minimum so waveform + Setlist stay usable.
        """
        split = getattr(self, "_timeline_split", None)
        monitor = getattr(self, "monitor", None)
        if split is None or monitor is None or split.count() < 2:
            return
        sizes = split.sizes()
        total = int(sum(sizes))
        if total <= 0:
            return
        timeline_floor = 200
        mon_min = max(120, int(monitor.minimumWidth()))
        mon_max = int(monitor.maximumWidth())
        timeline_w, mon_w = int(sizes[0]), int(sizes[1])
        if timeline_w >= timeline_floor:
            return
        if total < timeline_floor + mon_min:
            mon_w = min(mon_w, max(mon_min, total - max(80, total // 4)))
        else:
            mon_w = max(mon_min, min(mon_max, total - timeline_floor))
        mon_w = max(mon_min, min(mon_w, total))
        new_timeline = max(0, total - mon_w)
        if new_timeline == timeline_w and mon_w == int(sizes[1]):
            return
        split.setSizes([new_timeline, mon_w])

    def _lock_main_splitter_panels(self) -> None:
        """Prevent the Setlist / content panes from collapsing to zero width.

        When Setlist is hidden via View → Set List, index 0 may stay collapsed
        until the user shows it again — do not force it open here.
        """
        main_split = getattr(self, "_main_splitter", None)
        if main_split is None:
            return
        setlist_visible = self._setlist_panel_is_visible()
        if setlist_visible:
            main_split.setChildrenCollapsible(False)
            for index in range(main_split.count()):
                main_split.setCollapsible(index, False)
            left = main_split.widget(0)
            if left is not None and left.minimumWidth() < 160:
                left.setMinimumWidth(160)
        else:
            main_split.setChildrenCollapsible(False)
            main_split.setCollapsible(0, True)
            main_split.setCollapsible(1, False)
            left = main_split.widget(0)
            if left is not None:
                left.setMinimumWidth(0)
        right = main_split.widget(1)
        # Keep an explicit content floor so transport sizeHints cannot freeze
        # the Setlist splitter on narrow windows (see ctor comment).
        if right is not None and right.minimumWidth() < 280:
            right.setMinimumWidth(280)

    def _setlist_panel_is_visible(self) -> bool:
        return bool(getattr(self, "_setlist_visible", True))

    def _remember_setlist_width(self) -> None:
        main_split = getattr(self, "_main_splitter", None)
        if main_split is None:
            return
        sizes = main_split.sizes()
        if sizes and sizes[0] > 0:
            self._setlist_saved_width = int(sizes[0])

    def _set_setlist_visible(self, visible: bool, *, persist: bool = True) -> None:
        """Show or hide the left Set List panel (View menu)."""
        panel = getattr(self, "_setlist_panel", None)
        main_split = getattr(self, "_main_splitter", None)
        if panel is None or main_split is None:
            return
        visible = bool(visible)
        self._setlist_visible = visible
        if visible:
            panel.setVisible(True)
            panel.setMinimumWidth(160)
            main_split.setCollapsible(0, False)
            width = int(getattr(self, "_setlist_saved_width", 0) or 0)
            if width < 160:
                raw = self._settings.value(_KEY_SETLIST_WIDTH, 240)
                try:
                    width = int(raw)
                except (TypeError, ValueError):
                    width = 240
            width = max(160, width)
            total = sum(main_split.sizes()) or max(main_split.width(), width + 280)
            main_split.setSizes([width, max(280, total - width)])
        else:
            self._remember_setlist_width()
            panel.setMinimumWidth(0)
            main_split.setCollapsible(0, True)
            sizes = main_split.sizes()
            total = sum(sizes) if sizes else max(1, main_split.width())
            main_split.setSizes([0, max(1, total)])
            panel.setVisible(False)
        self._lock_main_splitter_panels()
        action = getattr(self, "_act_setlist", None)
        if action is not None and action.isChecked() != visible:
            action.blockSignals(True)
            action.setChecked(visible)
            action.blockSignals(False)
        if persist and not getattr(self, "_restoring_session", False):
            self._settings.setValue(_KEY_SETLIST_VISIBLE, visible)
            width = int(getattr(self, "_setlist_saved_width", 0) or 0)
            if visible:
                sizes = main_split.sizes()
                if sizes and sizes[0] > 0:
                    width = int(sizes[0])
            if width >= 160:
                self._settings.setValue(_KEY_SETLIST_WIDTH, width)
        self._sync_transport_layout()

    def _toggle_setlist_panel(self, visible: bool) -> None:
        self._set_setlist_visible(bool(visible))

    def _restore_ui_layout(self) -> None:
        geometry = self._settings.value(_KEY_MAIN_GEOMETRY)
        if geometry:
            self.restoreGeometry(geometry)
            # Keep a copy so we can re-apply after show() (multi-monitor / splash).
            self._pending_restore_geometry = geometry
        else:
            self._pending_restore_geometry = None
            self.resize(1600, 900)
        state = self._settings.value(_KEY_MAIN_STATE)
        if state:
            self.restoreState(state)
        main_split = getattr(self, "_main_splitter", None)
        if main_split is not None:
            raw = self._settings.value(_KEY_MAIN_SPLITTER)
            if raw:
                main_split.restoreState(raw)
            # restoreState can re-enable collapse from an older session; keep
            # Setlist from vanishing into the left edge when dragged narrow.
            self._lock_main_splitter_panels()
        raw_setlist_w = self._settings.value(_KEY_SETLIST_WIDTH, 240)
        try:
            self._setlist_saved_width = max(160, int(raw_setlist_w))
        except (TypeError, ValueError):
            self._setlist_saved_width = 240
        setlist_visible = bool(
            self._settings.value(_KEY_SETLIST_VISIBLE, True, type=bool)
        )
        self._set_setlist_visible(setlist_visible, persist=False)
        timeline_split = getattr(self, "_timeline_split", None)
        if timeline_split is not None:
            raw = self._settings.value(_KEY_TIMELINE_SPLITTER)
            if raw:
                timeline_split.restoreState(raw)
        preview_split = getattr(self, "_timeline_preview_split", None)
        if preview_split is not None:
            raw = self._settings.value(_KEY_TIMELINE_PREVIEW_SPLITTER)
            if raw:
                preview_split.restoreState(raw)
            self._clamp_video_preview_splitter()
        raw_hw = self._settings.value(_KEY_TIMELINE_HEADER_WIDTH)
        if raw_hw is not None:
            try:
                self.timeline.set_header_width(int(raw_hw), emit=False)
            except (TypeError, ValueError):
                pass
        self._sync_transport_layout()
        placement = str(self._settings.value(_KEY_NOW_SECONDARY_PLACEMENT, "right") or "right")
        payload = {
            "placement": placement,
            "right": self._settings.value(_KEY_NOW_SPLITTER_RIGHT),
            "below": self._settings.value(_KEY_NOW_SPLITTER_BELOW),
            "current": self._settings.value(_KEY_NOW_SPLITTER),
            "body": self._settings.value(_KEY_NOW_BODY_SPLITTER),
        }
        self.monitor.restore_now_splitter_state(payload)
        self._restore_monitor_ui_prefs()
        mode = str(self._settings.value(_KEY_VIEW_MODE, "timeline") or "timeline")
        if mode == "ma_patch":
            self.toolbar.set_view_mode("ma_patch")
            self._set_view_mode("ma_patch")
        elif mode == "setlist":
            self.toolbar.set_view_mode("setlist")
            self._set_view_mode("setlist")

    def _restore_monitor_ui_prefs(self) -> None:
        """Load global NOW / Cue List chrome (visibility, columns) from QSettings."""
        settings = self._settings
        prefs: dict = {}
        if settings.contains(_KEY_NOW_PRIMARY_VISIBLE):
            prefs["now_primary_visible"] = settings.value(_KEY_NOW_PRIMARY_VISIBLE, True, type=bool)
        if settings.contains(_KEY_NOW_SECONDARY_VISIBLE):
            prefs["now_secondary_visible"] = settings.value(
                _KEY_NOW_SECONDARY_VISIBLE, True, type=bool
            )
        if settings.contains(_KEY_CUE_LIST_VISIBLE):
            prefs["cue_list_visible"] = settings.value(_KEY_CUE_LIST_VISIBLE, True, type=bool)
        if settings.contains(_KEY_NOW_PRIMARY_SHOW_CUE_ID):
            prefs["now_primary_show_cue_id"] = settings.value(
                _KEY_NOW_PRIMARY_SHOW_CUE_ID, True, type=bool
            )
        if settings.contains(_KEY_NOW_PRIMARY_SINGLE_LINE):
            prefs["now_primary_single_line"] = settings.value(
                _KEY_NOW_PRIMARY_SINGLE_LINE, False, type=bool
            )
        if settings.contains(_KEY_CUE_LIST_SHOW_CUE_ID):
            prefs["cue_list_show_cue_id"] = settings.value(
                _KEY_CUE_LIST_SHOW_CUE_ID, True, type=bool
            )
        order = settings.value(_KEY_CUE_LIST_COLUMN_ORDER)
        if isinstance(order, list) and order:
            prefs["cue_list_column_order"] = order
        elif isinstance(order, str) and order.strip():
            prefs["cue_list_column_order"] = [p.strip() for p in order.split(",") if p.strip()]
        header = settings.value(_KEY_CUE_LIST_HEADER)
        if header:
            prefs["cue_list_header"] = header
        if prefs:
            self.monitor.apply_monitor_ui_prefs(prefs)
            self._sync_monitor_ui_prefs_to_songs()

    def _save_monitor_ui_prefs(self) -> None:
        prefs = self.monitor.monitor_ui_prefs()
        self._settings.setValue(_KEY_NOW_PRIMARY_VISIBLE, prefs["now_primary_visible"])
        self._settings.setValue(_KEY_NOW_SECONDARY_VISIBLE, prefs["now_secondary_visible"])
        self._settings.setValue(_KEY_CUE_LIST_VISIBLE, prefs["cue_list_visible"])
        self._settings.setValue(_KEY_NOW_PRIMARY_SHOW_CUE_ID, prefs["now_primary_show_cue_id"])
        self._settings.setValue(_KEY_NOW_PRIMARY_SINGLE_LINE, prefs["now_primary_single_line"])
        self._settings.setValue(_KEY_CUE_LIST_SHOW_CUE_ID, prefs["cue_list_show_cue_id"])
        self._settings.setValue(_KEY_CUE_LIST_COLUMN_ORDER, prefs["cue_list_column_order"])
        self._settings.setValue(_KEY_CUE_LIST_HEADER, prefs["cue_list_header"])

    def _sync_monitor_ui_prefs_to_songs(self) -> None:
        """Mirror global chrome onto every song so project files stay consistent."""
        prefs = self.monitor.monitor_ui_prefs()
        order = list(prefs["cue_list_column_order"])
        for song in self.project.songs:
            song.now_primary_visible = bool(prefs["now_primary_visible"])
            song.now_secondary_visible = bool(prefs["now_secondary_visible"])
            song.cue_list_visible = bool(prefs["cue_list_visible"])
            song.now_primary_show_cue_id = bool(prefs["now_primary_show_cue_id"])
            song.now_primary_single_line = bool(prefs["now_primary_single_line"])
            song.cue_list_show_cue_id = bool(prefs["cue_list_show_cue_id"])
            song.cue_list_column_order = list(order)

    def _on_monitor_ui_prefs_changed(self) -> None:
        if self._restoring_session:
            return
        self._sync_monitor_ui_prefs_to_songs()
        self._save_monitor_ui_prefs()
        self._mark_dirty()

    def _save_ui_session(self) -> None:
        if self._restoring_session:
            return
        self._settings.setValue(_KEY_MAIN_GEOMETRY, self.saveGeometry())
        self._settings.setValue(_KEY_MAIN_STATE, self.saveState())
        main_split = getattr(self, "_main_splitter", None)
        if main_split is not None:
            if self._setlist_panel_is_visible():
                self._remember_setlist_width()
            self._settings.setValue(_KEY_MAIN_SPLITTER, main_split.saveState())
            self._settings.setValue(
                _KEY_SETLIST_VISIBLE, self._setlist_panel_is_visible()
            )
            width = int(getattr(self, "_setlist_saved_width", 0) or 0)
            if width >= 160:
                self._settings.setValue(_KEY_SETLIST_WIDTH, width)
        timeline_split = getattr(self, "_timeline_split", None)
        if timeline_split is not None:
            self._settings.setValue(_KEY_TIMELINE_SPLITTER, timeline_split.saveState())
        preview_split = getattr(self, "_timeline_preview_split", None)
        if preview_split is not None:
            self._settings.setValue(
                _KEY_TIMELINE_PREVIEW_SPLITTER, preview_split.saveState()
            )
        self._settings.setValue(
            _KEY_TIMELINE_HEADER_WIDTH, int(self.timeline.header_width())
        )
        layout_state = self.monitor.save_now_splitter_state()
        self._settings.setValue(_KEY_NOW_SECONDARY_PLACEMENT, layout_state["placement"])
        self._settings.setValue(_KEY_NOW_SPLITTER, layout_state["current"])
        self._settings.setValue(_KEY_NOW_SPLITTER_RIGHT, layout_state["right"])
        self._settings.setValue(_KEY_NOW_SPLITTER_BELOW, layout_state["below"])
        self._settings.setValue(_KEY_NOW_BODY_SPLITTER, layout_state.get("body"))
        self._save_monitor_ui_prefs()
        mode = "timeline"
        stack_index = self.view_stack.currentIndex()
        if stack_index == 1:
            mode = "ma_patch"
        elif stack_index == 2:
            mode = "setlist"
        self._settings.setValue(_KEY_VIEW_MODE, mode)
        if self._project_path is not None:
            self._project_service.remember_recent(self._project_path)
            self._project_service.remember_last_song_id(self.current_song.id)
        self._settings.setValue(
            _KEY_CLEAN_OUTPUT_GEOMETRY, self.clean_output_window.saveGeometry()
        )
        self._settings.sync()

    def apply_restored_geometry_after_show(self) -> None:
        """Re-apply saved geometry after the window is shown.

        Splash / multi-monitor startup can ignore a pre-show ``restoreGeometry``.
        Call this from the show path so size and screen stick.
        """
        geometry = getattr(self, "_pending_restore_geometry", None)
        if not geometry:
            return
        self.restoreGeometry(geometry)
        self._pending_restore_geometry = None
        self._clamp_window_to_available_screens()

    def _clamp_window_to_available_screens(self) -> None:
        """If the frame sits on no connected screen, move it onto the primary."""
        app = QApplication.instance()
        if app is None:
            return
        frame = self.frameGeometry()
        screens = app.screens()
        if any(screen.availableGeometry().intersects(frame) for screen in screens):
            return
        screen = app.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.move(geo.x() + 40, geo.y() + 40)

    def _try_restore_last_project(self) -> bool:
        if self._project_path is not None:
            return False
        path = self._project_service.last_project_path()
        if path is None:
            return False
        song_id_str = self._project_service.last_song_id()
        if self._open_project_path(path, song_id=song_id_str, quiet=True):
            self.status.showMessage(f"Restored: {path.name}", 3500)
            return True
        return False

    def _open_project_path(
        self, path: Path, *, song_id: str | None = None, quiet: bool = False
    ) -> bool:
        try:
            project = self._project_service.open_project(path)
        except Exception as exc:  # noqa: BLE001
            if quiet:
                self.status.showMessage(f"Could not reopen last project: {exc}", 6000)
            else:
                QMessageBox.warning(self, "Unable to Open Project", str(exc))
            return False
        self.playback.stop()
        self.project = project
        self._audio_ltc_cache.update(load_all_ltc_channels())
        self._apply_project(preferred_song_id=song_id)
        self._set_clean()
        self._ltc_idle_timer.start()
        self._maybe_prompt_missing_media(quiet=quiet)
        return True

    def _open_missing_media_relink(self) -> None:
        initial = self._project_path.parent if self._project_path is not None else None
        dialog = MissingMediaRelinkDialog(
            self.project, parent=self, initial_dir=initial
        )
        dialog.exec()
        if dialog.changed:
            self._mark_dirty()
            # Reload current song so waveforms / video pick up new paths.
            idx = self.project.songs.index(self.current_song) if self.current_song in self.project.songs else 0
            self._activate_song(idx, stop_playback=False)
            remaining = scan_missing_media(self.project)
            if remaining:
                self.status.showMessage(
                    f"Relinked — {len(remaining)} file(s) still missing", 4500
                )
            else:
                self.status.showMessage("All media files linked", 3500)

    def _bundle_project_filename(self) -> str:
        if self._project_path is not None:
            name = self._project_path.name
            if name.lower().endswith(".cueplayer.json"):
                return name
        stem = (self.project.name or "Show").strip() or "Show"
        for ch in '<>:"/\\|?*':
            stem = stem.replace(ch, "_")
        return f"{stem}.cueplayer.json"

    def _collect_project_bundle(self) -> None:
        """Save As into a Bundle folder (incremental — safe to re-use the same folder)."""
        # Heal paths broken by earlier Media folder moves before claiming missing.
        if self._project_path is not None:
            healed = heal_stale_media_paths(
                self.project, project_file=self._project_path
            )
            if healed:
                self._mark_dirty()
                self.status.showMessage(
                    f"Relinked {healed} media path(s) under Media/",
                    3500,
                )
        missing = scan_missing_media(self.project)
        if missing:
            names = []
            seen: set[str] = set()
            for ref in missing:
                if ref.basename in seen:
                    continue
                seen.add(ref.basename)
                names.append(f"  · {ref.song_name}: {ref.basename}")
            preview = "\n".join(names[:8])
            more = "" if len(names) <= 8 else f"\n  · …and {len(names) - 8} more"
            answer = QMessageBox.question(
                self,
                "Collect Project Bundle",
                f"{len(missing)} media file(s) are missing and cannot be copied.\n\n"
                f"{preview}{more}\n\n"
                "Often this means a Setlist folder move left an old path behind — "
                "try File → Relink Missing Media… if the file is still on disk.\n\n"
                "Continue and bundle the files that are still available?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        start = (
            str(self._project_path.parent)
            if self._project_path is not None
            else ""
        )
        dest_str = QFileDialog.getExistingDirectory(
            self,
            "Bundle / Save As — choose folder "
            f"(project file at root, {DEFAULT_MEDIA_SUBDIR}/<Setlist>/<Song>/ inside). "
            "Re-selecting your current Bundle folder only adds new media.",
            start,
        )
        if not dest_str:
            return
        dest_dir = Path(dest_str)

        default_name = self._bundle_project_filename()
        # If we're already inside this folder, keep the live project filename.
        if (
            self._project_path is not None
            and self._project_path.parent.resolve() == dest_dir.resolve()
        ):
            default_name = self._project_path.name
        project_name, ok = QInputDialog.getText(
            self,
            "Project file name",
            "Name for the .cueplayer.json in this folder:",
            text=default_name,
        )
        if not ok:
            return
        project_name = (project_name or "").strip() or default_name
        if not project_name.endswith(".json"):
            if project_name.endswith(".cueplayer"):
                project_name = f"{project_name}.json"
            else:
                project_name = f"{project_name}.cueplayer.json"
        for ch in '<>:"/\\|?*':
            project_name = project_name.replace(ch, "_")

        target_project = dest_dir / project_name
        updating_same = (
            self._project_path is not None
            and self._project_path.resolve() == target_project.resolve()
        )
        if target_project.exists() and not updating_same:
            overwrite = QMessageBox.question(
                self,
                "Overwrite?",
                f"{project_name} already exists in this folder.\nOverwrite it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if overwrite != QMessageBox.StandardButton.Yes:
                return

        self.project.clean_video_output = self.clean_output_window.current_settings()
        self.project.video_decode_quality = self.video_sync.decode_quality()
        try:
            result = collect_project_bundle(
                self.project,
                dest_dir,
                project_filename=project_name,
                media_subdir=DEFAULT_MEDIA_SUBDIR,
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Bundle Failed", str(exc))
            return

        lines = [
            f"Project: {result.project_path.name}",
            f"Media: {result.media_dir.name}/<Setlist folder>/<Song>/",
            f"Copied (new): {len(result.copied)}",
            f"Reused (already in folder): {len(result.reused)}",
            f"Moved inside Media: {len(result.moved)}",
        ]
        if result.folders_used:
            lines.append("Setlist folders: " + ", ".join(result.folders_used))
        if result.renamed:
            lines.append(f"Renamed (name clash): {len(result.renamed)}")
        if result.missing:
            lines.append(f"Still missing (not copied): {len(result.missing)}")
        lines.append("")
        lines.append("This project now points at the Bundle folder.")

        QMessageBox.information(self, "Bundle Saved", "\n".join(lines))

        # Save As: switch the live session onto the bundled project.
        try:
            loaded = self._project_service.open_project(result.project_path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self,
                "Bundle Saved",
                f"Bundle written, but could not open it:\n{exc}",
            )
            return
        preferred = self.current_song.id if self.project.songs else None
        self.playback.stop()
        self.project = loaded
        # Bundle remapped media paths + cloned LTC disk cache — remount
        # in-memory keys and reload disk so Setlist L/R badges stay lit
        # (same as Open Project; without this lamps look "off until restart").
        self._remount_caches_after_bundle(result)
        self._apply_project(preferred_song_id=preferred)
        self._set_clean()
        self._ltc_idle_timer.start()
        self.status.showMessage(
            f"Working in Bundle: {result.project_path} "
            f"(+{len(result.copied)} new, {len(result.reused)} reused)",
            6000,
        )

    def _maybe_prompt_missing_media(self, *, quiet: bool = False) -> None:
        if self._project_path is not None:
            healed = heal_stale_media_paths(
                self.project, project_file=self._project_path
            )
            if healed and not quiet:
                self._mark_dirty()
                self.status.showMessage(
                    f"Relinked {healed} media path(s) under Media/",
                    4000,
                )
        missing = scan_missing_media(self.project)
        if not missing:
            return
        msg = f"{len(missing)} media file(s) missing"
        if quiet:
            self.status.showMessage(
                f"{msg} — File → Relink Missing Media…",
                8000,
            )
            return
        answer = QMessageBox.question(
            self,
            "Missing Media",
            f"{msg}.\n\nOpen Relink dialog now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._open_missing_media_relink()
        else:
            self.status.showMessage(f"{msg} — File → Relink Missing Media…", 6000)

    def _maybe_load_demo_fixture(self) -> None:
        """Auto-load demo fixture if present (Chinese path stress)."""
        demo = (
            Path(__file__).resolve().parents[2]
            / "fixtures"
            / "media"
            / "中文測試"
            / "LTC左_音樂右_測試.wav"
        )
        if demo.is_file():
            self._load_audio_path(demo, mark_dirty=False)
            self._set_clean()

    def _video_preview_visible(self) -> bool:
        panel = self.video_preview_panel
        if not panel.isVisible():
            return False
        split = getattr(self, "_timeline_preview_split", None)
        if split is not None:
            sizes = split.sizes()
            if len(sizes) >= 2 and sizes[1] <= 0:
                return False
        return True

    def _clean_output_visible(self) -> bool:
        return self.clean_output_window.isVisible()

    def _on_video_frame(self, frame) -> None:  # noqa: ANN001
        """Fan out one decoded RGB frame to Preview / Clean / NDI / Web Remote.

        Preview + Clean share a single QImage conversion. NDI keeps the
        ndarray. Invisible sinks are skipped so opening Clean Output does not
        pay for a hidden Preview panel copy. Web Remote copies RGB for WebRTC.

        Decode runs off-UI (async worker / land sync). This path only converts
        and presents — instrumented separately from ``video.decode``.
        """
        with perf_diag.span("video.present"):
            perf_diag.count("video.present.calls")
            present_t0 = time.monotonic()
            timeline = getattr(self, "timeline", None)
            zoom_busy = bool(
                timeline is not None
                and hasattr(timeline, "is_view_transform_busy")
                and timeline.is_view_transform_busy()
            )
            if zoom_busy:
                perf_diag.count("video.frames_ready_while_ui_busy")
            preview_vis = self._video_preview_visible()
            clean_vis = self._clean_output_visible()
            ndi_on = bool(self.project.clean_video_output.ndi_enabled)
            remote = getattr(self, "_web_remote", None)
            remote_prev = bool(remote is not None and remote.remote_preview_wanted)

            if frame is None:
                if preview_vis:
                    self.video_preview.set_qimage(None)
                if clean_vis:
                    self.clean_output_window.set_qimage(None)
                if ndi_on:
                    self._ndi_output.send_frame(None)
                if remote_prev and remote is not None:
                    remote.push_preview_frame(None)
                return

            # Reject zero-size / invalid buffers before converting.
            try:
                h, w = int(frame.shape[0]), int(frame.shape[1])
            except Exception:
                perf_diag.count("video.zero_size_frame_rejected")
                return
            if h <= 0 or w <= 0:
                perf_diag.count("video.zero_size_frame_rejected")
                return

            if preview_vis or clean_vis:
                with perf_diag.span("video.convert"):
                    perf_diag.count("video.convert.calls")
                    image = rgb_frame_to_qimage(frame)
                if image is None or image.isNull() or image.width() <= 0 or image.height() <= 0:
                    perf_diag.count("video.null_image_rejected")
                    return
                # Real frames clear the intentional loading chrome.
                if preview_vis:
                    self.video_preview.set_qimage(image)
                if clean_vis:
                    self.clean_output_window.set_qimage(image)
            if ndi_on:
                self._ndi_output.send_frame(frame)
            if remote_prev and remote is not None:
                remote.push_preview_frame(frame)
            if zoom_busy:
                delay_ms = (time.monotonic() - present_t0) * 1000.0
                perf_diag.record_ms("video.present_delayed_by_timeline_ms", delay_ms)

    def _on_video_activation_loading(self, text: str) -> None:
        """Show Loading only while a valid Video target is pending; clear otherwise."""
        preview = getattr(self, "video_preview", None)
        if preview is None or not hasattr(preview, "set_loading"):
            return
        if text:
            preview.set_loading(True, text)
        else:
            preview.set_loading(False)

    def _sync_video_output_active(self) -> None:
        """Skip video decode when no Preview / Clean / NDI / Web Remote sink needs frames."""
        if not hasattr(self, "video_preview_panel"):
            return
        remote = getattr(self, "_web_remote", None)
        remote_prev = bool(remote is not None and remote.remote_preview_wanted)
        active = (
            self._video_preview_visible()
            or self._clean_output_visible()
            or bool(self.project.clean_video_output.ndi_enabled)
            or remote_prev
        )
        self.video_sync.set_video_output_active(active)

    def _ensure_video_preview_frame(self) -> None:
        """Land a Preview/Clean frame after song swap or project open.

        ``video_sync.set_song`` clears the picture; if output was already
        active, ``set_video_output_active(True)`` is a no-op and Preview
        stayed black until Clean Output forced a re-decode. Defer one tick
        so splitter sizes (Preview visibility) settle after restore.
        """
        self._sync_video_output_active()
        if not self.video_sync.video_output_active():
            return
        pos = float(getattr(self.engine, "position", 0.0) or 0.0)
        # Defer: opening long video can contend with waveform workers on
        # av_path_lock; same pattern as set_video_output_active.
        QTimer.singleShot(0, lambda p=pos: self.video_sync.land_frame_at(p))

    def _build_file_menu(self) -> None:
        menu = self.menuBar().addMenu("&File")
        act_new = QAction("&New Project", self)
        act_new.setShortcut(QKeySequence.StandardKey.New)
        act_new.triggered.connect(self._file_new)
        act_open = QAction("&Open Project…", self)
        act_open.setShortcut(QKeySequence.StandardKey.Open)
        act_open.triggered.connect(self._file_open)
        act_save = QAction("&Save", self)
        act_save.setShortcut(QKeySequence.StandardKey.Save)
        act_save.triggered.connect(self._file_save)
        act_save_as = QAction("Save &As…", self)
        act_save_as.setShortcut(QKeySequence.StandardKey.SaveAs)
        act_save_as.triggered.connect(self._file_save_as)
        menu.addAction(act_new)
        menu.addAction(act_open)
        menu.addSeparator()
        menu.addAction(act_save)
        menu.addAction(act_save_as)
        menu.addSeparator()
        self._build_autosave_menu(menu)
        act_restore = QAction("&Restore from Backup…", self)
        act_restore.setToolTip(
            "Open a timestamped copy from .cueplayer_backups next to this project"
        )
        act_restore.triggered.connect(self._file_restore_backup)
        menu.addAction(act_restore)
        act_relink = QAction("Relink &Missing Media…", self)
        act_relink.setToolTip(
            "Find audio/video files that moved — relink one file or a whole folder by name"
        )
        act_relink.triggered.connect(self._open_missing_media_relink)
        menu.addAction(act_relink)
        act_bundle = QAction("Collect Project &Bundle / Save As…", self)
        act_bundle.setToolTip(
            "Save into a Bundle folder (name the project file). "
            "Re-run on the same folder to add new media without re-copying existing files."
        )
        act_bundle.triggered.connect(self._collect_project_bundle)
        menu.addAction(act_bundle)
        menu.addSeparator()
        act_export = QAction("&Export…", self)
        act_export.setShortcut(QKeySequence("Ctrl+E"))
        act_export.triggered.connect(self._open_ma_patch_page)
        menu.addAction(act_export)
        act_setlist_sheet = QAction("Set List &Sheet…", self)
        act_setlist_sheet.setShortcut(QKeySequence("Ctrl+Shift+S"))
        act_setlist_sheet.setToolTip(
            "Spreadsheet of song order, names, Timecode Generator starts, and notes"
        )
        act_setlist_sheet.triggered.connect(self._open_setlist_sheet_page)
        menu.addAction(act_setlist_sheet)

        tools_menu = self.menuBar().addMenu("&Tools")
        act_manager = QAction("Mark &Manager", self)
        act_manager.triggered.connect(self._open_mark_manager)
        act_display = QAction("&Display Settings…", self)
        act_display.triggered.connect(self._open_display_settings)
        act_audio = QAction("&Audio / Midi / Timecode…", self)
        act_audio.triggered.connect(self._open_audio_timecode)
        act_web_remote = QAction("&Web Remote…", self)
        act_web_remote.setToolTip(
            "Control CuePlayer from Safari on iPad / phone (same LAN). "
            "Playback and marks on this PC; LTC stays here."
        )
        act_web_remote.triggered.connect(self._open_web_remote)
        act_align_anchors = QAction("Align &Anchors…", self)
        act_align_anchors.setToolTip(
            "Align a song variant mix to the cue timeline (shell — Apply not wired yet)."
        )
        act_align_anchors.triggered.connect(self._open_align_anchors)
        act_ma_preflight = QAction("MA &Preflight…", self)
        act_ma_preflight.setToolTip(
            "Validate MA export labels, sequences, and executors (read-only; no auto-fix)."
        )
        act_ma_preflight.triggered.connect(self._open_ma_preflight)
        tools_menu.addAction(act_manager)
        tools_menu.addAction(act_display)
        tools_menu.addSeparator()
        tools_menu.addAction(act_audio)
        tools_menu.addAction(act_web_remote)
        # Sprint 8: experimental Tools entries hidden unless flag is True.
        if ENABLE_EXPERIMENTAL_FEATURES:
            tools_menu.addAction(act_align_anchors)
            tools_menu.addAction(act_ma_preflight)
        # Developer-only when CUEPLAYER_PERF=1 (no playback behavior change).
        if perf_diag.is_enabled():
            act_perf = QAction("Write &Performance Report…", self)
            act_perf.setToolTip(
                f"Append current CUEPLAYER_PERF spans to:\n{perf_diag.log_path()}"
            )
            act_perf.triggered.connect(self._write_performance_report)
            tools_menu.addAction(act_perf)
            act_profile = QAction("Profile &UI 5s (cProfile)…", self)
            act_profile.setToolTip(
                "Run stdlib cProfile for 5 seconds while you play/scrub. "
                "Use when Dense Mark spans are empty or to compare sparse vs dense."
            )
            act_profile.triggered.connect(self._profile_ui_5s)
            tools_menu.addAction(act_profile)
        tools_menu.addSeparator()

        bpm_menu = tools_menu.addMenu("&BPM")
        act_bpm_missing = QAction("Detect BPM (songs without BPM)", self)
        act_bpm_missing.setToolTip(
            "Run auto BPM only for songs with audio and an empty BPM cell."
        )
        act_bpm_missing.triggered.connect(
            lambda: self._schedule_bpm_detect_for_missing_songs(quiet=False)
        )
        bpm_menu.addAction(act_bpm_missing)
        act_bpm_all = QAction("Re-detect BPM (auto / empty only)", self)
        act_bpm_all.setToolTip(
            "Re-detect songs with auto BPM (<n>) or no BPM (one at a time). "
            "Manual typed BPM is never overwritten — clear the cell first to re-detect."
        )
        act_bpm_all.triggered.connect(self._redetect_bpm_all_songs)
        bpm_menu.addAction(act_bpm_all)

        tools_menu.addSeparator()
        video_menu = tools_menu.addMenu("Vide&o")
        act_add_video = QAction("Add &Video Clip…", self)
        act_add_video.triggered.connect(lambda: self._add_video_clip_at(self.playback.position))
        video_menu.addAction(act_add_video)
        self._ndi_output_action = QAction("&NDI Video Output", self)
        self._ndi_output_action.setCheckable(True)
        self._ndi_output_action.setChecked(
            bool(self.project.clean_video_output.ndi_enabled)
        )
        self._ndi_output_action.setToolTip(
            "Send the same Clean Output frames over NDI (Depence / other receivers). "
            "Requires cyndilib + NDI Runtime. Right-click Clean Output to rename."
        )
        self._ndi_output_action.triggered.connect(self._toggle_ndi_output)
        video_menu.addAction(self._ndi_output_action)
        act_ndi_name = QAction("NDI Source &Name…", self)
        act_ndi_name.setToolTip("Custom NDI name so Depence does not pick the wrong feed")
        act_ndi_name.triggered.connect(self._prompt_ndi_name)
        video_menu.addAction(act_ndi_name)
        self._build_video_decode_quality_menu(video_menu)

        view_menu = self.menuBar().addMenu("&View")
        act_setlist = QAction("Show &Set List", self)
        act_setlist.setCheckable(True)
        act_setlist.setChecked(True)
        act_setlist.setToolTip(
            "Show or hide the left Set List panel (song order / folders)"
        )
        act_setlist.triggered.connect(self._toggle_setlist_panel)
        view_menu.addAction(act_setlist)
        self._act_setlist = act_setlist
        self._show_video_track_action = QAction("Show &Video / LTC Tracks", self)
        self._show_video_track_action.setCheckable(True)
        self._show_video_track_action.setChecked(True)
        self._show_video_track_action.setToolTip(
            "Hide Video + LTC lanes after alignment to free timeline space. "
            "Applies to the whole show (all songs). "
            "Preview / Clean Output keep playing either way. "
            "LTC appears under Video when a file stripe is known."
        )
        self._show_video_track_action.toggled.connect(self._on_show_video_track_toggled)
        view_menu.addAction(self._show_video_track_action)
        act_video_preview = QAction("Video &Preview Panel", self)
        act_video_preview.setCheckable(True)
        act_video_preview.setChecked(True)
        act_video_preview.triggered.connect(self._toggle_video_preview_panel)
        view_menu.addAction(act_video_preview)
        self._act_video_preview = act_video_preview
        self._clean_output_action = QAction("&Clean Video Output", self)
        self._clean_output_action.setCheckable(True)
        self._clean_output_action.triggered.connect(self._toggle_clean_output)
        view_menu.addAction(self._clean_output_action)

    def _autosave_enabled(self) -> bool:
        return self._project_service.autosave_enabled()

    def _autosave_interval_seconds(self) -> int:
        return self._project_service.autosave_interval_seconds()

    def _autosave_interval_minutes(self) -> int:
        return self._project_service.autosave_interval_minutes()

    def _backup_keep_count(self) -> int:
        return self._project_service.backup_keep_count()

    def _build_autosave_menu(self, file_menu: QMenu) -> None:
        """File → Auto-Save submenu: Off, or every N minutes."""
        submenu = file_menu.addMenu("Auto-&Save")
        submenu.setToolTip(
            "Automatically overwrite the project file while dirty. "
            "Requires Save / Save As first. Each save also writes a backup."
        )
        group = QActionGroup(self)
        group.setExclusive(True)
        self._autosave_off_action = QAction("Off", self)
        self._autosave_off_action.setCheckable(True)
        self._autosave_off_action.triggered.connect(lambda: self._set_autosave_choice(None))
        group.addAction(self._autosave_off_action)
        submenu.addAction(self._autosave_off_action)

        self._autosave_interval_actions: dict[int, QAction] = {}
        for minutes in _AUTOSAVE_INTERVAL_MINUTES:
            label = f"Every {minutes} minutes"
            action = QAction(label, self)
            action.setCheckable(True)
            action.triggered.connect(
                lambda _checked=False, m=minutes: self._set_autosave_choice(m)
            )
            group.addAction(action)
            submenu.addAction(action)
            self._autosave_interval_actions[minutes] = action
        self._sync_autosave_menu_ui()

    def _set_autosave_choice(self, minutes: int | None) -> None:
        """``None`` = Off; otherwise enable Auto-Save every ``minutes``."""
        self._project_service.set_autosave_choice(minutes)
        self._setup_autosave()
        self._sync_autosave_menu_ui()
        if minutes is None:
            self.status.showMessage("Auto-Save off", 2500)
        else:
            self.status.showMessage(f"Auto-Save every {minutes} minutes", 2500)

    def _sync_autosave_menu_ui(self) -> None:
        off = getattr(self, "_autosave_off_action", None)
        actions = getattr(self, "_autosave_interval_actions", None)
        if off is None or not actions:
            return
        if not self._autosave_enabled():
            off.setChecked(True)
            return
        minutes = self._autosave_interval_minutes()
        action = actions.get(minutes)
        if action is not None:
            action.setChecked(True)
        else:
            off.setChecked(True)

    def _set_autosave_enabled(self, enabled: bool) -> None:
        # Kept for tests / callers that toggle on/off without picking minutes.
        self._project_service.set_autosave_enabled(bool(enabled))
        self._setup_autosave()
        self._sync_autosave_menu_ui()

    def _setup_autosave(self) -> None:
        timer = getattr(self, "_autosave_timer", None)
        if timer is None:
            self._autosave_timer = QTimer(self)
            self._autosave_timer.timeout.connect(self._autosave_tick)
        interval_ms = self._autosave_interval_seconds() * 1000
        self._autosave_timer.setInterval(interval_ms)
        if self._autosave_enabled():
            if not self._autosave_timer.isActive():
                self._autosave_timer.start()
            else:
                # Restart so a shorter interval takes effect immediately.
                self._autosave_timer.start()
        else:
            self._autosave_timer.stop()

    def _autosave_tick(self) -> None:
        if not self._project_service.should_autosave():
            return
        self._file_save(quiet=True)

    def _backup_before_overwrite(self, path: Path) -> None:
        try:
            self._project_service.backup_before_overwrite(path)
        except OSError as exc:
            # Backup failure must not block Save; surface a soft warning.
            self.status.showMessage(f"Backup failed: {exc}", 5000)

    def _build_video_decode_quality_menu(self, tools_menu: QMenu) -> None:
        """Preview / Clean Output decode resolution cap (perf knob).

        Both windows paint the same decoded frame (one decode path — see
        AGENTS.md), so this affects both at once; lowering it trades
        resolution for smoother scrubbing/dragging on heavy footage.
        """
        quality_menu = tools_menu.addMenu("Video Decode &Quality")
        group = QActionGroup(self)
        group.setExclusive(True)
        self._video_decode_quality_actions: dict[str, QAction] = {}
        for quality, label in (
            ("full", "Full (source resolution)"),
            ("1080p", "1080p"),
            ("720p", "720p"),
            ("540p", "540p"),
        ):
            action = quality_menu.addAction(label)
            action.setCheckable(True)
            action.triggered.connect(
                lambda _checked=False, q=quality: self._set_video_decode_quality(q)
            )
            group.addAction(action)
            self._video_decode_quality_actions[quality] = action
        self._sync_video_decode_quality_ui()

    def _clamp_video_preview_splitter(self) -> None:
        """Keep Preview tall enough after restore / drag (cannot collapse to 0)."""
        split = getattr(self, "_timeline_preview_split", None)
        panel = getattr(self, "video_preview_panel", None)
        if split is None or panel is None or not panel.isVisible():
            return
        sizes = split.sizes()
        if len(sizes) < 2:
            return
        floor = _VIDEO_PREVIEW_SPLIT_MIN_HEIGHT
        if sizes[1] >= floor:
            return
        total = max(sum(sizes), split.height(), floor + 80)
        preview = floor
        timeline = max(80, total - preview)
        split.setSizes([timeline, preview])

    def _toggle_video_preview_panel(self, visible: bool) -> None:
        split = getattr(self, "_timeline_preview_split", None)
        self.video_preview_panel.setVisible(visible)
        if split is None:
            self._sync_video_output_active()
            return
        if visible:
            total = max(1, split.height())
            split.setSizes(
                [
                    max(100, total * 3 // 5),
                    max(_VIDEO_PREVIEW_SPLIT_MIN_HEIGHT, total * 2 // 5),
                ]
            )
            self._clamp_video_preview_splitter()
        self._sync_video_output_active()

    def _set_video_decode_quality(self, quality: str) -> None:
        self.video_sync.set_decode_quality(quality)  # type: ignore[arg-type]
        self.project.video_decode_quality = self.video_sync.decode_quality()
        self._sync_video_decode_quality_ui()
        self._mark_dirty()

    def _sync_video_decode_quality_ui(self) -> None:
        actions = getattr(self, "_video_decode_quality_actions", None)
        if not actions:
            return
        current = self.video_sync.decode_quality()
        action = actions.get(current)
        if action is not None:
            action.setChecked(True)
        if hasattr(self, "clean_output_window"):
            self.clean_output_window.set_decode_quality(current)
        if hasattr(self, "video_preview"):
            self.video_preview.set_decode_quality(current)

    def _project_filter(self) -> str:
        return "CuePlayer Project (*.cueplayer.json);;JSON (*.json);;All Files (*.*)"

    def _refresh_window_title(self) -> None:
        name = self.project.name
        if self._project_path is not None:
            name = self._project_path.stem.replace(".cueplayer", "") or self.project.name
        dirty = " *" if self._dirty else ""
        self.setWindowTitle(f"{MAIN_WINDOW_TITLE_PREFIX} — {name}{dirty}")

    def _sync_undo_context(self) -> None:
        self._undo_ctx.project = self.project
        self._undo_ctx.current_song_id = self.current_song.id

    def _push_song_undo(self, command: object) -> None:
        self._undo.push(command, song_id=self.current_song.id)

    def _focus_song_for_undo(self, song_id: str | None) -> None:
        if not song_id or song_id == self.current_song.id:
            return
        for index, song in enumerate(self.project.songs):
            if song.id == song_id:
                self._activate_song(index, stop_playback=False)
                return

    def _mark_dirty(self) -> None:
        if not self._project_service.mark_dirty():
            return
        self._refresh_window_title()

    @contextmanager
    def _setlist_edit(self, label: str):
        """Capture setlist state before/after a mutation for Ctrl+Z."""
        before = SetlistStateSnapshot.capture(self.project)
        song_id = self.current_song.id
        selected_ids = tuple(
            self.project.songs[i].id for i in self._selected_song_indexes()
        )
        yield
        after = SetlistStateSnapshot.capture(self.project)
        if before != after:
            self._undo.push(
                SetlistEditCommand(
                    before=before,
                    after=after,
                    label=label,
                    current_song_id=song_id,
                    selected_song_ids=selected_ids,
                )
            )

    def _sync_after_setlist_undo_redo(self, cmd: SetlistEditCommand) -> None:
        if not self.project.songs:
            self._apply_empty_project_workspace()
            self._refresh_window_title()
            self._refresh_status()
            return
        try:
            idx = next(
                i for i, s in enumerate(self.project.songs) if s.id == cmd.current_song_id
            )
        except StopIteration:
            idx = 0
        self._undo_ctx.current_song_id = self.project.songs[idx].id
        select_indexes = [
            i for i, s in enumerate(self.project.songs) if s.id in cmd.selected_song_ids
        ]
        if not select_indexes:
            select_indexes = [idx]
        self._rebuild_song_list(select_indexes=select_indexes)
        self._activate_song(idx, stop_playback=False)
        patch = getattr(self, "show_patch_page", None)
        if patch is not None:
            patch.sync_songs()
        self._refresh_window_title()
        self._refresh_status()

    def _sync_media_layout_for_save(
        self,
        project_file: Path,
        *,
        rearrange_disk: bool = True,
    ) -> int:
        """
        Move Media/ files to match Setlist folders, then persist paths.

        Disk moves happen only here (Save / Save As / Auto-save) so an unsaved
        session never leaves the on-disk project JSON pointing at stale paths.

        When ``rearrange_disk`` is False (Save As beside the original file in the
        same folder), leave the shared Media tree untouched so the old project
        file can still open.
        """
        if not rearrange_disk:
            return 0
        return sync_all_songs_media_to_setlist_folders(
            self.project,
            project_file=project_file,
        )

    def _maybe_bundle_external_media_on_save(
        self,
        project_file: Path,
        *,
        quiet: bool = False,
    ) -> int:
        """
        If the user dropped media from outside the project folder, ask whether
        to copy those files into ``Media/<Setlist>/<Song>/`` before saving.

        Skipped during auto-save (``quiet``) so timers never block on a dialog.
        Returns how many files were copied in.
        """
        if quiet:
            return 0
        external = scan_external_media(self.project, project_file=project_file)
        if not external:
            return 0
        # Deduped display names (same file may be referenced twice).
        names: list[str] = []
        seen: set[str] = set()
        for ref in external:
            key = str(ref.path)
            if key in seen:
                continue
            seen.add(key)
            names.append(ref.basename)
        preview = "\n".join(f"  · {n}" for n in names[:8])
        more = "" if len(names) <= 8 else f"\n  · …and {len(names) - 8} more"
        answer = QMessageBox.question(
            self,
            "Bundle New Media?",
            f"{len(names)} media file(s) were added from outside this project "
            f"folder.\n\nCopy them into {DEFAULT_MEDIA_SUBDIR}/<Setlist>/<Song>/ "
            "so the show stays portable?\n\n"
            f"{preview}{more}\n\n"
            "Yes = copy into Media/ then Save\n"
            "No = Save with absolute paths (original files stay where they are)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return 0
        try:
            result = ingest_external_media_into_project(
                self.project,
                project_file=project_file,
                only=external,
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Bundle Media Failed", str(exc))
            return 0
        if result.failed:
            QMessageBox.warning(
                self,
                "Bundle Media",
                f"Could not copy {len(result.failed)} file(s). "
                "Other files were bundled; continuing Save.",
            )
        return len(result.copied)

    def _set_clean(self) -> None:
        self._project_service.mark_clean()
        self._refresh_window_title()

    def _confirm_discard_if_dirty(self) -> bool:
        if not self._dirty:
            return True
        answer = QMessageBox.question(
            self,
            "Unsaved Changes",
            "This project has unsaved changes. Save first?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            return self._file_save()
        return True

    def _project_is_pristine(self) -> bool:
        """Blank Untitled session with no media/marks — New can be silent."""
        if self._dirty or self._project_path is not None:
            return False
        if (self.project.name or "").strip() not in ("Untitled Project", "Untitled", ""):
            return False
        if self.project.setlist_categories:
            return False
        # Empty Setlist is the new blank project.
        if not self.project.songs:
            return True
        if len(self.project.songs) != 1:
            return False
        song = self.project.songs[0]
        if (song.name or "").strip() not in ("Untitled Song", ""):
            return False
        if song.audio_tracks or song.video_clips or song.marks:
            return False
        if any(song.category_id for song in self.project.songs):
            return False
        return True

    def _confirm_new_project(self) -> bool:
        """
        New Project gate:

        - Dirty → Save / Discard / Cancel
        - Loaded from disk and no edits → allow without ask
        - Untitled but already has songs/media/marks → Yes/No confirm
        - Pristine blank → silent
        """
        if self._dirty:
            return self._confirm_discard_if_dirty()
        if self._project_path is not None:
            # Just opened a file and made no changes.
            return True
        if self._project_is_pristine():
            return True
        answer = QMessageBox.question(
            self,
            "New Project",
            "Create a new project?\n\n"
            "The current setlist and media in this window will be closed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _file_new(self) -> None:
        if not self._confirm_new_project():
            return
        self.playback.stop()
        self.project = self._project_service.new_project(with_song=False)
        self._apply_project()
        self._set_clean()
        self.status.showMessage("New project created", 2500)

    def _file_open(self) -> None:
        if not self._confirm_discard_if_dirty():
            return
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Open Project",
            str(self._project_path.parent) if self._project_path else "",
            self._project_filter(),
        )
        if not path_str:
            return
        path = Path(path_str)
        if self._open_project_path(path):
            self.status.showMessage(f"Opened: {path.name}", 3500)

    def _file_save(self, *, quiet: bool = False) -> bool:
        if self._project_path is None:
            return self._file_save_as()
        self.project.clean_video_output = self.clean_output_window.current_settings()
        self.project.video_decode_quality = self.video_sync.decode_quality()
        n_bundled = self._maybe_bundle_external_media_on_save(
            self._project_path, quiet=quiet
        )
        n_media = self._sync_media_layout_for_save(self._project_path)
        self._backup_before_overwrite(self._project_path)
        try:
            self._project_service.save_project(self.project, self._project_path)
        except Exception as exc:  # noqa: BLE001
            if not quiet:
                QMessageBox.warning(self, "Unable to Save Project", str(exc))
            else:
                self.status.showMessage(f"Auto-save failed: {exc}", 5000)
            return False
        self._set_clean()
        label = "Auto-saved" if quiet else "Saved"
        bits: list[str] = []
        if n_bundled:
            bits.append(f"{n_bundled} bundled into Media/")
        if n_media:
            bits.append(f"{n_media} media file(s) arranged")
        extra = f" · {'; '.join(bits)}" if bits else ""
        self.status.showMessage(f"{label}: {self._project_path.name}{extra}", 2500)
        return True

    def _file_save_as(self) -> bool:
        suggested = (
            str(self._project_path)
            if self._project_path is not None
            else f"{self.project.name}.cueplayer.json"
        )
        path_str, _ = QFileDialog.getSaveFileName(
            self,
            "Save Project As",
            suggested,
            self._project_filter(),
        )
        if not path_str:
            return False
        path = self._project_service.normalize_save_as_path(Path(path_str))
        self.project.clean_video_output = self.clean_output_window.current_settings()
        self.project.video_decode_quality = self.video_sync.decode_quality()
        # Arrange Media/ under the *new* project folder only when files already
        # live there. Save As into another directory leaves the original Media
        # tree alone (paths become absolute). Save As beside the original file
        # shares that Media tree — skip rearrange so the old JSON still opens.
        shared_beside_original = self._project_service.is_save_as_beside_original(path)
        n_bundled = 0
        if not shared_beside_original:
            n_bundled = self._maybe_bundle_external_media_on_save(path, quiet=False)
        n_media = self._sync_media_layout_for_save(
            path,
            rearrange_disk=not shared_beside_original,
        )
        # Overwriting an existing path (or re-Save-As to the same file) still
        # gets a backup of whatever was previously on disk.
        self._backup_before_overwrite(path)
        try:
            self._project_service.save_project(self.project, path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Unable to Save Project", str(exc))
            return False
        self._project_service.apply_name_from_path(self.project, path)
        self._set_clean()
        self._refresh_status()
        if shared_beside_original:
            self.status.showMessage(
                f"Saved: {path.name} · shared Media with original "
                "(layout unchanged; use Bundle for an independent copy)",
                4500,
            )
        else:
            bits: list[str] = []
            if n_bundled:
                bits.append(f"{n_bundled} bundled into Media/")
            if n_media:
                bits.append(f"{n_media} media file(s) arranged")
            extra = f" · {'; '.join(bits)}" if bits else ""
            self.status.showMessage(f"Saved: {path.name}{extra}", 2500)
        return True

    def _file_restore_backup(self) -> None:
        if self._project_path is None:
            QMessageBox.information(
                self,
                "Restore from Backup",
                "Save the project once before restoring a backup.\n"
                "Backups live in a .cueplayer_backups folder next to the project file.",
            )
            return
        backups = list_backups(self._project_path)
        if not backups:
            QMessageBox.information(
                self,
                "Restore from Backup",
                f"No backups found for:\n{self._project_path.name}\n\n"
                "A backup is created automatically each time you Save.",
            )
            return
        if not self._confirm_discard_if_dirty():
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Restore from Backup")
        dialog.resize(480, 360)
        layout = QVBoxLayout(dialog)
        layout.addWidget(
            QLabel(
                "Pick a timestamped backup to open. "
                "The current project file is left untouched until you Save."
            )
        )
        listing = QListWidget()
        for path in backups:
            item = QListWidgetItem(path.name)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            listing.addItem(item)
        listing.setCurrentRow(0)
        layout.addWidget(listing, stretch=1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        listing.itemDoubleClicked.connect(lambda _item: dialog.accept())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        current = listing.currentItem()
        if current is None:
            return
        path = Path(str(current.data(Qt.ItemDataRole.UserRole)))
        try:
            project = load_project(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Unable to Open Backup", str(exc))
            return
        self.playback.stop()
        self.project = project
        # Keep pointing at the live project path so the next Save writes there
        # (and takes a fresh backup of whatever is currently on disk).
        self._apply_project()
        self._mark_dirty()
        self.status.showMessage(f"Restored backup into editor: {path.name}", 4500)

    def _apply_project(self, *, preferred_song_id: str | None = None) -> None:
        self._undo.clear()
        # Do not invent an Untitled Song — New Project / empty files stay empty.
        self.show_patch_page.set_project(self.project)
        self.setlist_sheet_page.set_project(self.project)
        self._sync_setlist_name_mode_ui()
        # Audio / MIDI / Timecode follow the machine, not the project file.
        self.settings.apply_audio_to_project(self.project)
        self.engine.apply_audio_settings(self.project.audio_output)
        self.clean_output_window.apply_settings(self.project.clean_video_output)
        self._apply_ndi_from_project(show_errors=False)
        if hasattr(self, "_ndi_output_action"):
            self._ndi_output_action.setChecked(
                bool(self.project.clean_video_output.ndi_enabled)
            )
        self.video_sync.set_decode_quality(self.project.video_decode_quality)
        self._sync_video_decode_quality_ui()
        self._restore_clean_output_visibility()
        self._sync_video_output_active()
        self._refresh_timecode_status()
        self._sync_output_timecode_clock_ui()
        self._refresh_output_timecode_clock()
        self.timeline.set_show_video_track(self.project.show_video_track, emit=False)
        if not self.project.songs:
            self._apply_empty_project_workspace()
            return
        song_index = 0
        if preferred_song_id:
            for i, song in enumerate(self.project.songs):
                if song.id == preferred_song_id:
                    song_index = i
                    break
        self._rebuild_song_list(select_indexes=[song_index])
        self._activate_song(song_index, stop_playback=True)

    def _apply_empty_project_workspace(self) -> None:
        """Clear timeline / monitor when the Setlist has no songs."""
        self._blank_song = Song.create("Untitled Song")
        self.current_song = self._blank_song
        self._undo_ctx = UndoContext(self.project, self.current_song.id)
        self._rebuild_song_list(select_indexes=[])
        self.show_session.apply_empty_workspace()

    def _sync_setlist_name_mode_ui(self) -> None:
        mode = self.project.setlist_name_mode
        if mode not in ("zh", "both", "en"):
            mode = "zh"
        # Top ZH/Both/EN combo removed — columns toggle via right-click only.
        # "en" (English-only) collapses to "both" so Song English stays a column toggle.
        if mode == "en":
            mode = "both"
            self.project.setlist_name_mode = "both"  # type: ignore[assignment]
        self.song_list.set_name_mode(mode)
        self._sync_setlist_column_prefs()

    def _sync_setlist_column_prefs(self) -> None:
        self.song_list.set_show_bpm(self.project.setlist_show_bpm)
        self.song_list.set_show_media_badges(
            show_ltc=bool(self.project.setlist_show_ltc_badge),
            show_video=bool(self.project.setlist_show_video_badge),
        )

    def _setlist_display_rows(self) -> list[_SetlistDisplayRow]:
        rows: list[_SetlistDisplayRow] = []
        for i, song in enumerate(self.project.songs):
            if not song.category_id:
                rows.append(_SetlistDisplayRow(kind="song", song_index=i))
        for category in self.project.setlist_categories:
            rows.append(_SetlistDisplayRow(kind="category", category_id=category.id))
            if not category.collapsed:
                for i, song in enumerate(self.project.songs):
                    if song.category_id == category.id:
                        rows.append(_SetlistDisplayRow(kind="song", song_index=i))
        return rows

    def _category_id_before_display_index(
        self, rows: list[_SetlistDisplayRow], index: int
    ) -> str | None:
        for i in range(index - 1, -1, -1):
            row = rows[i]
            if row.kind == "category":
                return row.category_id
            if row.kind == "song" and row.song_index is not None:
                return self.project.songs[row.song_index].category_id
        return None

    def _rebuild_song_list(
        self,
        select_indexes: list[int] | None = None,
        *,
        select_index: int | None = None,
    ) -> None:
        if select_indexes is None:
            if select_index is not None:
                select_indexes = [select_index]
            else:
                try:
                    select_indexes = [self.project.songs.index(self.current_song)]
                except ValueError:
                    select_indexes = [0]
        select_indexes = [
            i for i in select_indexes if 0 <= i < len(self.project.songs)
        ]
        if not select_indexes and self.project.songs:
            select_indexes = [0]
        current_song_index = select_indexes[-1] if select_indexes else 0
        self._switching_song = True
        keep_hscroll = self.song_list.horizontal_scroll_value()
        self.song_list.blockSignals(True)
        self.song_list._block_number_signal = True  # noqa: SLF001
        display_rows = self._setlist_display_rows()
        self.song_list.clearSpans()
        self.song_list.setRowCount(len(display_rows))
        mode = self.project.setlist_name_mode
        if mode not in ("zh", "both", "en"):
            mode = "zh"
        self.song_list.set_name_mode(mode)
        self._sync_setlist_column_prefs()
        song_index_to_table_row: dict[int, int] = {}
        for table_row, entry in enumerate(display_rows):
            if entry.kind == "category":
                category = self.project.setlist_category_by_id(entry.category_id or "")
                if category is None:
                    continue
                arrow = "▸" if category.collapsed else "▾"
                label = f"{arrow} {category.name}"
                folder_item = QTableWidgetItem(label)
                folder_item.setData(Qt.ItemDataRole.UserRole, category.id)
                folder_item.setData(SetlistWidget.ROLE_KIND, "category")
                folder_item.setData(SetlistWidget.ROLE_ROW_COLOR, category.row_color or "")
                folder_item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsDragEnabled
                )
                folder_item.setToolTip(
                    "Click ▸/▾ to expand or collapse · drag folder title to move "
                    "this folder and its songs above/below other folders · "
                    "double-click name to rename · right-click for more · "
                    "drag songs here to file them in this folder"
                )
                if category.row_color:
                    folder_item.setForeground(QColor(contrast_text_color(category.row_color)))
                else:
                    folder_item.setForeground(QColor("#a5b4fc"))
                font = folder_item.font()
                font.setBold(True)
                folder_item.setFont(font)
                self.song_list.setItem(table_row, SetlistWidget.COL_NUM, folder_item)
                self.song_list.setSpan(table_row, SetlistWidget.COL_NUM, 1, SetlistWidget.COL_COUNT)
                continue

            song_index = entry.song_index
            if song_index is None or song_index >= len(self.project.songs):
                continue
            song = self.project.songs[song_index]
            song_index_to_table_row[song_index] = table_row

            num_text = format_setlist_number(song.setlist_number)
            num_item = QTableWidgetItem(num_text)
            num_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            num_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEditable
                | Qt.ItemFlag.ItemIsDragEnabled
            )
            num_item.setData(Qt.ItemDataRole.UserRole, song.id)
            num_item.setData(Qt.ItemDataRole.UserRole + 1, num_text)
            num_item.setData(SetlistWidget.ROLE_KIND, "song")
            num_item.setData(SetlistWidget.ROLE_SONG_INDEX, song_index)
            num_item.setToolTip("Double-click to edit the number (0.5 supported)")
            self.song_list.setItem(table_row, SetlistWidget.COL_NUM, num_item)

            zh_name = song.name
            en_name = (song.ma_export_name or "").strip()
            if not en_name:
                from cueplayer.exporters.common import ma_export_name_from_display

                en_name = ma_export_name_from_display(zh_name)
                song.ma_export_name = en_name
            if mode == "en":
                primary = en_name or zh_name
            else:
                primary = zh_name
            name_item = QTableWidgetItem(primary)
            name_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEditable
                | Qt.ItemFlag.ItemIsDragEnabled
            )
            tip_parts = [f"#{format_setlist_number(song.setlist_number)}"]
            if zh_name:
                tip_parts.append(zh_name)
            if en_name:
                tip_parts.append(f"MA: {en_name}")
            if song.bpm:
                tip_parts.append(f"{song.bpm:g} BPM")
            tip_parts.append(f"LTC {song.start_timecode} @ {song.fps:g}fps")
            tip_parts.append("Double-click to rename")
            name_item.setToolTip(" · ".join(tip_parts))
            if mode == "en" and not en_name:
                name_item.setForeground(QColor("#8b949e"))
                name_item.setToolTip(
                    name_item.toolTip() + "\n(No English/MA name set yet, showing Chinese)"
                )
            self.song_list.setItem(table_row, SetlistWidget.COL_TITLE, name_item)

            ma_item = QTableWidgetItem(en_name)
            ma_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEditable
                | Qt.ItemFlag.ItemIsDragEnabled
            )
            ma_item.setToolTip((en_name + "\n" if en_name else "") + "Double-click to edit the English/MA name")
            self.song_list.setItem(table_row, SetlistWidget.COL_EN, ma_item)

            bpm_text = ""
            progress = self._bpm_ui_progress.get(song.id)
            if progress is not None:
                if progress < 0:
                    bpm_text = "…"
                else:
                    bpm_text = f"{min(100, int(progress))}%"
            elif song.bpm is not None and float(song.bpm) > 0:
                from cueplayer.media.bpm_analyzer import format_bpm_cell

                bpm_text = format_bpm_cell(float(song.bpm), auto=bool(song.bpm_auto))
            bpm_item = QTableWidgetItem(bpm_text)
            bpm_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            bpm_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEditable
                | Qt.ItemFlag.ItemIsDragEnabled
            )
            if progress is not None:
                from cueplayer.ui.theme import ACCENT

                bpm_item.setForeground(QColor(ACCENT))
                if progress < 0:
                    bpm_item.setToolTip("排隊偵測 BPM 中…")
                else:
                    bpm_item.setToolTip(f"正在偵測 BPM… {min(100, int(progress))}%")
            elif song.bpm is not None and song.bpm_auto:
                from cueplayer.ui.theme import secondary_text_on_background

                row_color = (song.row_color or "").strip() or None
                bpm_item.setForeground(QColor(secondary_text_on_background(row_color)))
                bpm_item.setToolTip(
                    "Auto-detected BPM (gray <n>).\n"
                    "Double-click to type the correct value if needed."
                )
            else:
                bpm_item.setToolTip(
                    "Double-click to enter BPM (blank = not set)."
                )
            self.song_list.setItem(table_row, SetlistWidget.COL_BPM, bpm_item)

            ltc_channel = self._ltc_channel_for_song(song)
            has_video = bool(song.video_clips)
            ltc_item = QTableWidgetItem("")
            ltc_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsDragEnabled
            )
            ltc_item.setData(SetlistWidget.ROLE_LTC_CHANNEL, ltc_channel)
            ltc_item.setData(SetlistWidget.ROLE_HAS_VIDEO, has_video)
            tip_parts_media: list[str] = []
            if has_video:
                tip_parts_media.append("Has video clip(s) on the timeline")
            if ltc_channel == 0:
                tip_parts_media.append("Striped LTC detected on Left channel")
            elif ltc_channel == 1:
                tip_parts_media.append("Striped LTC detected on Right channel")
            if tip_parts_media:
                ltc_item.setToolTip("\n".join(tip_parts_media))
            self.song_list.setItem(table_row, SetlistWidget.COL_LTC, ltc_item)
            if song.id == self.current_song.id:
                self._ensure_ltc_detect_scheduled(song)

            for cell in (num_item, name_item, ma_item, bpm_item, ltc_item):
                cell.setData(SetlistWidget.ROLE_ROW_COLOR, song.row_color or "")

        self.song_list.clearSelection()
        for song_index in select_indexes:
            table_row = song_index_to_table_row.get(song_index)
            if table_row is not None:
                self.song_list.selectRow(table_row)
        if self.project.songs:
            current_table_row = song_index_to_table_row.get(
                current_song_index, song_index_to_table_row.get(select_indexes[0], 0)
            )
            if current_table_row is not None:
                self.song_list.setCurrentCell(current_table_row, SetlistWidget.COL_TITLE)
        # setRowCount / selectRow can reset or yank the horizontal bar; keep
        # the user's Song-column scroll position across rebuilds.
        self.song_list.set_horizontal_scroll_value(keep_hscroll)
        self.song_list._block_number_signal = False  # noqa: SLF001
        self.song_list.blockSignals(False)
        self._switching_song = False
        patch = getattr(self, "show_patch_page", None)
        if patch is not None:
            patch.sync_songs()
        sheet = getattr(self, "setlist_sheet_page", None)
        if sheet is not None:
            sheet.sync_songs()

    def _selected_song_indexes(self) -> list[int]:
        indexes: list[int] = []
        for row in sorted({idx.row() for idx in self.song_list.selectedIndexes()}):
            song_index = self.song_list.row_song_index(row)
            if song_index is not None:
                indexes.append(song_index)
        return indexes

    def _table_rows_for_song_indexes(self, song_indexes: list[int]) -> list[int]:
        rows: list[int] = []
        display_rows = self._setlist_display_rows()
        for table_row, entry in enumerate(display_rows):
            if entry.kind == "song" and entry.song_index in song_indexes:
                rows.append(table_row)
        return rows

    def _song_to_draft(self, song: Song) -> SongDraft:
        audio_path = Path(song.audio_tracks[0].path) if song.audio_tracks else None
        video_path = Path(song.video_clips[0].path) if song.video_clips else None
        return SongDraft(
            name=song.name,
            setlist_number=float(song.setlist_number),
            ma_export_name=(song.ma_export_name or "").strip()
            or suggest_ma_export_name(song.name),
            bpm=song.bpm,
            start_timecode=song.start_timecode or "01:00:00:00",
            fps=float(song.fps or 30.0),
            audio_path=audio_path if audio_path is not None else None,
            video_path=video_path if video_path is not None else None,
            song_id=song.id,
            file_ltc_side=str(getattr(song, "file_ltc_side", "auto") or "auto"),
        )

    def _apply_draft_to_song(self, song: Song, draft: SongDraft) -> None:
        from cueplayer.exporters.common import ma_export_name_from_display

        song.name = draft.name
        song.setlist_number = float(draft.setlist_number)
        # English / MA name must never stay blank — fall back to pinyin from display name.
        song.ma_export_name = (draft.ma_export_name or "").strip() or ma_export_name_from_display(
            draft.name
        )
        old_bpm = song.bpm
        old_bpm_auto = bool(getattr(song, "bpm_auto", False))
        song.bpm = draft.bpm
        if draft.bpm is None:
            song.bpm_auto = False
        elif (
            old_bpm_auto
            and old_bpm is not None
            and abs(float(old_bpm) - float(draft.bpm)) < 1e-9
        ):
            # Edit Song OK without changing BPM should keep gray auto-detected value.
            song.bpm_auto = True
        else:
            song.bpm_auto = False
        song.start_timecode = draft.start_timecode
        song.fps = draft.fps
        from cueplayer.domain.models import coerce_file_ltc_side

        song.file_ltc_side = coerce_file_ltc_side(getattr(draft, "file_ltc_side", "off"))

        current_audio = song.active_audio_path()
        current_video = Path(song.video_clips[0].path) if song.video_clips else None
        draft_audio = Path(draft.audio_path) if draft.audio_path is not None else None
        draft_video = Path(draft.video_path) if draft.video_path is not None else None

        if bool(getattr(draft, "media_cleared", False)):
            song.clear_audio_media()
            song.video_clips = []
        else:
            if draft_audio is not None and draft_audio.is_file():
                if not self._same_media_path(current_audio, draft_audio):
                    song.replace_main_audio(draft_audio)
                    # Metadata duration now — do not wait for full waveform decode
                    # (empty project used to show 1:00 until load finished).
                    self._apply_probed_audio_duration(draft_audio, song=song)
                    if song.bpm is None:
                        self._schedule_bpm_detect_for_song(song, draft_audio)
            # Never wipe audio_tracks on rename / metadata-only Edit Song.

            if draft_video is not None and draft_video.is_file():
                if not self._same_media_path(current_video, draft_video):
                    self._attach_video_source_to_song(song, draft_video, replace_clips=True)
            # Never wipe video_clips when draft.video_path is None (rename used to
            # drop VJ clips because the file cell only showed the .wav).

        if song is self.current_song:
            self.engine.set_song_timebase(song.start_timecode, song.fps)
            self.engine.set_song(song)
            self.engine.refresh_song_ltc_routing()
            self._refresh_setlist_ltc_cells()
            self._refresh_timeline_waveform_for_ltc()
            self._refresh_timecode_status()
    @staticmethod
    def _same_media_path(a: Path | None, b: Path | None) -> bool:
        if a is None or b is None:
            return False
        try:
            return Path(a).resolve() == Path(b).resolve()
        except OSError:
            return Path(a) == Path(b)

    def _song_media_paths(self, song: Song) -> tuple[Path | None, Path | None]:
        audio = Path(song.audio_tracks[0].path) if song.audio_tracks else None
        video = Path(song.video_clips[0].path) if song.video_clips else None
        return audio, video

    def _draft_changes_media(self, song: Song, draft: SongDraft) -> bool:
        if bool(getattr(draft, "media_cleared", False)):
            return bool(song.audio_tracks or song.video_clips)
        cur_audio, cur_video = self._song_media_paths(song)
        draft_audio = Path(draft.audio_path) if draft.audio_path is not None else None
        draft_video = Path(draft.video_path) if draft.video_path is not None else None
        # Unchanged / preserved media → no activate needed.
        audio_same = (
            (cur_audio is None and draft_audio is None)
            or self._same_media_path(cur_audio, draft_audio)
            or (draft_audio is None and cur_audio is not None)
        )
        video_same = (
            (cur_video is None and draft_video is None)
            or self._same_media_path(cur_video, draft_video)
            # Draft omitted video but live song still has clips (legacy drafts).
            or (draft_video is None and cur_video is not None)
        )
        return not (audio_same and video_same)
    def _attach_video_source_to_song(
        self,
        song: Song,
        path: Path,
        *,
        replace_clips: bool = False,
    ) -> VideoClip | None:
        """Attach a video/still file as the song's primary timeline media."""
        try:
            info = probe_media(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Unable to Load Media", str(exc))
            return None
        is_still = info.media_kind == "still"
        if is_still:
            duration = DEFAULT_STILL_CLIP_DURATION_SECONDS
            source_duration = 0.0
        else:
            source_duration = info.duration_seconds
            duration = default_video_clip_duration(
                source_duration,
                max(song.duration_seconds, source_duration),
                0.0,
            )
        clip = VideoClip.create(
            name=path.stem,
            path=path,
            start_seconds=0.0,
            duration_seconds=duration,
            media_kind="still" if is_still else "video",
            source_duration_seconds=source_duration,
        )
        if replace_clips:
            song.video_clips = [clip]
        else:
            song.add_video_clip(clip)
        song.duration_seconds = max(float(song.duration_seconds), clip.end_seconds)
        if not is_still and source_needs_long_video_warning(
            duration_seconds=source_duration, path=path
        ):
            QTimer.singleShot(
                0, lambda p=path, d=source_duration: self._warn_long_rehearsal_video(p, d)
            )
        return clip

    def _next_setlist_number(self, category_id: str | None = None) -> float:
        return self.project.next_setlist_number(category_id)

    def _assign_songs_to_category(self, songs: list[Song], category_id: str | None) -> None:
        """Move songs into a folder (or back to the main list) with fresh local #s."""
        next_num = self.project.next_setlist_number(category_id)
        for song in songs:
            song.category_id = category_id
            song.setlist_number = next_num
            next_num += 1.0

    def _on_song_cell_changed(
        self, row: int, _column: int, _prev_row: int, _prev_column: int
    ) -> None:
        song_index = self.song_list.row_song_index(row)
        if song_index is None:
            return
        if self._switching_song or song_index < 0 or song_index >= len(self.project.songs):
            return
        if self.project.songs[song_index] is self.current_song:
            return
        self._activate_song(song_index, stop_playback=True)

    def _on_song_title_edited(self, row: int, text: str) -> None:
        song_index = self.song_list.row_song_index(row)
        if song_index is None or song_index < 0 or song_index >= len(self.project.songs):
            return
        song = self.project.songs[song_index]
        mode = self.project.setlist_name_mode
        if mode == "en":
            # Primary column shows English in EN mode.
            self._apply_inline_ma_name(song, text, row=row)
            return
        name = text.strip() or "Untitled Song"
        if song.name == name:
            return
        with self._setlist_edit("Rename Song"):
            song.name = name
            self._mark_dirty()
            self._refresh_status()
            patch = getattr(self, "show_patch_page", None)
            if patch is not None:
                patch.sync_songs()
            self.timeline.update()
        self.status.showMessage(
            f'Song name changed to "{name}" (Media folder updates on Save)',
            2000,
        )

    def _on_song_ma_name_edited(self, row: int, text: str) -> None:
        song_index = self.song_list.row_song_index(row)
        if song_index is None or song_index < 0 or song_index >= len(self.project.songs):
            return
        self._apply_inline_ma_name(self.project.songs[song_index], text, row=song_index)

    def _apply_inline_ma_name(self, song: Song, text: str, *, row: int) -> None:
        from cueplayer.exporters.common import ma_export_name_from_display, sanitize_ma_name

        raw = text.strip()
        if raw:
            ma = sanitize_ma_name(raw, fallback="")
            if not ma:
                QMessageBox.warning(
                    self,
                    "Invalid English/MA Name",
                    "Use letters/numbers (spaces, _ . - allowed). "
                    "Chinese is converted to pinyin; leave blank to auto-fill from the song name.",
                )
                self._rebuild_song_list(select_indexes=[row])
                return
        else:
            ma = ma_export_name_from_display(song.name)
        new_val = ma or ma_export_name_from_display(song.name)
        if (song.ma_export_name or "") == new_val:
            if raw != new_val:
                self._rebuild_song_list(select_indexes=[row])
            return
        with self._setlist_edit("Edit English/MA Name"):
            song.ma_export_name = new_val
            self._mark_dirty()
            self._refresh_status()
            patch = getattr(self, "show_patch_page", None)
            if patch is not None:
                patch.sync_songs()
            self._rebuild_song_list(select_indexes=[row])
        self.status.showMessage(f'English/MA name changed to "{new_val}"', 2000)

    def _on_song_bpm_edited(self, row: int, value: object) -> None:
        song_index = self.song_list.row_song_index(row)
        if song_index is None or song_index < 0 or song_index >= len(self.project.songs):
            return
        song = self.project.songs[song_index]
        bpm: float | None
        if value is None:
            bpm = None
        else:
            try:
                bpm = float(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                self._on_song_bpm_edit_failed(row)
                return
            if bpm <= 0:
                bpm = None
        same_value = song.bpm == bpm or (
            song.bpm is not None
            and bpm is not None
            and abs(float(song.bpm) - bpm) < 1e-9
        )
        # Typing the same number still marks it as a user override (white).
        if same_value and (bpm is None or not song.bpm_auto):
            from cueplayer.media.bpm_analyzer import format_bpm_cell

            item = self.song_list.item(row, SetlistWidget.COL_BPM)
            if item is not None:
                self.song_list._block_number_signal = True  # noqa: SLF001
                item.setText(format_bpm_cell(bpm, auto=False))
                self.song_list._block_number_signal = False  # noqa: SLF001
            return
        with self._setlist_edit("Edit BPM"):
            song.bpm = bpm
            song.bpm_auto = False
            self._mark_dirty()
            self._rebuild_song_list(select_indexes=[row])
            sheet = getattr(self, "setlist_sheet_page", None)
            if sheet is not None:
                sheet.sync_songs()
        if bpm is None:
            self.status.showMessage("BPM cleared", 2000)
        else:
            from cueplayer.media.bpm_analyzer import format_bpm_value

            self.status.showMessage(f"BPM set to {format_bpm_value(bpm)}", 2000)

    def _on_song_bpm_edit_failed(self, row: int) -> None:
        QMessageBox.warning(self, "Invalid BPM", "Enter a positive number (e.g. 120, 128.5), or leave blank.")
        indexes = self._selected_song_indexes()
        if not indexes:
            song_index = self.song_list.row_song_index(row)
            if song_index is not None:
                indexes = [song_index]
        self._rebuild_song_list(select_indexes=indexes)

    def _add_setlist_column_actions(
        self, menu: QMenu
    ) -> tuple[QAction, QAction, QAction, QAction]:
        en_action = menu.addAction("Song English")
        en_action.setCheckable(True)
        en_action.setChecked(self.project.setlist_name_mode in ("both", "en"))
        en_action.setToolTip("Show the English / MA name column")
        bpm_action = menu.addAction("Song BPM")
        bpm_action.setCheckable(True)
        bpm_action.setChecked(bool(self.project.setlist_show_bpm))
        bpm_action.setToolTip("Show the BPM column")
        ltc_action = menu.addAction("LTC Output Status")
        ltc_action.setCheckable(True)
        ltc_action.setChecked(bool(self.project.setlist_show_ltc_badge))
        ltc_action.setToolTip("Show striped LTC L/R in the media column")
        video_action = menu.addAction("Video Output Status")
        video_action.setCheckable(True)
        video_action.setChecked(bool(self.project.setlist_show_video_badge))
        video_action.setToolTip("Show V when the song has video clips")
        return en_action, bpm_action, ltc_action, video_action

    def _apply_setlist_column_action(
        self,
        chosen: QAction | None,
        *,
        en_action: QAction,
        bpm_action: QAction,
        ltc_action: QAction,
        video_action: QAction,
    ) -> bool:
        if chosen is en_action:
            self.project.setlist_name_mode = "both" if en_action.isChecked() else "zh"  # type: ignore[assignment]
            self._sync_setlist_name_mode_ui()
            self._mark_dirty()
            self._rebuild_song_list(select_indexes=self._selected_song_indexes() or None)
            self.status.showMessage(
                "Song English shown" if en_action.isChecked() else "Song English hidden",
                1500,
            )
            return True
        if chosen is bpm_action:
            self.project.setlist_show_bpm = bool(bpm_action.isChecked())
            self.song_list.set_show_bpm(self.project.setlist_show_bpm)
            self._mark_dirty()
            self.status.showMessage(
                "Song BPM shown" if self.project.setlist_show_bpm else "Song BPM hidden",
                1500,
            )
            return True
        if chosen is ltc_action:
            self.project.setlist_show_ltc_badge = bool(ltc_action.isChecked())
            self._sync_setlist_column_prefs()
            self._mark_dirty()
            self.song_list.viewport().update()
            self.status.showMessage(
                "LTC Output Status shown"
                if ltc_action.isChecked()
                else "LTC Output Status hidden",
                1500,
            )
            return True
        if chosen is video_action:
            self.project.setlist_show_video_badge = bool(video_action.isChecked())
            self._sync_setlist_column_prefs()
            self._mark_dirty()
            self.song_list.viewport().update()
            self.status.showMessage(
                "Video Output Status shown"
                if video_action.isChecked()
                else "Video Output Status hidden",
                1500,
            )
            return True
        return False

    def _on_setlist_header_context_menu(self, pos) -> None:  # noqa: ANN001
        menu = QMenu(self)
        en_action, bpm_action, ltc_action, video_action = self._add_setlist_column_actions(menu)
        chosen = menu.exec(self.song_list.horizontalHeader().mapToGlobal(pos))
        self._apply_setlist_column_action(
            chosen,
            en_action=en_action,
            bpm_action=bpm_action,
            ltc_action=ltc_action,
            video_action=video_action,
        )

    def _on_setlist_context_menu(self, pos) -> None:  # noqa: ANN001
        index = self.song_list.indexAt(pos)
        if index.isValid():
            row = index.row()
            cat_id = self.song_list.row_category_id(row)
            if cat_id is not None:
                self._on_setlist_category_context_menu(cat_id, pos)
                return
            selected = {idx.row() for idx in self.song_list.selectedIndexes()}
            if row not in selected:
                self.song_list.selectRow(row)
        menu = QMenu(self)
        edit_action = menu.addAction("Edit…")
        duplicate_action = menu.addAction("Duplicate")
        add_action = menu.addAction("Add Song…")
        selected_songs = self._selected_songs()
        if selected_songs:
            new_category_action = menu.addAction(
                f"New Folder with Selected ({len(selected_songs)})…"
            )
        else:
            new_category_action = menu.addAction("New Folder…")
        move_menu = menu.addMenu("Move to Folder")
        remove_from_folder_action = move_menu.addAction("Main list (no folder)")
        remove_from_folder_action.setEnabled(False)
        category_actions: dict[QAction, str] = {}
        for category in self.project.setlist_categories:
            action = move_menu.addAction(category.name)
            category_actions[action] = category.id
        menu.addSeparator()
        row_color_action = menu.addAction("Row Color…")
        clear_row_color_action = menu.addAction("Clear Row Color")
        menu.addSeparator()
        en_action, bpm_action, ltc_action, video_action = self._add_setlist_column_actions(menu)
        menu.addSeparator()
        detect_selected_bpm_action = menu.addAction("Detect BPM (selected)")
        detect_missing_bpm_action = menu.addAction("Detect BPM (all without BPM)")
        detect_all_bpm_action = menu.addAction("Re-detect BPM (auto / empty only)")
        detect_selected_bpm_action.setToolTip(
            "Re-run auto BPM for selected songs that are auto or empty. "
            "Manual typed BPM is skipped."
        )
        detect_missing_bpm_action.setToolTip(
            "Only songs that still have an empty BPM cell and an audio file."
        )
        detect_all_bpm_action.setToolTip(
            "Re-detect auto BPM / empty cells only — never overwrites typed BPM."
        )
        menu.addSeparator()
        renumber_action = menu.addAction("Renumber")
        set_numbers_action = menu.addAction("Set Numbers Starting at…")
        menu.addSeparator()
        up_action = menu.addAction("Move Up")
        down_action = menu.addAction("Move Down")
        menu.addSeparator()
        delete_action = menu.addAction("Delete")
        has_selection = bool(self._selected_song_indexes()) or self.song_list.currentRow() >= 0
        edit_action.setEnabled(has_selection)
        duplicate_action.setEnabled(has_selection)
        remove_from_folder_action.setEnabled(
            has_selection and any(song.category_id for song in selected_songs)
        )
        move_menu.setEnabled(has_selection and bool(self.project.setlist_categories))
        row_color_action.setEnabled(has_selection)
        row_color_action.setToolTip("Pick a background color for the selected song(s) (e.g. VIP, problem cue)")
        clear_row_color_action.setEnabled(
            has_selection and any(song.row_color for song in selected_songs)
        )
        detect_selected_bpm_action.setEnabled(
            has_selection
            and any(self._main_audio_path_for_song(s) is not None for s in selected_songs)
        )
        detect_missing_bpm_action.setEnabled(
            any(
                s.bpm is None and self._main_audio_path_for_song(s) is not None
                for s in self.project.songs
            )
        )
        detect_all_bpm_action.setEnabled(
            any(self._main_audio_path_for_song(s) is not None for s in self.project.songs)
        )
        delete_action.setEnabled(has_selection and len(self.project.songs) >= 1)
        renumber_action.setEnabled(has_selection)
        renumber_action.setToolTip(
            "Reset selected songs to 1, 2, 3… within each folder (list order)"
        )
        set_numbers_action.setEnabled(has_selection)
        set_numbers_action.setToolTip(
            "Type a starting number (e.g. 21) — selected songs become 21, 22, 23…"
        )
        up_action.setEnabled(has_selection)
        down_action.setEnabled(has_selection)
        chosen = menu.exec(self.song_list.viewport().mapToGlobal(pos))
        if self._apply_setlist_column_action(
            chosen,
            en_action=en_action,
            bpm_action=bpm_action,
            ltc_action=ltc_action,
            video_action=video_action,
        ):
            return
        if chosen is detect_selected_bpm_action:
            n = self._detect_bpm_for_songs(selected_songs, force=True)
            skipped_manual = sum(
                1
                for s in selected_songs
                if s.bpm is not None
                and float(s.bpm) > 0
                and not bool(getattr(s, "bpm_auto", False))
            )
            if n:
                self.status.showMessage(f"Detecting BPM for {n} selected song(s)…", 4000)
            elif skipped_manual:
                self.status.showMessage(
                    f"Skipped {skipped_manual} song(s) with manual BPM "
                    "(clear the cell to re-detect).",
                    4000,
                )
            else:
                self.status.showMessage("No audio file on the selected song(s).", 3000)
            return
        if chosen is detect_missing_bpm_action:
            self._schedule_bpm_detect_for_missing_songs(quiet=False)
            return
        if chosen is detect_all_bpm_action:
            self._redetect_bpm_all_songs()
            return
        if chosen is edit_action:
            self._edit_song()
        elif chosen is duplicate_action:
            self._duplicate_song()
        elif chosen is add_action:
            self._add_song()
        elif chosen is new_category_action:
            self._add_setlist_category()
        elif chosen is remove_from_folder_action:
            self._move_selected_songs_to_category(None)
        elif chosen in category_actions:
            self._move_selected_songs_to_category(category_actions[chosen])
        elif chosen is row_color_action:
            self._pick_row_color()
        elif chosen is clear_row_color_action:
            self._clear_row_color()
        elif chosen is renumber_action:
            self._renumber_selected_songs()
        elif chosen is set_numbers_action:
            self._set_selected_songs_numbers_from()
        elif chosen is up_action:
            self._move_selected_songs(-1)
        elif chosen is down_action:
            self._move_selected_songs(1)
        elif chosen is delete_action:
            self._delete_song()

    def _selected_songs(self) -> list[Song]:
        return [self.project.songs[i] for i in self._selected_song_indexes()]

    def _pick_row_color(self) -> None:
        songs = self._selected_songs()
        if not songs:
            return
        initial = QColor(songs[0].row_color) if songs[0].row_color else QColor(BG_SELECTED)
        from cueplayer.ui.color_presets import get_color

        chosen = get_color(initial, self, "Row Color")
        if not chosen.isValid():
            return
        hex_color = chosen.name().upper()
        with self._setlist_edit("Row Color"):
            for song in songs:
                song.row_color = hex_color
            self._mark_dirty()
            self._rebuild_song_list(select_indexes=self._selected_song_indexes())
        label = songs[0].name if len(songs) == 1 else f"{len(songs)} songs"
        self.status.showMessage(f'Row color set for "{label}"', 2000)

    def _clear_row_color(self) -> None:
        songs = self._selected_songs()
        if not songs:
            return
        with self._setlist_edit("Clear Row Color"):
            for song in songs:
                song.row_color = ""
            self._mark_dirty()
            self._rebuild_song_list(select_indexes=self._selected_song_indexes())
        self.status.showMessage("Row color cleared", 2000)

    def _on_setlist_number_edit_failed(self, row: int) -> None:
        QMessageBox.warning(self, "Invalid Number", "Enter a number (e.g. 1, 0.5, 2.5).")
        indexes = self._selected_song_indexes()
        if not indexes:
            song_index = self.song_list.row_song_index(row)
            if song_index is not None:
                indexes = [song_index]
        self._rebuild_song_list(select_indexes=indexes)

    def _on_setlist_number_edited(self, row: int, value: float) -> None:
        song_index = self.song_list.row_song_index(row)
        if song_index is None or song_index < 0 or song_index >= len(self.project.songs):
            return
        song = self.project.songs[song_index]
        if abs(float(song.setlist_number) - value) < 1e-9:
            # Normalize display text.
            item = self.song_list.item(row, 0)
            if item is not None:
                text = format_setlist_number(value)
                self.song_list._block_number_signal = True  # noqa: SLF001
                item.setText(text)
                item.setData(Qt.ItemDataRole.UserRole + 1, text)
                self.song_list._block_number_signal = False  # noqa: SLF001
            return
        with self._setlist_edit("Edit Number"):
            song.setlist_number = value
            item = self.song_list.item(row, 0)
            if item is not None:
                text = format_setlist_number(value)
                self.song_list._block_number_signal = True  # noqa: SLF001
                item.setText(text)
                item.setData(Qt.ItemDataRole.UserRole + 1, text)
                self.song_list._block_number_signal = False  # noqa: SLF001
            self._mark_dirty()
        self.status.showMessage(
            f'Number changed to {format_setlist_number(value)} (within this folder)',
            2500,
        )

    def _on_setlist_rows_reordered(self, song_ids: list, drop_row: int) -> None:
        ids = [str(sid) for sid in song_ids]
        if not ids:
            return
        id_set = set(ids)
        by_id = {song.id: song for song in self.project.songs}
        moving = [by_id[sid] for sid in ids if sid in by_id]
        if not moving:
            return

        with self._setlist_edit("Reorder Songs"):
            old_categories = {song.id: song.category_id for song in moving}
            entries = self._setlist_display_rows()
            moving_entries = [
                e
                for e in entries
                if e.kind == "song"
                and e.song_index is not None
                and self.project.songs[e.song_index].id in id_set
            ]
            rest = [
                e
                for e in entries
                if not (
                    e.kind == "song"
                    and e.song_index is not None
                    and self.project.songs[e.song_index].id in id_set
                )
            ]
            insert_at = max(0, min(int(drop_row), len(rest)))
            new_entries = rest[:insert_at] + moving_entries + rest[insert_at:]

            moving_id_set = id_set
            for i, entry in enumerate(new_entries):
                if entry.kind != "song" or entry.song_index is None:
                    continue
                song = self.project.songs[entry.song_index]
                if song.id not in moving_id_set:
                    continue
                song.category_id = self._category_id_before_display_index(new_entries, i)

            ordered_songs: list[Song] = []
            seen: set[str] = set()
            for entry in new_entries:
                if entry.kind != "song" or entry.song_index is None:
                    continue
                song = self.project.songs[entry.song_index]
                if song.id in seen:
                    continue
                seen.add(song.id)
                ordered_songs.append(song)
            for song in self.project.songs:
                if song.id not in seen:
                    ordered_songs.append(song)

            keep_id = self.current_song.id
            self.project.songs = ordered_songs
            new_indexes = [i for i, song in enumerate(self.project.songs) if song.id in id_set]
            if not new_indexes:
                new_indexes = [min(insert_at, len(self.project.songs) - 1)]
            self._rebuild_song_list(select_indexes=new_indexes)
            try:
                current_row = next(
                    i for i, song in enumerate(self.project.songs) if song.id == keep_id
                )
            except StopIteration:
                current_row = new_indexes[-1]
            self.current_song = self.project.songs[current_row]
            self._undo_ctx.current_song_id = self.current_song.id
            self._mark_dirty()
            self._refresh_status()
        folder_changed = any(
            song.category_id != old_categories.get(song.id) for song in moving
        )
        tip = " · Media moves on Save" if folder_changed else ""
        self.status.showMessage(f"Song order updated by drag{tip}", 2000)

    def _on_songs_moved_to_category(self, song_ids: list, category_id: str) -> None:
        category = self.project.setlist_category_by_id(str(category_id))
        if category is None:
            return
        id_set = {str(sid) for sid in song_ids}
        moving = [song for song in self.project.songs if song.id in id_set]
        if not moving:
            return
        with self._setlist_edit("Move to Folder"):
            self._assign_songs_to_category(moving, category.id)
            indexes = [i for i, song in enumerate(self.project.songs) if song.id in id_set]
            self._rebuild_song_list(select_indexes=indexes)
            self._mark_dirty()
        self.status.showMessage(
            f'Moved {len(moving)} song(s) into "{category.name}" · Media moves on Save',
            2500,
        )

    def _on_setlist_categories_reordered(self, category_id: str, insert_before: int) -> None:
        """Drag a folder header to a new place among other folders."""
        cats = self.project.setlist_categories
        cat_id = str(category_id)
        old_index = next((i for i, cat in enumerate(cats) if cat.id == cat_id), None)
        if old_index is None:
            return
        target = max(0, min(int(insert_before), len(cats)))
        if old_index < target:
            target -= 1
        if target == old_index:
            return
        with self._setlist_edit("Reorder Folders"):
            category = cats.pop(old_index)
            cats.insert(target, category)
            self._rebuild_song_list()
            sheet = getattr(self, "setlist_sheet_page", None)
            if sheet is not None:
                sheet.sync_songs()
            self._mark_dirty()
        self.status.showMessage(f'Folder order updated: "{category.name}"', 2000)

    def _toggle_setlist_category(self, category_id: str) -> None:
        category = self.project.setlist_category_by_id(category_id)
        if category is None:
            return
        with self._setlist_edit("Toggle Folder"):
            category.collapsed = not category.collapsed
            self._rebuild_song_list(select_indexes=self._selected_song_indexes() or None)
            self._mark_dirty()
        state = "collapsed" if category.collapsed else "expanded"
        self.status.showMessage(f'Folder "{category.name}" {state}', 1500)

    def _add_setlist_category(self, *, wrap_selected: bool | None = None) -> None:
        selected = self._selected_songs()
        if wrap_selected is None:
            wrap_selected = bool(selected)
        title = "New Folder with Selected" if wrap_selected and selected else "New Setlist Folder"
        prompt = (
            f"Folder name for {len(selected)} selected song(s):"
            if wrap_selected and selected
            else "Folder name:"
        )
        name, ok = QInputDialog.getText(self, title, prompt)
        if not ok:
            return
        category = SetlistCategory.create(name)
        with self._setlist_edit("New Folder"):
            self.project.setlist_categories.append(category)
            if wrap_selected and selected:
                self._assign_songs_to_category(selected, category.id)
            indexes = (
                [self.project.songs.index(s) for s in selected]
                if wrap_selected and selected
                else (self._selected_song_indexes() or None)
            )
            self._rebuild_song_list(select_indexes=indexes)
            self._mark_dirty()
        if wrap_selected and selected:
            self.status.showMessage(
                f'Created folder "{category.name}" with {len(selected)} song(s)'
                f" · Media moves on Save",
                2500,
            )
        else:
            self.status.showMessage(f'Created folder "{category.name}"', 2500)

    def _rename_setlist_category(self, category_id: str) -> None:
        category = self.project.setlist_category_by_id(category_id)
        if category is None:
            return
        name, ok = QInputDialog.getText(
            self, "Rename Folder", "Folder name:", text=category.name
        )
        if not ok:
            return
        new_name = name.strip() or category.name
        if new_name == category.name:
            return
        with self._setlist_edit("Rename Folder"):
            category.name = new_name
            self._rebuild_song_list(select_indexes=self._selected_song_indexes() or None)
            self._mark_dirty()
        self.status.showMessage(
            f'Renamed folder to "{category.name}" · Media folder renames on Save',
            2500,
        )

    def _delete_setlist_category(self, category_id: str) -> None:
        category = self.project.setlist_category_by_id(category_id)
        if category is None:
            return
        member_count = sum(1 for song in self.project.songs if song.category_id == category.id)
        prompt = (
            f'Delete folder "{category.name}"?'
            if member_count == 0
            else (
                f'Delete folder "{category.name}"?\n\n'
                f"{member_count} song(s) inside will move back to the main list."
            )
        )
        answer = QMessageBox.question(
            self,
            "Delete Folder",
            prompt,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        released = [song for song in self.project.songs if song.category_id == category.id]
        with self._setlist_edit("Delete Folder"):
            for song in released:
                song.category_id = None
            self.project.setlist_categories = [
                c for c in self.project.setlist_categories if c.id != category.id
            ]
            self._rebuild_song_list(select_indexes=self._selected_song_indexes() or None)
            self._mark_dirty()
        tip = " · Media moves on Save" if released else ""
        self.status.showMessage(f'Deleted folder "{category.name}"{tip}', 2500)

    def _move_selected_songs_to_category(self, category_id: str | None) -> None:
        songs = self._selected_songs()
        if not songs:
            return
        indexes = self._selected_song_indexes()
        with self._setlist_edit("Move to Folder"):
            self._assign_songs_to_category(songs, category_id)
            self._rebuild_song_list(select_indexes=indexes)
            self._mark_dirty()
        if category_id is None:
            self.status.showMessage("Moved song(s) out of folder · Media moves on Save", 2000)
            return
        category = self.project.setlist_category_by_id(category_id)
        label = category.name if category is not None else "folder"
        self.status.showMessage(
            f'Moved song(s) into "{label}" · Media moves on Save',
            2000,
        )

    def _on_setlist_category_context_menu(self, category_id: str, pos) -> None:  # noqa: ANN001
        category = self.project.setlist_category_by_id(category_id)
        if category is None:
            return
        menu = QMenu(self)
        add_song_action = menu.addAction("Add Song…")
        rename_action = menu.addAction("Rename Folder…")
        toggle_action = menu.addAction(
            "Expand Folder" if category.collapsed else "Collapse Folder"
        )
        renumber_action = menu.addAction("Renumber Folder")
        renumber_action.setEnabled(bool(self.project.songs_in_category(category.id)))
        menu.addSeparator()
        folder_color_action = menu.addAction("Folder Color…")
        folder_color_action.setToolTip("Pick a background color for this folder row")
        clear_folder_color_action = menu.addAction("Clear Folder Color")
        clear_folder_color_action.setEnabled(bool(category.row_color))
        menu.addSeparator()
        delete_action = menu.addAction("Delete Folder")
        chosen = menu.exec(self.song_list.viewport().mapToGlobal(pos))
        if chosen is add_song_action:
            self._add_song(category_id)
        elif chosen is rename_action:
            self._rename_setlist_category(category_id)
        elif chosen is toggle_action:
            self._toggle_setlist_category(category_id)
        elif chosen is renumber_action:
            self._renumber_songs_in_category(category_id)
        elif chosen is folder_color_action:
            self._pick_folder_color(category_id)
        elif chosen is clear_folder_color_action:
            self._clear_folder_color(category_id)
        elif chosen is delete_action:
            self._delete_setlist_category(category_id)

    def _pick_folder_color(self, category_id: str) -> None:
        category = self.project.setlist_category_by_id(category_id)
        if category is None:
            return
        initial = QColor(category.row_color) if category.row_color else QColor(BG_SELECTED)
        from cueplayer.ui.color_presets import get_color

        chosen = get_color(initial, self, "Folder Color")
        if not chosen.isValid():
            return
        hex_color = chosen.name().upper()
        with self._setlist_edit("Folder Color"):
            category.row_color = hex_color
            self._mark_dirty()
            self._rebuild_song_list(select_indexes=self._selected_song_indexes())
        self.status.showMessage(f'Folder color set for "{category.name}"', 2000)

    def _clear_folder_color(self, category_id: str) -> None:
        category = self.project.setlist_category_by_id(category_id)
        if category is None or not category.row_color:
            return
        with self._setlist_edit("Clear Folder Color"):
            category.row_color = ""
            self._mark_dirty()
            self._rebuild_song_list(select_indexes=self._selected_song_indexes())
        self.status.showMessage(f'Folder color cleared for "{category.name}"', 2000)

    def _move_selected_songs(self, delta: int) -> None:
        indexes = self._selected_song_indexes()
        if not indexes:
            return
        start, end = indexes[0], indexes[-1]
        if indexes != list(range(start, end + 1)):
            self.status.showMessage("Select consecutive songs to move up/down", 2500)
            return
        new_start = start + delta
        new_end = end + delta
        if new_start < 0 or new_end >= len(self.project.songs):
            return
        keep_id = self.current_song.id
        with self._setlist_edit("Move Songs"):
            block = self.project.songs[start : end + 1]
            del self.project.songs[start : end + 1]
            self.project.songs[new_start:new_start] = block
            new_indexes = list(range(new_start, new_end + 1))
            self._rebuild_song_list(select_indexes=new_indexes)
            try:
                current_row = next(
                    i for i, song in enumerate(self.project.songs) if song.id == keep_id
                )
            except StopIteration:
                current_row = new_indexes[-1]
            self.current_song = self.project.songs[current_row]
            self._undo_ctx.current_song_id = self.current_song.id
            self._mark_dirty()
            self._refresh_status()
        self.status.showMessage("Song order updated", 2000)

    def _sort_key(self, song: Song) -> tuple[float, str]:
        return (float(song.setlist_number), song.name)

    def _apply_sort_sections(self, sorted_sections: set[str | None]) -> None:
        if not self.project.songs:
            return
        current_id = self.current_song.id
        with self._setlist_edit("Sort by Number"):
            ordered: list[Song] = []
            main = self._songs_in_category_display_order(None)
            if None in sorted_sections and len(main) > 1:
                main = sorted(main, key=self._sort_key)
            ordered.extend(main)
            for category in self.project.setlist_categories:
                members = self._songs_in_category_display_order(category.id)
                if category.id in sorted_sections and len(members) > 1:
                    members = sorted(members, key=self._sort_key)
                ordered.extend(members)
            self.project.songs = ordered
            try:
                new_row = next(
                    i for i, s in enumerate(self.project.songs) if s.id == current_id
                )
            except StopIteration:
                new_row = 0
            self._rebuild_song_list(select_indexes=[new_row])
            self._activate_song(new_row, stop_playback=False)
            self._mark_dirty()

    def _sort_songs_in_category(self, category_id: str | None) -> None:
        members = self._songs_in_category_display_order(category_id)
        if len(members) <= 1:
            return
        self._apply_sort_sections({category_id})
        section = self._setlist_section_label(category_id)
        self.status.showMessage(f'Sorted "{section}" by number', 2500)

    def _sort_all_sections(self) -> None:
        if len(self.project.songs) <= 1:
            return
        sections: set[str | None] = {None}
        sections.update(category.id for category in self.project.setlist_categories)
        self._apply_sort_sections(sections)
        self.status.showMessage("Sorted all sections by number", 2500)

    def _setlist_section_label(self, category_id: str | None) -> str:
        if category_id is None:
            return "Main list"
        category = self.project.setlist_category_by_id(category_id)
        return category.name if category is not None else "Folder"

    def _show_setlist_section_menu(
        self,
        anchor: QWidget,
        *,
        on_section: Callable[[str | None], None],
        on_all: Callable[[], None],
    ) -> None:
        menu = QMenu(self)
        section_actions: dict[QAction, str | None] = {}
        main_action = menu.addAction("Main list (no folder)")
        main_action.setEnabled(bool(self.project.songs_in_category(None)))
        section_actions[main_action] = None
        if self.project.setlist_categories:
            menu.addSeparator()
        for category in self.project.setlist_categories:
            action = menu.addAction(category.name)
            action.setEnabled(bool(self.project.songs_in_category(category.id)))
            section_actions[action] = category.id
        menu.addSeparator()
        all_action = menu.addAction("All")
        all_action.setEnabled(len(self.project.songs) > 1)
        chosen = menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height())))
        if chosen is all_action:
            on_all()
        elif chosen in section_actions:
            on_section(section_actions[chosen])

    def _show_sort_section_menu(self) -> None:
        self._show_setlist_section_menu(
            self.sort_by_number_button,
            on_section=self._sort_songs_in_category,
            on_all=self._sort_all_sections,
        )

    def _show_renumber_section_menu(self) -> None:
        self._show_setlist_section_menu(
            self.renumber_button,
            on_section=self._renumber_songs_in_category,
            on_all=self._renumber_all_sections,
        )

    def _songs_in_category_display_order(self, category_id: str | None) -> list[Song]:
        songs: list[Song] = []
        for entry in self._setlist_display_rows():
            if entry.kind != "song" or entry.song_index is None:
                continue
            song = self.project.songs[entry.song_index]
            if song.category_id == category_id:
                songs.append(song)
        return songs

    def _selected_songs_in_display_order(self) -> list[Song]:
        selected_ids = {self.project.songs[i].id for i in self._selected_song_indexes()}
        if not selected_ids:
            return []
        songs: list[Song] = []
        for entry in self._setlist_display_rows():
            if entry.kind != "song" or entry.song_index is None:
                continue
            song = self.project.songs[entry.song_index]
            if song.id in selected_ids:
                songs.append(song)
        return songs

    def _set_selected_songs_numbers_from(self) -> None:
        songs = self._selected_songs_in_display_order()
        if not songs:
            return
        default = format_setlist_number(songs[0].setlist_number)
        start_text, ok = QInputDialog.getText(
            self,
            "Set Numbers",
            f"Starting number for {len(songs)} selected song(s)\n"
            "(list order — e.g. 21 becomes 21, 22, 23…):",
            text=default,
        )
        if not ok:
            return
        start = parse_setlist_number(start_text)
        if start is None:
            QMessageBox.warning(self, "Set Numbers", "Invalid number.")
            return
        with self._setlist_edit("Set Numbers"):
            for offset, song in enumerate(songs):
                song.setlist_number = start + float(offset)
            first = format_setlist_number(start)
            last = format_setlist_number(start + len(songs) - 1)
            self._finish_renumber(message=f"Set numbers {first}–{last}")

    def _renumber_songs_in_category(self, category_id: str | None) -> None:
        members = self._songs_in_category_display_order(category_id)
        if not members:
            return
        section = self._setlist_section_label(category_id)
        answer = QMessageBox.question(
            self,
            "Renumber",
            f'Renumber all songs in "{section}" to 1, 2, 3… following list order?\n'
            "(Custom numbers such as 0.5 will be overwritten.)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        with self._setlist_edit("Renumber"):
            for index, song in enumerate(members, start=1):
                song.setlist_number = float(index)
            self._finish_renumber()

    def _renumber_selected_songs(self) -> None:
        indexes = self._selected_song_indexes()
        if not indexes:
            return
        selected_ids = {self.project.songs[i].id for i in indexes}
        grouped: dict[str | None, list[Song]] = {}
        for entry in self._setlist_display_rows():
            if entry.kind != "song" or entry.song_index is None:
                continue
            song = self.project.songs[entry.song_index]
            if song.id not in selected_ids:
                continue
            grouped.setdefault(song.category_id, []).append(song)
        if not grouped:
            return
        if len(grouped) == 1:
            (category_id, songs) = next(iter(grouped.items()))
            section = self._setlist_section_label(category_id)
            prompt = (
                f'Renumber {len(songs)} selected song(s) in "{section}" to 1, 2, 3… '
                "following list order?\n(Custom numbers such as 0.5 will be overwritten.)"
            )
        else:
            parts = [
                f"{len(songs)} in \"{self._setlist_section_label(category_id)}\""
                for category_id, songs in grouped.items()
            ]
            prompt = (
                "Renumber selected songs to 1, 2, 3… within each folder?\n"
                + " · ".join(parts)
                + "\n(Custom numbers such as 0.5 will be overwritten.)"
            )
        answer = QMessageBox.question(
            self,
            "Renumber",
            prompt,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        with self._setlist_edit("Renumber"):
            for songs in grouped.values():
                for index, song in enumerate(songs, start=1):
                    song.setlist_number = float(index)
            self._finish_renumber()

    def _renumber_all_sections(self) -> None:
        if not self.project.songs:
            return
        answer = QMessageBox.question(
            self,
            "Renumber",
            "Reset every section to 1, 2, 3… following the current top-to-bottom order?\n"
            "Each folder and the main list get their own 1, 2, 3… sequence.\n"
            "(Custom numbers such as 0.5 will be overwritten.)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        with self._setlist_edit("Renumber All"):
            next_by_category: dict[str | None, float] = {}
            for entry in self._setlist_display_rows():
                if entry.kind != "song" or entry.song_index is None:
                    continue
                song = self.project.songs[entry.song_index]
                cat = song.category_id
                num = next_by_category.get(cat, 1.0)
                song.setlist_number = num
                next_by_category[cat] = num + 1.0
            self._finish_renumber(message="Renumbered all sections to 1, 2, 3…")

    def _finish_renumber(self, *, message: str = "Renumbered to 1, 2, 3…") -> None:
        indexes = self._selected_song_indexes()
        self._rebuild_song_list(select_indexes=indexes)
        self._mark_dirty()
        self._refresh_status()
        self.status.showMessage(message, 2500)

    def _renumber_songs_by_list_order(self) -> None:
        """Back-compat entry point — opens the section picker."""
        self._show_renumber_section_menu()

    def _activate_song(self, index: int, *, stop_playback: bool = True) -> None:
        """Activate setlist song — orchestration lives on ``ShowSessionService``."""
        self.show_session.activate_song_at(index, stop_playback=stop_playback)

    def _activate_song_monitor(self, gen: int, song) -> None:  # noqa: ANN001
        """Back-compat wrapper; prefer ``ShowSessionService._activate_song_monitor``."""
        self.show_session._activate_song_monitor(gen, song)

    def _next_song_default_name(self) -> str:
        return f"Song {len(self.project.songs) + 1}"

    def _default_start_timecode(self) -> str:
        if self.project.songs:
            return self.project.songs[-1].start_timecode or "01:00:00:00"
        return "01:00:00:00"

    def _default_fps(self) -> float:
        if self.project.songs:
            return float(self.project.songs[-1].fps or 30.0)
        return 30.0

    def _add_song(self, category_id: str | None = None) -> None:
        draft = SongDraft(
            name=self._next_song_default_name(),
            setlist_number=self._next_setlist_number(category_id),
            ma_export_name="",
            start_timecode=self._default_start_timecode(),
            fps=self._default_fps(),
        )
        dialog = SongEditDialog([draft], title="Add Song", parent=self)
        if not dialog.exec():
            return
        result = dialog.result_drafts()[0]
        song = self.project.new_song(result.name)
        with self._setlist_edit("Add Song"):
            self._apply_draft_to_song(song, result)
            if category_id is not None:
                song.category_id = category_id
            self.project.songs.append(song)
            index = len(self.project.songs) - 1
            self._rebuild_song_list(select_indexes=[index])
            self._activate_song(index, stop_playback=True)
            self._mark_dirty()
        folder = self.project.setlist_category_by_id(category_id) if category_id else None
        where = f' in "{folder.name}"' if folder is not None else ""
        ma = f" · MA {song.ma_export_name}" if song.ma_export_name else ""
        self.status.showMessage(
            f"Added song{where}: #{format_setlist_number(song.setlist_number)} {song.name}{ma}",
            3000,
        )

    def _add_songs_from_media_paths(self, paths: list) -> None:
        """Drop onto Setlist → confirm number/name/MA/TC/FPS, then add."""
        drafts: list[SongDraft] = []
        next_num = self._next_setlist_number()
        for raw in paths:
            path = Path(raw)
            if not path.is_file():
                continue
            suf = path.suffix.lower()
            if suf in AUDIO_SUFFIXES:
                drafts.append(
                    SongDraft(
                        name=path.stem,
                        setlist_number=next_num,
                        ma_export_name=suggest_ma_export_name(path.stem),
                        start_timecode=self._default_start_timecode(),
                        fps=self._default_fps(),
                        audio_path=path,
                    )
                )
                next_num += 1.0
            elif suf in VIDEO_SUFFIXES:
                drafts.append(
                    SongDraft(
                        name=path.stem,
                        setlist_number=next_num,
                        ma_export_name=suggest_ma_export_name(path.stem),
                        start_timecode=self._default_start_timecode(),
                        fps=self._default_fps(),
                        video_path=path,
                    )
                )
                next_num += 1.0
        if not drafts:
            self.status.showMessage("No audio or video files to add", 2500)
            return
        title = "Import Song" if len(drafts) == 1 else f"Batch Import Songs ({len(drafts)})"
        dialog = SongEditDialog(drafts, title=title, parent=self)
        if not dialog.exec():
            return
        last_index: int | None = None
        added_indexes: list[int] = []
        with self._setlist_edit("Import Songs"):
            for draft in dialog.result_drafts():
                song = self.project.new_song(draft.name)
                self._apply_draft_to_song(song, draft)
                self.project.songs.append(song)
                last_index = len(self.project.songs) - 1
                added_indexes.append(last_index)
            if last_index is None:
                return
            self._rebuild_song_list(select_indexes=added_indexes)
            self._activate_song(last_index, stop_playback=True)
            self._mark_dirty()
        if last_index is None:
            return
        self._prefetch_all_setlist_audio()
        if self._media_warm_active:
            self._refresh_media_warm_status()
        elif len(added_indexes) == 1:
            song = self.project.songs[last_index]
            self.status.showMessage(
                f"Added song: #{format_setlist_number(song.setlist_number)} {song.name}",
                3000,
            )
        else:
            self.status.showMessage(f"Added {len(added_indexes)} songs", 3000)

    def _edit_song(self) -> None:
        indexes = self._selected_song_indexes()
        if not indexes:
            row = self.song_list.currentRow()
            if row < 0 or row >= len(self.project.songs):
                return
            indexes = [row]
        drafts = [self._song_to_draft(self.project.songs[i]) for i in indexes]
        title = "Edit Song" if len(drafts) == 1 else f"Batch Edit Songs ({len(drafts)})"
        dialog = SongEditDialog(drafts, title=title, parent=self)
        if not dialog.exec():
            return
        by_id = {song.id: song for song in self.project.songs}
        media_changed = False
        with self._setlist_edit("Edit Song"):
            for draft in dialog.result_drafts():
                if draft.song_id and draft.song_id in by_id:
                    song = by_id[draft.song_id]
                    if self._draft_changes_media(song, draft):
                        media_changed = True
                    self._apply_draft_to_song(song, draft)
            self._rebuild_song_list(select_indexes=indexes)
            if self.current_song.id in {d.song_id for d in dialog.result_drafts() if d.song_id}:
                try:
                    cur = self.project.songs.index(self.current_song)
                except ValueError:
                    cur = indexes[0]
                if media_changed:
                    self._activate_song(cur, stop_playback=False)
                else:
                    # Rename / metadata only — keep waveform + video clips warm.
                    self.engine.set_song_timebase(
                        self.current_song.start_timecode, self.current_song.fps
                    )
                    self.timeline.update()
                    self._refresh_timecode_status()
            self._mark_dirty()
            self._refresh_status()
        if len(indexes) == 1:
            song = self.project.songs[indexes[0]]
            self.status.showMessage(
                f"Updated: #{format_setlist_number(song.setlist_number)} {song.name}",
                3000,
            )
        else:
            self.status.showMessage(f"Updated {len(indexes)} songs", 3000)

    def _duplicate_song(self) -> None:
        indexes = self._selected_song_indexes()
        if not indexes:
            row = self.song_list.currentRow()
            if 0 <= row < len(self.project.songs):
                indexes = [row]
        if not indexes:
            return

        new_indexes: list[int] = []
        with self._setlist_edit("Duplicate Song"):
            for row in sorted(indexes, reverse=True):
                source = self.project.songs[row]
                dup = source.duplicate(
                    name=f"{source.name} (copy)",
                    setlist_number=self._next_setlist_number(source.category_id),
                )
                insert_at = row + 1
                self.project.songs.insert(insert_at, dup)
                new_indexes.append(insert_at)
            new_indexes.sort()

            self._rebuild_song_list(select_indexes=new_indexes)
            self._activate_song(new_indexes[0], stop_playback=True)
            self._mark_dirty()
            patch = getattr(self, "show_patch_page", None)
            if patch is not None:
                patch.sync_songs()

        if len(new_indexes) == 1:
            src_row = indexes[0]
            dup = self.project.songs[new_indexes[0]]
            src_name = self.project.songs[src_row].name
            self.status.showMessage(
                f'Duplicated "{src_name}" as #{format_setlist_number(dup.setlist_number)} '
                f"{dup.name} — use Edit… to replace audio",
                4000,
            )
            self._edit_song()
        else:
            self.status.showMessage(f"Duplicated {len(new_indexes)} songs", 3000)

    def _delete_song(self) -> None:
        indexes = self._selected_song_indexes()
        if not indexes:
            row = self.song_list.currentRow()
            song_index = self.song_list.row_song_index(row) if row >= 0 else None
            if song_index is not None and 0 <= song_index < len(self.project.songs):
                indexes = [song_index]
        if not indexes:
            return
        if len(indexes) == 1:
            song = self.project.songs[indexes[0]]
            prompt = f'Delete "{song.name}"?\n(Its marks and audio link will also be removed)'
        else:
            prompt = f"Delete the selected {len(indexes)} songs?\n(Their marks and audio links will also be removed)"
        answer = QMessageBox.question(
            self,
            "Delete Song",
            prompt,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        removed_names = [self.project.songs[i].name for i in indexes]
        with self._setlist_edit("Delete Song"):
            for i in sorted(indexes, reverse=True):
                del self.project.songs[i]
            if self.project.songs:
                new_row = min(indexes[0], len(self.project.songs) - 1)
                self._rebuild_song_list(select_indexes=[new_row])
                self._activate_song(new_row, stop_playback=True)
            else:
                self._apply_empty_project_workspace()
            self._mark_dirty()
        if len(removed_names) == 1:
            self.status.showMessage(f"Deleted song: {removed_names[0]}", 2500)
        else:
            self.status.showMessage(f"Deleted {len(removed_names)} songs", 2500)

    # ── MainWindow-level drag/drop fallback ──────────────────────────────────
    # When the cursor is over chrome that isn't a registered drop_target child
    # (e.g. the status bar, toolbar, outer window border) there is no other
    # handler and the cursor shows 🚫. Accept everything here so the cursor
    # stays "copy" across the whole window; the actual routing happens in
    # dropEvent below.

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if mime_looks_like_file_drop(event.mimeData()):
            accept_file_drag(event)
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        if mime_looks_like_file_drop(event.mimeData()):
            accept_file_drag(event)
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        """Fallback drop handler for the whole main window."""
        mime = event.mimeData()
        audio = audio_paths_from_mime(mime)
        video = video_paths_from_mime(mime)
        if audio:
            accept_file_drop(event)
            self._add_songs_from_media_paths(audio)
        elif video:
            accept_file_drop(event)
            self._add_video_clips_from_paths(video, self.playback.position)
        else:
            self.status.showMessage(rejected_file_drop_reason(mime), 5000)
            event.ignore()

    # ── window management ─────────────────────────────────────────────────────

    def _shutdown_secondary_windows(self) -> None:
        """Close persistent tool windows so the app can exit with the main UI."""
        self.playback.stop()
        self.engine.shutdown_midi_outputs()
        if hasattr(self, "_ndi_output"):
            self._ndi_output.close()
        self.clean_output_window.force_close()
        app = QApplication.instance()
        if app is None:
            return
        for widget in list(app.topLevelWidgets()):
            if widget is self or not widget.isVisible():
                continue
            widget.close()

    def _sync_timeline_overview(self) -> None:
        transport = getattr(self, "transport", None)
        timeline = getattr(self, "timeline", None)
        if transport is None or timeline is None:
            return
        view_start, view_end = timeline.visible_time_window()
        title = ""
        song = getattr(self, "current_song", None)
        if song is not None:
            title = (song.name or "").strip()
        transport.set_overview_state(
            duration=float(timeline._duration()),  # noqa: SLF001
            position=float(timeline.playhead_seconds()),
            view_start=view_start,
            view_end=view_end,
            title=title,
        )

    def _sync_timeline_geometry(self) -> None:
        """QScrollArea(widgetResizable=False): match viewport width, content height.

        Timeline horizontal pan/zoom uses ``_scroll_x`` against the *visible*
        width — never stretch the widget to the full song pixel width.
        """
        if getattr(self, "_syncing_timeline_geometry", False):
            return
        scroll = getattr(self, "_timeline_scroll", None)
        if scroll is None:
            return
        self._syncing_timeline_geometry = True
        try:
            vp = scroll.viewport()
            tl = self.timeline
            w = max(1, vp.width())
            h = max(tl.minimumHeight(), tl._content_height)  # noqa: SLF001
            resizing = bool(
                getattr(tl, "_resizing_wave", False)
                or getattr(tl, "_resizing_video_lane", False)
                or getattr(tl, "_resizing_mark_lanes", False)
            )
            if tl.width() != w or tl.height() != h:
                # Mark busy so timeline.resizeEvent does not re-enter layout
                # apply while we are syncing from the parent scroll area.
                # (Overlay chrome still repositions — see TimelineWidget.resizeEvent.)
                tl._layout_heights_busy = True  # noqa: SLF001
                try:
                    tl.resize(w, h)
                    tl._clamp_scroll()  # noqa: SLF001
                finally:
                    tl._layout_heights_busy = False  # noqa: SLF001
                # Belt-and-suspenders: pin overlays even if resize was a no-op
                # for Qt (same size) after a previous partial layout.
                tl._layout_zoom_overlay()  # noqa: SLF001
                tl._layout_video_track_overlay()  # noqa: SLF001
            tl.update()
            # Don't yank the scrollbar while the user is dragging a splitter.
            if not resizing:
                self._ensure_mark_tracks_in_view()
        finally:
            self._syncing_timeline_geometry = False

    def _ensure_mark_tracks_in_view(self) -> None:
        """If Marks were scrolled completely out of view above, pull them back.

        Order is Music → Video → LTC → Marks, so Marks often sit below the fold
        when Video is open — that is intentional (scroll down). Only recover when
        the user has scrolled *past* the mark band.
        """
        scroll = getattr(self, "_timeline_scroll", None)
        if scroll is None:
            return
        bar = scroll.verticalScrollBar()
        if bar is None or bar.maximum() <= 0:
            return
        tl = self.timeline
        marks_top = int(tl._tracks_top_y())  # noqa: SLF001
        marks_bottom = int(tl._tracks_bottom_y())  # noqa: SLF001
        value = int(bar.value())
        # Entire mark band scrolled away above the viewport → jump back.
        if marks_bottom <= value:
            bar.setValue(max(0, marks_top - 8))

    def eventFilter(self, watched, event) -> bool:  # noqa: N802, ANN001
        """Forward Explorer file drops from setlist chrome and the main view."""
        if event is not None and isinstance(event, QKeyEvent):
            if event.type() == QEvent.Type.KeyRelease:
                digit = event.key() - int(Qt.Key.Key_0)
                if 1 <= digit <= 9:
                    self._mark_shortcut_latch.discard(str(digit))
        scroll = getattr(self, "_timeline_scroll", None)
        if scroll is not None and watched is scroll.viewport():
            if event is not None and event.type() == QEvent.Type.Resize:
                self._sync_timeline_geometry()
        panel = getattr(self, "_setlist_panel", None)
        if panel is not None and watched is panel and event is not None:
            if event.type() == QEvent.Type.Resize:
                self._fit_setlist_footer()
        view_stack = getattr(self, "view_stack", None)
        timeline_center = getattr(self, "_timeline_center", None)
        drop_targets = {panel, view_stack, timeline_center}
        if watched in drop_targets and event is not None:
            etype = event.type()
            if etype in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
                if mime_looks_like_file_drop(event.mimeData()):
                    accept_file_drag(event)
                    return True
            elif etype == QEvent.Type.Drop:
                mime = event.mimeData()
                audio_paths = audio_paths_from_mime(mime)
                video_paths = video_paths_from_mime(mime)
                setlist_paths = setlist_import_paths_from_mime(mime)
                if setlist_paths and watched is panel:
                    accept_file_drop(event)
                    self._add_songs_from_media_paths(setlist_paths)
                    return True
                if video_paths and watched in {view_stack, timeline_center}:
                    accept_file_drop(event)
                    drop_at = self.playback.position
                    if watched is timeline_center:
                        local = self.timeline.mapFromGlobal(event.globalPosition().toPoint())
                        drop_at = self.timeline._time_for_x(local.x())  # noqa: SLF001
                    self._add_video_clips_from_paths(video_paths, drop_at)
                    return True
                if audio_paths and watched is view_stack:
                    accept_file_drop(event)
                    self._add_songs_from_media_paths(audio_paths)
                    return True
                if watched is panel:
                    self.status.showMessage(rejected_setlist_drop_reason(mime), 5000)
                else:
                    self.status.showMessage(rejected_file_drop_reason(mime), 5000)
                event.ignore()
                return True
        return super().eventFilter(watched, event)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if not self._confirm_discard_if_dirty():
            event.ignore()
            return
        # Remember visibility before force_close() hides this window.
        was_open = self.clean_output_window.isVisible()
        self.project.clean_video_output.was_open = was_open
        self._settings.setValue(_KEY_CLEAN_OUTPUT_WAS_OPEN, was_open)
        self._save_ui_session()
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        # Clean Output normally only hides on its own X button (so re-opening
        # keeps the OBS capture target valid) — but that must not let it
        # survive the main window closing, or keep the app process alive.
        self._shutdown_secondary_windows()
        remote = getattr(self, "_web_remote", None)
        if remote is not None:
            remote.stop()
        event.accept()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _rebuild_digit_shortcuts(self) -> None:
        for shortcut in self._digit_shortcuts:
            shortcut.setParent(None)
            shortcut.deleteLater()
        self._digit_shortcuts.clear()
        for digit in range(1, 10):
            key = str(digit)
            sc = QShortcut(QKeySequence(key), self)
            sc.setAutoRepeat(False)
            sc.activated.connect(lambda k=key: self._add_mark_by_shortcut(k))
            self._digit_shortcuts.append(sc)

    def _forward_engine_position_to_video(self, engine_seconds: float) -> None:
        """Legacy hook — play path now schedules video inside position fan-out."""
        if self.video_sync.engine_video_gated():
            return
        self.video_sync.update_position(
            self.playback.engine_to_song_time(engine_seconds), source="engine"
        )

    def _on_timeline_scrub_started(self) -> None:
        """Enter SCRUB_PREVIEW before audio scrub pause so Video owns the schedule."""
        was_playing = bool(self.playback.playing)
        self.video_sync.set_scrubbing(True, was_playing=was_playing)
        self.playback.begin_scrub()

    def _on_timeline_scrub_ended(self) -> None:
        """Finalize Video (FINAL_LANDING) before audio resume so engine cannot overwrite land."""
        try:
            from cueplayer.diagnostics import video_sm_trace as sm_trace

            sm_trace.trace(
                "END_SCRUB_CALLED",
                state=self.video_sync.pipeline_state(),
                song_time=float(self.timeline.playhead_seconds()),
                scheduler="mainwindow_scrub_ended",
                extra={
                    "scrub_transaction_id": int(
                        getattr(self.video_sync, "_scrub_transaction_id", 0)
                    ),
                },
            )
        except Exception:
            pass
        self.video_sync.set_scrubbing(False)
        self.playback.end_scrub()

    def _on_video_pipeline_state(self, state: str) -> None:
        """Suspend Video Audio window scheduling during scrub/land/resume."""
        from cueplayer.playback.video_sync import VideoPipelineState

        suspend = state in (
            VideoPipelineState.SCRUB_PREVIEW,
            VideoPipelineState.FINAL_LANDING,
            VideoPipelineState.RESUME_PLAYBACK,
        )
        try:
            self.engine.set_video_audio_schedule_suspended(suspend)
        except Exception:
            pass

    def _on_position_changed(self, engine_seconds: float) -> None:
        # Engine position is Variant Time; Timeline / cues stay on Song Time.
        # Diagnostics only on the Qt position path — never in the audio callback.
        from time import monotonic

        fanout_t0 = monotonic()
        with perf_diag.span("ui.position_fanout"):
            seconds = self.playback.engine_to_song_time(engine_seconds)
            self.playback.sync_from_engine()
            self._perf_note_position_tick(seconds, source="engine")

            # Dense-mark A/B metrics (correlate slow fanout with cue density).
            song = self.current_song
            self._perf_record_mark_density(seconds, song)

            with perf_diag.span("timeline.set_position"):
                self.timeline.set_position(seconds)
            with perf_diag.span("transport.position_sync_ms"):
                self.transport.set_times(seconds, self.engine.duration)
            with perf_diag.span("monitor.position_sync_ms"):
                self.monitor.set_position(seconds, self.engine.duration)
            with perf_diag.span("status.timecode_refresh_ms"):
                self._refresh_output_timecode_clock(seconds)

            # Canonical video schedule (after playhead). Gate while scrub
            # preview or final-land owns the Video pipeline.
            video_ready_waiting = False
            if not self.video_sync.engine_video_gated():
                with perf_diag.span("video.schedule_ms"):
                    self.video_sync.update_position(seconds, source="engine")
                # Frame already decoded but UI thread was busy in fanout?
                if perf_diag.is_enabled():
                    try:
                        waiting = bool(
                            getattr(self.video_sync, "_async_inflight", False) is False
                            and self._sm_trace_worker_waiting(self.video_sync)
                        )
                        video_ready_waiting = waiting
                    except Exception:
                        video_ready_waiting = False
            elif perf_diag.is_enabled():
                from cueplayer.diagnostics import video_sm_trace as sm_trace

                # Count gated ticks; sample one breadcrumb per land window.
                perf_diag.count("video.sm.engine_fanout_gated")
                if sm_trace.gap_ms_since_land_present() is None:
                    sm_trace.trace(
                        "DISCARD",
                        state=self.video_sync.pipeline_state(),
                        song_time=float(seconds),
                        scheduler="mainwindow_position_fanout",
                        kind="play",
                        reason="engine_video_gated",
                        inflight=bool(self.video_sync._async_inflight),
                    )

            if perf_diag.is_enabled():
                from cueplayer.diagnostics import video_sm_trace as sm_trace

                remote = getattr(self, "_web_remote", None)
                if remote is not None and getattr(remote, "running", False):
                    with perf_diag.span("remote.position_sync_ms"):
                        # Remote polls on its own timer — do not push full mark
                        # lists here. Span exists so A/B can prove absence of work.
                        perf_diag.count("remote.position_fanout.noop")

                fanout_ms = (monotonic() - fanout_t0) * 1000.0
                perf_diag.record_ms("ui.position_fanout.total_ms", fanout_ms)
                # Correlate slow samples (> one frame budget) with mark density.
                if fanout_ms >= 16.7:
                    perf_diag.count("ui.position_fanout.slow_samples")
                    perf_diag.note("ui.position_fanout.slow_song_time", float(seconds))
                    if song is not None:
                        perf_diag.note(
                            "ui.position_fanout.slow_marks_near",
                            song.mark_count_in_window(seconds, 0.5),
                        )
                    perf_diag.note(
                        "ui.position_fanout.slow_video_ready_waiting",
                        video_ready_waiting,
                    )
                    perf_diag.note(
                        "ui.position_fanout.slow_worker_runtime",
                        sm_trace.worker_runtime(),
                    )

            # Overview syncs via timeline.view_changed (set_position) — do not
            # call _sync_timeline_overview again here (~60 Hz double work).
            perf_diag.count("ui.position_fanout.calls")

    def _perf_note_position_tick(self, seconds: float, *, source: str) -> None:
        """Prove the UI position path is alive (dump-time live check).

        Must stay O(1): notes + one bounded ``record_ms``. Never call
        ``perf.snapshot()`` here — aggregating all samples on every tick was a
        multi-second cProfile hotspot with CUEPLAYER_PERF enabled.
        """
        if not perf_diag.is_enabled():
            return
        now = time.monotonic()
        perf_diag.note("perf.position_tick_source", source)
        perf_diag.note("perf.position_tick_song_time", float(seconds))
        perf_diag.note("perf.position_tick_mono", now)
        # Reset baseline across PERF session / song-activate clears so a quiet
        # gap cannot produce multi-million-ms fake max intervals.
        session = perf_diag.get_attr("perf.session_id")
        if getattr(self, "_perf_session_id", None) != session:
            self._perf_session_id = session
            self._perf_tick_mono = None
        prev = getattr(self, "_perf_tick_mono", None)
        if prev is not None:
            delta_ms = (now - float(prev)) * 1000.0
            # Reject cross-reset / idle gaps (not a real tick interval).
            if 0.0 < delta_ms < 5000.0:
                perf_diag.record_ms("perf.position_tick_interval_ms", delta_ms)
        self._perf_tick_mono = now

    def _perf_record_mark_density(self, seconds: float, song) -> None:  # noqa: ANN001
        if song is None or not perf_diag.is_enabled():
            return
        with perf_diag.span("mark.lookup_ms"):
            total = len(song.marks)
            near = song.mark_count_in_window(seconds, 0.5)
            # ±0.5 s window ≈ "current second" for ~10 cues/s stress zones.
            per_sec = near
            perf_diag.note("mark.total_count", total)
            perf_diag.note("mark.count_in_current_second", per_sec)
            perf_diag.note("mark.count_near_playhead", near)
            prev = getattr(self, "_fanout_prev_seconds", None)
            if prev is not None:
                lo, hi = sorted((float(prev), float(seconds)))
                crossed = len(song.mark_slice_in_time_range(lo, hi))
                perf_diag.note("mark.crossings_per_position_update", crossed)
                perf_diag.count("mark.crossings_total", crossed)
            self._fanout_prev_seconds = float(seconds)
            try:
                zoom = float(self.timeline.pixels_per_second())
            except Exception:
                zoom = -1.0
            perf_diag.note("timeline.zoom_pps", zoom)

    @staticmethod
    def _sm_trace_worker_waiting(video_sync) -> bool:  # noqa: ANN001
        """True when a decoded frame may be waiting on the UI thread."""
        try:
            from cueplayer.diagnostics import video_sm_trace as sm_trace

            return sm_trace.worker_runtime() in (
                sm_trace.WorkerRuntime.WAITING_FRAME,
                sm_trace.WorkerRuntime.PRESENTING,
            )
        except Exception:
            return False

    def _on_scrub_preview(self, seconds: float) -> None:
        """Update transport + cue list while dragging the timeline playhead.

        Must share Dense Mark / fan-out instrumentation with the engine play
        path. Scrub previously bypassed ``ui.position_fanout`` entirely, so
        seek/scrub-heavy Windows sessions dumped empty A/B sections while
        ``video.seek.*`` attrs still looked live.
        """
        from time import monotonic

        fanout_t0 = monotonic()
        with perf_diag.span("ui.position_fanout"):
            with perf_diag.span("ui.scrub_fanout"):
                self._perf_note_position_tick(seconds, source="scrub")
                song = self.current_song
                self._perf_record_mark_density(seconds, song)
                # Timeline already moved the playhead locally; still time the
                # chrome that Dense Mark A/B needs (NOW / Cue List / clock).
                with perf_diag.span("transport.position_sync_ms"):
                    self.transport.set_times(seconds, self.engine.duration)
                with perf_diag.span("monitor.position_sync_ms"):
                    self.monitor.set_position(seconds, self.engine.duration)
                with perf_diag.span("status.timecode_refresh_ms"):
                    self._refresh_output_timecode_clock(seconds)
                # Overview is updated via throttled timeline.view_changed during
                # scrub — do not sync it on every preview tick.
            if perf_diag.is_enabled():
                fanout_ms = (monotonic() - fanout_t0) * 1000.0
                perf_diag.record_ms("ui.position_fanout.total_ms", fanout_ms)
                perf_diag.record_ms("ui.scrub_fanout.total_ms", fanout_ms)
                if fanout_ms >= 16.7:
                    perf_diag.count("ui.position_fanout.slow_samples")
                    perf_diag.note("ui.position_fanout.slow_song_time", float(seconds))
                    if song is not None:
                        perf_diag.note(
                            "ui.position_fanout.slow_marks_near",
                            song.mark_count_in_window(seconds, 0.5),
                        )
            perf_diag.count("ui.position_fanout.calls")
            perf_diag.count("ui.scrub_fanout.calls")

    def _open_align_anchors(self) -> None:
        """Tools → Align Anchors… — draft, preview session, Apply via undo."""
        dialog = AlignAnchorsDialog(
            self.current_song,
            self,
            get_song_playhead=lambda: float(self.playback.position),
            get_media_playhead=lambda: float(self.engine.position),
            begin_preview=self.playback.begin_anchor_preview,
            end_preview=self.playback.end_anchor_preview,
            is_preview_active=lambda: bool(self.playback.anchor_preview_active),
        )
        dialog.offset_committed.connect(self._on_align_anchors_committed)
        dialog.exec()
        # Safety: preview must not survive dialog close.
        if self.playback.anchor_preview_active:
            self.playback.end_anchor_preview(restore_entry=True)

    def _open_ma_preflight(self) -> None:
        """Tools → MA Preflight… — build report outside the dialog, show read-only UI."""
        report = build_preflight_report_for_project(self.project)
        dialog = MaPreflightDialog(report, self)
        dialog.navigate_requested.connect(self._on_preflight_navigate)
        dialog.exec()

    def _write_performance_report(self) -> None:
        """Tools → Write Performance Report… (only when CUEPLAYER_PERF enabled)."""
        if not perf_diag.is_enabled():
            self.status.showMessage("Set CUEPLAYER_PERF=1 before launch to enable", 4000)
            return
        try:
            self.engine.publish_audio_continuity_to_perf()
        except Exception:
            pass
        snap = perf_diag.snapshot()
        counters = snap.get("counters") or {}
        fanout_calls = int(counters.get("ui.position_fanout.calls", 0))
        scrub_calls = int(counters.get("ui.scrub_fanout.calls", 0))
        path = perf_diag.flush_report(label="manual-dump")
        if path is None:
            self.status.showMessage("Could not write performance log", 4000)
            return
        self.status.showMessage(f"Performance report → {path}", 8000)
        try:
            from PySide6.QtWidgets import QMessageBox

            mode = self.video_sync.pipeline_mode()
            attrs = snap.get("attrs") or {}
            live_src = attrs.get("perf.position_tick_source", "(none)")
            live_t = attrs.get("perf.position_tick_song_time", "(none)")
            valid = fanout_calls > 0 or scrub_calls > 0
            warning = ""
            if not valid:
                warning = (
                    "\n\n⚠ INVALID A/B DUMP: ui.position_fanout.calls=0 and "
                    "ui.scrub_fanout.calls=0.\n"
                    "Play or scrub for several seconds FIRST, then dump again.\n"
                    "Do not use session-start / after-activate sections for Dense Mark."
                )
            QMessageBox.information(
                self,
                "Performance Report",
                f"Appended report to:\n\n{path}\n\n"
                f"video.pipeline_mode = {mode}\n"
                f"ui.position_fanout.calls = {fanout_calls}\n"
                f"ui.scrub_fanout.calls = {scrub_calls}\n"
                f"last tick source = {live_src} @ song_t={live_t}\n"
                f"{'LIVE CHECK: OK' if valid else 'LIVE CHECK: FAILED'}"
                f"{warning}\n\n"
                "Open that file in Notepad. Use ONLY the last ===== manual-dump "
                "section. Dense Mark spans must show n>0 — if all (none), the "
                "dump is invalid.",
            )
        except Exception:  # noqa: BLE001
            pass

    def _profile_ui_5s(self) -> None:
        """Tools → Profile UI 5s — stdlib cProfile of the Qt event loop."""
        if getattr(self, "_ui_profile_active", False):
            self.status.showMessage("UI profile already running", 3000)
            return
        import cProfile
        import pstats
        from io import StringIO

        self._ui_profile_active = True
        profiler = cProfile.Profile()
        profiler.enable()
        self.status.showMessage(
            "Profiling UI thread for 5s — play/scrub sparse then dense now…", 5000
        )

        def _finish() -> None:
            profiler.disable()
            self._ui_profile_active = False
            stream = StringIO()
            stats = pstats.Stats(profiler, stream=stream)
            stats.sort_stats("cumulative")
            stats.print_stats(40)
            text = stream.getvalue()
            path = perf_diag.log_path().with_name("cueplayer_ui_profile.txt")
            try:
                path.write_text(text, encoding="utf-8")
            except Exception:  # noqa: BLE001
                path = Path(tempfile.gettempdir()) / "cueplayer_ui_profile.txt"
                path.write_text(text, encoding="utf-8")
            if perf_diag.is_enabled():
                perf_diag.note("perf.ui_profile_path", str(path))
                perf_diag.flush_report(label="ui-profile-5s")
            self.status.showMessage(f"UI profile → {path}", 8000)
            try:
                from PySide6.QtWidgets import QMessageBox

                QMessageBox.information(
                    self,
                    "UI Profile (5s)",
                    f"Wrote cProfile cumulative top-40 to:\n\n{path}\n\n"
                    "Compare sparse vs dense by running this twice.",
                )
            except Exception:  # noqa: BLE001
                pass

        QTimer.singleShot(5000, _finish)

    def _on_preflight_navigate(
        self, song_id: str, object_kind: str, object_id: str
    ) -> None:
        """Activate Song (and optionally select/seek a mark) from Preflight double-click."""
        song_id = str(song_id or "").strip()
        if not song_id:
            self.status.showMessage("Preflight: no Song to navigate to", 2000)
            return
        index = next(
            (i for i, s in enumerate(self.project.songs) if s.id == song_id),
            None,
        )
        if index is None:
            self.status.showMessage("Preflight: Song not found in setlist", 2500)
            return
        self._activate_song(index, stop_playback=False)
        kind = str(object_kind or "").strip().lower()
        oid = str(object_id or "").strip()
        if kind == "mark" and oid:
            mark = self.current_song.mark_by_id(oid)
            if mark is not None:
                self.timeline.set_selected_mark_ids([oid])
                self.monitor.set_selected_mark_ids([oid])
                self.playback.seek(float(mark.time_seconds))
                self.timeline.set_position(float(mark.time_seconds))
                self.status.showMessage(
                    f"Preflight → {self.current_song.name} · mark", 2500
                )
                return
        self.status.showMessage(f"Preflight → {self.current_song.name}", 2000)

    def _on_align_anchors_committed(self, command: SetVariantAnchorOffsetCommand) -> None:
        """Undo stack + dirty after Align Anchors Apply (command already applied)."""
        self._push_song_undo(command)
        self._mark_dirty()
        self.status.showMessage("Anchor offset applied", 2500)

    def _open_mark_manager(self) -> None:
        dialog = MarkManagerDialog(self.current_song, self, project=self.project)
        dialog.preview_changed.connect(self.timeline.update)
        dialog.preview_changed.connect(lambda: self.monitor.set_song(self.current_song))
        dialog.project_defaults_changed.connect(self._on_mark_template_applied)
        if dialog.exec():
            self._undo.clear()
            self._mark_dirty()
            self.timeline.set_song(self.current_song)
            self._apply_project_mark_line_settings()
            self.monitor.set_song(self.current_song)
            self._rebuild_digit_shortcuts()
            self._refresh_status()
            self.status.showMessage("Mark Manager updated", 2500)
        else:
            self.timeline.set_song(self.current_song)
            self._apply_project_mark_line_settings()
            self.timeline.update()

    def _on_mark_template_applied(self) -> None:
        """Template load / project default changed while Manager is open."""
        self._undo.clear()
        self._mark_dirty()
        self.timeline.set_song(self.current_song)
        self._apply_project_mark_line_settings()
        self.monitor.set_song(self.current_song)
        self._rebuild_digit_shortcuts()
        self.timeline.update()

    def _on_timeline_seek_requested(self, seconds: float) -> None:
        source = "timeline"
        try:
            source = self.timeline.consume_seek_input_source()
        except Exception:
            source = "timeline"
        self._canonical_seek(float(seconds), input_source=source)

    def _canonical_seek(self, seconds: float, *, input_source: str) -> None:
        """Single seek endpoint for Mark / cue / overview / empty-timeline jumps.

        Timeline scrub still owns FINAL_LAND via scrub_ended; this path covers
        position-changing clicks that previously called ``playback.seek`` only.
        """
        try:
            from_t = float(self.playback.engine_to_song_time(self.engine.position))
        except Exception:
            from_t = float(seconds)
        try:
            self.video_sync.note_discontinuous_seek(
                float(seconds),
                from_seconds=from_t,
                input_source=str(input_source),
                playing=bool(self.playback.playing),
            )
        except Exception:
            pass
        self.playback.seek(float(seconds))

    def _seek_from_cue_list(self, seconds: float) -> None:
        self._canonical_seek(float(seconds), input_source="cue_list")
        self.timeline.set_position(seconds)
        self.status.showMessage(f"Jumped to Cue @ {seconds:.3f}s", 1500)

    def _on_timeline_selection(self, mark_ids: list) -> None:
        if self._syncing_selection:
            return
        self._syncing_selection = True
        self.monitor.set_selected_mark_ids(mark_ids)
        self._syncing_selection = False

    def _on_monitor_selection(self, mark_ids: list) -> None:
        if self._syncing_selection:
            return
        self._syncing_selection = True
        self.timeline.set_selected_mark_ids(mark_ids, emit=False)
        self._syncing_selection = False

    # Gap (seconds) since the last repeat activation above which a Left/Right
    # arrow-key activation is treated as a brand-new tap rather than a
    # continuation of a held key. Sized to comfortably exceed typical OS
    # keyboard "repeat delay" settings (commonly ~0.25–1.0 s) so that the
    # very first key-repeat after the initial OS delay is still recognized
    # as part of the same hold.
    _NUDGE_HOLD_GAP_SECONDS = 1.0

    def _nudge_frames(self, direction: int) -> None:
        """Seek the playhead by one video frame, accelerating while held.

        `direction` is -1 (Left) or +1 (Right). Qt's own key-repeat delivers
        one `activated()` call per OS repeat tick while the arrow key is
        held, so we infer hold duration from the gap between successive
        calls: a short gap continues the current hold (and the step size
        ramps up via `hold_step_frames`); a long gap starts a fresh hold at
        exactly one frame.
        """
        now = time.monotonic()
        last = self._nudge_last_time.get(direction, 0.0)
        start = self._nudge_hold_start.get(direction)
        if start is None or (now - last) > self._NUDGE_HOLD_GAP_SECONDS:
            start = now
        self._nudge_hold_start[direction] = start
        self._nudge_last_time[direction] = now

        fps = self.current_song.fps if self.current_song and self.current_song.fps > 0 else 30.0
        frames = hold_step_frames(now - start)
        self.playback.nudge(direction * frames / fps)

    def _delete_current_selection(self) -> None:
        if _text_input_has_focus():
            return
        if _song_list_has_keyboard_focus(self.song_list):
            self._delete_song()
            return
        clip_ids = self.timeline.selected_video_clip_ids()
        if clip_ids:
            self._delete_video_clips(clip_ids)
            return
        ids = self.timeline.selected_mark_ids() or self.monitor.selected_mark_ids()
        if ids:
            self._delete_marks(ids)

    def _on_marks_changed(self) -> None:
        self.timeline.bump_mark_backdrop_revision(reason="marks_changed")
        self.timeline.update()
        self._schedule_cue_list_refresh()
        self._refresh_status()

    def _schedule_cue_list_refresh(self) -> None:
        self._cue_list_refresh_timer.start()

    def _flush_cue_list_refresh(self) -> None:
        self.monitor.refresh_list()
        self.monitor.set_position(self.playback.position, self.engine.duration)

    def _refresh_marks_ui(self) -> None:
        # Marks are baked into the play/scrub backdrop — invalidate once.
        self.timeline.bump_mark_backdrop_revision(reason="marks_ui_refresh")
        self.timeline.update()
        self._schedule_cue_list_refresh()
        self._refresh_status()

    def _on_marks_moved(self, moved: object) -> None:
        if not isinstance(moved, dict) or not moved:
            return
        from cueplayer.domain.main_cue_id import refresh_main_cue_ids

        self._push_song_undo(MoveMarksCommand(times=dict(moved)))
        refresh_main_cue_ids(self.current_song, mark_ids=set(moved.keys()))
        self._mark_dirty()
        self._refresh_marks_ui()

    def _offset_marks(self, mark_ids: list, delta: float) -> None:
        if not mark_ids or abs(delta) < 1e-9:
            return
        duration = self.current_song.duration_seconds
        moved: dict[str, tuple[float, float]] = {}
        for mark_id in mark_ids:
            mark = self.current_song.mark_by_id(str(mark_id))
            if mark is None:
                continue
            lane = self.current_song.lane_by_index(mark.lane_index)
            if lane is not None and lane.locked:
                continue
            old_t = mark.time_seconds
            new_t = min(max(0.0, old_t + float(delta)), duration)
            if abs(new_t - old_t) < 1e-9:
                continue
            mark.time_seconds = new_t
            moved[mark.id] = (old_t, new_t)
        if not moved:
            return
        self.current_song.sort_marks()
        from cueplayer.domain.main_cue_id import refresh_main_cue_ids

        refresh_main_cue_ids(self.current_song, mark_ids=set(moved.keys()))
        self._push_song_undo(MoveMarksCommand(times=moved, label="Offset Mark"))
        self._mark_dirty()
        self._refresh_marks_ui()
        self.status.showMessage(f"Offset {len(moved)} mark(s) by {delta:+.3f}s", 2500)

    def _on_note_changed(self, mark_id: str, old_name: str, new_name: str) -> None:
        self._push_song_undo(RenameMarkCommand(mark_id=mark_id, old_name=old_name, new_name=new_name))
        self._mark_dirty()
        self._refresh_marks_ui()

    def _on_cue_id_changed(self, mark_id: str, old_id: str, new_id: str) -> None:
        self._push_song_undo(
            EditMainCueIdCommand(mark_id=mark_id, old_id=old_id, new_id=new_id)
        )
        self._mark_dirty()
        self._refresh_marks_ui()

    def _undo_action(self) -> None:
        result = self._undo.undo(self._undo_ctx)
        if result is None:
            self.status.showMessage("Nothing to undo", 1500)
            return
        label, setlist_cmd, song_id = result
        if setlist_cmd is not None:
            self._sync_after_setlist_undo_redo(setlist_cmd)
        else:
            self._focus_song_for_undo(song_id)
            self.timeline.clear_selection(emit=False)
            self.monitor.set_selected_mark_ids([])
            self.video_sync.refresh()
            self.engine.refresh_video_clips()
            self._refresh_marks_ui()
        self._mark_dirty()
        self.status.showMessage(f"Undone: {label}", 2000)

    def _redo_action(self) -> None:
        result = self._undo.redo(self._undo_ctx)
        if result is None:
            self.status.showMessage("Nothing to redo", 1500)
            return
        label, setlist_cmd, song_id = result
        if setlist_cmd is not None:
            self._sync_after_setlist_undo_redo(setlist_cmd)
        else:
            self._focus_song_for_undo(song_id)
            self.timeline.clear_selection(emit=False)
            self.monitor.set_selected_mark_ids([])
            self.video_sync.refresh()
            self.engine.refresh_video_clips()
            self._refresh_marks_ui()
        self._mark_dirty()
        self.status.showMessage(f"Redone: {label}", 2000)

    def _renumber_main_cue_ids(self, lane_index: int | None = None) -> None:
        from cueplayer.domain.main_cue_id import (
            capture_main_cue_ids,
            renumber_main_cue_ids_sequential,
            renumberable_cue_list_lanes,
        )

        lanes = renumberable_cue_list_lanes(self.current_song)
        if not lanes:
            self.status.showMessage("No Cue List Main marks to renumber", 2500)
            return
        if lane_index is not None:
            lane = self.current_song.lane_by_index(lane_index)
            allowed = {item.index for item in lanes}
            if lane is None or lane_index not in allowed:
                self.status.showMessage("That mark type is not in the Cue List", 2500)
                return
            scope = {lane_index}
            scope_label = lane.name
        else:
            scope = None
            scope_label = "all Cue List types"
        before = capture_main_cue_ids(self.current_song, lane_indices=scope)
        if not before:
            self.status.showMessage("No Main cues to renumber", 2500)
            return
        answer = QMessageBox.question(
            self,
            "Renumber Cue IDs",
            f'Renumber Cue IDs for {scope_label} to 1, 2, 3… in time order?\n'
            f"({len(before)} cue(s) — existing Cue IDs will be overwritten.)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        after = renumber_main_cue_ids_sequential(self.current_song, lane_indices=scope)
        if before == after:
            self.status.showMessage("Cue IDs already 1, 2, 3…", 2000)
            return
        self._push_song_undo(RenumberMainCueIdsCommand(before=before, after=after))
        self._mark_dirty()
        self._refresh_marks_ui()
        self.status.showMessage(f"Renumbered {scope_label} to 1, 2, 3…", 2500)

    def _delete_marks(self, mark_ids: list) -> None:
        if not mark_ids:
            return
        wanted = set(mark_ids)
        snapshots = [
            MarkSnapshot.from_mark(m) for m in self.current_song.marks if m.id in wanted
        ]
        removed = self.current_song.remove_marks_by_ids(mark_ids)
        if removed <= 0:
            return
        self._push_song_undo(DeleteMarksCommand(marks=snapshots))
        self._mark_dirty()
        self.timeline.clear_selection(emit=False)
        self.monitor.set_selected_mark_ids([])
        self._refresh_marks_ui()
        self.status.showMessage(f"Deleted {removed} cue(s)", 2500)

    def _change_mark_types(self, mark_ids: list, lane_index: int) -> None:
        """Move selected marks onto another Mark Manager type (lane)."""
        if not mark_ids:
            return
        lane = self.current_song.lane_by_index(int(lane_index))
        if lane is None:
            return
        from cueplayer.domain.main_cue_id import assign_main_cue_id_for_mark

        changes: dict[str, tuple[int, int, str, str]] = {}
        for mark_id in mark_ids:
            mark = self.current_song.mark_by_id(str(mark_id))
            if mark is None or mark.lane_index == lane.index:
                continue
            old_lane = int(mark.lane_index)
            old_cue = str(mark.main_cue_id)
            mark.lane_index = int(lane.index)
            if self.current_song.lane_has_cue_id(lane.index):
                assign_main_cue_id_for_mark(self.current_song, mark, force=True)
            else:
                mark.main_cue_id = ""
            changes[mark.id] = (old_lane, int(lane.index), old_cue, str(mark.main_cue_id))
        if not changes:
            return
        self.current_song.sort_marks()
        self._push_song_undo(ChangeMarkLanesCommand(changes=changes))
        self._mark_dirty()
        self._refresh_marks_ui()
        label = lane.name
        self.status.showMessage(
            f"Moved {len(changes)} mark(s) to {label}",
            2500,
        )

    def _sync_loop_ui(self) -> None:
        self.transport.set_loop_status(
            self.playback.loop_a,
            self.playback.loop_b,
            enabled=self.playback.loop_enabled,
        )
        self.timeline.set_loop_region(
            self.playback.loop_a,
            self.playback.loop_b,
            enabled=self.playback.loop_enabled,
        )

    def _on_loop_region_dragged(self, a: object, b: object) -> None:
        self.playback.set_loop_region(
            float(a) if a is not None else None,
            float(b) if b is not None else None,
        )
        self.transport.set_loop_status(
            self.playback.loop_a,
            self.playback.loop_b,
            enabled=self.playback.loop_enabled,
        )

    def _set_loop_a(self) -> None:
        """Mark A at the visible playhead.

        If A+B already form a complete loop, tapping A again starts a *new*
        loop (clears B) instead of stretching the old pair to the new point.
        """
        t = float(self.timeline.playhead_seconds())
        a = self.playback.set_loop_a_at(t)
        self._sync_loop_ui()
        self.status.showMessage(f"A = {a:.3f}s", 2000)

    def _set_loop_b(self) -> None:
        """Mark B at the visible playhead (same fresh-pair rule as A)."""
        t = float(self.timeline.playhead_seconds())
        b = self.playback.set_loop_b_at(t)
        self._sync_loop_ui()
        self.status.showMessage(f"B = {b:.3f}s", 2000)

    def _clear_loop(self) -> None:
        self.playback.clear_loop()
        self._sync_loop_ui()
        self.status.showMessage("Cleared A-B", 2000)

    def _set_loop_enabled(self, enabled: bool) -> None:
        reason = self.playback.try_set_loop_enabled(enabled)
        if reason is not None:
            self.transport.set_loop_status(
                self.playback.loop_a,
                self.playback.loop_b,
                enabled=False,
            )
            self.status.showMessage(reason, 2500)
            return
        self._sync_loop_ui()

    def _set_music_muted_from_ui(self, muted: bool) -> None:
        """Transport mute chip — same engine flag as Web Remote Mute PC."""
        self.playback.set_music_muted(bool(muted))
        self.status.showMessage(
            "PC music muted (LTC stays)" if muted else "PC music unmuted",
            2500,
        )

    def _set_view_mode(self, mode: str) -> None:
        if mode == "ma_patch":
            self.show_patch_page.set_project(self.project)
            self.view_stack.setCurrentIndex(1)
            self.status.showMessage("Export: Sequence chain and Fader mapping", 2500)
        elif mode == "setlist":
            self.setlist_sheet_page.set_project(self.project)
            self.view_stack.setCurrentIndex(2)
            self.status.showMessage(
                "Set List Sheet: Copy order / names / Timecode / notes for MA3",
                2500,
            )
        else:
            self.view_stack.setCurrentIndex(0)

    def _open_ma_patch_page(self) -> None:
        self.toolbar.set_view_mode("ma_patch")
        self._set_view_mode("ma_patch")

    def _open_setlist_sheet_page(self) -> None:
        self.toolbar.set_view_mode("setlist")
        self._set_view_mode("setlist")

    def _on_setlist_sheet_changed(self) -> None:
        self._mark_dirty()
        self._refresh_status()
        indexes = self._selected_song_indexes() or None
        self._rebuild_song_list(select_indexes=indexes)
        patch = getattr(self, "show_patch_page", None)
        if patch is not None:
            patch.sync_songs()
        if self.current_song is not None:
            self.timeline.update()

    def _on_ma_export_finished(self, paths: object) -> None:
        if isinstance(paths, dict) and paths:
            first = next(iter(paths.values()))
            self.status.showMessage(
                f"Exported {len(paths)} file(s) → {first.parent}",
                5000,
            )

    def _apply_project_mark_line_settings(self) -> None:
        """Push project-global mark lines + waveform color onto the timeline."""
        p = self.project
        self.timeline.apply_mark_line_settings(
            style=str(p.mark_line_style or "solid"),
            width=float(p.mark_line_width),
            dash_on=float(p.mark_dash_on),
            dash_off=float(p.mark_dash_off),
            waveform_color=str(p.waveform_color or "#616161"),
            playhead_color=str(getattr(p, "playhead_color", None) or "#3dd68c"),
            wave_label_font_px=int(getattr(p, "wave_label_font_px", 10) or 10),
        )
        self.timeline.apply_mark_lane_height(float(getattr(p, "mark_lane_height", 28.0)))
        self.timeline.apply_mark_track_colors(bool(getattr(p, "show_mark_track_colors", True)))
        self.timeline.set_show_wave_gain_line(bool(getattr(p, "show_wave_gain_line", False)), emit=False)
        self.timeline.set_show_ltc_gain_line(bool(getattr(p, "show_ltc_gain_line", False)), emit=False)
        if hasattr(self, "monitor"):
            self._sync_output_timecode_clock_ui()

    def _sync_output_timecode_clock_ui(self) -> None:
        p = self.project
        self.monitor.configure_output_timecode_clock(
            visible=bool(getattr(p, "show_output_timecode_clock", True)),
            color=str(getattr(p, "output_timecode_clock_color", None) or "#3dd68c"),
        )
        self.monitor.configure_output_quick_toggles(
            visible=bool(getattr(p, "show_output_quick_toggles", True)),
        )
        self.monitor.sync_output_quick_toggles(self.project.audio_output)

    @staticmethod
    def _midi_features_active(ao) -> bool:  # noqa: ANN001
        return bool(
            ao.mtc_enabled
            or ao.midi_cue_notes_enabled
            or getattr(ao, "ltc_to_mtc_translate", False)
        )

    def _on_output_quick_toggle(self, key: str, enabled: bool) -> None:
        ao = self.project.audio_output
        if key == "translate":
            ao.ltc_to_mtc_translate = enabled
        elif key == "mtc":
            ao.mtc_enabled = enabled
        elif key == "ltc":
            ao.ltc_enabled = enabled
        elif key == "note":
            ao.midi_cue_notes_enabled = enabled
        else:
            return

        if enabled and key in ("translate", "mtc", "note"):
            ao.midi_enabled = True
        elif not self._midi_features_active(ao):
            ao.midi_enabled = False

        if ao.midi_enabled and not ao.midi_port_name:
            QMessageBox.warning(
                self,
                "MIDI",
                "Choose a MIDI output port in Audio / Midi / Timecode settings first.",
            )
            self.monitor.sync_output_quick_toggles(self.project.audio_output)
            return

        warning = self.engine.apply_audio_settings(ao)
        self._refresh_timecode_status()
        self._refresh_output_timecode_clock()
        self.monitor.sync_output_quick_toggles(ao)
        self.settings.save_audio_output(ao)
        self._mark_dirty()
        if warning:
            self.status.showMessage(warning, 5000)

    def _on_output_quick_toggles_visibility_changed(self) -> None:
        self.project.show_output_quick_toggles = self.monitor.show_output_quick_toggles
        self._mark_dirty()

    def _refresh_output_timecode_clock(self, position: float | None = None) -> None:
        state = self.engine.output_timecode_state(position)
        self.monitor.set_output_timecode(
            timecode=state.timecode,
            outputs=state.outputs,
            sending=state.sending,
        )

    def _on_output_timecode_clock_changed(self) -> None:
        self.project.show_output_timecode_clock = self.monitor.show_output_timecode_clock
        self._mark_dirty()

    def _open_display_settings(self) -> None:
        latency_ms = int(round(self.engine.sync_offset_ms()))
        dialog = MarkDisplayDialog(
            self.current_song,
            project=self.project,
            latency_ms=latency_ms,
            parent=self,
        )

        def _apply_live() -> None:
            self.engine.set_sync_offset_ms(dialog.latency_ms())
            self.timeline.apply_song_display_settings()
            self._apply_project_mark_line_settings()
            self.monitor.apply_now_display_settings()
            self._refresh_output_timecode_clock()

        def _run_calib() -> None:
            from cueplayer.ui.sync_calib_dialog import SyncCalibrationDialog

            calib = SyncCalibrationDialog(self.engine, parent=dialog)
            if calib.exec():
                dialog.set_latency_ms(int(round(calib.result_offset_ms())))
                self.status.showMessage(
                    f"Sync calibration complete: offset {self.engine.sync_offset_ms():.0f} ms",
                    4000,
                )

        dialog.settings_changed.connect(_apply_live)
        dialog.settings_changed.connect(lambda: self._mark_dirty())
        dialog.calibrate_requested.connect(_run_calib)
        dialog.exec()
        _apply_live()

    def _open_web_remote(self) -> None:
        dialog = WebRemoteDialog(
            self._web_remote.prefs,
            running=self._web_remote.running,
            parent=self,
        )
        if not dialog.exec():
            return
        result = dialog.result_prefs()
        save_web_remote_prefs(result)
        err = self._web_remote.apply_prefs(result, restart=True)
        if err:
            QMessageBox.warning(self, "Web Remote", f"Could not start server:\n{err}")
            self.status.showMessage(f"Web Remote failed: {err}", 6000)
            return
        if result.enabled:
            from cueplayer.web_remote.bridge import lan_urls

            urls = lan_urls(result.normalized_port())
            tip = urls[-1] if urls else f"http://127.0.0.1:{result.normalized_port()}/"
            self.status.showMessage(f"Web Remote on — open {tip} on iPad Safari", 8000)
        else:
            self.status.showMessage("Web Remote off", 3000)

    def _open_audio_timecode(self) -> None:
        dialog = AudioTimecodeDialog(self.project.audio_output, parent=self)
        if not dialog.exec():
            return
        settings = dialog.result_settings()
        self.project.audio_output = settings
        self.settings.save_audio_output(settings)
        warning = self.engine.apply_audio_settings(settings)
        self._refresh_timecode_status()
        self._refresh_output_timecode_clock()
        self.monitor.sync_output_quick_toggles(settings)
        self._mark_dirty()
        if warning:
            # Virtual MIDI ports (e.g. Bome) sometimes need a moment after the
            # previous handle is closed before accepting a new connection.
            delays_ms = (400, 900, 1800, 3000)

            def _retry_mtc(attempt: int = 0) -> None:
                retry_warn = self.engine.apply_audio_settings(self.project.audio_output)
                self._refresh_timecode_status()
                self._refresh_output_timecode_clock()
                if not retry_warn:
                    self.status.showMessage("Audio routing updated (MIDI reconnected)", 3500)
                    return
                if attempt < len(delays_ms):
                    self.status.showMessage(
                        f"MIDI: retrying ({attempt + 1}/{len(delays_ms)})…",
                        4000,
                    )
                    QTimer.singleShot(
                        delays_ms[attempt],
                        lambda a=attempt + 1: _retry_mtc(a),
                    )
                    return
                QMessageBox.warning(self, "Audio / Midi / Timecode", retry_warn)
                self.status.showMessage(retry_warn, 6000)

            self.status.showMessage(f"MIDI: retrying… ({warning})", 3000)
            QTimer.singleShot(delays_ms[0], lambda: _retry_mtc(0))
        else:
            parts = []
            if settings.ltc_enabled:
                parts.append("LTC on")
            if settings.midi_enabled:
                parts.append("MIDI on")
                if settings.mtc_enabled:
                    parts.append("MTC")
                if settings.ltc_to_mtc_translate:
                    parts.append("Translate")
                if settings.midi_cue_notes_enabled:
                    parts.append("Notes")
            msg = "Audio routing updated"
            if parts:
                msg += " · " + ", ".join(parts)
            self.status.showMessage(msg, 3500)

    def _refresh_timecode_status(self) -> None:
        self.transport.set_timecode_status(
            ltc=self.engine.ltc_enabled,
            mtc=self.engine.mtc_enabled,
        )

    def _open_audio(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Audio",
            "",
            "Audio (*.wav *.flac *.ogg *.mp3 *.aiff *.aif);;All Files (*.*)",
        )
        if path:
            self._load_audio_path(Path(path))

    def _load_audio_path(
        self,
        path: Path,
        *,
        mark_dirty: bool = True,
        replace_track: bool = True,
        bump_token: bool = True,
        keep_waveform: bool = False,
    ) -> None:
        path = Path(path)
        cached = self._cached_audio_buffer(path)
        if cached is not None:
            self.timeline.set_audio_loading(False)
            if replace_track or self._audio_path_matches_current_song(path, replace_track=False):
                self._apply_loaded_audio(
                    cached,
                    path,
                    mark_dirty=mark_dirty,
                    replace_track=replace_track,
                    refresh_song_widgets=replace_track,
                )
            return

        if bump_token:
            self._audio_load_token += 1
        token = self._audio_load_token
        self._apply_probed_audio_duration(path, song=self.current_song)
        if not keep_waveform:
            peaks = load_cached_waveform_peaks(path)
            if peaks is not None:
                self.timeline.set_audio_loading(False)
                self.timeline.set_audio(peaks, reset_view=replace_track)
                keep_waveform = True
            else:
                self.timeline.set_audio_loading(True, path.name)
        if not self._media_warm_active and not keep_waveform:
            self.status.showMessage(f"Loading {path.name}…", 0)
        elif not self._media_warm_active and keep_waveform:
            self.status.showMessage(f"Waveform ready — loading audio… ({path.name})", 0)
        # Reserve pending *before* submit so a fast PCM-ready signal can match.
        self._pending_audio_load = (token, None, path, mark_dirty, replace_track)
        future = self._start_audio_load(path, executor=self._audio_load_executor)
        self._pending_audio_load = (token, future, path, mark_dirty, replace_track)
        if not self._audio_load_timer.isActive():
            self._audio_load_timer.start()

    def _audio_cache_key(self, path: Path) -> tuple[str, int, int] | None:
        try:
            resolved = path.resolve()
            stat = resolved.stat()
            return (str(resolved), int(stat.st_mtime_ns), int(stat.st_size))
        except OSError:
            return None

    def _remount_caches_after_bundle(self, result: BundleResult) -> None:
        """Keep LTC L/R badges + RAM waveforms after Bundle remaps paths.

        Disk clone runs during collect; this remounts in-memory keys from the
        pre-Bundle path → new Bundle path, then merges the full disk LTC map.
        """
        pairs: list[tuple[Path, Path]] = []
        for src, dest in (*result.copied, *result.moved, *result.reused):
            if src is None or dest is None:
                continue
            try:
                if Path(src).resolve() == Path(dest).resolve():
                    continue
            except OSError:
                if Path(src) == Path(dest):
                    continue
            pairs.append((Path(src), Path(dest)))

        for src, dest in pairs:
            new_key = self._audio_cache_key(dest)
            if new_key is None:
                continue
            try:
                old_path = str(Path(src).expanduser().resolve())
            except OSError:
                old_path = str(Path(src).expanduser())

            donor: tuple[str, int, int] | None = None
            for key in self._audio_ltc_cache:
                if key[0] == old_path:
                    donor = key
                    break
            if donor is None:
                for key in self._audio_ltc_cache:
                    if key[1] == new_key[1] and key[2] == new_key[2]:
                        donor = key
                        break
            if donor is None:
                for key in self._audio_buffer_cache:
                    if key[0] == old_path or (
                        key[1] == new_key[1] and key[2] == new_key[2]
                    ):
                        donor = key
                        break
            if donor is None:
                continue
            if donor in self._audio_ltc_cache:
                self._audio_ltc_cache[new_key] = self._audio_ltc_cache[donor]
            if donor in self._audio_buffer_cache:
                self._audio_buffer_cache[new_key] = self._audio_buffer_cache[donor]

        self._audio_ltc_cache.update(load_all_ltc_channels())

    def _cached_audio_buffer(self, path: Path) -> AudioBuffer | None:
        """Return a RAM-resident buffer only — never block the UI on disk I/O.

        On-disk ``.npz`` hits go through ``_load_audio_path`` /
        ``load_audio_cached`` on a worker thread so Setlist song switches stay
        snappy after the first warm.
        """
        key = self._audio_cache_key(path)
        if key is None:
            return None
        return self._audio_buffer_cache.get(key)

    def _resolved_path_str(self, path: Path | None) -> str | None:
        if path is None:
            return None
        try:
            return str(path.resolve())
        except OSError:
            return str(path)

    def _invalidate_display_waveform_cache(self, path: Path) -> None:
        key = self._audio_cache_key(path)
        if key is None:
            return
        drop = [k for k in self._display_waveform_cache if k[0] == key]
        for cache_key in drop:
            self._display_waveform_cache.pop(cache_key, None)

    def _waveform_for_timeline(
        self, buffer: AudioBuffer, path: Path, exclude: int | None
    ) -> AudioBuffer:
        key = self._audio_cache_key(path)
        cache_key = (key, exclude)
        cached = self._display_waveform_cache.get(cache_key)
        if cached is not None:
            return cached
        result = waveform_display_buffer(buffer, exclude_channel=exclude)
        if key is not None and exclude is not None:
            self._display_waveform_cache[cache_key] = result
        return result

    def _store_audio_cache(
        self,
        path: Path,
        buffer: AudioBuffer,
        *,
        write_disk: bool = True,
        schedule_ltc: bool = False,
    ) -> None:
        key = self._audio_cache_key(path)
        if key is not None:
            self._audio_buffer_cache[key] = buffer
            self._invalidate_display_waveform_cache(path)
            self._note_media_warm_step(key, "audio")
            self._media_warm_progress.emit()
        if write_disk:
            self._audio_prefetch_executor.submit(save_cached_audio, path, buffer)
        if schedule_ltc:
            self._schedule_ltc_detect_for_buffer(path, buffer)

    def _ltc_channel_for_song(self, song: Song) -> int | None:
        from cueplayer.domain.models import coerce_file_ltc_side

        side = coerce_file_ltc_side(getattr(song, "file_ltc_side", "auto"))
        if side == "left":
            return 0
        if side == "right":
            return 1
        if side == "auto":
            path = self._main_audio_path_for_song(song)
            if path is None:
                return None
            key = self._audio_cache_key(path)
            if key is None:
                return None
            return self._audio_ltc_cache.get(key)
        path = self._main_audio_path_for_song(song)
        if path is None:
            return None
        key = self._audio_cache_key(path)
        if key is None:
            return None
        return self._audio_ltc_cache.get(key)

    def _ensure_ltc_detect_scheduled(self, song: Song) -> None:
        path = self._main_audio_path_for_song(song)
        if path is None:
            return
        key = self._audio_cache_key(path)
        if key is None or key in self._audio_ltc_cache or key in self._audio_ltc_inflight:
            return
        buffer = self._audio_buffer_cache.get(key)
        if buffer is not None:
            self._schedule_ltc_detect_for_buffer(path, buffer)

    def _schedule_idle_ltc_detect(self) -> None:
        """After idle: run LTC detect for songs whose buffer is cached but LTC unknown."""
        if bool(getattr(self.engine, "playing", False)):
            # Don't scan neighbor files for LTC while PortAudio needs the GIL.
            self._ltc_idle_timer.start()
            return
        for song in self.project.songs:
            path = self._main_audio_path_for_song(song)
            if path is None:
                continue
            key = self._audio_cache_key(path)
            if key is None or key in self._audio_ltc_cache or key in self._audio_ltc_inflight:
                continue
            buffer = self._audio_buffer_cache.get(key)
            if buffer is not None:
                self._schedule_ltc_detect_for_buffer(path, buffer)
                return

    def _schedule_ltc_detect_for_buffer(self, path: Path, buffer: AudioBuffer) -> None:
        key = self._audio_cache_key(path)
        if key is None or key in self._audio_ltc_cache or key in self._audio_ltc_inflight:
            return
        if buffer.channels < 2:
            self._audio_ltc_cache[key] = None
            self._note_media_warm_step(key, "ltc")
            self._setlist_ltc_cache_updated.emit()
            self._media_warm_progress.emit()
            return

        samples = buffer.samples
        sample_rate = int(buffer.sample_rate)

        def _run() -> tuple[tuple[str, int, int], int | None]:
            from cueplayer.util.thread_priority import lower_background_thread_priority

            lower_background_thread_priority()
            return key, detect_ltc_channel(samples, sample_rate)

        future = self._ltc_detect_executor.submit(_run)
        self._audio_ltc_inflight[key] = future

        def _done(fut) -> None:
            try:
                cache_key, channel = fut.result()
            except Exception:
                self._ltc_detect_finished.emit(key, None, False)
                return
            self._ltc_detect_finished.emit(cache_key, channel, True)

        future.add_done_callback(_done)

    def _on_ltc_detect_finished(
        self, cache_key: object, channel: object, ok: bool
    ) -> None:
        if not isinstance(cache_key, tuple) or len(cache_key) != 3:
            return
        key = cache_key  # type: ignore[assignment]
        self._audio_ltc_inflight.pop(key, None)
        if ok:
            ch = channel if isinstance(channel, int) else None
            self._audio_ltc_cache[key] = ch
            self._audio_prefetch_executor.submit(save_ltc_channel, key, ch)
            self._setlist_ltc_cache_updated.emit()
            # Keep the live engine's music-strip / Translate channel in sync.
            current = self._main_audio_path_for_song(self.current_song)
            if current is not None and self._audio_cache_key(current) == key:
                self.engine._detected_ltc_channel = ch
                self.engine._ltc_detect_ran = True
                self.engine._refresh_source_routing_cache()
                if self.project.audio_output.effective_ltc_to_mtc_translate():
                    self.engine._sync_mtc_to_file_ltc(self.engine.raw_position, force=True)
        self._note_media_warm_step(key, "ltc")
        self._media_warm_progress.emit()
        self._ltc_idle_timer.start()

    def _schedule_bpm_detect_for_song(
        self,
        song: Song,
        path: Path | None = None,
        *,
        force: bool = False,
    ) -> bool:
        """Estimate BPM from the song's main audio (async, one at a time).

        Default (``force=False``): only runs when ``song.bpm`` is still empty.
        ``force=True`` re-runs for auto BPM (gray ``<n>``) or empty cells.
        Manual typed BPM (``bpm_auto=False``) is never overwritten — clear the
        cell first if you want a fresh detect.
        Jobs are serialized on ``_bpm_detect_executor`` so opening a project
        or "detect all" cannot peg the machine.
        """
        # Sticky manual BPM: Re-detect / Detect selected must not wipe it.
        if (
            song.bpm is not None
            and float(song.bpm) > 0
            and not bool(getattr(song, "bpm_auto", False))
        ):
            return False
        if not force and song.bpm is not None:
            return False
        audio_path = path or self._main_audio_path_for_song(song)
        if audio_path is None or not Path(audio_path).is_file():
            return False
        song_id = song.id
        if song_id in self._bpm_detect_inflight:
            return False
        if any(item[0] == song_id for item in self._bpm_detect_queue):
            return False
        resolved = Path(audio_path)
        exclude = self._ltc_channel_for_song(song)
        if force:
            self._bpm_force_ids.add(song_id)
        else:
            self._bpm_force_ids.discard(song_id)
        self._bpm_detect_inflight.add(song_id)
        self._bpm_detect_queue.append((song_id, resolved, exclude, force))
        self._bpm_ui_progress[song_id] = -1  # queued
        self._refresh_bpm_progress_cell(song_id)
        self._pump_bpm_detect_queue()
        return True

    def _pump_bpm_detect_queue(self) -> None:
        if self._bpm_detect_running or not self._bpm_detect_queue:
            if not self._bpm_detect_queue and not self._bpm_detect_running:
                self._bpm_active_song_id = None
            return
        song_id, resolved, exclude, _force = self._bpm_detect_queue.pop(0)
        self._bpm_detect_running = True
        self._bpm_active_song_id = song_id
        self._bpm_ui_progress[song_id] = 0
        self._refresh_bpm_progress_cell(song_id)
        self._refresh_bpm_detect_status()

        def _run() -> tuple[str, float | None]:
            from cueplayer.media.bpm_analyzer import estimate_bpm_from_path
            from cueplayer.util.thread_priority import lower_background_thread_priority

            lower_background_thread_priority()

            def _progress(percent: int) -> None:
                # Worker thread → queued to UI via Signal.
                self._bpm_progress_changed.emit(song_id, int(percent))

            return song_id, estimate_bpm_from_path(
                resolved,
                exclude_channel=exclude,
                progress=_progress,
            )

        future = self._bpm_detect_executor.submit(_run)

        def _done(fut) -> None:  # noqa: ANN001
            self._bpm_detect_running = False
            self._bpm_detect_inflight.discard(song_id)
            if self._bpm_active_song_id == song_id:
                self._bpm_active_song_id = None
            try:
                sid, bpm = fut.result()
            except Exception:  # noqa: BLE001
                self._bpm_force_ids.discard(song_id)
                self._bpm_ui_progress.pop(song_id, None)
                self._bpm_job_finished.emit()
                return
            self._bpm_detected.emit(sid, bpm)
            self._bpm_job_finished.emit()

        future.add_done_callback(_done)

    def _on_bpm_progress_changed(self, song_id: str, percent: int) -> None:
        if song_id not in self._bpm_detect_inflight and song_id not in self._bpm_ui_progress:
            return
        # Queued marker is -1; never let worker reports clobber another song.
        if self._bpm_active_song_id not in (None, song_id):
            return
        prev = self._bpm_ui_progress.get(song_id, 0)
        value = max(int(prev) if prev >= 0 else 0, min(100, int(percent)))
        if self._bpm_ui_progress.get(song_id) == value:
            return
        self._bpm_ui_progress[song_id] = value
        self._refresh_bpm_progress_cell(song_id)
        self._refresh_bpm_detect_status()

    def _refresh_bpm_detect_status(self) -> None:
        if self._media_warm_active:
            return
        active_id = self._bpm_active_song_id
        pending = len(self._bpm_detect_queue) + (1 if self._bpm_detect_running else 0)
        if active_id is None and pending <= 0:
            return
        song = next((s for s in self.project.songs if s.id == active_id), None)
        pct = self._bpm_ui_progress.get(active_id or "", 0)
        if song is None:
            if pending > 0:
                self.status.showMessage(f"偵測 BPM 排隊中…（剩餘 {pending}）", 1500)
            return
        if pct < 0:
            label = "排隊中"
        else:
            label = f"{min(100, int(pct))}%"
        remaining = len(self._bpm_detect_queue)
        extra = f"（尚有 {remaining} 首排隊）" if remaining else ""
        self.status.showMessage(f'偵測 BPM：{song.name} {label}{extra}', 1500)

    def _table_row_for_song_id(self, song_id: str) -> int | None:
        for row in range(self.song_list.rowCount()):
            item = self.song_list.item(row, SetlistWidget.COL_NUM)
            if item is None:
                continue
            if item.data(SetlistWidget.ROLE_KIND) != "song":
                continue
            if str(item.data(Qt.ItemDataRole.UserRole) or "") == song_id:
                return row
            idx = item.data(SetlistWidget.ROLE_SONG_INDEX)
            if idx is None:
                continue
            try:
                song = self.project.songs[int(idx)]
            except (IndexError, TypeError, ValueError):
                continue
            if song.id == song_id:
                return row
        return None

    def _refresh_bpm_progress_cell(self, song_id: str) -> None:
        """Update one setlist BPM cell without rebuilding the whole list."""
        progress = self._bpm_ui_progress.get(song_id)
        # Cap displayed progress below 100% — 100 only appears briefly before
        # the result handler clears progress; never leave Sheet stuck on "100%".
        display_progress = progress
        if display_progress is not None and display_progress >= 100:
            display_progress = 99

        sheet = getattr(self, "setlist_sheet_page", None)
        if sheet is not None and hasattr(sheet, "set_song_bpm_progress"):
            # Always sync Sheet, even when the setlist row is hidden/collapsed.
            sheet.set_song_bpm_progress(song_id, display_progress)

        row = self._table_row_for_song_id(song_id)
        if row is None:
            return
        item = self.song_list.item(row, SetlistWidget.COL_NUM)
        idx = item.data(SetlistWidget.ROLE_SONG_INDEX) if item is not None else None
        song = None
        if idx is not None:
            try:
                song = self.project.songs[int(idx)]
            except (IndexError, TypeError, ValueError):
                song = None
        if song is None:
            song = next((s for s in self.project.songs if s.id == song_id), None)
        if song is None:
            return

        from cueplayer.ui.theme import ACCENT, secondary_text_on_background

        bpm_item = self.song_list.item(row, SetlistWidget.COL_BPM)
        if bpm_item is None:
            bpm_item = QTableWidgetItem("")
            bpm_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            bpm_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEditable
                | Qt.ItemFlag.ItemIsDragEnabled
            )
            self.song_list.setItem(row, SetlistWidget.COL_BPM, bpm_item)

        if display_progress is not None:
            if display_progress < 0:
                text = "…"
                tip = "排隊偵測 BPM 中…"
            else:
                text = f"{min(99, int(display_progress))}%"
                tip = f"正在偵測 BPM… {min(99, int(display_progress))}%"
            self.song_list._block_number_signal = True  # noqa: SLF001
            bpm_item.setText(text)
            bpm_item.setToolTip(tip)
            bpm_item.setForeground(QColor(ACCENT))
            self.song_list._block_number_signal = False  # noqa: SLF001
        elif song.bpm is not None and float(song.bpm) > 0:
            from cueplayer.media.bpm_analyzer import format_bpm_cell

            self.song_list._block_number_signal = True  # noqa: SLF001
            bpm_item.setText(format_bpm_cell(float(song.bpm), auto=bool(song.bpm_auto)))
            if song.bpm_auto:
                row_color = (song.row_color or "").strip() or None
                bpm_item.setForeground(QColor(secondary_text_on_background(row_color)))
                bpm_item.setToolTip(
                    "Auto-detected BPM (gray <n>).\n"
                    "Double-click to type the correct value if needed."
                )
            else:
                bpm_item.setForeground(QColor())
                bpm_item.setToolTip(
                    "Double-click to enter BPM (blank = not set)."
                )
            self.song_list._block_number_signal = False  # noqa: SLF001
        else:
            self.song_list._block_number_signal = True  # noqa: SLF001
            bpm_item.setText("")
            bpm_item.setForeground(QColor())
            bpm_item.setToolTip(
                "Double-click to enter BPM (blank = not set)."
            )
            self.song_list._block_number_signal = False  # noqa: SLF001

    def _schedule_bpm_detect_for_missing_songs(self, *, quiet: bool = False) -> int:
        """Queue detect for songs that have audio but no BPM yet."""
        queued = 0
        for song in self.project.songs:
            if self._schedule_bpm_detect_for_song(song, force=False):
                queued += 1
        if not quiet:
            if queued:
                self.status.showMessage(
                    f"Detecting BPM for {queued} song(s) without BPM…",
                    4000,
                )
            else:
                self.status.showMessage("All songs with audio already have a BPM.", 3000)
        return queued

    def _redetect_bpm_all_songs(self) -> None:
        """Re-detect auto/empty BPM only — never overwrite manual typed values."""
        n = self._detect_bpm_for_songs(list(self.project.songs), force=True)
        skipped_manual = sum(
            1
            for s in self.project.songs
            if s.bpm is not None
            and float(s.bpm) > 0
            and not bool(getattr(s, "bpm_auto", False))
            and self._main_audio_path_for_song(s) is not None
        )
        if n:
            extra = (
                f" (skipped {skipped_manual} manual)"
                if skipped_manual
                else ""
            )
            self.status.showMessage(
                f"Re-detecting BPM for {n} song(s)…{extra} (queued one at a time)",
                5000,
            )
        elif skipped_manual:
            self.status.showMessage(
                f"All songs with audio have manual BPM ({skipped_manual}) — nothing to re-detect.",
                4000,
            )
        else:
            self.status.showMessage("No songs with audio to re-detect.", 3000)

    def _detect_bpm_for_songs(self, songs: list[Song], *, force: bool = False) -> int:
        """Queue BPM detect for the given songs. ``force`` re-runs even if set."""
        queued = 0
        for song in songs:
            if self._schedule_bpm_detect_for_song(song, force=force):
                queued += 1
        return queued

    def _on_bpm_detected(self, song_id: str, bpm: object) -> None:
        self._bpm_ui_progress.pop(song_id, None)
        # Clear Sheet progress before any rebuild/sync so "100%" cannot stick.
        sheet = getattr(self, "setlist_sheet_page", None)
        if sheet is not None and hasattr(sheet, "clear_song_bpm_progress"):
            sheet.clear_song_bpm_progress(song_id)
        elif sheet is not None and hasattr(sheet, "set_song_bpm_progress"):
            sheet.set_song_bpm_progress(song_id, None)
        song = next((s for s in self.project.songs if s.id == song_id), None)
        forced = song_id in self._bpm_force_ids
        self._bpm_force_ids.discard(song_id)
        if song is None:
            self._refresh_bpm_progress_cell(song_id)
            return
        # Without force, never overwrite a user-typed BPM (e.g. typed while detect ran).
        if (
            not forced
            and song.bpm is not None
            and not bool(getattr(song, "bpm_auto", False))
        ):
            self._refresh_bpm_progress_cell(song_id)
            return
        # Force path also respects sticky manual BPM (scheduled only for auto/empty).
        if (
            song.bpm is not None
            and float(song.bpm) > 0
            and not bool(getattr(song, "bpm_auto", False))
        ):
            self._refresh_bpm_progress_cell(song_id)
            return
        if bpm is None:
            self._refresh_bpm_progress_cell(song_id)
            self.status.showMessage(
                f'Could not detect BPM for "{song.name}" (too quiet / talky?)',
                4000,
            )
            return
        try:
            value = float(bpm)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            self._refresh_bpm_progress_cell(song_id)
            return
        if value <= 0:
            self._refresh_bpm_progress_cell(song_id)
            return
        if (
            song.bpm is not None
            and abs(float(song.bpm) - value) < 1e-9
            and bool(getattr(song, "bpm_auto", False))
        ):
            self._refresh_bpm_progress_cell(song_id)
            return
        song.bpm = value
        song.bpm_auto = True
        self._mark_dirty()
        self._refresh_bpm_progress_cell(song_id)
        if sheet is not None:
            sheet.sync_songs()
        from cueplayer.media.bpm_analyzer import format_bpm_value

        self.status.showMessage(
            f'Auto BPM for "{song.name}": <{format_bpm_value(value)}>',
            5000,
        )

    def _refresh_setlist_ltc_cells(self) -> None:
        for table_row in range(self.song_list.rowCount()):
            if self.song_list.row_kind(table_row) != "song":
                continue
            song_index = self.song_list.row_song_index(table_row)
            if song_index is None or song_index >= len(self.project.songs):
                continue
            song = self.project.songs[song_index]
            channel = self._ltc_channel_for_song(song)
            item = self.song_list.item(table_row, SetlistWidget.COL_LTC)
            if item is None:
                continue
            item.setData(SetlistWidget.ROLE_LTC_CHANNEL, channel)
            if channel == 0:
                item.setToolTip("Striped LTC detected on Left channel")
            elif channel == 1:
                item.setToolTip("Striped LTC detected on Right channel")
            else:
                item.setToolTip("")
        self.song_list.viewport().update()
        self._refresh_timeline_waveform_for_ltc()

    def _refresh_timeline_waveform_for_ltc(self) -> None:
        """Redraw Music (sans LTC) + optional LTC inspect lane for the current song."""
        path = self._main_audio_path_for_song(self.current_song)
        if path is None:
            self.timeline.set_ltc_audio(None)
            return
        buffer = self._cached_audio_buffer(path)
        if buffer is None:
            self.timeline.set_ltc_audio(None)
            return
        exclude = self._ltc_channel_for_song(self.current_song)
        if exclude != self._timeline_ltc_exclude:
            prev = self._timeline_ltc_exclude
            self._timeline_ltc_exclude = exclude
            # Initial paint is in _apply_loaded_audio; only re-paint Music when
            # LTC side becomes known (or a previous strip is cleared).
            if not (exclude is None and prev is None):
                self.timeline.set_audio(
                    self._waveform_for_timeline(buffer, path, exclude),
                    reset_view=False,
                )
        self._apply_timeline_ltc_lane(buffer, exclude)

    def _apply_timeline_ltc_lane(
        self, buffer: AudioBuffer, channel: int | None
    ) -> None:
        if channel is None:
            self.timeline.set_ltc_audio(None)
            return
        ltc_buf = ltc_waveform_display_buffer(buffer, channel)
        self.timeline.set_ltc_audio(ltc_buf, channel=channel if ltc_buf is not None else None)

    def _start_audio_load(self, path: Path, *, executor: ThreadPoolExecutor) -> object:
        path = Path(path)
        key = self._audio_cache_key(path)
        if key is not None and key in self._audio_inflight:
            return self._audio_inflight[key]

        def _load() -> AudioBuffer:
            from cueplayer.util.thread_priority import lower_background_thread_priority

            lower_background_thread_priority()

            def _on_pcm(buffer: AudioBuffer) -> None:
                # Handler ignores non-pending / already-peaked (cache) buffers.
                self._audio_pcm_ready.emit(path, buffer)

            with perf_diag.span("audio.load.worker", path=str(path.name)):
                return load_audio_cached(path, on_pcm_ready=_on_pcm)

        future = executor.submit(_load)
        if key is not None:
            self._audio_inflight[key] = future

            def _done(fut) -> None:
                try:
                    buffer = fut.result()
                except Exception as exc:  # noqa: BLE001
                    self._audio_prefetch_finished.emit(path, exc)
                    return
                self._audio_prefetch_finished.emit(path, buffer)

            future.add_done_callback(_done)
        return future

    def _apply_probed_audio_duration(
        self, path: Path, *, song: Song | None = None
    ) -> None:
        """Set song/engine/transport duration from file metadata (no decode)."""
        dur = probe_audio_duration(path)
        if dur is None:
            return
        target = song if song is not None else self.current_song
        target.duration_seconds = float(dur)
        if target is not self.current_song:
            return
        self.engine.set_duration(float(dur))
        pos = float(self.playback.position)
        self.transport.set_times(pos, self.engine.duration)
        self.monitor.set_position(pos, self.engine.duration)
        self.timeline.update()
        self._sync_timeline_overview()

    def _on_audio_pcm_ready(self, path: object, buffer: object) -> None:
        """PCM decoded — arm playback before the waveform pyramid finishes."""
        if not isinstance(path, Path) or not isinstance(buffer, AudioBuffer):
            return
        # Disk-cache hits already have peaks; final apply will run immediately.
        if buffer.peak_levels:
            return
        pending = self._pending_audio_load
        if pending is None:
            return
        token, _future, pending_path, mark_dirty, replace_track = pending
        del mark_dirty
        if token != self._audio_load_token:
            return
        try:
            same_path = Path(pending_path).resolve() == path.resolve()
        except OSError:
            same_path = Path(pending_path) == path
        if not same_path:
            return
        if not self._audio_path_matches_current_song(path, replace_track=replace_track):
            return
        if self.engine.buffer is buffer:
            return
        self.current_song.duration_seconds = buffer.duration_seconds
        if replace_track:
            self.current_song.replace_main_audio(path)
        self.engine.set_buffer(buffer)
        self.engine.ensure_playback_ready()
        self.transport.set_times(0.0, self.engine.duration)
        self.monitor.set_position(0.0, self.engine.duration)
        # Keep any peaks-sidecar waveform; otherwise show loading until peaks land.
        if self.timeline._audio is None:
            self.timeline.set_audio_loading(True, path.name)
        if not self._media_warm_active:
            self.status.showMessage(
                f"Audio ready — decoding continues… ({path.name})", 0
            )

    def _on_audio_prefetch_finished(self, path: object, result: object) -> None:
        if not isinstance(path, Path):
            return
        key = self._audio_cache_key(path)
        if key is not None:
            self._audio_inflight.pop(key, None)
        if isinstance(result, Exception) or result is None:
            if key is not None:
                self._note_media_warm_step(key, "audio")
                self._note_media_warm_step(key, "ltc")
            self._media_warm_progress.emit()
            return
        from cueplayer.media.audio_loader import AudioBuffer as _AudioBuffer

        if not isinstance(result, _AudioBuffer):
            return
        self._store_audio_cache(path, result, write_disk=False, schedule_ltc=False)
        self._media_warm_progress.emit()

    def _begin_media_warm_progress(self) -> None:
        """Track pending waveform decode + LTC detect for status-bar %."""
        units: dict[tuple[str, int, int], dict[str, bool]] = {}
        for song in self.project.songs:
            path = self._main_audio_path_for_song(song)
            if path is None:
                continue
            key = self._audio_cache_key(path)
            if key is None:
                continue
            audio_done = key in self._audio_buffer_cache
            ltc_done = key in self._audio_ltc_cache
            if audio_done and ltc_done:
                continue
            units[key] = {"audio": audio_done, "ltc": ltc_done}
        self._media_warm_units = units
        self._media_warm_active = bool(units)
        if self._media_warm_active:
            self._refresh_media_warm_status()

    def _note_media_warm_step(self, key: tuple[str, int, int] | None, step: str) -> None:
        if key is None or not self._media_warm_active:
            return
        unit = self._media_warm_units.get(key)
        if unit is None:
            return
        if step in unit:
            unit[step] = True

    def _media_warm_counts(self) -> tuple[int, int]:
        total = 0
        done = 0
        for unit in self._media_warm_units.values():
            for step in ("audio", "ltc"):
                total += 1
                if unit.get(step):
                    done += 1
        return done, total

    def _refresh_media_warm_status(self) -> None:
        if not self._media_warm_active:
            return
        done, total = self._media_warm_counts()
        if total <= 0 or done >= total:
            self._media_warm_active = False
            self._media_warm_units.clear()
            self.status.showMessage("Waveform / LTC ready", 2500)
            return
        pct = int(round(100.0 * done / total))
        pending_files = sum(
            1
            for unit in self._media_warm_units.values()
            if not (unit.get("audio") and unit.get("ltc"))
        )
        self.status.showMessage(
            f"Loading waveform / LTC: {pct}%（{done}/{total} · {pending_files} file(s) left）",
            0,
        )

    def _main_audio_path_for_song(self, song: Song) -> Path | None:
        """Existing-file path for the song's active playback media (variant-aware)."""
        path = self.playback.resolve_active_audio_path(song)
        if path is None:
            return None
        return path if path.is_file() else None

    def _song_has_main_audio_file(self, song: Song | None = None) -> bool:
        return self._main_audio_path_for_song(song or self.current_song) is not None

    def _primary_video_clip_for_standin(self, song: Song | None = None) -> VideoClip | None:
        song = song or self.current_song
        for clip in song.video_clips:
            if clip.hidden or clip.media_kind == "still":
                continue
            if Path(clip.path).is_file():
                return clip
        return None

    def _video_standin_cache_key(
        self, clip: VideoClip, *, timeline_duration: float
    ) -> str | None:
        path = Path(clip.path)
        try:
            resolved = str(path.resolve())
            stat = path.stat()
            mtime_ns = int(stat.st_mtime_ns)
            size = int(stat.st_size)
        except OSError:
            return None
        return (
            f"{clip.id}|{resolved}|{mtime_ns}|{size}|"
            f"{round(float(timeline_duration), 3)}|"
            f"{round(float(clip.start_seconds), 3)}|"
            f"{round(float(clip.source_in_seconds), 3)}|"
            f"{round(float(clip.source_span_seconds or clip.duration_seconds), 3)}"
        )

    def _arm_timeline_audio_loading_placeholder(self, song: Song) -> None:
        """Show Loading immediately when a cold decode is about to start.

        Avoids a frame of empty-project copy ("Open audio…") and clears a
        previous song's waveform so we don't flash the wrong music lane.
        Skips when RAM / peaks / stand-in disk cache will paint instantly.
        """
        path = self._main_audio_path_for_song(song)
        if path is not None:
            if self._cached_audio_buffer(path) is not None:
                return
            if load_cached_waveform_peaks(path) is not None:
                return
            self.timeline.set_audio_loading(True, path.name)
            return
        if song.audio_tracks:
            # Path missing — activate will show Relink; don't pretend to load.
            return
        clip = self._primary_video_clip_for_standin(song)
        if clip is None:
            return
        duration = float(song.duration_seconds)
        cache_key = self._video_standin_cache_key(clip, timeline_duration=duration)
        if cache_key is not None:
            if cache_key in self._video_standin_cache:
                return
        from cueplayer.media.video_music_standin import try_music_standin_artifact_from_disk

        art = try_music_standin_artifact_from_disk(
            clip, timeline_duration=duration, allow_disk=False
        )
        if art is not None:
            return
        self.timeline.set_audio_loading(True, f"{clip.name} (video)")

    def _on_playing_changed_video_standin(self, playing: bool) -> None:
        """While playing, pause shared waveform artifact builds for av_path_lock.

        Cancel in-flight standin on Play; resume after Pause/Stop if needed.
        """
        from cueplayer.media.video_waveform_artifact import set_waveform_build_paused

        set_waveform_build_paused(bool(playing))
        if self._song_has_main_audio_file():
            return
        if playing:
            if self.timeline.audio_loading():
                self._video_standin_token += 1
            return
        flush = getattr(self.timeline, "_video_waveform_cache", None)
        if flush is not None and hasattr(flush, "flush_pending_gui_notify"):
            flush.flush_pending_gui_notify()
        has_main_wave = (
            getattr(self.timeline, "_audio", None) is not None
            or getattr(self.timeline, "_artifact_wave", None) is not None
        )
        if not has_main_wave and self._primary_video_clip_for_standin() is not None:
            self._schedule_video_music_standin()

    def _schedule_video_music_standin(self) -> None:
        """Fill the Music waveform from the shared VideoWaveformArtifact."""
        if self._song_has_main_audio_file():
            return
        if bool(getattr(self.engine, "playing", False)):
            return
        clip = self._primary_video_clip_for_standin()
        if clip is None:
            self._video_standin_token += 1
            self.timeline.clear_artifact_waveform()
            self.timeline.set_audio(None)
            self.timeline.set_audio_loading(False)
            return
        duration = float(self.current_song.duration_seconds)
        from cueplayer.media.video_music_standin import (
            try_music_standin_artifact_from_disk,
        )

        disk_art = try_music_standin_artifact_from_disk(
            clip, timeline_duration=duration, allow_disk=False
        )
        if disk_art is not None and disk_art.complete:
            self._video_standin_token += 1
            self.timeline.set_audio_loading(False)
            self.timeline.set_artifact_waveform(disk_art, clip, complete=True)
            self.timeline.refresh_video_clip_waveforms()
            self._sync_timeline_overview()
            if not self._media_warm_active:
                self.status.showMessage(
                    f"Music waveform from cache ({clip.name})", 2500
                )
            return
        if disk_art is not None and disk_art.coverage_ratio > 0:
            # Partial RAM hit — show immediately while build continues.
            self.timeline.set_artifact_waveform(disk_art, clip, complete=False)
        self._video_standin_token += 1
        token = self._video_standin_token
        song_id = self.current_song.id
        if getattr(self.timeline, "_artifact_wave", None) is None:
            self.timeline.set_audio_loading(True, f"{clip.name} (video)")
        clip_snapshot = clip

        def _job() -> None:
            from cueplayer.util.thread_priority import lower_background_thread_priority

            lower_background_thread_priority()

            def _cancel() -> bool:
                return (
                    token != self._video_standin_token
                    or song_id != self.current_song.id
                    or bool(getattr(self.engine, "playing", False))
                )

            try:
                art = build_music_standin_from_video(
                    clip_snapshot,
                    timeline_duration=duration,
                    cancel_check=_cancel,
                    pause_check=lambda: bool(getattr(self.engine, "playing", False)),
                    on_progress=lambda a: self._video_standin_finished.emit(
                        token, ("progress_art", a)
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                self._video_standin_finished.emit(token, exc)
                return
            if _cancel():
                self._video_standin_finished.emit(token, False)
                return
            self._video_standin_finished.emit(token, art)

        self._audio_load_executor.submit(_job)

    def _on_video_standin_finished(self, token: int, result: object) -> None:
        if token != self._video_standin_token:
            return
        if self._song_has_main_audio_file():
            self.timeline.set_audio_loading(False)
            return
        if isinstance(result, Exception):
            self.timeline.set_audio_loading(False)
            self.timeline.clear_artifact_waveform()
            self.timeline.set_audio(None)
            self.status.showMessage(f"Video waveform failed: {result}", 4000)
            return
        if result is False:
            clip = self._primary_video_clip_for_standin()
            if (
                clip is not None
                and getattr(self.timeline, "_audio", None) is None
                and getattr(self.timeline, "_artifact_wave", None) is None
            ):
                self.timeline.set_audio_loading(True, f"{clip.name} (video)")
            return
        from cueplayer.media.video_waveform_artifact import VideoWaveformArtifact

        if (
            isinstance(result, tuple)
            and len(result) == 2
            and result[0] == "progress_art"
            and isinstance(result[1], VideoWaveformArtifact)
        ):
            partial = result[1]
            clip = self._primary_video_clip_for_standin()
            self.timeline.set_artifact_waveform(partial, clip, complete=False)
            # Do not refresh_video_clip_waveforms() here — that invalidates Marks.
            # Video lane already listens on the same artifact store.
            self.timeline.set_audio_loading(True, "Building waveform…")
            self._sync_timeline_overview()
            return
        # Legacy progress AudioBuffer path — ignore (must not rebuild full buffer).
        if (
            isinstance(result, tuple)
            and len(result) == 2
            and result[0] == "progress"
        ):
            return
        if result is None:
            self.timeline.set_audio_loading(False)
            self.timeline.clear_artifact_waveform()
            self.timeline.set_audio(None)
            if self._primary_video_clip_for_standin() is not None:
                self.status.showMessage(
                    "Video has no embedded audio — Music lane stays empty",
                    4000,
                )
            return
        if isinstance(result, VideoWaveformArtifact):
            self.timeline.set_audio_loading(False)
            clip = self._primary_video_clip_for_standin()
            self.timeline.set_artifact_waveform(
                result, clip, complete=bool(result.complete)
            )
            self.timeline.refresh_video_clip_waveforms()
            self._sync_timeline_overview()
            mins = float(result.duration_seconds) / 60.0
            self.status.showMessage(
                f"Music waveform from video audio ({mins:.0f} min)",
                3500,
            )
            return
        if not isinstance(result, AudioBuffer):
            self.timeline.set_audio_loading(False)
            self.timeline.set_audio(None)
            return
        # Legacy AudioBuffer completion (should be rare after artifact bind).
        self.timeline.set_audio_loading(False)
        clip = self._primary_video_clip_for_standin()
        if clip is not None:
            key = self._video_standin_cache_key(
                clip, timeline_duration=float(self.current_song.duration_seconds)
            )
            if key is not None:
                self._video_standin_cache[key] = result
        self.timeline.set_audio(result, reset_view=False)
        self.timeline.refresh_video_clip_waveforms()
        self._sync_timeline_overview()
        self.status.showMessage(
            f"Music waveform from video audio ({result.duration_seconds / 60.0:.0f} min)",
            3500,
        )

    def _prefetch_neighbor_audio(self, *, skip_path: Path | None = None) -> None:
        """Background-load the current song's neighbors (keeps song switch responsive)."""
        try:
            idx = self.project.songs.index(self.current_song)
        except ValueError:
            return
        skip_resolved = self._resolved_path_str(skip_path)
        for i in (idx - 1, idx + 1):
            if i < 0 or i >= len(self.project.songs):
                continue
            path = self._main_audio_path_for_song(self.project.songs[i])
            if path is None:
                continue
            if skip_resolved is not None and self._resolved_path_str(path) == skip_resolved:
                continue
            if self._cached_audio_buffer(path) is not None:
                continue
            key = self._audio_cache_key(path)
            if key is not None and key in self._audio_inflight:
                continue
            self._start_audio_load(path, executor=self._audio_prefetch_executor)

    def _prefetch_all_setlist_audio(self) -> None:
        """Background-load every song (batch import) with status-bar warm progress."""
        self._begin_media_warm_progress()
        for song in self.project.songs:
            path = self._main_audio_path_for_song(song)
            if path is None:
                continue
            if self._cached_audio_buffer(path) is not None:
                continue
            key = self._audio_cache_key(path)
            if key is not None and key in self._audio_inflight:
                continue
            self._start_audio_load(path, executor=self._audio_prefetch_executor)
        self._refresh_media_warm_status()

    def _poll_pending_audio_load(self) -> None:
        pending = self._pending_audio_load
        if pending is None:
            self._audio_load_timer.stop()
            return
        token, future, path, mark_dirty, replace_track = pending
        if token != self._audio_load_token:
            self._pending_audio_load = None
            self._audio_load_timer.stop()
            self.timeline.set_audio_loading(False)
            return
        if future is None or not future.done():
            return
        self._audio_load_timer.stop()
        self._pending_audio_load = None
        try:
            buffer = future.result()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Unable to Load Audio", str(exc))
            self.timeline.set_audio_loading(False)
            self.status.clearMessage()
            return
        if not self._audio_path_matches_current_song(path, replace_track=replace_track):
            return
        self._apply_loaded_audio(
            buffer, path, mark_dirty=mark_dirty, replace_track=replace_track
        )

    def _audio_path_matches_current_song(self, path: Path, *, replace_track: bool) -> bool:
        if replace_track:
            return True
        main = self.playback.resolve_active_audio_path(self.current_song)
        if main is None:
            return False
        try:
            return Path(main).resolve() == path.resolve()
        except OSError:
            return Path(main) == path

    def _apply_loaded_audio(
        self,
        buffer: AudioBuffer,
        path: Path,
        *,
        mark_dirty: bool = True,
        replace_track: bool = True,
        refresh_song_widgets: bool = True,
        reset_view: bool | None = None,
    ) -> None:
        with perf_diag.span("audio.apply", path=str(Path(path).name)):
            self._store_audio_cache(path, buffer, schedule_ltc=True)
            self.timeline.set_audio_loading(False)
            self.current_song.duration_seconds = buffer.duration_seconds
            if replace_track:
                self.current_song.replace_main_audio(path)
            # Same buffer object may already be playing from _on_audio_pcm_ready
            # (peaks filled in place / progressive tail decode). Do not set_buffer
            # again — that seeks to 0 and cuts playback mid-stream.
            already_armed = self.engine.buffer is buffer
            if not already_armed:
                self.engine.set_buffer(buffer)
                if replace_track:
                    self.engine.ensure_playback_ready()
            else:
                # Progressive load: refresh resample snapshot now that PCM is complete.
                self.engine.rebind_playback_samples()
            exclude = self._ltc_channel_for_song(self.current_song)
            self._timeline_ltc_exclude = exclude
            # Song switch (replace_track=False) keeps the current zoom scale;
            # importing / replacing audio still resets to the default zoom.
            keep_zoom = replace_track is False if reset_view is None else (not reset_view)
            with perf_diag.span("waveform.display_build"):
                self.timeline.set_audio(
                    self._waveform_for_timeline(buffer, path, exclude),
                    reset_view=not keep_zoom,
                )
            self._apply_timeline_ltc_lane(buffer, exclude)
            perf_diag.note("audio.playback_ready", True)
            perf_diag.count("audio.apply.calls")
            if refresh_song_widgets:
                self.timeline.set_song(self.current_song)
                self._apply_project_mark_line_settings()
                self.monitor.set_song(self.current_song)
            if already_armed:
                pos = float(self.playback.position)
                self.transport.set_times(pos, self.engine.duration)
                self.monitor.set_position(pos, self.engine.duration)
            else:
                self.transport.set_times(0.0, self.engine.duration)
                self.monitor.set_position(0.0, self.engine.duration)
            self._refresh_output_timecode_clock(
                0.0 if not already_armed else float(self.playback.position)
            )
            if mark_dirty:
                self._mark_dirty()
            self._refresh_status()
            if self.current_song.bpm is None:
                self._schedule_bpm_detect_for_song(self.current_song, path)
            msg = f"Loaded: {path.name} ({buffer.duration_seconds:.2f}s)"
            det = self.engine.detected_ltc_channel
            if det is not None:
                side = "Left" if det == 0 else "Right"
                msg += f" — striped LTC detected on {side}"
            self.status.showMessage(msg, 6000)

    def _persist_clean_output_was_open(self, visible: bool) -> None:
        if self._block_clean_output_visibility_persist:
            return
        self._settings.setValue(_KEY_CLEAN_OUTPUT_WAS_OPEN, bool(visible))
        if self.project.clean_video_output.was_open != visible:
            self.project.clean_video_output.was_open = visible
            self._mark_dirty()

    def _clean_output_want_open(self) -> bool:
        if self.project.clean_video_output.was_open:
            return True
        if self._project_path is None:
            return bool(
                self._settings.value(_KEY_CLEAN_OUTPUT_WAS_OPEN, False, type=bool)
            )
        return False

    def _restore_clean_output_geometry(self) -> None:
        geometry = self._settings.value(_KEY_CLEAN_OUTPUT_GEOMETRY)
        if geometry:
            self.clean_output_window.restoreGeometry(geometry)

    def _restore_clean_output_visibility(self) -> None:
        want_open = self._clean_output_want_open()
        self._block_clean_output_visibility_persist = True
        try:
            if want_open:
                self.clean_output_window.present_for_obs_capture()
                self._clean_output_action.setChecked(True)
            else:
                if self.clean_output_window.isVisible():
                    self.clean_output_window.hide()
                self._clean_output_action.setChecked(False)
        finally:
            self._block_clean_output_visibility_persist = False

    def present_clean_output_for_obs(self) -> None:
        """Re-raise Clean Output after the main window shows (OBS window picker)."""
        if self.clean_output_window.isVisible():
            self.clean_output_window.present_for_obs_capture()
        self.raise_()
        self.activateWindow()

    def _toggle_clean_output(self, checked: bool) -> None:
        if checked:
            self.clean_output_window.present_for_obs_capture()
        else:
            self.clean_output_window.hide()

    def _apply_ndi_from_project(self, *, show_errors: bool = True) -> str | None:
        settings = self.project.clean_video_output
        width, height = int(settings.width), int(settings.height)
        fit_mode = "fit"
        if hasattr(self, "clean_output_window"):
            try:
                width, height = self.clean_output_window.content_size()
                fit_mode = self.clean_output_window.preview.fit_mode()
            except Exception:  # noqa: BLE001
                pass
        mode = str(getattr(settings, "ndi_frame_mode", "") or "output_window")
        if mode not in ("video", "output_window"):
            mode = "output_window"
        err = self._ndi_output.configure(
            enabled=bool(settings.ndi_enabled),
            name=str(settings.ndi_name or "CuePlayer"),
            frame_mode=mode,
            width=width,
            height=height,
            fit_mode=fit_mode,
        )
        self.clean_output_window.set_ndi_enabled(bool(settings.ndi_enabled))
        self.clean_output_window.set_ndi_name(str(settings.ndi_name or "CuePlayer"))
        self.clean_output_window.set_ndi_frame_mode(mode)
        if hasattr(self, "_ndi_output_action"):
            self._ndi_output_action.setChecked(bool(settings.ndi_enabled) and err is None)
        self._sync_video_output_active()
        if err and show_errors:
            if ndi_install_required(err):
                show_ndi_install_dialog(
                    self, detail=err, kind=ndi_failure_kind(err)
                )
            else:
                QMessageBox.warning(self, "NDI Video Output", err)
        return err

    def _on_clean_output_settings_changed(self) -> None:
        """Persist geometry / Fit-Fill; refresh NDI canvas when in Output-window mode."""
        self._mark_dirty()
        if not self.project.clean_video_output.ndi_enabled:
            return
        live = self.clean_output_window.current_settings()
        self.project.clean_video_output.width = live.width
        self.project.clean_video_output.height = live.height
        self.project.clean_video_output.aspect_locked = live.aspect_locked
        self.project.clean_video_output.ndi_frame_mode = live.ndi_frame_mode
        if live.ndi_frame_mode == "output_window":
            self._ndi_output.set_presentation(
                width=live.width,
                height=live.height,
                fit_mode=self.clean_output_window.preview.fit_mode(),
            )

    def _toggle_ndi_output(self, checked: bool) -> None:
        self.project.clean_video_output.ndi_enabled = bool(checked)
        self.clean_output_window.set_ndi_enabled(bool(checked))
        err = self._apply_ndi_from_project(show_errors=True)
        if err:
            self.project.clean_video_output.ndi_enabled = False
            self.clean_output_window.set_ndi_enabled(False)
            if hasattr(self, "_ndi_output_action"):
                self._ndi_output_action.setChecked(False)
            self._apply_ndi_from_project(show_errors=False)
            return
        if checked:
            mode = self.project.clean_video_output.ndi_frame_mode
            hint = (
                "video size"
                if mode == "video"
                else "Output window (Fit/Fill)"
            )
            self.status.showMessage(
                f"NDI “{self.project.clean_video_output.ndi_name or 'CuePlayer'}” "
                f"— {hint}. Play a clip to see picture.",
                5000,
            )
        self._mark_dirty()

    def _on_ndi_name_changed(self, name: str) -> None:
        name = (name or "").strip() or "CuePlayer"
        self.project.clean_video_output.ndi_name = name
        self.clean_output_window.set_ndi_name(name)
        if self.project.clean_video_output.ndi_enabled:
            err = self._apply_ndi_from_project(show_errors=True)
            if err:
                return
            self.status.showMessage(f"NDI renamed to “{name}”", 3500)
        self._mark_dirty()

    def _on_ndi_frame_mode_changed(self, mode: str) -> None:
        mode = "video" if mode == "video" else "output_window"
        self.project.clean_video_output.ndi_frame_mode = mode
        self.clean_output_window.set_ndi_frame_mode(mode)
        if self.project.clean_video_output.ndi_enabled:
            err = self._apply_ndi_from_project(show_errors=True)
            if err:
                return
            label = "Video (source size)" if mode == "video" else "Output window (Fit/Fill)"
            self.status.showMessage(f"NDI frame size: {label}", 3500)
        self._mark_dirty()

    def _prompt_ndi_name(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        current = str(self.project.clean_video_output.ndi_name or "CuePlayer")
        text, ok = QInputDialog.getText(
            self,
            "NDI Source Name",
            "Name shown in Depence / NDI receivers:",
            text=current,
        )
        if not ok:
            return
        self._on_ndi_name_changed((text or "").strip() or "CuePlayer")

    def _on_video_clips_changed(self) -> None:
        self.video_sync.refresh()
        self.engine.refresh_video_clips()
        self._mark_dirty()
        self.timeline.update()

    def _on_video_track_mute_toggled(self, muted: bool) -> None:
        self.current_song.video_track_muted = bool(muted)
        self.engine.set_video_track_muted(muted)
        self._mark_dirty()
        self.status.showMessage(
            "Video Track muted (embedded clip audio silenced)" if muted else "Video Track unmuted",
            2000,
        )

    def _on_video_track_visibility_changed(self, visible: bool) -> None:
        self.project.set_show_video_track(bool(visible))
        self.video_sync.set_timeline_video_heavy(bool(visible))
        action = getattr(self, "_show_video_track_action", None)
        if action is not None:
            action.blockSignals(True)
            action.setChecked(bool(visible))
            action.blockSignals(False)
        self._sync_timeline_geometry()
        self._mark_dirty()
        self.status.showMessage(
            "Video / LTC Tracks shown"
            if visible
            else "Video / LTC Tracks hidden (Preview/Clean Output still play)",
            2500,
        )

    def _on_ltc_track_visibility_changed(self, visible: bool) -> None:
        # Bound to the Video eye — project-global sync.
        self.project.set_show_video_track(bool(visible))

    def _on_wave_gain_line_visibility_changed(self, visible: bool) -> None:
        self.project.show_wave_gain_line = bool(visible)
        self._mark_dirty()

    def _on_ltc_gain_line_visibility_changed(self, visible: bool) -> None:
        self.project.show_ltc_gain_line = bool(visible)
        self._mark_dirty()

    def _on_show_video_track_toggled(self, checked: bool) -> None:
        # set_show_video_track emits the canonical visibility handler. Avoid a
        # second geometry/decode-budget pass per menu click; repeated duplicate
        # repaints starved queued Video frame presentation.
        self.timeline.set_show_video_track(bool(checked))

    def _on_video_clip_volume_changed(self, clip_id: str, volume: float) -> None:
        # Volume is already applied to the clip by the timeline widget; this
        # just persists the change (no undo entry, matching lock/hide toggles).
        del clip_id, volume
        self._mark_dirty()

    def _on_music_volume_changed(self, volume: float) -> None:
        # song.music_volume is already updated by the timeline widget; this
        # applies it live to playback and persists it (no undo entry,
        # matching Master Volume / lock-hide toggles).
        self.playback.set_music_volume(volume)
        self._mark_dirty()

    def _on_audio_gain_changed(self, gain_db: float) -> None:
        self.playback.set_audio_gain_db(gain_db)
        self._mark_dirty()

    def _on_now_layout_changed(self) -> None:
        if self._restoring_session:
            return
        layout_state = self.monitor.save_now_splitter_state()
        self._settings.setValue(_KEY_NOW_SECONDARY_PLACEMENT, layout_state["placement"])
        self._settings.setValue(_KEY_NOW_SPLITTER, layout_state["current"])
        self._settings.setValue(_KEY_NOW_SPLITTER_RIGHT, layout_state["right"])
        self._settings.setValue(_KEY_NOW_SPLITTER_BELOW, layout_state["below"])
        self._settings.setValue(_KEY_NOW_BODY_SPLITTER, layout_state.get("body"))

    def _on_mark_lane_height_changed(self, height: float) -> None:
        self.project.mark_lane_height = float(height)
        self._mark_dirty()

    def _on_mark_track_colors_changed(self, show: bool) -> None:
        self.project.show_mark_track_colors = bool(show)
        self._mark_dirty()

    def _on_mark_lane_renamed(self, lane_index: int, new_name: str) -> None:
        del lane_index, new_name
        self._mark_dirty()
        self.monitor.set_song(self.current_song)
        self.timeline.update()
        self.status.showMessage("Mark track renamed", 2000)

    def _on_video_clip_edited(self, clip_id: str, old: tuple, new: tuple) -> None:
        self._push_song_undo(EditVideoClipsCommand(changes={clip_id: (old, new)}))
        self.video_sync.refresh()
        self.engine.refresh_video_clips()
        self.timeline.refresh_video_clip_waveforms()
        self._mark_dirty()

    def _on_video_clips_batch_edited(self, changes: object) -> None:
        if not isinstance(changes, dict) or not changes:
            return
        self._push_song_undo(EditVideoClipsCommand(changes=dict(changes)))
        self.video_sync.refresh()
        self.engine.refresh_video_clips()
        self._mark_dirty()
        self.timeline.update()

    def _add_video_clip_at(self, seconds: float) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Add Video Clip",
            "",
            _MEDIA_DIALOG_FILTER,
        )
        if not path_str:
            return
        self._add_video_clip_from_path(Path(path_str), start_seconds=float(seconds))

    def _add_video_clip_from_path(self, path: Path, *, start_seconds: float) -> None:
        """Queue media probing; completion mutates Qt/domain state on the GUI thread."""
        self._add_video_clips_from_paths([path], start_seconds)

    def _finish_add_video_clip(
        self, path: Path, info: VideoInfo, *, start_seconds: float
    ) -> VideoClip:
        is_still = info.media_kind == "still"
        video_only = not self._song_has_main_audio_file()
        if is_still:
            duration = DEFAULT_STILL_CLIP_DURATION_SECONDS
            source_duration = 0.0
        else:
            source_duration = info.duration_seconds
            if video_only and source_duration > 0.05:
                # No music bed — use the full take so rehearsal marking has
                # the whole timeline (and Music-lane video waveform).
                duration = max(0.02, float(source_duration))
            else:
                duration = default_video_clip_duration(
                    source_duration,
                    self.current_song.duration_seconds,
                    start_seconds,
                )
        start = clip_start_after_body_drag(start_seconds, 0.0)
        clip = VideoClip.create(
            name=path.stem,
            path=path,
            start_seconds=start,
            duration_seconds=duration,
            media_kind="still" if is_still else "video",
            source_duration_seconds=source_duration,
        )
        self.current_song.add_video_clip(clip)
        # Video-only songs: song length follows the clip so the Music lane /
        # transport cover the whole rehearsal take.
        if video_only:
            self.current_song.duration_seconds = max(
                float(self.current_song.duration_seconds), float(clip.end_seconds)
            )
        self._push_song_undo(AddVideoClipsCommand(clips=[VideoClipSnapshot.from_clip(clip)]))
        self.video_sync.refresh()
        self.engine.refresh_video_clips()
        self.timeline.refresh_video_clip_waveforms()
        self.timeline.update()
        # Preview follows the audio clock — without a position tick after add,
        # the panel stays black until the user seeks/plays. Land the playhead
        # inside the new clip when needed, then force one decode.
        if not clip.contains(float(self.playback.position)):
            self.playback.seek(float(clip.start_seconds))
        else:
            self.video_sync.update_position(float(self.playback.position))
        if not self._song_has_main_audio_file():
            self.engine.set_duration(self.current_song.duration_seconds)
            self.transport.set_times(0.0, self.engine.duration)
            self._schedule_video_music_standin()
        self._mark_dirty()
        kind_label = "still image" if is_still else "video clip"
        msg = f"Added {kind_label}: {clip.name} ({duration:.2f}s)"
        if not is_still and source_needs_long_video_warning(
            duration_seconds=source_duration, path=path
        ):
            mins = source_duration / 60.0
            msg = (
                f"Added long video ({mins:.0f} min source) as {duration:.1f}s clip — "
                f"picture OK; waveform/scrub preload skipped; "
                f"embedded audio uses {HEAVY_VIDEO_AUDIO_DECODE_SECONDS:.0f}s windows"
            )
            self._warn_long_rehearsal_video(path, source_duration)
        elif not is_still and source_duration > max(
            600.0, self.current_song.duration_seconds * 2
        ):
            mins = source_duration / 60.0
            msg = (
                f"Added long video ({mins:.0f} min source) as {duration:.1f}s clip — "
                f"picture OK; embedded audio loads trim only "
                f"(max {MAX_VIDEO_AUDIO_DECODE_SECONDS / 60:.0f} min)"
            )
        self.status.showMessage(msg, 5000)
        return clip

    def _warn_long_rehearsal_video(self, path: Path, source_duration: float) -> None:
        mins = max(1.0, source_duration / 60.0)
        QMessageBox.information(
            self,
            "Long video loaded",
            (
                f"\"{path.name}\" is about {mins:.0f} minutes.\n\n"
                "CuePlayer will show picture + embedded audio for marking.\n"
                "Heavy waveform / scrub preload is skipped on long rehearsal "
                "files so opening Clean Output does not freeze the computer.\n\n"
                "Tip: Save the project (and MA work) before opening Clean Output "
                "on very large files. If picture looks soft, try Decode Quality "
                "Full; if the app feels heavy, use 720p."
            ),
        )

    def _add_video_clips_from_paths(self, paths: list, drop_seconds: object) -> None:
        """Probe dropped videos off-thread so even slow containers cannot freeze Qt."""
        requested = [Path(raw) for raw in paths]
        if not requested:
            return
        song_id = self.current_song.id
        start = float(drop_seconds)  # type: ignore[arg-type]
        self.status.showMessage(
            "Reading video info in background…" if len(requested) == 1
            else f"Reading {len(requested)} videos in background…",
            0,
        )

        def _job() -> None:
            results: list[tuple[Path, VideoInfo | Exception]] = []
            for path in requested:
                try:
                    results.append((path, probe_media(path)))
                except Exception as exc:  # noqa: BLE001
                    results.append((path, exc))
            self._video_probe_finished.emit((song_id, start, results))

        self._video_probe_executor.submit(_job)

    def _on_video_probe_finished(self, result: object) -> None:
        song_id, start, probed = result  # type: ignore[misc]
        if str(song_id) != self.current_song.id:
            self.status.showMessage("Video import cancelled because the song changed", 3000)
            return
        t = float(start)
        failures: list[tuple[Path, Exception]] = []
        added = 0
        for path, info in probed:
            if isinstance(info, Exception):
                failures.append((Path(path), info))
                continue
            clip = self._finish_add_video_clip(Path(path), info, start_seconds=t)
            t = clip.end_seconds
            added += 1
        if failures:
            names = ", ".join(path.name for path, _exc in failures[:3])
            detail = str(failures[0][1])
            QMessageBox.warning(
                self,
                "Unable to Load Media",
                f"Could not load {names}.\n\n{detail}",
            )
        elif added > 1:
            self.status.showMessage(f"Added {added} video clips", 5000)

    def _delete_video_clips(self, clip_ids: list) -> None:
        if not clip_ids:
            return
        wanted = set(str(c) for c in clip_ids)
        snapshots = [
            VideoClipSnapshot.from_clip(c) for c in self.current_song.video_clips if c.id in wanted
        ]
        removed = self.current_song.remove_video_clips_by_ids(wanted)
        if removed <= 0:
            return
        self._push_song_undo(DeleteVideoClipsCommand(clips=snapshots))
        self.timeline.set_selected_video_clip_ids([])
        self.video_sync.refresh()
        self.engine.refresh_video_clips()
        self.timeline.update()
        if not self._song_has_main_audio_file():
            self._schedule_video_music_standin()
        self._mark_dirty()
        self.status.showMessage(f"Deleted {removed} video clip(s)", 2500)

    def _split_video_clip(self, clip_id: str, at_seconds: float) -> None:
        clip = self.current_song.video_clip_by_id(clip_id)
        if clip is None or clip.locked:
            return
        if not (clip.start_seconds + 0.02 < at_seconds < clip.end_seconds - 0.02):
            self.status.showMessage("Move the playhead inside the clip to split", 2500)
            return
        old_transform = (clip.start_seconds, clip.source_in_seconds, clip.duration_seconds)
        first_duration = at_seconds - clip.start_seconds
        second = VideoClip.create(
            name=clip.name,
            path=clip.path,
            start_seconds=at_seconds,
            source_in_seconds=clip.source_in_seconds + first_duration,
            duration_seconds=clip.duration_seconds - first_duration,
            volume=clip.volume,
        )
        second.locked = clip.locked
        second.hidden = clip.hidden
        clip.duration_seconds = first_duration
        clip.source_out_seconds = clip.source_in_seconds + first_duration
        self.current_song.add_video_clip(second)
        self._push_song_undo(
            EditVideoClipsCommand(
                changes={
                    clip.id: (
                        old_transform,
                        (clip.start_seconds, clip.source_in_seconds, clip.duration_seconds),
                    )
                },
                label="Split Video Clip",
            )
        )
        self._push_song_undo(
            AddVideoClipsCommand(clips=[VideoClipSnapshot.from_clip(second)], label="Split Video Clip")
        )
        self.video_sync.refresh()
        self.engine.refresh_video_clips()
        self.timeline.update()
        self._mark_dirty()
        self.status.showMessage(f"Split clip at {at_seconds:.3f}s", 2500)

    def _duplicate_video_clip(self, clip_id: str) -> None:
        clip = self.current_song.video_clip_by_id(clip_id)
        if clip is None:
            return
        new_start = clip_start_after_body_drag(clip.end_seconds, 0.0)
        dup = VideoClip.create(
            name=f"{clip.name} copy",
            path=clip.path,
            start_seconds=new_start,
            source_in_seconds=clip.source_in_seconds,
            duration_seconds=clip.duration_seconds,
            volume=clip.volume,
        )
        dup.locked = clip.locked
        dup.hidden = clip.hidden
        self.current_song.add_video_clip(dup)
        self._push_song_undo(
            AddVideoClipsCommand(clips=[VideoClipSnapshot.from_clip(dup)], label="Duplicate Video Clip")
        )
        self.video_sync.refresh()
        self.engine.refresh_video_clips()
        self.timeline.update()
        self._mark_dirty()
        self.status.showMessage(f"Duplicated clip: {dup.name}", 2500)

    def _copy_video_clips(self) -> None:
        """Ctrl+C: snapshot the selected video clip(s) to an internal clipboard
        (path, in/out, source offset, volume, lock/hide — everything needed to
        recreate them). Silently a no-op with nothing selected."""
        if _text_input_has_focus():
            return
        ids = set(self.timeline.selected_video_clip_ids())
        if not ids:
            return
        clips = sorted(
            (c for c in self.current_song.video_clips if c.id in ids),
            key=lambda c: c.start_seconds,
        )
        if not clips:
            return
        self._video_clip_clipboard = [VideoClipSnapshot.from_clip(c) for c in clips]
        if len(clips) == 1:
            self.status.showMessage(f"Copied video clip: {clips[0].name}", 2000)
        else:
            self.status.showMessage(f"Copied {len(clips)} video clips", 2000)

    def _paste_video_clips(self) -> None:
        """Ctrl+V: paste the copied clip(s) at the playhead, preserving their
        relative spacing for a multi-clip copy. Undoable via AddVideoClipsCommand."""
        if _text_input_has_focus():
            return
        if not self._video_clip_clipboard:
            return
        anchor = min(snap.start_seconds for snap in self._video_clip_clipboard)
        paste_at = self.playback.position
        new_clips: list[VideoClip] = []
        for snap in self._video_clip_clipboard:
            offset = snap.start_seconds - anchor
            start = clip_start_after_body_drag(paste_at + offset, 0.0)
            clip = VideoClip.create(
                name=f"{snap.name} copy",
                path=Path(snap.path),
                start_seconds=start,
                source_in_seconds=snap.source_in_seconds,
                duration_seconds=snap.duration_seconds,
                volume=snap.volume,
                media_kind="still" if snap.media_kind == "still" else "video",
                source_duration_seconds=snap.source_duration_seconds,
            )
            clip.locked = snap.locked
            clip.hidden = snap.hidden
            new_clips.append(clip)
        for clip in new_clips:
            self.current_song.add_video_clip(clip)
        self._push_song_undo(
            AddVideoClipsCommand(
                clips=[VideoClipSnapshot.from_clip(c) for c in new_clips],
                label="Paste Video Clip" if len(new_clips) == 1 else "Paste Video Clips",
            )
        )
        self.timeline.set_selected_video_clip_ids([c.id for c in new_clips])
        self.video_sync.refresh()
        self.engine.refresh_video_clips()
        self.timeline.update()
        self._mark_dirty()
        if len(new_clips) == 1:
            self.status.showMessage(f"Pasted video clip: {new_clips[0].name}", 2500)
        else:
            self.status.showMessage(f"Pasted {len(new_clips)} video clips", 2500)

    def _add_mark_by_shortcut(self, shortcut: str) -> None:
        if shortcut in self._mark_shortcut_latch:
            return
        self._mark_shortcut_latch.add(shortcut)
        lane = self.current_song.lane_by_shortcut(shortcut)
        if lane is None:
            self.status.showMessage(f"Shortcut {shortcut} is not assigned to any mark in Mark Manager", 2500)
            return
        # Hidden Mark tracks (eye off / only 1–3 shown) must not accept shortcuts.
        if not lane.visible:
            self.status.showMessage(
                f"Mark track {shortcut} ({lane.name}) is hidden — show it to mark",
                2000,
            )
            return
        if not getattr(self.current_song, "show_mark_tracks", True):
            self.status.showMessage("Mark tracks are hidden — show them to mark", 2000)
            return
        self._add_mark(lane.index)

    def _add_mark(self, lane_index: int) -> None:
        lane = self.current_song.lane_by_index(lane_index)
        if lane is None or lane.locked:
            return
        # Belt-and-suspenders: never place on a hidden track (shortcut or click).
        if not lane.visible:
            return
        if not getattr(self.current_song, "show_mark_tracks", True):
            return
        # Use the visual playhead while scrubbing (engine still sits at press).
        # While playing, read the engine's interpolated write-head so marks are
        # not quantized to the audio-block grid (often 10ms → sticky ms digit).
        if self.playback.playing and not self.timeline.is_scrubbing():
            mark_at = float(self.playback.position)
        else:
            mark_at = self.timeline.playhead_seconds()
        mark = self.current_song.add_mark(lane_index, mark_at)
        self._push_song_undo(AddMarksCommand(marks=[MarkSnapshot.from_mark(mark)]))
        self._mark_dirty()
        self._refresh_marks_ui()
        paused = False
        if bool(getattr(lane, "pause_on_mark", False)) and self.playback.playing:
            self.playback.pause()
            paused = True
        if bool(getattr(lane, "prompt_note_on_mark", False)):
            text, ok = QInputDialog.getText(
                self,
                "Mark Note",
                f"Note for {lane.name}:",
                text=mark.display_name,
            )
            if ok:
                new_name = text.strip()
                if new_name != mark.display_name:
                    old_name = mark.display_name
                    mark.display_name = new_name
                    self._push_song_undo(
                        RenameMarkCommand(
                            mark_id=mark.id, old_name=old_name, new_name=new_name
                        )
                    )
                    self._mark_dirty()
                    self._refresh_marks_ui()
        lat_ms = self.engine.sync_offset_ms()
        self.status.showMessage(
            f"Marked: {lane.name} @ {mark.time_seconds:.3f}s"
            + (" · paused" if paused else "")
            + (f" · sync offset {lat_ms:.0f}ms" if abs(lat_ms) >= 0.5 else "")
            + " · edit directly in the Note column on the right",
            2500,
        )

    def _refresh_status(self) -> None:
        if self._media_warm_active:
            self._refresh_media_warm_status()
            return
        count = len(self.current_song.marks)
        lanes = len(self.current_song.mark_lanes)
        audio_name = self.current_song.audio_tracks[0].name if self.current_song.audio_tracks else "No audio"
        tc_flags = []
        if self.engine.ltc_enabled:
            mode = self.engine.ltc_source_mode
            if mode == "generator":
                if self.engine.audio_settings.ltc_generator_enabled:
                    tc_flags.append("LTC gen")
                else:
                    tc_flags.append("LTC gen off")
            elif mode == "auto":
                det = self.engine.detected_ltc_channel
                if det is not None:
                    side = "L" if det == 0 else "R"
                    tc_flags.append(f"LTC file {side}")
                else:
                    tc_flags.append("LTC auto?")
            elif mode == "source_left":
                tc_flags.append("LTC file L")
            elif mode == "source_right":
                tc_flags.append("LTC file R")
        if self.engine.mtc_enabled:
            tc_flags.append("MTC")
        tc_extra = (" · " + "+".join(tc_flags)) if tc_flags else ""
        self.status.showMessage(
            f"{self.project.name} · {self.current_song.name}"
            + (f" [{self.current_song.ma_export_name}]" if self.current_song.ma_export_name else "")
            + f" · TC {self.current_song.start_timecode} @ {self.current_song.fps:g}fps"
            + tc_extra
            + f" · {audio_name} · Marks tracks {lanes} · Cues {count}"
        )
