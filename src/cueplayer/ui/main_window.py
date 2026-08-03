"""Main application window with waveform timeline and marking."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QEvent, QModelIndex, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QColor,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QKeySequence,
    QPainter,
    QPen,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
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
    Song,
    VideoClip,
)
from cueplayer.persistence.backup import (
    DEFAULT_KEEP,
    create_backup_before_save,
    list_backups,
)
from cueplayer.persistence.project_store import load_project, save_project
from cueplayer.ui.row_color import ROLE_ROW_COLOR, RowColorDelegate
from cueplayer.domain.undo import (
    AddMarksCommand,
    AddVideoClipsCommand,
    DeleteMarksCommand,
    DeleteVideoClipsCommand,
    EditVideoClipsCommand,
    MarkSnapshot,
    MoveMarksCommand,
    RenameMarkCommand,
    UndoStack,
    VideoClipSnapshot,
)
from cueplayer.media.audio_loader import load_audio
from cueplayer.media.video_loader import STILL_IMAGE_SUFFIXES, probe_media
from cueplayer.playback.audio_engine import AudioEngine
from cueplayer.playback.jog import hold_step_frames
from cueplayer.playback.video_sync import VideoSyncController
from cueplayer.ui.audio_timecode_dialog import AudioTimecodeDialog
from cueplayer.ui.cue_monitor_panel import CueMonitorPanel
from cueplayer.ui.mark_display_dialog import MarkDisplayDialog
from cueplayer.ui.mark_manager_dialog import MarkManagerDialog
from cueplayer.ui.show_patch_page import ShowPatchPage
from cueplayer.ui.song_edit_dialog import (
    SongDraft,
    SongEditDialog,
    format_setlist_number,
    parse_setlist_number,
    suggest_ma_export_name,
)
from cueplayer.ui.theme import ACCENT, BG_SELECTED, with_alpha
from cueplayer.ui.timeline_widget import TimelineWidget
from cueplayer.ui.transport_bar import BottomTransportBar, TopToolBar
from cueplayer.ui.video_output_window import CleanVideoOutputWindow
from cueplayer.ui.video_preview import VideoPreviewWidget

_AUDIO_SUFFIXES = {".wav", ".flac", ".ogg", ".mp3", ".aiff", ".aif"}
_VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"} | set(STILL_IMAGE_SUFFIXES)
_MEDIA_DIALOG_FILTER = (
    "Video & Images (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.png *.jpg *.jpeg *.webp);;"
    "All Files (*.*)"
)
_SETTINGS_ORG = "CuePlayer"
_SETTINGS_APP = "CuePlayer"
_KEY_AUTOSAVE_ENABLED = "autosave/enabled"
_KEY_AUTOSAVE_INTERVAL_SEC = "autosave/interval_seconds"
_KEY_BACKUP_KEEP = "autosave/backup_keep"
_DEFAULT_AUTOSAVE_INTERVAL_SEC = 120


def _text_input_has_focus() -> bool:
    """True when a widget that owns typing shortcuts is focused."""
    widget = QApplication.focusWidget()
    return isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox))


def _audio_paths_from_mime(mime) -> list[Path]:  # noqa: ANN001
    if mime is None or not mime.hasUrls():
        return []
    out: list[Path] = []
    for url in mime.urls():
        if not url.isLocalFile():
            continue
        path = Path(url.toLocalFile())
        if path.is_file() and path.suffix.lower() in _AUDIO_SUFFIXES:
            out.append(path)
    return out


class SetlistWidget(QTableWidget):
    """Setlist: click # to edit, drag rows to reorder, drop audio to add songs."""

    COL_NUM = 0
    COL_TITLE = 1
    COL_EN = 2
    COL_BPM = 3

    # Shared with export/show-patch song lists (see cueplayer.ui.row_color).
    ROLE_ROW_COLOR = ROLE_ROW_COLOR

    audio_files_dropped = Signal(list)
    rows_reordered = Signal(list, int)  # song ids in drag order, insert-before row
    setlist_number_edited = Signal(int, float)  # row, new number
    setlist_number_edit_failed = Signal(int)  # row
    song_title_edited = Signal(int, str)  # row, display title for column 1
    song_ma_name_edited = Signal(int, str)  # row, English / MA name (column 2)
    song_bpm_edited = Signal(int, object)  # row, float | None
    song_bpm_edit_failed = Signal(int)  # row

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, 4, parent)
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
        self.setHorizontalHeaderLabels(["#", "Song", "English", "BPM"])
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(0, 52)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(3, 56)
        self.setColumnHidden(2, True)
        self.setColumnHidden(3, False)
        self.verticalHeader().setDefaultSectionSize(28)
        self.setToolTip(
            "Double-click #/Name/BPM to edit; right-click to toggle columns or open full editor; "
            "drag to reorder; drop audio files to add; Ctrl/Shift to multi-select"
        )
        self._block_number_signal = False
        self._drag_song_ids: list[str] = []
        self._insert_indicator_row: int | None = None
        self._name_mode = "zh"
        self._show_bpm = True
        self.itemChanged.connect(self._on_item_changed)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def set_name_mode(self, mode: str) -> None:
        """zh = Chinese · both = Chinese + English · en = English."""
        if mode not in ("zh", "both", "en"):
            mode = "zh"
        self._name_mode = mode
        if mode == "both":
            self.setHorizontalHeaderLabels(["#", "Song", "English", "BPM"])
            self.setColumnHidden(self.COL_EN, False)
        elif mode == "en":
            self.setHorizontalHeaderLabels(["#", "English", "English", "BPM"])
            self.setColumnHidden(self.COL_EN, True)
        else:
            self.setHorizontalHeaderLabels(["#", "Song", "English", "BPM"])
            self.setColumnHidden(self.COL_EN, True)
        self.setColumnHidden(self.COL_BPM, not self._show_bpm)

    def set_show_bpm(self, visible: bool) -> None:
        self._show_bpm = bool(visible)
        self.setColumnHidden(self.COL_BPM, not self._show_bpm)

    def set_ma_column_visible(self, visible: bool) -> None:
        # Back-compat for older callers.
        self.set_name_mode("both" if visible else "zh")

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
            raw = item.text().strip()
            if not raw:
                self.song_bpm_edited.emit(item.row(), None)
                return
            try:
                value = float(raw.replace(",", "."))
            except ValueError:
                self.song_bpm_edit_failed.emit(item.row())
                return
            if value <= 0:
                self.song_bpm_edit_failed.emit(item.row())
                return
            self.song_bpm_edited.emit(item.row(), value)

    def startDrag(self, supportedActions) -> None:  # noqa: N802, ANN001
        ids: list[str] = []
        for row in sorted({idx.row() for idx in self.selectedIndexes()}):
            item = self.item(row, 0)
            if item is None:
                continue
            song_id = item.data(Qt.ItemDataRole.UserRole)
            if song_id:
                ids.append(str(song_id))
        self._drag_song_ids = ids
        super().startDrag(supportedActions)

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
        ok = super().viewportEvent(event)
        if event.type() == QEvent.Type.Paint and self._insert_indicator_row is not None:
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
        if _audio_paths_from_mime(event.mimeData()) or event.source() is self:
            event.acceptProposedAction()
            if event.source() is self:
                self._set_insert_indicator(self._insert_row_at(event.position().toPoint()))
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        if _audio_paths_from_mime(event.mimeData()) or event.source() is self:
            event.acceptProposedAction()
            if event.source() is self:
                self._set_insert_indicator(self._insert_row_at(event.position().toPoint()))
            else:
                self._clear_insert_indicator()
        else:
            self._clear_insert_indicator()
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802, ANN001
        self._clear_insert_indicator()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self._clear_insert_indicator()
        paths = _audio_paths_from_mime(event.mimeData())
        if paths:
            event.acceptProposedAction()
            self.audio_files_dropped.emit(paths)
            return
        if event.source() is not self:
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
        self.rows_reordered.emit(ids, drop_row)


