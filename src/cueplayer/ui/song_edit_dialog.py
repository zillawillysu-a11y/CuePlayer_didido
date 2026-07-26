"""Edit song setlist number / name / MA English / start timecode / FPS."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cueplayer.exporters.common import sanitize_ma_name

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
_COL_FILE = 6


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
    song_id: str | None = None


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
    return sanitize_ma_name(display_name, fallback="")


def _fps_label(fps: float) -> str:
    for label, value in _FPS_CHOICES:
        if abs(value - fps) < 0.01:
            return label
    return f"{fps:g}"


def _line_edit(text: str) -> QLineEdit:
    """Real line edit so drag-select works (native table editors leave ghost text)."""
    edit = QLineEdit(text)
    edit.setStyleSheet(_EDIT_STYLE)
    edit.setClearButtonEnabled(True)
    edit.setCursorPosition(0)
    return edit


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
        width = 1020 if len(drafts) > 1 else 820
        self.resize(width, min(480, 180 + 44 * len(drafts)))
        self._drafts = [
            SongDraft(
                name=d.name,
                setlist_number=d.setlist_number,
                ma_export_name=d.ma_export_name,
                bpm=d.bpm,
                start_timecode=d.start_timecode,
                fps=d.fps,
                audio_path=d.audio_path,
                song_id=d.song_id,
            )
            for d in drafts
        ]

        root = QVBoxLayout(self)
        hint = QLabel(
            "Numbers can be customized (e.g. 0.5 for an interlude). After editing, use "
            '"Sort by Number" in the Setlist. Names can be Chinese; English/MA should use '
            "pinyin or letters/numbers; BPM can be left blank."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; margin-bottom: 4px;")
        root.addWidget(hint)

        self.table = QTableWidget(len(self._drafts), 7)
        self.table.setHorizontalHeaderLabels(
            ["Number", "Song Name", "English / MA", "BPM", "Start Timecode", "FPS", "Audio File"]
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
        header.resizeSection(_COL_FPS, 90)
        header.setSectionResizeMode(_COL_FILE, QHeaderView.ResizeMode.Stretch)

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

            file_text = draft.audio_path.name if draft.audio_path is not None else "—"
            file_item = QTableWidgetItem(file_text)
            file_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            if draft.audio_path is not None:
                file_item.setToolTip(str(draft.audio_path))
            self.table.setItem(row, _COL_FILE, file_item)

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
            updated.append(
                SongDraft(
                    name=name,
                    setlist_number=num,
                    ma_export_name=ma_name,
                    bpm=bpm if isinstance(bpm, float) else None,
                    start_timecode=tc,
                    fps=fps,
                    audio_path=self._drafts[row].audio_path,
                    song_id=self._drafts[row].song_id,
                )
            )
        self._drafts = updated
        self.accept()
