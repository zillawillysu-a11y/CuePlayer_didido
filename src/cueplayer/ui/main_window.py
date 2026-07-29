"""Main application window with waveform timeline and marking."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from PySide6.QtCore import QEvent, QModelIndex, QPoint, QRect, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QColor,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QFontMetrics,
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
from cueplayer.persistence.backup import (
    DEFAULT_KEEP,
    create_backup_before_save,
    list_backups,
)
from cueplayer.persistence.project_store import load_project, save_project
from cueplayer.media.ltc_detect import detect_ltc_channel
from cueplayer.ui.row_color import ROLE_ROW_COLOR
from cueplayer.ui.setlist_delegate import ROLE_LTC_CHANNEL, SetlistRowDelegate
from cueplayer.domain.undo import (
    AddMarksCommand,
    AddVideoClipsCommand,
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
    UndoContext,
    UndoStack,
    VideoClipSnapshot,
)
from cueplayer.media.audio_disk_cache import load_audio_cached, load_cached_audio, save_cached_audio
from cueplayer.media.audio_loader import AudioBuffer, ltc_waveform_display_buffer, waveform_display_buffer
from cueplayer.media.video_loader import probe_media
from cueplayer.media.video_audio_loader import MAX_VIDEO_AUDIO_DECODE_SECONDS
from cueplayer.playback.audio_engine import AudioEngine
from cueplayer.playback.jog import hold_step_frames
from cueplayer.playback.ndi_output import NdiVideoOutput
from cueplayer.playback.video_sync import VideoSyncController
from cueplayer.ui.audio_timecode_dialog import AudioTimecodeDialog
from cueplayer.ui.cue_monitor_panel import CueMonitorPanel
from cueplayer.ui.mark_display_dialog import MarkDisplayDialog
from cueplayer.ui.mark_manager_dialog import MarkManagerDialog
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
from cueplayer.ui.video_preview import VideoPreviewWidget

_AUDIO_SUFFIXES = AUDIO_SUFFIXES  # re-export for tests / callers
_MEDIA_DIALOG_FILTER = (
    "Video & Images (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.png *.jpg *.jpeg *.webp);;"
    "All Files (*.*)"
)
_SETTINGS_ORG = "CuePlayer"
_SETTINGS_APP = "CuePlayer"
MAIN_WINDOW_TITLE_PREFIX = "CuePlayer Main"
_KEY_AUTOSAVE_ENABLED = "autosave/enabled"
_KEY_AUTOSAVE_INTERVAL_SEC = "autosave/interval_seconds"
_KEY_BACKUP_KEEP = "autosave/backup_keep"
_KEY_CLEAN_OUTPUT_WAS_OPEN = "clean_output/was_open"
_KEY_CLEAN_OUTPUT_GEOMETRY = "clean_output/geometry"
_KEY_MAIN_GEOMETRY = "mainwindow/geometry"
_KEY_MAIN_STATE = "mainwindow/state"
_KEY_MAIN_SPLITTER = "ui/main_splitter"
_KEY_TIMELINE_SPLITTER = "ui/timeline_splitter"
_KEY_TIMELINE_PREVIEW_SPLITTER = "ui/timeline_preview_splitter"
_KEY_NOW_SPLITTER = "ui/now_splitter"
_KEY_NOW_SECONDARY_PLACEMENT = "ui/now_secondary_placement"
_KEY_NOW_SPLITTER_RIGHT = "ui/now_splitter_right"
_KEY_NOW_SPLITTER_BELOW = "ui/now_splitter_below"
_KEY_NOW_BODY_SPLITTER = "ui/now_body_splitter"
_KEY_VIEW_MODE = "ui/view_mode"
_KEY_LAST_PROJECT = "session/last_project_path"
_KEY_LAST_SONG_ID = "session/last_song_id"
_DEFAULT_AUTOSAVE_INTERVAL_SEC = 120


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


class SetlistWidget(QTableWidget):
    """Setlist: click No. to edit, drag rows to reorder, drop audio/video to add songs."""

    _TRIANGLE_HIT_MIN_PX = 28

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

    audio_files_dropped = Signal(list)
    audio_drop_rejected = Signal(str)
    rows_reordered = Signal(list, int)  # song ids in drag order, insert-before table row
    songs_moved_to_category = Signal(list, str)  # song ids, category id
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
        # All columns draggable — Song is Interactive (not Stretch) so edges can be pulled.
        header.setSectionsMovable(False)
        header.setStretchLastSection(True)
        header.setMinimumSectionSize(36)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.setColumnWidth(self.COL_NUM, 48)
        self.setColumnWidth(self.COL_TITLE, 160)
        self.setColumnWidth(self.COL_EN, 110)
        self.setColumnWidth(self.COL_BPM, 56)
        self.setColumnWidth(self.COL_LTC, 68)
        ltc_header = self.horizontalHeaderItem(self.COL_LTC)
        if ltc_header is not None:
            ltc_header.setToolTip(
                "Striped LTC badge (L/R) when file timecode is detected or set in Edit → File LTC"
            )
        self.setColumnHidden(2, True)
        self.setColumnHidden(3, False)
        self.verticalHeader().setDefaultSectionSize(28)
        self.setToolTip(
            "Double-click No./Name/BPM to edit; drag column edges to resize; "
            "right-click for categories and full editor; "
            "drag to reorder or drop songs onto a folder; drop audio/video to add songs; "
            "Ctrl/Shift to multi-select"
        )
        self.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._block_number_signal = False
        self._drag_song_ids: list[str] = []
        self._insert_indicator_row: int | None = None
        self._name_mode = "zh"
        self._show_bpm = True
        self.itemChanged.connect(self._on_item_changed)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.viewport().setAcceptDrops(True)

    def set_name_mode(self, mode: str) -> None:
        """zh = Chinese · both = Chinese + English · en = English."""
        if mode not in ("zh", "both", "en"):
            mode = "zh"
        self._name_mode = mode
        if mode == "both":
            self.setHorizontalHeaderLabels(["No.", "Song", "English", "BPM", ""])
            self.setColumnHidden(self.COL_EN, False)
        elif mode == "en":
            self.setHorizontalHeaderLabels(["No.", "English", "English", "BPM", ""])
            self.setColumnHidden(self.COL_EN, True)
        else:
            self.setHorizontalHeaderLabels(["No.", "Song", "English", "BPM", ""])
            self.setColumnHidden(self.COL_EN, True)
        self.setColumnHidden(self.COL_BPM, not self._show_bpm)

    def set_show_bpm(self, visible: bool) -> None:
        self._show_bpm = bool(visible)
        self.setColumnHidden(self.COL_BPM, not self._show_bpm)

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
            from cueplayer.media.bpm_analyzer import parse_bpm_cell

            parsed = parse_bpm_cell(item.text())
            if parsed is False:
                self.song_bpm_edit_failed.emit(item.row())
                return
            self.song_bpm_edited.emit(item.row(), parsed)

    def startDrag(self, supportedActions) -> None:  # noqa: N802, ANN001
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

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
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
                    return
        super().mousePressEvent(event)

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
            self._set_insert_indicator(self._insert_row_at(event.position().toPoint()))
            return
        if mime_looks_like_file_drop(event.mimeData()):
            accept_file_drag(event)
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        if event.source() is self:
            accept_file_drag(event)
            self._set_insert_indicator(self._insert_row_at(event.position().toPoint()))
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
        drop_row = self._insert_row_at(pos)
        ids = list(self._drag_song_ids)
        self._drag_song_ids = []
        if not ids:
            event.ignore()
            return
        # CopyAction: Qt must not delete source rows (MoveAction clears the list).
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        drop_index = self.indexAt(pos)
        if drop_index.isValid() and self.row_kind(drop_index.row()) == "category":
            cat_id = self.row_category_id(drop_index.row())
            if cat_id:
                self.songs_moved_to_category.emit(ids, cat_id)
                return
        self.rows_reordered.emit(ids, drop_row)


class MainWindow(QMainWindow):
    _setlist_ltc_cache_updated = Signal()
    _bpm_detected = Signal(str, object)  # song_id, float | None
    startup_ready = Signal()

    def __init__(self, project: Project | None = None) -> None:
        super().__init__()
        self.startup_session_ready = False
        self.project = project or Project.create("Untitled Project")
        if not self.project.songs:
            self.project.songs.append(self.project.new_song("Untitled Song"))
        self.current_song = self.project.songs[0]
        self._project_path: Path | None = None
        self._dirty = False
        self._digit_shortcuts: list[QShortcut] = []
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
        self._audio_prefetch_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ui-audio-prefetch")
        self._audio_load_token = 0
        self._pending_audio_load: tuple | None = None
        self._audio_buffer_cache: dict[tuple[str, int, int], AudioBuffer] = {}
        self._audio_ltc_cache: dict[tuple[str, int, int], int | None] = {}
        self._audio_ltc_inflight: dict[tuple[str, int, int], object] = {}
        self._timeline_ltc_exclude: int | None = None
        self._audio_inflight: dict[tuple[str, int, int], object] = {}
        self._ltc_detect_executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="ui-ltc-detect"
        )
        self._setlist_ltc_cache_updated.connect(self._refresh_setlist_ltc_cells)
        self._bpm_detect_inflight: set[str] = set()
        self._bpm_detected.connect(self._on_bpm_detected)
        self._audio_load_timer = QTimer(self)
        self._audio_load_timer.setInterval(25)
        self._audio_load_timer.timeout.connect(self._poll_pending_audio_load)
        self._block_clean_output_visibility_persist = False

        self.engine = AudioEngine(self)
        self.engine.set_duration(self.current_song.duration_seconds)
        self.engine.set_song_timebase(
            self.current_song.start_timecode, self.current_song.fps
        )
        self.engine.apply_audio_settings(self.project.audio_output)

        # Video clips are driven by the audio sample clock (AudioEngine) —
        # no independent video timer (AGENTS.md non-negotiable).
        self.video_sync = VideoSyncController(self)
        self.video_sync.set_decode_quality(self.project.video_decode_quality)
        self.video_sync.set_song(self.current_song)
        self.engine.set_song(self.current_song)
        self.video_preview = VideoPreviewWidget()
        # Parented to MainWindow for object lifetime, but Qt.Window still makes
        # this a separate top-level capture target for OBS. Its X button only
        # hides (see CleanVideoOutputWindow.closeEvent); MainWindow.closeEvent()
        # must force-close it so the process can exit.
        self.clean_output_window = CleanVideoOutputWindow(self)
        self.clean_output_window.apply_settings(self.project.clean_video_output)
        self._ndi_output = NdiVideoOutput()

        self.setWindowTitle(f"{MAIN_WINDOW_TITLE_PREFIX} — {self.project.name}")
        self.resize(1600, 900)

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
        self.song_list.set_show_bpm(self.project.setlist_show_bpm)
        self._rebuild_song_list(select_indexes=[0])
        song_btns = QHBoxLayout()
        song_btns.setContentsMargins(0, 0, 0, 0)
        song_btns.setSpacing(4)
        self.add_song_button = QPushButton("Add")
        self.edit_song_button = QPushButton("Edit")
        self.delete_song_button = QPushButton("Delete")
        self.add_song_button.setToolTip("Add a new song")
        self.edit_song_button.setToolTip(
            "Full edit: number / name / English MA / BPM / Timecode / FPS (or right-click → Edit)"
        )
        self.delete_song_button.setToolTip("Delete selected song(s)")
        song_btns.addWidget(self.add_song_button)
        song_btns.addWidget(self.edit_song_button)
        song_btns.addWidget(self.delete_song_button)

        order_btns = QHBoxLayout()
        order_btns.setContentsMargins(0, 0, 0, 0)
        order_btns.setSpacing(4)
        self.move_up_button = QPushButton("↑")
        self.move_down_button = QPushButton("↓")
        self.sort_by_number_button = QPushButton("Sort by Number")
        self.renumber_button = QPushButton("Renumber")
        self.move_up_button.setFixedWidth(32)
        self.move_down_button.setFixedWidth(32)
        self.move_up_button.setToolTip("Move selected song(s) up")
        self.move_down_button.setToolTip("Move selected song(s) down")
        self.sort_by_number_button.setToolTip(
            "Sort songs by # within Main list, a folder, or All"
        )
        self.renumber_button.setToolTip(
            "Renumber to 1, 2, 3… within Main list, a folder, or All"
        )
        order_btns.addWidget(self.move_up_button)
        order_btns.addWidget(self.move_down_button)
        order_btns.addWidget(self.sort_by_number_button)
        order_btns.addWidget(self.renumber_button)

        left_layout.addLayout(title_row)
        left_layout.addWidget(self.song_list, stretch=1)
        left_layout.addLayout(song_btns)
        left_layout.addLayout(order_btns)

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
        self._timeline_scroll.setWidget(self.timeline)
        self.timeline.content_geometry_changed.connect(self._sync_timeline_geometry)
        self._timeline_scroll.viewport().installEventFilter(self)
        center_layout.addWidget(self._timeline_scroll, stretch=1)

        # Center column: Timeline (waveform + video lane + mark lanes) on top,
        # Video Preview directly underneath — not stacked under the Cue list.
        self.video_preview_panel = QWidget()
        self.video_preview_panel.setObjectName("videoPreviewPanel")
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
        timeline_preview_split.setCollapsible(0, False)
        timeline_preview_split.setCollapsible(1, True)
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

        splitter.addWidget(left)
        splitter.addWidget(self.view_stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 1340])

        root_layout.addWidget(self.toolbar)
        root_layout.addWidget(splitter, stretch=1)
        root_layout.addWidget(self.transport)
        self.setCentralWidget(root)

        self.status = QStatusBar(self)
        self.setStatusBar(self.status)
        self._settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        self._build_file_menu()
        self._setup_autosave()
        self._refresh_window_title()
        self._refresh_status()

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
        self.transport.play_clicked.connect(self.engine.play)
        self.transport.pause_clicked.connect(self.engine.pause)
        self.transport.stop_clicked.connect(self.engine.stop)
        self.toolbar.view_mode_changed.connect(self._set_view_mode)
        self.show_patch_page.settings_changed.connect(self._mark_dirty)
        self.show_patch_page.export_finished.connect(self._on_ma_export_finished)
        self.setlist_sheet_page.song_field_changed.connect(self._on_setlist_sheet_changed)
        self.setlist_sheet_page.sheet_layout_changed.connect(self._mark_dirty)
        self.transport.set_loop_a_clicked.connect(self._set_loop_a)
        self.transport.set_loop_b_clicked.connect(self._set_loop_b)
        self.transport.clear_loop_clicked.connect(self._clear_loop)
        self.transport.loop_toggled.connect(self._set_loop_enabled)
        self.transport.volume_changed.connect(self.engine.set_volume)
        self.timeline.seek_requested.connect(self.engine.seek)
        self.timeline.scrub_started.connect(self.engine.begin_scrub)
        self.timeline.scrub_ended.connect(self.engine.end_scrub)
        # Throttle video decode while the playhead is actively being
        # dragged — see VideoSyncController.set_scrubbing(). Mid-drag
        # preview uses scrub_preview_requested (not full engine seek).
        self.timeline.scrub_started.connect(lambda: self.video_sync.set_scrubbing(True))
        self.timeline.scrub_ended.connect(lambda: self.video_sync.set_scrubbing(False))
        self.timeline.scrub_preview_requested.connect(self.video_sync.update_position)
        self.timeline.selection_changed.connect(self._on_timeline_selection)
        self.timeline.delete_requested.connect(self._delete_marks)
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
        self.timeline.video_clip_volume_changed.connect(self._on_video_clip_volume_changed)
        self.timeline.music_volume_changed.connect(self._on_music_volume_changed)
        self.timeline.lane_name_changed.connect(self._on_mark_lane_renamed)
        self.engine.position_changed.connect(self.video_sync.update_position)
        # Throttles video decode to a display cadence while playing, so the
        # audio clock's ~60Hz position ticks can't starve the UI thread the
        # timeline also lives on — see VideoSyncController.set_playing().
        self.engine.playing_changed.connect(self.video_sync.set_playing)
        self.video_sync.frame_changed.connect(self.video_preview.set_frame)
        self.video_sync.frame_changed.connect(self.clean_output_window.set_frame)
        self.video_sync.frame_changed.connect(self._ndi_output.send_frame)
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
        self.monitor.now_visibility_changed.connect(self._mark_dirty)
        self.monitor.cue_list_visibility_changed.connect(self._mark_dirty)
        self.monitor.cue_list_layout_changed.connect(self._mark_dirty)
        self.monitor.now_layout_changed.connect(self._on_now_layout_changed)
        self.monitor.renumber_cue_ids_requested.connect(self._renumber_main_cue_ids)
        self.engine.position_changed.connect(self._on_position_changed)
        self.engine.playing_changed.connect(self.transport.set_playing)
        self.engine.playing_changed.connect(self.timeline.set_playing)
        self.engine.timecode_status_changed.connect(self._refresh_timecode_status)
        self.engine.timecode_status_changed.connect(self._refresh_setlist_ltc_cells)
        self._refresh_timecode_status()

        QShortcut(QKeySequence(Qt.Key.Key_Space), self, activated=self.engine.toggle)
        QShortcut(QKeySequence(Qt.Key.Key_Left), self, activated=lambda: self._nudge_frames(-1))
        QShortcut(QKeySequence(Qt.Key.Key_Right), self, activated=lambda: self._nudge_frames(1))
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self, activated=self._delete_current_selection)
        QShortcut(QKeySequence(Qt.Key.Key_Backspace), self, activated=self._delete_current_selection)
        QShortcut(QKeySequence.StandardKey.Undo, self, activated=self._undo_action)
        QShortcut(QKeySequence.StandardKey.Redo, self, activated=self._redo_action)
        QShortcut(QKeySequence.StandardKey.Copy, self, activated=self._copy_video_clips)
        QShortcut(QKeySequence.StandardKey.Paste, self, activated=self._paste_video_clips)
        self._rebuild_digit_shortcuts()

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
                self.monitor.ensure_now_splitter_ready()
                QTimer.singleShot(0, self.monitor.ensure_now_splitter_ready)
                QTimer.singleShot(100, self.monitor.ensure_now_splitter_ready)
            except Exception:  # noqa: BLE001
                import traceback

                traceback.print_exc()
        finally:
            self._restoring_session = False
            # Let queued splitter/layout timers settle, then tell the splash we are ready.
            def _emit_ready() -> None:
                self.startup_session_ready = True
                self.startup_ready.emit()

            QTimer.singleShot(0, _emit_ready)

    def _restore_ui_layout(self) -> None:
        geometry = self._settings.value(_KEY_MAIN_GEOMETRY)
        if geometry:
            self.restoreGeometry(geometry)
        else:
            self.resize(1600, 900)
        state = self._settings.value(_KEY_MAIN_STATE)
        if state:
            self.restoreState(state)
        main_split = getattr(self, "_main_splitter", None)
        if main_split is not None:
            raw = self._settings.value(_KEY_MAIN_SPLITTER)
            if raw:
                main_split.restoreState(raw)
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
        placement = str(self._settings.value(_KEY_NOW_SECONDARY_PLACEMENT, "right") or "right")
        payload = {
            "placement": placement,
            "right": self._settings.value(_KEY_NOW_SPLITTER_RIGHT),
            "below": self._settings.value(_KEY_NOW_SPLITTER_BELOW),
            "current": self._settings.value(_KEY_NOW_SPLITTER),
            "body": self._settings.value(_KEY_NOW_BODY_SPLITTER),
        }
        self.monitor.restore_now_splitter_state(payload)
        mode = str(self._settings.value(_KEY_VIEW_MODE, "timeline") or "timeline")
        if mode == "ma_patch":
            self.toolbar.set_view_mode("ma_patch")
            self._set_view_mode("ma_patch")
        elif mode == "setlist":
            self.toolbar.set_view_mode("setlist")
            self._set_view_mode("setlist")

    def _save_ui_session(self) -> None:
        if self._restoring_session:
            return
        self._settings.setValue(_KEY_MAIN_GEOMETRY, self.saveGeometry())
        self._settings.setValue(_KEY_MAIN_STATE, self.saveState())
        main_split = getattr(self, "_main_splitter", None)
        if main_split is not None:
            self._settings.setValue(_KEY_MAIN_SPLITTER, main_split.saveState())
        timeline_split = getattr(self, "_timeline_split", None)
        if timeline_split is not None:
            self._settings.setValue(_KEY_TIMELINE_SPLITTER, timeline_split.saveState())
        preview_split = getattr(self, "_timeline_preview_split", None)
        if preview_split is not None:
            self._settings.setValue(
                _KEY_TIMELINE_PREVIEW_SPLITTER, preview_split.saveState()
            )
        layout_state = self.monitor.save_now_splitter_state()
        self._settings.setValue(_KEY_NOW_SECONDARY_PLACEMENT, layout_state["placement"])
        self._settings.setValue(_KEY_NOW_SPLITTER, layout_state["current"])
        self._settings.setValue(_KEY_NOW_SPLITTER_RIGHT, layout_state["right"])
        self._settings.setValue(_KEY_NOW_SPLITTER_BELOW, layout_state["below"])
        self._settings.setValue(_KEY_NOW_BODY_SPLITTER, layout_state.get("body"))
        mode = "timeline"
        stack_index = self.view_stack.currentIndex()
        if stack_index == 1:
            mode = "ma_patch"
        elif stack_index == 2:
            mode = "setlist"
        self._settings.setValue(_KEY_VIEW_MODE, mode)
        if self._project_path is not None:
            self._settings.setValue(_KEY_LAST_PROJECT, str(self._project_path))
            self._settings.setValue(_KEY_LAST_SONG_ID, self.current_song.id)
        self._settings.setValue(
            _KEY_CLEAN_OUTPUT_GEOMETRY, self.clean_output_window.saveGeometry()
        )

    def _try_restore_last_project(self) -> bool:
        if self._project_path is not None:
            return False
        raw = self._settings.value(_KEY_LAST_PROJECT)
        if not raw:
            return False
        path = Path(str(raw))
        if not path.is_file():
            return False
        song_id = self._settings.value(_KEY_LAST_SONG_ID)
        song_id_str = str(song_id) if song_id else None
        if self._open_project_path(path, song_id=song_id_str, quiet=True):
            self.status.showMessage(f"Restored: {path.name}", 3500)
            return True
        return False

    def _open_project_path(
        self, path: Path, *, song_id: str | None = None, quiet: bool = False
    ) -> bool:
        try:
            project = load_project(path)
        except Exception as exc:  # noqa: BLE001
            if quiet:
                self.status.showMessage(f"Could not reopen last project: {exc}", 6000)
            else:
                QMessageBox.warning(self, "Unable to Open Project", str(exc))
            return False
        self.engine.stop()
        self.project = project
        self._project_path = path
        self._apply_project(preferred_song_id=song_id)
        self._set_clean()
        return True

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

    def _sync_video_output_active(self) -> None:
        """Skip video decode when neither Preview, Clean Output, nor NDI needs frames."""
        if not hasattr(self, "video_preview_panel"):
            return
        active = (
            self._video_preview_visible()
            or self._clean_output_visible()
            or bool(self.project.clean_video_output.ndi_enabled)
        )
        self.video_sync.set_video_output_active(active)

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
        self._autosave_action = QAction("Auto-&Save", self)
        self._autosave_action.setCheckable(True)
        self._autosave_action.setChecked(self._autosave_enabled())
        self._autosave_action.setToolTip(
            f"Automatically save dirty projects every "
            f"{self._autosave_interval_seconds()}s (only after Save As)"
        )
        self._autosave_action.toggled.connect(self._set_autosave_enabled)
        menu.addAction(self._autosave_action)
        act_restore = QAction("&Restore from Backup…", self)
        act_restore.setToolTip(
            "Open a timestamped copy from .cueplayer_backups next to this project"
        )
        act_restore.triggered.connect(self._file_restore_backup)
        menu.addAction(act_restore)
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
        act_manager = QAction("&Manager", self)
        act_manager.triggered.connect(self._open_mark_manager)
        act_display = QAction("&Display Settings…", self)
        act_display.triggered.connect(self._open_display_settings)
        act_audio = QAction("&Audio / Timecode…", self)
        act_audio.triggered.connect(self._open_audio_timecode)
        tools_menu.addAction(act_manager)
        tools_menu.addAction(act_display)
        tools_menu.addSeparator()
        tools_menu.addAction(act_audio)
        tools_menu.addSeparator()
        act_add_video = QAction("Add &Video Clip…", self)
        act_add_video.triggered.connect(lambda: self._add_video_clip_at(self.engine.position))
        tools_menu.addAction(act_add_video)
        act_video_preview = QAction("Video &Preview Panel", self)
        act_video_preview.setCheckable(True)
        act_video_preview.setChecked(True)
        act_video_preview.triggered.connect(self._toggle_video_preview_panel)
        tools_menu.addAction(act_video_preview)
        self._act_video_preview = act_video_preview
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
        tools_menu.addAction(self._show_video_track_action)
        self._clean_output_action = QAction("&Clean Video Output", self)
        self._clean_output_action.setCheckable(True)
        self._clean_output_action.triggered.connect(self._toggle_clean_output)
        tools_menu.addAction(self._clean_output_action)
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
        tools_menu.addAction(self._ndi_output_action)
        act_ndi_name = QAction("NDI Source &Name…", self)
        act_ndi_name.setToolTip("Custom NDI name so Depence does not pick the wrong feed")
        act_ndi_name.triggered.connect(self._prompt_ndi_name)
        tools_menu.addAction(act_ndi_name)
        self._build_video_decode_quality_menu(tools_menu)

    def _autosave_enabled(self) -> bool:
        return bool(self._settings.value(_KEY_AUTOSAVE_ENABLED, True, type=bool))

    def _autosave_interval_seconds(self) -> int:
        raw = self._settings.value(
            _KEY_AUTOSAVE_INTERVAL_SEC, _DEFAULT_AUTOSAVE_INTERVAL_SEC
        )
        try:
            seconds = int(raw)
        except (TypeError, ValueError):
            seconds = _DEFAULT_AUTOSAVE_INTERVAL_SEC
        return max(15, seconds)

    def _backup_keep_count(self) -> int:
        raw = self._settings.value(_KEY_BACKUP_KEEP, DEFAULT_KEEP)
        try:
            keep = int(raw)
        except (TypeError, ValueError):
            keep = DEFAULT_KEEP
        return max(1, keep)

    def _set_autosave_enabled(self, enabled: bool) -> None:
        self._settings.setValue(_KEY_AUTOSAVE_ENABLED, bool(enabled))
        self._setup_autosave()

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
            self._autosave_timer.stop()

    def _autosave_tick(self) -> None:
        if not self._autosave_enabled():
            return
        if not self._dirty or self._project_path is None:
            return
        self._file_save(quiet=True)

    def _backup_before_overwrite(self, path: Path) -> None:
        try:
            create_backup_before_save(path, keep=self._backup_keep_count())
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

    def _toggle_video_preview_panel(self, visible: bool) -> None:
        split = getattr(self, "_timeline_preview_split", None)
        if split is None:
            self.video_preview_panel.setVisible(visible)
            self._sync_video_output_active()
            return
        if visible:
            total = split.height()
            split.setSizes([max(100, total * 3 // 5), max(120, total * 2 // 5)])
        else:
            total = split.height()
            split.setSizes([total, 0])
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
        if self._dirty:
            return
        self._dirty = True
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

    def _set_clean(self) -> None:
        self._dirty = False
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
        if len(self.project.songs) != 1:
            return False
        song = self.project.songs[0]
        if (song.name or "").strip() not in ("Untitled Song", ""):
            return False
        if song.audio_tracks or song.video_clips or song.marks:
            return False
        if self.project.setlist_categories:
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
        self.engine.stop()
        self.project = Project.create("Untitled Project")
        self._project_path = None
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
        self._backup_before_overwrite(self._project_path)
        try:
            save_project(self.project, self._project_path)
        except Exception as exc:  # noqa: BLE001
            if not quiet:
                QMessageBox.warning(self, "Unable to Save Project", str(exc))
            else:
                self.status.showMessage(f"Auto-save failed: {exc}", 5000)
            return False
        self._set_clean()
        label = "Auto-saved" if quiet else "Saved"
        self.status.showMessage(f"{label}: {self._project_path.name}", 2500)
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
        path = Path(path_str)
        name_lower = path.name.lower()
        if name_lower.endswith(".cueplayer.json"):
            pass
        elif path.suffix.lower() == ".json":
            path = path.with_name(f"{path.stem}.cueplayer.json")
        else:
            path = path.with_name(f"{path.name}.cueplayer.json")
        self.project.clean_video_output = self.clean_output_window.current_settings()
        self.project.video_decode_quality = self.video_sync.decode_quality()
        # Overwriting an existing path (or re-Save-As to the same file) still
        # gets a backup of whatever was previously on disk.
        self._backup_before_overwrite(path)
        try:
            save_project(self.project, path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Unable to Save Project", str(exc))
            return False
        self._project_path = path
        stem = path.name
        if stem.endswith(".cueplayer.json"):
            self.project.name = stem[: -len(".cueplayer.json")] or self.project.name
        else:
            self.project.name = path.stem or self.project.name
        self._set_clean()
        self._refresh_status()
        self.status.showMessage(f"Saved: {path.name}", 2500)
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
        self.engine.stop()
        self.project = project
        # Keep pointing at the live project path so the next Save writes there
        # (and takes a fresh backup of whatever is currently on disk).
        self._apply_project()
        self._mark_dirty()
        self.status.showMessage(f"Restored backup into editor: {path.name}", 4500)

    def _apply_project(self, *, preferred_song_id: str | None = None) -> None:
        self._undo.clear()
        if not self.project.songs:
            self.project.songs.append(self.project.new_song("Untitled Song"))
        self.show_patch_page.set_project(self.project)
        self.setlist_sheet_page.set_project(self.project)
        self._sync_setlist_name_mode_ui()
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
        self.timeline.set_show_video_track(self.project.show_video_track, emit=False)
        song_index = 0
        if preferred_song_id:
            for i, song in enumerate(self.project.songs):
                if song.id == preferred_song_id:
                    song_index = i
                    break
        self._rebuild_song_list(select_indexes=[song_index])
        self._activate_song(song_index, stop_playback=True)
        self._warm_project_audio_on_open()

    def _warm_project_audio_on_open(self) -> None:
        """Background-decode / disk-load every setlist song once when a project opens."""
        paths = [
            p
            for song in self.project.songs
            if (p := self._main_audio_path_for_song(song)) is not None
        ]
        if not paths:
            return
        ready = sum(1 for p in paths if self._cached_audio_buffer(p) is not None)
        if ready < len(paths):
            self.status.showMessage(
                f"Preparing audio cache ({ready}/{len(paths)} ready)…", 0
            )
        self._prefetch_setlist_audio()

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
        self.song_list.set_show_bpm(self.project.setlist_show_bpm)

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
        self.song_list.blockSignals(True)
        self.song_list._block_number_signal = True  # noqa: SLF001
        display_rows = self._setlist_display_rows()
        self.song_list.clearSpans()
        self.song_list.setRowCount(len(display_rows))
        mode = self.project.setlist_name_mode
        if mode not in ("zh", "both", "en"):
            mode = "zh"
        self.song_list.set_name_mode(mode)
        self.song_list.set_show_bpm(self.project.setlist_show_bpm)
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
                folder_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                folder_item.setToolTip(
                    "Click ▸/▾ to expand or collapse · double-click folder name to rename · "
                    "right-click for more · drag songs here to file them in this folder"
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
            if song.bpm is not None and float(song.bpm) > 0:
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
            if song.bpm is not None and song.bpm_auto:
                from cueplayer.ui.theme import TEXT_MUTED

                bpm_item.setForeground(QColor(TEXT_MUTED))
                bpm_item.setToolTip(
                    "Auto-detected BPM (gray <n>). Type your value to override."
                )
            else:
                bpm_item.setToolTip("Double-click to enter BPM (blank = not set)")
            self.song_list.setItem(table_row, SetlistWidget.COL_BPM, bpm_item)

            ltc_channel = self._ltc_channel_for_song(song)
            ltc_item = QTableWidgetItem("")
            ltc_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsDragEnabled
            )
            ltc_item.setData(SetlistWidget.ROLE_LTC_CHANNEL, ltc_channel)
            if ltc_channel == 0:
                ltc_item.setToolTip("Striped LTC detected on Left channel")
            elif ltc_channel == 1:
                ltc_item.setToolTip("Striped LTC detected on Right channel")
            self.song_list.setItem(table_row, SetlistWidget.COL_LTC, ltc_item)
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
        song.bpm = draft.bpm
        # Dialog value is always a user choice (including blank → clear auto).
        song.bpm_auto = False
        song.start_timecode = draft.start_timecode
        song.fps = draft.fps
        from cueplayer.domain.models import coerce_file_ltc_side

        song.file_ltc_side = coerce_file_ltc_side(getattr(draft, "file_ltc_side", "off"))
        if draft.audio_path is not None and Path(draft.audio_path).is_file():
            song.audio_tracks = [
                AudioTrack(
                    id="main_audio",
                    name=Path(draft.audio_path).stem,
                    path=Path(draft.audio_path),
                    role="main",
                )
            ]
            if song.bpm is None:
                self._schedule_bpm_detect_for_song(song, Path(draft.audio_path))
        else:
            song.audio_tracks = []
        if draft.video_path is not None and Path(draft.video_path).is_file():
            self._attach_video_source_to_song(song, Path(draft.video_path), replace_clips=True)
        else:
            song.video_clips = []
        if song is self.current_song:
            self.engine.set_song_timebase(song.start_timecode, song.fps)
            self.engine.set_song(song)
            self.engine.refresh_song_ltc_routing()
            self._refresh_setlist_ltc_cells()
            self._refresh_timeline_waveform_for_ltc()
            self._refresh_timecode_status()

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
        self.status.showMessage(f'Song name changed to "{name}"', 2000)

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

    def _add_setlist_column_actions(self, menu: QMenu) -> tuple[QAction, QAction]:
        en_action = menu.addAction("Song English")
        en_action.setCheckable(True)
        en_action.setChecked(self.project.setlist_name_mode in ("both", "en"))
        en_action.setToolTip("Show the English / MA name column")
        bpm_action = menu.addAction("Song BPM")
        bpm_action.setCheckable(True)
        bpm_action.setChecked(bool(self.project.setlist_show_bpm))
        bpm_action.setToolTip("Show the BPM column")
        return en_action, bpm_action

    def _apply_setlist_column_action(
        self,
        chosen: QAction | None,
        *,
        en_action: QAction,
        bpm_action: QAction,
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
        return False

    def _on_setlist_header_context_menu(self, pos) -> None:  # noqa: ANN001
        menu = QMenu(self)
        en_action, bpm_action = self._add_setlist_column_actions(menu)
        chosen = menu.exec(self.song_list.horizontalHeader().mapToGlobal(pos))
        self._apply_setlist_column_action(
            chosen, en_action=en_action, bpm_action=bpm_action
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
        en_action, bpm_action = self._add_setlist_column_actions(menu)
        menu.addSeparator()
        renumber_action = menu.addAction("Renumber")
        set_numbers_action = menu.addAction("Set Numbers Starting at…")
        menu.addSeparator()
        up_action = menu.addAction("Move Up")
        down_action = menu.addAction("Move Down")
        menu.addSeparator()
        delete_action = menu.addAction("Delete")
        has_selection = bool(self._selected_song_indexes()) or self.song_list.currentRow() >= 0
        selected_songs = self._selected_songs()
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
        delete_action.setEnabled(has_selection and len(self.project.songs) > 1)
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
            chosen, en_action=en_action, bpm_action=bpm_action
        ):
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
        self.status.showMessage("Song order updated by drag", 2000)

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
            f'Moved {len(moving)} song(s) into "{category.name}"',
            2500,
        )

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

    def _add_setlist_category(self) -> None:
        name, ok = QInputDialog.getText(self, "New Setlist Folder", "Folder name:")
        if not ok:
            return
        category = SetlistCategory.create(name)
        with self._setlist_edit("New Folder"):
            self.project.setlist_categories.append(category)
            self._rebuild_song_list(select_indexes=self._selected_song_indexes() or None)
            self._mark_dirty()
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
        self.status.showMessage(f'Renamed folder to "{category.name}"', 2500)

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
        with self._setlist_edit("Delete Folder"):
            for song in self.project.songs:
                if song.category_id == category.id:
                    song.category_id = None
            self.project.setlist_categories = [
                c for c in self.project.setlist_categories if c.id != category.id
            ]
            self._rebuild_song_list(select_indexes=self._selected_song_indexes() or None)
            self._mark_dirty()
        self.status.showMessage(f'Deleted folder "{category.name}"', 2500)

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
            self.status.showMessage("Moved song(s) out of folder", 2000)
            return
        category = self.project.setlist_category_by_id(category_id)
        label = category.name if category is not None else "folder"
        self.status.showMessage(f'Moved song(s) into "{label}"', 2000)

    def _on_setlist_category_context_menu(self, category_id: str, pos) -> None:  # noqa: ANN001
        category = self.project.setlist_category_by_id(category_id)
        if category is None:
            return
        menu = QMenu(self)
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
        if chosen is rename_action:
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
        if index < 0 or index >= len(self.project.songs):
            return
        self._audio_load_token += 1
        if stop_playback:
            self.engine.stop()
        self.current_song = self.project.songs[index]
        self._sync_undo_context()
        self.engine.clear_loop()
        self._sync_loop_ui()
        self.timeline.clear_selection(emit=False)
        self.monitor.set_selected_mark_ids([])
        self.timeline.set_song(self.current_song)
        self._apply_project_mark_line_settings()
        self.monitor.set_song(self.current_song)
        self.video_sync.set_song(self.current_song)
        self.engine.set_song(self.current_song)
        action = getattr(self, "_show_video_track_action", None)
        if action is not None:
            action.blockSignals(True)
            action.setChecked(bool(self.project.show_video_track))
            action.blockSignals(False)
        # Keep timeline eye in sync with project-global preference across songs.
        self.timeline.set_show_video_track(self.project.show_video_track, emit=False)
        self._rebuild_digit_shortcuts()
        self.engine.set_song_timebase(
            self.current_song.start_timecode, self.current_song.fps
        )
        main_audio = next(
            (t for t in self.current_song.audio_tracks if t.role == "main"),
            self.current_song.audio_tracks[0] if self.current_song.audio_tracks else None,
        )
        if main_audio is not None and Path(main_audio.path).is_file():
            audio_path = Path(main_audio.path)
            cached = self._cached_audio_buffer(audio_path)
            if cached is not None:
                self.timeline.set_audio_loading(False)
                self._apply_loaded_audio(
                    cached,
                    audio_path,
                    mark_dirty=False,
                    replace_track=False,
                    refresh_song_widgets=False,
                )
            else:
                self.engine.set_buffer(None)
                self._timeline_ltc_exclude = None
                self.timeline.set_audio_loading(True, audio_path.name)
                self._load_audio_path(
                    audio_path, mark_dirty=False, replace_track=False, bump_token=False
                )
            self._prefetch_setlist_audio(skip_path=audio_path)
        else:
            self.engine.set_buffer(None)
            self._timeline_ltc_exclude = None
            self.timeline.set_audio(None)
            self.timeline.set_ltc_audio(None)
            self.timeline.set_audio_loading(False)
            self.engine.set_duration(self.current_song.duration_seconds)
            self.transport.set_times(0.0, self.engine.duration)
            self.monitor.set_position(0.0, self.engine.duration)
            if main_audio is not None:
                self.status.showMessage(
                    f"Audio file not found: {main_audio.path} (drop a new audio file to relink)",
                    5000,
                )
        self._refresh_window_title()
        self._refresh_status()

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

    def _add_song(self) -> None:
        draft = SongDraft(
            name=self._next_song_default_name(),
            setlist_number=self._next_setlist_number(),
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
            self.project.songs.append(song)
            index = len(self.project.songs) - 1
            self._rebuild_song_list(select_indexes=[index])
            self._activate_song(index, stop_playback=True)
            self._mark_dirty()
        ma = f" · MA {song.ma_export_name}" if song.ma_export_name else ""
        self.status.showMessage(
            f"Added song: #{format_setlist_number(song.setlist_number)} {song.name}{ma}",
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
        if len(added_indexes) == 1:
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
        with self._setlist_edit("Edit Song"):
            for draft in dialog.result_drafts():
                if draft.song_id and draft.song_id in by_id:
                    self._apply_draft_to_song(by_id[draft.song_id], draft)
            self._rebuild_song_list(select_indexes=indexes)
            if self.current_song.id in {d.song_id for d in dialog.result_drafts() if d.song_id}:
                try:
                    cur = self.project.songs.index(self.current_song)
                except ValueError:
                    cur = indexes[0]
                self._activate_song(cur, stop_playback=False)
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
            if 0 <= row < len(self.project.songs):
                indexes = [row]
        if not indexes:
            return
        if len(self.project.songs) - len(indexes) < 1:
            QMessageBox.information(self, "Cannot Delete", "The project must keep at least one song.")
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
            new_row = min(indexes[0], len(self.project.songs) - 1)
            self._rebuild_song_list(select_indexes=[new_row])
            self._activate_song(new_row, stop_playback=True)
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
            self._add_video_clips_from_paths(video, self.engine.position)
        else:
            self.status.showMessage(rejected_file_drop_reason(mime), 5000)
            event.ignore()

    # ── window management ─────────────────────────────────────────────────────

    def _shutdown_secondary_windows(self) -> None:
        """Close persistent tool windows so the app can exit with the main UI."""
        self.engine.stop()
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

    def _sync_timeline_geometry(self) -> None:
        """QScrollArea(widgetResizable=False): match viewport width, content height.

        Timeline horizontal pan/zoom uses ``_scroll_x`` against the *visible*
        width — never stretch the widget to the full song pixel width.
        """
        scroll = getattr(self, "_timeline_scroll", None)
        if scroll is None:
            return
        vp = scroll.viewport()
        tl = self.timeline
        w = max(1, vp.width())
        h = max(tl.minimumHeight(), tl._content_height)  # noqa: SLF001
        if tl.width() != w or tl.height() != h:
            tl.resize(w, h)
            tl._clamp_scroll()  # noqa: SLF001
            tl.update()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802, ANN001
        """Forward Explorer file drops from setlist chrome and the main view."""
        scroll = getattr(self, "_timeline_scroll", None)
        if scroll is not None and watched is scroll.viewport():
            if event is not None and event.type() == QEvent.Type.Resize:
                self._sync_timeline_geometry()
        panel = getattr(self, "_setlist_panel", None)
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
                    drop_at = self.engine.position
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
        # Clean Output normally only hides on its own X button (so re-opening
        # keeps the OBS capture target valid) — but that must not let it
        # survive the main window closing, or keep the app process alive.
        self._shutdown_secondary_windows()
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
            sc.activated.connect(lambda k=key: self._add_mark_by_shortcut(k))
            self._digit_shortcuts.append(sc)

    def _on_position_changed(self, seconds: float) -> None:
        self.timeline.set_position(seconds)
        self.transport.set_times(seconds, self.engine.duration)
        self.monitor.set_position(seconds, self.engine.duration)

    def _open_mark_manager(self) -> None:
        dialog = MarkManagerDialog(self.current_song, self, project=self.project)
        dialog.preview_changed.connect(self.timeline.update)
        dialog.project_defaults_changed.connect(self._on_mark_template_applied)
        if dialog.exec():
            self._undo.clear()
            self._mark_dirty()
            self.timeline.set_song(self.current_song)
            self.monitor.set_song(self.current_song)
            self._rebuild_digit_shortcuts()
            self._refresh_status()
            self.status.showMessage("Mark Manager updated", 2500)
        else:
            self.timeline.set_song(self.current_song)
            self.timeline.update()

    def _on_mark_template_applied(self) -> None:
        """Template load / project default changed while Manager is open."""
        self._undo.clear()
        self._mark_dirty()
        self.timeline.set_song(self.current_song)
        self.monitor.set_song(self.current_song)
        self._rebuild_digit_shortcuts()
        self.timeline.update()

    def _seek_from_cue_list(self, seconds: float) -> None:
        self.engine.seek(seconds)
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
        self.engine.nudge(direction * frames / fps)

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
        self.monitor.refresh_list()
        self.monitor.set_position(self.engine.position, self.engine.duration)
        self._refresh_status()

    def _refresh_marks_ui(self) -> None:
        self.timeline.update()
        self.monitor.refresh_list()
        self.monitor.set_position(self.engine.position, self.engine.duration)
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

    def _sync_loop_ui(self) -> None:
        self.transport.set_loop_status(
            self.engine.loop_a,
            self.engine.loop_b,
            enabled=self.engine.loop_enabled,
        )
        self.timeline.set_loop_region(
            self.engine.loop_a,
            self.engine.loop_b,
            enabled=self.engine.loop_enabled,
        )

    def _on_loop_region_dragged(self, a: object, b: object) -> None:
        self.engine.loop_a = float(a) if a is not None else None
        self.engine.loop_b = float(b) if b is not None else None
        if (
            self.engine.loop_a is not None
            and self.engine.loop_b is not None
            and abs(self.engine.loop_b - self.engine.loop_a) >= 0.01
        ):
            self.engine.loop_enabled = True
            self.engine.engage_ab_loop()
        self.transport.set_loop_status(
            self.engine.loop_a,
            self.engine.loop_b,
            enabled=self.engine.loop_enabled,
        )

    def _set_loop_a(self) -> None:
        self.engine.loop_a = self.engine.position
        if self.engine.loop_a is not None and self.engine.loop_b is not None:
            if abs(self.engine.loop_b - self.engine.loop_a) >= 0.01:
                self.engine.loop_enabled = True
                self.engine.engage_ab_loop()
        self._sync_loop_ui()
        self.status.showMessage(f"A = {self.engine.loop_a:.3f}s", 2000)

    def _set_loop_b(self) -> None:
        self.engine.loop_b = self.engine.position
        if self.engine.loop_a is not None and self.engine.loop_b is not None:
            if abs(self.engine.loop_b - self.engine.loop_a) >= 0.01:
                self.engine.loop_enabled = True
                self.engine.engage_ab_loop()
        self._sync_loop_ui()
        self.status.showMessage(f"B = {self.engine.loop_b:.3f}s", 2000)

    def _clear_loop(self) -> None:
        self.engine.clear_loop()
        self._sync_loop_ui()
        self.status.showMessage("Cleared A-B", 2000)

    def _set_loop_enabled(self, enabled: bool) -> None:
        if enabled and (self.engine.loop_a is None or self.engine.loop_b is None):
            self.transport.set_loop_status(
                self.engine.loop_a,
                self.engine.loop_b,
                enabled=False,
            )
            self.status.showMessage("Set point A and B first", 2500)
            return
        if enabled and abs((self.engine.loop_b or 0) - (self.engine.loop_a or 0)) < 0.01:
            self.transport.set_loop_status(
                self.engine.loop_a,
                self.engine.loop_b,
                enabled=False,
            )
            self.status.showMessage("A / B are too close together", 2500)
            return
        self.engine.set_loop_enabled(enabled)
        self._sync_loop_ui()

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
            waveform_color=str(p.waveform_color or "#3dd68c"),
            playhead_color=str(getattr(p, "playhead_color", None) or "#ff5a5f"),
        )

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

    def _open_audio_timecode(self) -> None:
        dialog = AudioTimecodeDialog(self.project.audio_output, parent=self)
        if not dialog.exec():
            return
        settings = dialog.result_settings()
        self.project.audio_output = settings
        warning = self.engine.apply_audio_settings(settings)
        self._refresh_timecode_status()
        self._mark_dirty()
        if warning:
            QMessageBox.warning(self, "Audio / Timecode", warning)
            self.status.showMessage(warning, 6000)
        else:
            parts = []
            if settings.ltc_enabled:
                parts.append("LTC on")
            if settings.mtc_enabled:
                parts.append("MTC on")
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
            self._prefetch_setlist_audio(skip_path=path)
            return

        if bump_token:
            self._audio_load_token += 1
        token = self._audio_load_token
        self.timeline.set_audio_loading(True, path.name)
        self.status.showMessage(f"Loading {path.name}…", 0)
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

    def _cached_audio_buffer(self, path: Path) -> AudioBuffer | None:
        key = self._audio_cache_key(path)
        if key is None:
            return None
        hit = self._audio_buffer_cache.get(key)
        if hit is not None:
            return hit
        disk = load_cached_audio(path)
        if disk is None:
            return None
        self._store_audio_cache(path, disk, write_disk=False)
        return disk

    def _store_audio_cache(
        self, path: Path, buffer: AudioBuffer, *, write_disk: bool = True
    ) -> None:
        key = self._audio_cache_key(path)
        if key is not None:
            self._audio_buffer_cache[key] = buffer
        if write_disk:
            self._audio_prefetch_executor.submit(save_cached_audio, path, buffer)
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

    def _schedule_ltc_detect_for_buffer(self, path: Path, buffer: AudioBuffer) -> None:
        key = self._audio_cache_key(path)
        if key is None or key in self._audio_ltc_cache or key in self._audio_ltc_inflight:
            return
        if buffer.channels < 2:
            self._audio_ltc_cache[key] = None
            self._setlist_ltc_cache_updated.emit()
            return

        samples = buffer.samples
        sample_rate = int(buffer.sample_rate)

        def _run() -> tuple[tuple[str, int, int], int | None]:
            return key, detect_ltc_channel(samples, sample_rate)

        future = self._ltc_detect_executor.submit(_run)
        self._audio_ltc_inflight[key] = future

        def _done(fut) -> None:
            self._audio_ltc_inflight.pop(key, None)
            try:
                cache_key, channel = fut.result()
            except Exception:
                return
            self._audio_ltc_cache[cache_key] = channel
            self._setlist_ltc_cache_updated.emit()

        future.add_done_callback(_done)

    def _schedule_bpm_detect_for_song(self, song: Song, path: Path | None = None) -> None:
        """Fill empty / auto BPM from the song's main audio (async)."""
        if song.bpm is not None and not bool(getattr(song, "bpm_auto", False)):
            return
        audio_path = path or self._main_audio_path_for_song(song)
        if audio_path is None or not Path(audio_path).is_file():
            return
        song_id = song.id
        if song_id in self._bpm_detect_inflight:
            return
        resolved = Path(audio_path)

        def _run() -> tuple[str, float | None]:
            from cueplayer.media.bpm_analyzer import estimate_bpm_from_path

            return song_id, estimate_bpm_from_path(resolved)

        self._bpm_detect_inflight.add(song_id)
        future = self._ltc_detect_executor.submit(_run)

        def _done(fut) -> None:  # noqa: ANN001
            self._bpm_detect_inflight.discard(song_id)
            try:
                sid, bpm = fut.result()
            except Exception:  # noqa: BLE001
                return
            self._bpm_detected.emit(sid, bpm)

        future.add_done_callback(_done)

    def _on_bpm_detected(self, song_id: str, bpm: object) -> None:
        if bpm is None:
            return
        try:
            value = float(bpm)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return
        if value <= 0:
            return
        song = next((s for s in self.project.songs if s.id == song_id), None)
        if song is None:
            return
        if song.bpm is not None and not bool(getattr(song, "bpm_auto", False)):
            return
        if (
            song.bpm is not None
            and song.bpm_auto
            and abs(float(song.bpm) - value) < 1e-9
        ):
            return
        song.bpm = value
        song.bpm_auto = True
        self._mark_dirty()
        self._rebuild_song_list()
        sheet = getattr(self, "setlist_sheet_page", None)
        if sheet is not None:
            sheet.sync_songs()
        from cueplayer.media.bpm_analyzer import format_bpm_value

        self.status.showMessage(
            f'Auto BPM for "{song.name}": <{format_bpm_value(value)}>',
            3500,
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
                    waveform_display_buffer(buffer, exclude_channel=exclude),
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
        future = executor.submit(load_audio_cached, path)
        if key is not None:
            self._audio_inflight[key] = future

            def _done(fut) -> None:
                self._audio_inflight.pop(key, None)
                try:
                    buffer = fut.result()
                except Exception:
                    return
                self._store_audio_cache(path, buffer, write_disk=False)

            future.add_done_callback(_done)
        return future

    def _main_audio_path_for_song(self, song: Song) -> Path | None:
        main_audio = next(
            (t for t in song.audio_tracks if t.role == "main"),
            song.audio_tracks[0] if song.audio_tracks else None,
        )
        if main_audio is None:
            return None
        path = Path(main_audio.path)
        return path if path.is_file() else None

    def _prefetch_setlist_audio(self, *, skip_path: Path | None = None) -> None:
        skip_resolved: str | None = None
        if skip_path is not None:
            try:
                skip_resolved = str(skip_path.resolve())
            except OSError:
                skip_resolved = str(skip_path)
        for song in self.project.songs:
            path = self._main_audio_path_for_song(song)
            if path is None:
                continue
            try:
                if skip_resolved is not None and str(path.resolve()) == skip_resolved:
                    continue
            except OSError:
                if skip_resolved is not None and str(path) == skip_resolved:
                    continue
            if self._cached_audio_buffer(path) is not None:
                continue
            key = self._audio_cache_key(path)
            if key is not None and key in self._audio_inflight:
                continue
            self._start_audio_load(path, executor=self._audio_prefetch_executor)

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
        if not future.done():
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
        main_audio = next(
            (t for t in self.current_song.audio_tracks if t.role == "main"),
            self.current_song.audio_tracks[0] if self.current_song.audio_tracks else None,
        )
        if main_audio is None:
            return False
        try:
            return Path(main_audio.path).resolve() == path.resolve()
        except OSError:
            return Path(main_audio.path) == path

    def _apply_loaded_audio(
        self,
        buffer: AudioBuffer,
        path: Path,
        *,
        mark_dirty: bool = True,
        replace_track: bool = True,
        refresh_song_widgets: bool = True,
    ) -> None:
        self._store_audio_cache(path, buffer)
        self.timeline.set_audio_loading(False)
        self.current_song.duration_seconds = buffer.duration_seconds
        if replace_track:
            self.current_song.audio_tracks = [
                AudioTrack(
                    id="main_audio",
                    name=path.stem,
                    path=path,
                    role="main",
                )
            ]
        self.engine.set_buffer(buffer)
        self.engine.ensure_playback_ready()
        key = self._audio_cache_key(path)
        # Never copy engine.detected_ltc_channel here — it can still be the
        # previous song's result until async detect finishes, which wrongly
        # lit LTC L/R on pure-music tracks after playing a striped song.
        if key is not None and key not in self._audio_ltc_cache:
            self._schedule_ltc_detect_for_buffer(path, buffer)
        self._refresh_setlist_ltc_cells()
        exclude = self._ltc_channel_for_song(self.current_song)
        self._timeline_ltc_exclude = exclude
        self.timeline.set_audio(waveform_display_buffer(buffer, exclude_channel=exclude))
        self._apply_timeline_ltc_lane(buffer, exclude)
        if refresh_song_widgets:
            self.timeline.set_song(self.current_song)
            self.monitor.set_song(self.current_song)
        self.transport.set_times(0.0, self.engine.duration)
        self.monitor.set_position(0.0, self.engine.duration)
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
        action = getattr(self, "_show_video_track_action", None)
        if action is not None:
            action.blockSignals(True)
            action.setChecked(bool(visible))
            action.blockSignals(False)
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

    def _on_show_video_track_toggled(self, checked: bool) -> None:
        self.project.set_show_video_track(bool(checked))
        self.timeline.set_show_video_track(bool(checked))
        self._mark_dirty()

    def _on_video_clip_volume_changed(self, clip_id: str, volume: float) -> None:
        # Volume is already applied to the clip by the timeline widget; this
        # just persists the change (no undo entry, matching lock/hide toggles).
        del clip_id, volume
        self._mark_dirty()

    def _on_music_volume_changed(self, volume: float) -> None:
        # song.music_volume is already updated by the timeline widget; this
        # applies it live to playback and persists it (no undo entry,
        # matching Master Volume / lock-hide toggles).
        self.engine.set_music_volume(volume)
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

    def _add_video_clip_from_path(self, path: Path, *, start_seconds: float) -> VideoClip | None:
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
        self._push_song_undo(AddVideoClipsCommand(clips=[VideoClipSnapshot.from_clip(clip)]))
        self.video_sync.refresh()
        self.engine.refresh_video_clips()
        self.timeline.refresh_video_clip_waveforms()
        self.timeline.update()
        self._mark_dirty()
        kind_label = "still image" if is_still else "video clip"
        msg = f"Added {kind_label}: {clip.name} ({duration:.2f}s)"
        if not is_still and source_duration > max(600.0, self.current_song.duration_seconds * 2):
            mins = source_duration / 60.0
            msg = (
                f"Added long video ({mins:.0f} min source) as {duration:.1f}s clip — "
                f"picture OK; embedded audio loads trim only "
                f"(max {MAX_VIDEO_AUDIO_DECODE_SECONDS / 60:.0f} min)"
            )
        self.status.showMessage(msg, 5000)
        return clip

    def _add_video_clips_from_paths(self, paths: list, drop_seconds: object) -> None:
        t = float(drop_seconds)  # type: ignore[arg-type]
        for raw in paths:
            clip = self._add_video_clip_from_path(Path(raw), start_seconds=t)
            if clip is not None:
                t = clip.end_seconds  # stack subsequent drops after the previous clip

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
        paste_at = self.engine.position
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
        lane = self.current_song.lane_by_shortcut(shortcut)
        if lane is None:
            self.status.showMessage(f"Shortcut {shortcut} is not assigned to any Mark in Manager", 2500)
            return
        self._add_mark(lane.index)

    def _add_mark(self, lane_index: int) -> None:
        lane = self.current_song.lane_by_index(lane_index)
        if lane is None or lane.locked:
            return
        mark = self.current_song.add_mark(lane_index, self.engine.position)
        self._push_song_undo(AddMarksCommand(marks=[MarkSnapshot.from_mark(mark)]))
        self._mark_dirty()
        self._refresh_marks_ui()
        lat_ms = self.engine.sync_offset_ms()
        self.status.showMessage(
            f"Marked: {lane.name} @ {mark.time_seconds:.3f}s"
            + (f" · sync offset {lat_ms:.0f}ms" if abs(lat_ms) >= 0.5 else "")
            + " · edit directly in the Note column on the right",
            2500,
        )

    def _refresh_status(self) -> None:
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