class MainWindow(QMainWindow):
    def __init__(self, project: Project | None = None) -> None:
        super().__init__()
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
        # Internal clipboard for Ctrl+C/Ctrl+V on timeline video clips
        # (Delete/Backspace reuse the existing _delete_video_clips path).
        self._video_clip_clipboard: list[VideoClipSnapshot] = []
        # Left/Right arrow-key jog: elapsed-hold-time bookkeeping per
        # direction, used to accelerate the seek step (see _nudge_frames()).
        self._nudge_hold_start: dict[int, float] = {}
        self._nudge_last_time: dict[int, float] = {}

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

        self.setWindowTitle(f"CuePlayer — {self.project.name}")
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
        left = QWidget()
        left.setObjectName("setlistPanel")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_title = QLabel("Setlist")
        left_title.setStyleSheet("font-weight: 600;")
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.addWidget(left_title)
        title_row.addStretch(1)
        self.song_list = SetlistWidget()
        self.song_list.setItemDelegate(RowColorDelegate(self.song_list))
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
        self.sort_by_number_button.setToolTip("Re-sort the list by custom number (supports 0.5)")
        self.renumber_button.setToolTip("Reset to 1, 2, 3… following the current list order")
        order_btns.addWidget(self.move_up_button)
        order_btns.addWidget(self.move_down_button)
        order_btns.addWidget(self.sort_by_number_button)
        order_btns.addWidget(self.renumber_button)

        left_layout.addLayout(title_row)
        left_layout.addWidget(self.song_list, stretch=1)
        left_layout.addLayout(song_btns)
        left_layout.addLayout(order_btns)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.addWidget(self.timeline, stretch=1)

        # Video Preview lives under the Marks (cue list) in this same
        # right-hand column — not squeezed into a separate dock pinned to
        # the far right edge of the whole window.
        self.video_preview_panel = QWidget()
        self.video_preview_panel.setObjectName("videoPreviewPanel")
        video_panel_layout = QVBoxLayout(self.video_preview_panel)
        video_panel_layout.setContentsMargins(0, 8, 0, 0)
        video_panel_layout.setSpacing(6)
        video_title = QLabel("Video Preview")
        video_title.setStyleSheet("font-weight: 600; color: #a1a1aa;")
        video_panel_layout.addWidget(video_title)
        video_panel_layout.addWidget(self.video_preview, stretch=1)

        marks_video_split = QSplitter(Qt.Orientation.Vertical)
        marks_video_split.setObjectName("marksVideoSplitter")
        marks_video_split.addWidget(self.monitor)
        marks_video_split.addWidget(self.video_preview_panel)
        marks_video_split.setStretchFactor(0, 3)
        marks_video_split.setStretchFactor(1, 2)
        marks_video_split.setSizes([520, 300])

        timeline_split = QSplitter(Qt.Orientation.Horizontal)
        timeline_split.addWidget(center)
        timeline_split.addWidget(marks_video_split)
        timeline_split.setStretchFactor(0, 1)
        timeline_split.setStretchFactor(1, 0)
        timeline_split.setSizes([1020, 320])

        self.show_patch_page = ShowPatchPage()
        self.show_patch_page.set_project(self.project)
        self.view_stack = QStackedWidget()
        self.view_stack.addWidget(timeline_split)  # 0 = timeline
        self.view_stack.addWidget(self.show_patch_page)  # 1 = MA patch

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

        self.add_song_button.clicked.connect(self._add_song)
        self.edit_song_button.clicked.connect(self._edit_song)
        self.delete_song_button.clicked.connect(self._delete_song)
        self.move_up_button.clicked.connect(lambda: self._move_selected_songs(-1))
        self.move_down_button.clicked.connect(lambda: self._move_selected_songs(1))
        self.sort_by_number_button.clicked.connect(self._sort_songs_by_number)
        self.renumber_button.clicked.connect(self._renumber_songs_by_list_order)
        self.song_list.currentCellChanged.connect(self._on_song_cell_changed)
        self.song_list.audio_files_dropped.connect(self._add_songs_from_audio_paths)
        self.song_list.rows_reordered.connect(self._on_setlist_rows_reordered)
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
        self.transport.set_loop_a_clicked.connect(self._set_loop_a)
        self.transport.set_loop_b_clicked.connect(self._set_loop_b)
        self.transport.clear_loop_clicked.connect(self._clear_loop)
        self.transport.loop_toggled.connect(self._set_loop_enabled)
        self.transport.volume_changed.connect(self.engine.set_volume)
        self.timeline.seek_requested.connect(self.engine.seek)
        self.timeline.scrub_started.connect(self.engine.begin_scrub)
        self.timeline.scrub_ended.connect(self.engine.end_scrub)
        # Throttle video decode while the playhead is actively being
        # dragged — see VideoSyncController.set_scrubbing().
        self.timeline.scrub_started.connect(lambda: self.video_sync.set_scrubbing(True))
        self.timeline.scrub_ended.connect(lambda: self.video_sync.set_scrubbing(False))
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
        self.timeline.video_clip_volume_changed.connect(self._on_video_clip_volume_changed)
        self.timeline.music_volume_changed.connect(self._on_music_volume_changed)
        self.engine.position_changed.connect(self.video_sync.update_position)
        # Throttles video decode to a display cadence while playing, so the
        # audio clock's ~60Hz position ticks can't starve the UI thread the
        # timeline also lives on — see VideoSyncController.set_playing().
        self.engine.playing_changed.connect(self.video_sync.set_playing)
        self.video_sync.frame_changed.connect(self.video_preview.set_frame)
        self.video_sync.frame_changed.connect(self.clean_output_window.set_frame)
        self.video_sync.overlap_warning.connect(lambda msg: self.status.showMessage(msg, 4000))
        self.clean_output_window.visibility_changed.connect(self._clean_output_action.setChecked)
        self.clean_output_window.settings_changed.connect(self._mark_dirty)
        self.monitor.seek_requested.connect(self._seek_from_cue_list)
        self.monitor.selection_changed.connect(self._on_monitor_selection)
        self.monitor.delete_requested.connect(self._delete_marks)
        self.monitor.note_changed.connect(self._on_note_changed)
        self.engine.position_changed.connect(self._on_position_changed)
        self.engine.playing_changed.connect(self.transport.set_playing)
        self.engine.playing_changed.connect(self.timeline.set_playing)
        self.engine.timecode_status_changed.connect(self._refresh_timecode_status)
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

        # Auto-load demo fixture if present (Chinese path stress).
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
        act_video_preview.triggered.connect(self.video_preview_panel.setVisible)
        tools_menu.addAction(act_video_preview)
        self._clean_output_action = QAction("&Clean Video Output", self)
        self._clean_output_action.setCheckable(True)
        self._clean_output_action.triggered.connect(self._toggle_clean_output)
        tools_menu.addAction(self._clean_output_action)
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

    def _project_filter(self) -> str:
        return "CuePlayer Project (*.cueplayer.json);;JSON (*.json);;All Files (*.*)"

    def _refresh_window_title(self) -> None:
        name = self.project.name
        if self._project_path is not None:
            name = self._project_path.stem.replace(".cueplayer", "") or self.project.name
        dirty = " *" if self._dirty else ""
        self.setWindowTitle(f"CuePlayer — {name}{dirty}")

    def _mark_dirty(self) -> None:
        if self._dirty:
            return
        self._dirty = True
        self._refresh_window_title()

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

    def _file_new(self) -> None:
        if not self._confirm_discard_if_dirty():
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
        try:
            project = load_project(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Unable to Open Project", str(exc))
            return
        self.engine.stop()
        self.project = project
        self._project_path = path
        self._apply_project()
        self._set_clean()
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

    def _apply_project(self) -> None:
        if not self.project.songs:
            self.project.songs.append(self.project.new_song("Untitled Song"))
        self.show_patch_page.set_project(self.project)
        self._sync_setlist_name_mode_ui()
        self.engine.apply_audio_settings(self.project.audio_output)
        self.clean_output_window.apply_settings(self.project.clean_video_output)
        self.video_sync.set_decode_quality(self.project.video_decode_quality)
        self._sync_video_decode_quality_ui()
        self._refresh_timecode_status()
        self._rebuild_song_list(select_indexes=[0])
        self._activate_song(0, stop_playback=True)

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
        current = select_indexes[-1] if select_indexes else 0
        self._switching_song = True
        self.song_list.blockSignals(True)
        self.song_list._block_number_signal = True  # noqa: SLF001
        self.song_list.setRowCount(0)
        self.song_list.setRowCount(len(self.project.songs))
        mode = self.project.setlist_name_mode
        if mode not in ("zh", "both", "en"):
            mode = "zh"
        self.song_list.set_name_mode(mode)
        self.song_list.set_show_bpm(self.project.setlist_show_bpm)
        for i, song in enumerate(self.project.songs):
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
            num_item.setToolTip("Double-click to edit the number (0.5 supported)")
            self.song_list.setItem(i, SetlistWidget.COL_NUM, num_item)

            zh_name = song.name
            en_name = (song.ma_export_name or "").strip()
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
            self.song_list.setItem(i, SetlistWidget.COL_TITLE, name_item)

            ma_item = QTableWidgetItem(en_name)
            ma_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEditable
                | Qt.ItemFlag.ItemIsDragEnabled
            )
            ma_item.setToolTip((en_name + "\n" if en_name else "") + "Double-click to edit the English/MA name")
            self.song_list.setItem(i, SetlistWidget.COL_EN, ma_item)

            bpm_text = ""
            if song.bpm is not None and float(song.bpm) > 0:
                bpm_val = float(song.bpm)
                bpm_text = (
                    str(int(bpm_val))
                    if abs(bpm_val - round(bpm_val)) < 1e-9
                    else f"{bpm_val:g}"
                )
            bpm_item = QTableWidgetItem(bpm_text)
            bpm_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            bpm_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEditable
                | Qt.ItemFlag.ItemIsDragEnabled
            )
            bpm_item.setToolTip("Double-click to enter BPM (blank = not set)")
            self.song_list.setItem(i, SetlistWidget.COL_BPM, bpm_item)

            for cell in (num_item, name_item, ma_item, bpm_item):
                cell.setData(SetlistWidget.ROLE_ROW_COLOR, song.row_color or "")

        self.song_list.clearSelection()
        for idx in select_indexes:
            self.song_list.selectRow(idx)
        if self.project.songs:
            self.song_list.setCurrentCell(current, SetlistWidget.COL_TITLE)
        self.song_list._block_number_signal = False  # noqa: SLF001
        self.song_list.blockSignals(False)
        self._switching_song = False
        patch = getattr(self, "show_patch_page", None)
        if patch is not None:
            patch.sync_songs()

    def _selected_song_indexes(self) -> list[int]:
        rows = sorted({idx.row() for idx in self.song_list.selectedIndexes()})
        return [r for r in rows if 0 <= r < len(self.project.songs)]

    def _song_to_draft(self, song: Song) -> SongDraft:
        audio_path = Path(song.audio_tracks[0].path) if song.audio_tracks else None
        return SongDraft(
            name=song.name,
            setlist_number=float(song.setlist_number),
            ma_export_name=(song.ma_export_name or ""),
            bpm=song.bpm,
            start_timecode=song.start_timecode or "01:00:00:00",
            fps=float(song.fps or 30.0),
            audio_path=audio_path if audio_path is not None else None,
            song_id=song.id,
        )

    def _apply_draft_to_song(self, song: Song, draft: SongDraft) -> None:
        song.name = draft.name
        song.setlist_number = float(draft.setlist_number)
        song.ma_export_name = draft.ma_export_name or None
        song.bpm = draft.bpm
        song.start_timecode = draft.start_timecode
        song.fps = draft.fps
        if song is self.current_song:
            self.engine.set_song_timebase(song.start_timecode, song.fps)

    def _next_setlist_number(self) -> float:
        if not self.project.songs:
            return 1.0
        return max(float(s.setlist_number) for s in self.project.songs) + 1.0

    def _on_song_cell_changed(
        self, row: int, _column: int, _prev_row: int, _prev_column: int
    ) -> None:
        if self._switching_song or row < 0 or row >= len(self.project.songs):
            return
        if self.project.songs[row] is self.current_song:
            return
        self._activate_song(row, stop_playback=True)

    def _on_song_title_edited(self, row: int, text: str) -> None:
        if row < 0 or row >= len(self.project.songs):
            return
        song = self.project.songs[row]
        mode = self.project.setlist_name_mode
        if mode == "en":
            # Primary column shows English in EN mode.
            self._apply_inline_ma_name(song, text, row=row)
            return
        name = text.strip() or "Untitled Song"
        if song.name == name:
            return
        song.name = name
        self._mark_dirty()
        self._refresh_status()
        patch = getattr(self, "show_patch_page", None)
        if patch is not None:
            patch.sync_songs()
        self.status.showMessage(f'Song name changed to "{name}"', 2000)

    def _on_song_ma_name_edited(self, row: int, text: str) -> None:
        if row < 0 or row >= len(self.project.songs):
            return
        self._apply_inline_ma_name(self.project.songs[row], text, row=row)

    def _apply_inline_ma_name(self, song: Song, text: str, *, row: int) -> None:
        from cueplayer.exporters.common import sanitize_ma_name

        raw = text.strip()
        ma = sanitize_ma_name(raw, fallback="") if raw else ""
        if raw and not ma:
            QMessageBox.warning(
                self,
                "Invalid English/MA Name",
                "Use letters/numbers (spaces, _ . - allowed); Chinese characters will be stripped.",
            )
            self._rebuild_song_list(select_indexes=[row])
            return
        new_val = ma or None
        if (song.ma_export_name or None) == new_val:
            # Normalize display if user typed unsanitized text.
            if raw != (ma or ""):
                self._rebuild_song_list(select_indexes=[row])
            return
        song.ma_export_name = new_val
        self._mark_dirty()
        self._refresh_status()
        patch = getattr(self, "show_patch_page", None)
        if patch is not None:
            patch.sync_songs()
        label = ma or "(blank)"
        self.status.showMessage(f'English/MA name changed to "{label}"', 2000)
        # Refresh so EN-mode primary column / sanitization stay consistent.
        self._rebuild_song_list(select_indexes=[row])

    def _on_song_bpm_edited(self, row: int, value: object) -> None:
        if row < 0 or row >= len(self.project.songs):
            return
        song = self.project.songs[row]
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
        if song.bpm == bpm or (
            song.bpm is not None
            and bpm is not None
            and abs(float(song.bpm) - bpm) < 1e-9
        ):
            # Normalize display.
            item = self.song_list.item(row, SetlistWidget.COL_BPM)
            if item is not None and bpm is not None:
                text = (
                    str(int(bpm)) if abs(bpm - round(bpm)) < 1e-9 else f"{bpm:g}"
                )
                self.song_list._block_number_signal = True  # noqa: SLF001
                item.setText(text)
                self.song_list._block_number_signal = False  # noqa: SLF001
            return
        song.bpm = bpm
        self._mark_dirty()
        if bpm is None:
            self.status.showMessage("BPM cleared", 2000)
        else:
            shown = str(int(bpm)) if abs(bpm - round(bpm)) < 1e-9 else f"{bpm:g}"
            self.status.showMessage(f"BPM set to {shown}", 2000)

    def _on_song_bpm_edit_failed(self, row: int) -> None:
        QMessageBox.warning(self, "Invalid BPM", "Enter a positive number (e.g. 120, 128.5), or leave blank.")
        indexes = self._selected_song_indexes() or [row]
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
            # Right-click on unselected row → select that row only.
            selected = {idx.row() for idx in self.song_list.selectedIndexes()}
            if row not in selected:
                self.song_list.selectRow(row)
        menu = QMenu(self)
        edit_action = menu.addAction("Edit…")
        add_action = menu.addAction("Add Song…")
        menu.addSeparator()
        row_color_action = menu.addAction("Row Color…")
        clear_row_color_action = menu.addAction("Clear Row Color")
        menu.addSeparator()
        en_action, bpm_action = self._add_setlist_column_actions(menu)
        menu.addSeparator()
        up_action = menu.addAction("Move Up")
        down_action = menu.addAction("Move Down")
        menu.addSeparator()
        delete_action = menu.addAction("Delete")
        has_selection = bool(self._selected_song_indexes()) or self.song_list.currentRow() >= 0
        selected_songs = self._selected_songs()
        edit_action.setEnabled(has_selection)
        row_color_action.setEnabled(has_selection)
        row_color_action.setToolTip("Pick a background color for the selected song(s) (e.g. VIP, problem cue)")
        clear_row_color_action.setEnabled(
            has_selection and any(song.row_color for song in selected_songs)
        )
        delete_action.setEnabled(has_selection and len(self.project.songs) > 1)
        up_action.setEnabled(has_selection)
        down_action.setEnabled(has_selection)
        chosen = menu.exec(self.song_list.viewport().mapToGlobal(pos))
        if self._apply_setlist_column_action(
            chosen, en_action=en_action, bpm_action=bpm_action
        ):
            return
        if chosen is edit_action:
            self._edit_song()
        elif chosen is add_action:
            self._add_song()
        elif chosen is row_color_action:
            self._pick_row_color()
        elif chosen is clear_row_color_action:
            self._clear_row_color()
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
        chosen = QColorDialog.getColor(initial, self, "Row Color")
        if not chosen.isValid():
            return
        hex_color = chosen.name().upper()
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
        for song in songs:
            song.row_color = ""
        self._mark_dirty()
        self._rebuild_song_list(select_indexes=self._selected_song_indexes())
        self.status.showMessage("Row color cleared", 2000)

    def _on_setlist_number_edit_failed(self, row: int) -> None:
        QMessageBox.warning(self, "Invalid Number", "Enter a number (e.g. 1, 0.5, 2.5).")
        indexes = self._selected_song_indexes() or [row]
        self._rebuild_song_list(select_indexes=indexes)

    def _on_setlist_number_edited(self, row: int, value: float) -> None:
        if row < 0 or row >= len(self.project.songs):
            return
        song = self.project.songs[row]
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
            f'Number changed to {format_setlist_number(value)} (use "Sort by Number" to reorder)',
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
        old_indexes = [i for i, song in enumerate(self.project.songs) if song.id in id_set]
        remaining = [song for song in self.project.songs if song.id not in id_set]
        drop_row = int(drop_row)
        removed_before = sum(1 for i in old_indexes if i < drop_row)
        insert_at = max(0, min(drop_row - removed_before, len(remaining)))
        keep_id = self.current_song.id
        self.project.songs = remaining[:insert_at] + moving + remaining[insert_at:]
        new_indexes = [i for i, song in enumerate(self.project.songs) if song.id in id_set]
        if not new_indexes:
            new_indexes = [insert_at]
        self._rebuild_song_list(select_indexes=new_indexes)
        # Keep the same song loaded — do not stop/reload audio just for a reorder.
        try:
            current_row = next(
                i for i, song in enumerate(self.project.songs) if song.id == keep_id
            )
        except StopIteration:
            current_row = new_indexes[-1]
        self.current_song = self.project.songs[current_row]
        self._mark_dirty()
        self._refresh_status()
        self.status.showMessage("Song order updated by drag", 2000)

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
        self._mark_dirty()
        self._refresh_status()
        self.status.showMessage("Song order updated", 2000)

    def _sort_songs_by_number(self) -> None:
        if len(self.project.songs) <= 1:
            return
        current_id = self.current_song.id
        self.project.songs.sort(key=lambda s: (float(s.setlist_number), s.name))
        try:
            new_row = next(
                i for i, s in enumerate(self.project.songs) if s.id == current_id
            )
        except StopIteration:
            new_row = 0
        self._rebuild_song_list(select_indexes=[new_row])
        self._activate_song(new_row, stop_playback=False)
        self._mark_dirty()
        self.status.showMessage("Sorted by number", 2500)

    def _renumber_songs_by_list_order(self) -> None:
        if not self.project.songs:
            return
        answer = QMessageBox.question(
            self,
            "Renumber",
            "Reset to 1, 2, 3… following the current top-to-bottom order?\n"
            "(Custom numbers such as 0.5 will be overwritten)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        for i, song in enumerate(self.project.songs):
            song.setlist_number = float(i + 1)
        indexes = self._selected_song_indexes() or [self.song_list.currentRow()]
        self._rebuild_song_list(select_indexes=indexes)
        self._mark_dirty()
        self._refresh_status()
        self.status.showMessage("Renumbered to 1, 2, 3…", 2500)

    def _activate_song(self, index: int, *, stop_playback: bool = True) -> None:
        if index < 0 or index >= len(self.project.songs):
            return
        if stop_playback:
            self.engine.stop()
        self.current_song = self.project.songs[index]
        self._undo.clear()
        self.engine.clear_loop()
        self._sync_loop_ui()
        self.timeline.clear_selection(emit=False)
        self.monitor.set_selected_mark_ids([])
        self.timeline.set_song(self.current_song)
        self._apply_project_mark_line_settings()
        self.monitor.set_song(self.current_song)
        self.video_sync.set_song(self.current_song)
        self.engine.set_song(self.current_song)
        self._rebuild_digit_shortcuts()
        self.engine.set_song_timebase(
            self.current_song.start_timecode, self.current_song.fps
        )
        self.engine.set_buffer(None)
        self.timeline.set_audio(None)
        main_audio = next(
            (t for t in self.current_song.audio_tracks if t.role == "main"),
            self.current_song.audio_tracks[0] if self.current_song.audio_tracks else None,
        )
        if main_audio is not None and Path(main_audio.path).is_file():
            self._load_audio_path(Path(main_audio.path), mark_dirty=False, replace_track=False)
        else:
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

    def _add_songs_from_audio_paths(self, paths: list) -> None:
        """Drop onto Setlist → confirm number/name/MA/TC/FPS, then add."""
        drafts: list[SongDraft] = []
        next_num = self._next_setlist_number()
        for raw in paths:
            path = Path(raw)
            if not path.is_file():
                continue
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
        if not drafts:
            self.status.showMessage("No audio files to add", 2500)
            return
        title = "Import Song" if len(drafts) == 1 else f"Batch Import Songs ({len(drafts)})"
        dialog = SongEditDialog(drafts, title=title, parent=self)
        if not dialog.exec():
            return
        last_index: int | None = None
        added_indexes: list[int] = []
        for draft in dialog.result_drafts():
            song = self.project.new_song(draft.name)
            self._apply_draft_to_song(song, draft)
            if draft.audio_path is not None:
                song.audio_tracks = [
                    AudioTrack(
                        id="main_audio",
                        name=draft.audio_path.stem,
                        path=draft.audio_path,
                        role="main",
                    )
                ]
            self.project.songs.append(song)
            last_index = len(self.project.songs) - 1
            added_indexes.append(last_index)
        if last_index is None:
            return
        self._rebuild_song_list(select_indexes=added_indexes)
        self._activate_song(last_index, stop_playback=True)
        self._mark_dirty()
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
        for draft in dialog.result_drafts():
            if draft.song_id and draft.song_id in by_id:
                self._apply_draft_to_song(by_id[draft.song_id], draft)
        self._rebuild_song_list(select_indexes=indexes)
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

    def _shutdown_secondary_windows(self) -> None:
        """Close persistent tool windows so the app can exit with the main UI."""
        self.engine.stop()
        self.clean_output_window.force_close()
        app = QApplication.instance()
        if app is None:
            return
        for widget in list(app.topLevelWidgets()):
            if widget is self or not widget.isVisible():
                continue
            widget.close()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if not self._confirm_discard_if_dirty():
            event.ignore()
            return
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
        self._undo.push(MoveMarksCommand(times=dict(moved)))
        self._mark_dirty()

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
        self._undo.push(MoveMarksCommand(times=moved, label="Offset Mark"))
        self._mark_dirty()
        self._refresh_marks_ui()
        self.status.showMessage(f"Offset {len(moved)} mark(s) by {delta:+.3f}s", 2500)

    def _on_note_changed(self, mark_id: str, old_name: str, new_name: str) -> None:
        self._undo.push(RenameMarkCommand(mark_id=mark_id, old_name=old_name, new_name=new_name))
        self._mark_dirty()

    def _undo_action(self) -> None:
        label = self._undo.undo(self.current_song)
        if label is None:
            self.status.showMessage("Nothing to undo", 1500)
            return
        self.timeline.clear_selection(emit=False)
        self.monitor.set_selected_mark_ids([])
        self.video_sync.refresh()
        self.engine.refresh_video_clips()
        self._mark_dirty()
        self._refresh_marks_ui()
        self.status.showMessage(f"Undone: {label}", 2000)

    def _redo_action(self) -> None:
        label = self._undo.redo(self.current_song)
        if label is None:
            self.status.showMessage("Nothing to redo", 1500)
            return
        self.timeline.clear_selection(emit=False)
        self.monitor.set_selected_mark_ids([])
        self.video_sync.refresh()
        self.engine.refresh_video_clips()
        self._mark_dirty()
        self._refresh_marks_ui()
        self.status.showMessage(f"Redone: {label}", 2000)

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
        self._undo.push(DeleteMarksCommand(marks=snapshots))
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
        self._sync_loop_ui()
        self.status.showMessage(f"A = {self.engine.loop_a:.3f}s", 2000)

    def _set_loop_b(self) -> None:
        self.engine.loop_b = self.engine.position
        if self.engine.loop_a is not None and self.engine.loop_b is not None:
            if abs(self.engine.loop_b - self.engine.loop_a) >= 0.01:
                self.engine.loop_enabled = True
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
        else:
            self.view_stack.setCurrentIndex(0)

    def _open_ma_patch_page(self) -> None:
        self.toolbar.set_view_mode("ma_patch")
        self._set_view_mode("ma_patch")

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
    ) -> None:
        try:
            buffer = load_audio(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Unable to Load Audio", str(exc))
            return

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
        self.timeline.set_audio(buffer)
        self.timeline.set_song(self.current_song)
        self.monitor.set_song(self.current_song)
        self.transport.set_times(0.0, self.engine.duration)
        self.monitor.set_position(0.0, self.engine.duration)
        if mark_dirty:
            self._mark_dirty()
        self._refresh_status()
        self.status.showMessage(f"Loaded: {path.name} ({buffer.duration_seconds:.2f}s)", 4000)

    def _toggle_clean_output(self, checked: bool) -> None:
        if checked:
            self.clean_output_window.show()
            self.clean_output_window.raise_()
        else:
            self.clean_output_window.hide()

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

    def _on_video_clip_edited(self, clip_id: str, old: tuple, new: tuple) -> None:
        self._undo.push(EditVideoClipsCommand(changes={clip_id: (old, new)}))
        self.video_sync.refresh()
        self.engine.refresh_video_clips()
        self._mark_dirty()

    def _on_video_clips_batch_edited(self, changes: object) -> None:
        if not isinstance(changes, dict) or not changes:
            return
        self._undo.push(EditVideoClipsCommand(changes=dict(changes)))
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
            duration = max(0.2, info.duration_seconds)
            source_duration = info.duration_seconds
        max_start = max(0.0, self.current_song.duration_seconds - duration)
        clip = VideoClip.create(
            name=path.stem,
            path=path,
            start_seconds=min(max(0.0, start_seconds), max_start),
            duration_seconds=duration,
            media_kind="still" if is_still else "video",
            source_duration_seconds=source_duration,
        )
        self.current_song.add_video_clip(clip)
        self._undo.push(AddVideoClipsCommand(clips=[VideoClipSnapshot.from_clip(clip)]))
        self.video_sync.refresh()
        self.engine.refresh_video_clips()
        self.timeline.update()
        self._mark_dirty()
        kind_label = "still image" if is_still else "video clip"
        self.status.showMessage(f"Added {kind_label}: {clip.name} ({duration:.2f}s)", 3000)
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
        self._undo.push(DeleteVideoClipsCommand(clips=snapshots))
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
        self._undo.push(
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
        self._undo.push(
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
        max_start = max(0.0, self.current_song.duration_seconds - clip.duration_seconds)
        new_start = min(clip.end_seconds, max_start)
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
        self._undo.push(
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
        duration = self.current_song.duration_seconds
        new_clips: list[VideoClip] = []
        for snap in self._video_clip_clipboard:
            offset = snap.start_seconds - anchor
            max_start = max(0.0, duration - snap.duration_seconds)
            start = min(max(0.0, paste_at + offset), max_start)
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
        self._undo.push(
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
        self._undo.push(AddMarksCommand(marks=[MarkSnapshot.from_mark(mark)]))
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
            tc_flags.append("LTC gen")
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
