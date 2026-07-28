"""Edit song setlist number / name / MA English / start timecode / FPS."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cueplayer.exporters.common import sanitize_ma_name
from cueplayer.ui.drag_drop import AUDIO_SUFFIXES, VIDEO_SUFFIXES

_FPS_CHOICES: list[tuple[str, float]] = [
    ("24", 24.0),
    ("25", 25.0),
    ("29.97", 29.97),
    ("30", 30.0),
]

_COL_NUM = 0
_COL_NAME = 1
_COL_MA = 2
_COL_BPM = 3
_COL_TC = 4
_COL_FPS = 5
_COL_LEFT_LTC = 6
_COL_FILE = 7
_COL_COUNT = 8


_EDIT_STYLE = "QLineEdit { border-radius: 3px; }"


@dataclass
class SongDraft:
    name: str
    setlist_number: float = 1.0
    ma_export_name: str = ""
    bpm: float | None = None
    start_timecode: str = "01:00:00:00"
    fps: float = 30.0
    audio_path: Path | None = None
    video_path: Path | None = None
    song_id: str | None = None
    # off | left | right | auto — send that file channel to Settings LTC Ch.
    file_ltc_side: str = "auto"


def format_bpm(value: float | None) -> str:
    if value is None or value <= 0:
        return ""
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:g}"


def parse_bpm(text: str) -> float | None | bool:
    """Return float, None (blank), or False (invalid)."""
    raw = text.strip().replace(",", ".")
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return False
    if value <= 0:
        return False
    return value


def format_setlist_number(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text or "0"


def parse_setlist_number(text: str) -> float | None:
    raw = text.strip().replace(",", ".")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def normalize_timecode(text: str, *, fps: float = 30.0) -> str | None:
    """Accept H:MM:SS:FF or HH:MM:SS:FF; return zero-padded form or None."""
    raw = text.strip().replace(";", ":")
    parts = raw.split(":")
    if len(parts) != 4:
        return None
    try:
        hours, minutes, seconds, frames = (int(p) for p in parts)
    except ValueError:
        return None
    max_frame = max(0, int(round(fps)) - 1)
    if hours < 0 or not (0 <= minutes < 60 and 0 <= seconds < 60 and 0 <= frames <= max_frame):
        return None
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}"


def suggest_ma_export_name(display_name: str) -> str:
    """Keep ASCII-ish names; leave blank when the display name is Chinese-only."""
    if not re.search(r"[A-Za-z0-9]", display_name):
        return ""
    return sanitize_ma_name(display_name, fallback="")


def _fps_label(fps: float) -> str:
    for label, value in _FPS_CHOICES:
        if abs(value - fps) < 0.01:
            return label
    return f"{fps:g}"


_MEDIA_BROWSE_FILTER = (
    "Media (*.wav *.mp3 *.flac *.ogg *.aiff *.aif *.m4a *.aac *.wma *.opus "
    "*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.png *.jpg *.jpeg *.webp);;"
    "All Files (*.*)"
)


def _line_edit(text: str) -> QLineEdit:
    """Real line edit so drag-select works (native table editors leave ghost text)."""
    edit = QLineEdit(text)
    edit.setStyleSheet(_EDIT_STYLE)
    edit.setClearButtonEnabled(True)
    edit.setCursorPosition(0)
    return edit


class _AudioFileCell(QWidget):
    """Rightmost Add/Edit Song column: path label + Browse… (+ Clear)."""

    def __init__(self, path: Path | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._path = Path(path) if path is not None else None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)
        # Ignored horizontal policy lets the label shrink so Browse/Clear stay visible
        # (default Preferred sizeHint fights Stretch siblings and overlaps buttons).
        self._label = QLabel()
        self._label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._label.setMinimumWidth(0)
        self._label.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )
        browse = QPushButton("Browse…")
        browse.setFixedWidth(78)
        browse.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        browse.setToolTip("Choose an audio or video file for this song")
        browse.clicked.connect(self._browse)
        clear = QPushButton("X")
        clear.setFixedWidth(28)
        clear.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        clear.setToolTip("Clear media file")
        clear.clicked.connect(self._clear)
        layout.addWidget(self._label, stretch=1)
        layout.addWidget(browse, stretch=0)
        layout.addWidget(clear, stretch=0)
        self._refresh_label()

    @property
    def path(self) -> Path | None:
        return self._path

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._refresh_label()

    def _full_label_text(self) -> str:
        return self._path.name if self._path is not None else "—"

    def _refresh_label(self) -> None:
        full = self._full_label_text()
        tip = str(self._path) if self._path is not None else "No media file"
        self._label.setToolTip(tip)
        width = max(0, self._label.width())
        if width <= 0:
            self._label.setText(full)
            return
        elided = self._label.fontMetrics().elidedText(
            full, Qt.TextElideMode.ElideMiddle, width
        )
        self._label.setText(elided)

    def _browse(self) -> None:
        start = str(self._path.parent) if self._path is not None else ""
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Media File",
            start,
            _MEDIA_BROWSE_FILTER,
        )
        if not path_str:
            return
        self._path = Path(path_str)
        self._refresh_label()

    def _clear(self) -> None:
        self._path = None
        self._refresh_label()


class SongEditDialog(QDialog):
    """Table editor for one or many songs (CuePoints-like track fields)."""

    def __init__(
        self,
        drafts: list[SongDraft],
        *,
        title: str = "Edit Song",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if not drafts:
            raise ValueError("SongEditDialog requires at least one draft")
        self.setWindowTitle(title)
        width = 1200 if len(drafts) > 1 else 1040
        self.resize(width, min(480, 180 + 44 * len(drafts)))
        self.setMinimumWidth(900)
        self._drafts = [
            SongDraft(
                name=d.name,
                setlist_number=d.setlist_number,
                ma_export_name=d.ma_export_name,
                bpm=d.bpm,
                start_timecode=d.start_timecode,
                fps=d.fps,
                audio_path=d.audio_path,
                video_path=d.video_path,
                song_id=d.song_id,
                file_ltc_side=str(d.file_ltc_side or "auto"),
            )
            for d in drafts
        ]

        root = QVBoxLayout(self)
        hint = QLabel(
            "Numbers can be customized (e.g. 0.5 for an interlude). After editing, use "
            '"Sort by Number" in the Setlist. Names can be Chinese; English/MA should use '
            "pinyin or letters/numbers; BPM can be left blank. "
            "File LTC: send Left/Right (or Auto-detect) striped timecode to the LTC "
            "channel in Audio / Timecode settings; that side is removed from speakers."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; margin-bottom: 4px;")
        root.addWidget(hint)

        self.table = QTableWidget(len(self._drafts), _COL_COUNT)
        self.table.setHorizontalHeaderLabels(
            [
                "Number",
                "Song Name",
                "English / MA",
                "BPM",
                "Start Timecode",
                "FPS",
                "File LTC",
                "Media File",
            ]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.verticalHeader().setDefaultSectionSize(36)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(_COL_NUM, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(_COL_NUM, 64)
        header.setSectionResizeMode(_COL_NAME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(_COL_MA, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(_COL_BPM, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(_COL_BPM, 64)
        header.setSectionResizeMode(_COL_TC, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(_COL_TC, 130)
        header.setSectionResizeMode(_COL_FPS, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(_COL_FPS, 72)
        header.setSectionResizeMode(_COL_LEFT_LTC, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(_COL_LEFT_LTC, 78)
        header.setSectionResizeMode(_COL_FILE, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(_COL_FILE, 260)
        header.setMinimumSectionSize(40)

        for row, draft in enumerate(self._drafts):
            num_edit = _line_edit(format_setlist_number(draft.setlist_number))
            num_edit.setToolTip('Accepts 0.5, 1, 1.5…; use "Sort by Number" in the Setlist to reorder')
            num_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            num_edit.setClearButtonEnabled(False)
            self.table.setCellWidget(row, _COL_NUM, num_edit)

            name_edit = _line_edit(draft.name)
            name_edit.setToolTip("Name shown in the Setlist (Chinese allowed)")
            self.table.setCellWidget(row, _COL_NAME, name_edit)

            ma_edit = _line_edit(draft.ma_export_name)
            ma_edit.setToolTip("Pinyin or English; leave blank to fill in later at export time")
            self.table.setCellWidget(row, _COL_MA, ma_edit)

            bpm_edit = _line_edit(format_bpm(draft.bpm))
            bpm_edit.setToolTip("Can be left blank; e.g. 120, 128.5")
            bpm_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            bpm_edit.setClearButtonEnabled(False)
            self.table.setCellWidget(row, _COL_BPM, bpm_edit)

            tc_edit = _line_edit(draft.start_timecode)
            tc_edit.setToolTip("HH:MM:SS:FF (LTC Generator start)")
            self.table.setCellWidget(row, _COL_TC, tc_edit)

            fps_combo = QComboBox()
            for label, _value in _FPS_CHOICES:
                fps_combo.addItem(label)
            idx = fps_combo.findText(_fps_label(draft.fps))
            fps_combo.setCurrentIndex(idx if idx >= 0 else fps_combo.findText("30"))
            self.table.setCellWidget(row, _COL_FPS, fps_combo)

            ltc_combo = QComboBox()
            for label, value in (
                ("Auto", "auto"),
                ("Left", "left"),
                ("Right", "right"),
                ("Off", "off"),
            ):
                ltc_combo.addItem(label, value)
            side = str(draft.file_ltc_side or "auto")
            idx = ltc_combo.findData(side)
            ltc_combo.setCurrentIndex(idx if idx >= 0 else ltc_combo.findData("auto"))
            ltc_combo.setToolTip(
                "Send this song’s Left or Right (or Auto-detect) channel to the LTC "
                "Channel in Audio / Timecode settings. That side is stripped from "
                "speaker Music Source so LTC stays clean."
            )
            self.table.setCellWidget(row, _COL_LEFT_LTC, ltc_combo)

            file_cell = _AudioFileCell(draft.audio_path or draft.video_path)
            self.table.setCellWidget(row, _COL_FILE, file_cell)

        root.addWidget(self.table, stretch=1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        focus = self.table.cellWidget(0, _COL_NAME)
        if isinstance(focus, QLineEdit):
            focus.setFocus()
            focus.selectAll()

    def result_drafts(self) -> list[SongDraft]:
        return list(self._drafts)

    def _edit_text(self, row: int, col: int) -> str:
        widget = self.table.cellWidget(row, col)
        if isinstance(widget, QLineEdit):
            return widget.text()
        return ""

    def _fps_at_row(self, row: int) -> float:
        widget = self.table.cellWidget(row, _COL_FPS)
        if isinstance(widget, QComboBox):
            text = widget.currentText()
            for label, value in _FPS_CHOICES:
                if label == text:
                    return value
            try:
                return float(text)
            except ValueError:
                return 30.0
        return 30.0

    def _file_ltc_side_at_row(self, row: int) -> str:
        widget = self.table.cellWidget(row, _COL_LEFT_LTC)
        if isinstance(widget, QComboBox):
            return str(widget.currentData() or "auto")
        return "auto"

    def _accept(self) -> None:
        updated: list[SongDraft] = []
        for row in range(self.table.rowCount()):
            num = parse_setlist_number(self._edit_text(row, _COL_NUM))
            if num is None:
                QMessageBox.warning(
                    self,
                    "Invalid Number",
                    f"Row {row + 1}: enter a number for the setlist number (e.g. 1, 0.5, 2.5).",
                )
                widget = self.table.cellWidget(row, _COL_NUM)
                if isinstance(widget, QLineEdit):
                    widget.setFocus()
                return
            name = self._edit_text(row, _COL_NAME).strip()
            if not name:
                QMessageBox.warning(self, "Name Is Blank", f"Row {row + 1}: song name cannot be blank.")
                widget = self.table.cellWidget(row, _COL_NAME)
                if isinstance(widget, QLineEdit):
                    widget.setFocus()
                return
            ma_raw = self._edit_text(row, _COL_MA).strip()
            ma_name = sanitize_ma_name(ma_raw, fallback="") if ma_raw else ""
            if ma_raw and not ma_name:
                QMessageBox.warning(
                    self,
                    "Invalid English / MA Name",
                    f'Row {row + 1}: "English / MA" must use pinyin or letters/numbers '
                    "(cannot be Chinese-only or symbols).",
                )
                widget = self.table.cellWidget(row, _COL_MA)
                if isinstance(widget, QLineEdit):
                    widget.setFocus()
                return
            bpm = parse_bpm(self._edit_text(row, _COL_BPM))
            if bpm is False:
                QMessageBox.warning(
                    self,
                    "Invalid BPM",
                    f"Row {row + 1}: enter a positive BPM (e.g. 120), or leave blank.",
                )
                widget = self.table.cellWidget(row, _COL_BPM)
                if isinstance(widget, QLineEdit):
                    widget.setFocus()
                return
            fps = self._fps_at_row(row)
            tc_raw = self._edit_text(row, _COL_TC).strip()
            tc = normalize_timecode(tc_raw, fps=fps)
            if tc is None:
                QMessageBox.warning(
                    self,
                    "Invalid Timecode",
                    f"Row {row + 1}: use HH:MM:SS:FF (e.g. 01:00:00:00).",
                )
                widget = self.table.cellWidget(row, _COL_TC)
                if isinstance(widget, QLineEdit):
                    widget.setFocus()
                return
            file_widget = self.table.cellWidget(row, _COL_FILE)
            media_path = (
                file_widget.path
                if isinstance(file_widget, _AudioFileCell)
                else (self._drafts[row].audio_path or self._drafts[row].video_path)
            )
            audio_path = None
            video_path = None
            if media_path is not None:
                suf = media_path.suffix.lower()
                if suf in VIDEO_SUFFIXES:
                    video_path = media_path
                elif suf in AUDIO_SUFFIXES:
                    audio_path = media_path
            updated.append(
                SongDraft(
                    name=name,
                    setlist_number=num,
                    ma_export_name=ma_name,
                    bpm=bpm if isinstance(bpm, float) else None,
                    start_timecode=tc,
                    fps=fps,
                    audio_path=audio_path,
                    video_path=video_path,
                    song_id=self._drafts[row].song_id,
                    file_ltc_side=self._file_ltc_side_at_row(row),
                )
            )
        self._drafts = updated
        self.accept()
