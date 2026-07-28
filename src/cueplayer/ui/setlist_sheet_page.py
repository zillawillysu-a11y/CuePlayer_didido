"""Excel-like Setlist sheet — order / names / Timecode Generator starts for MA paste."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cueplayer.domain.models import Project, Song
from cueplayer.exporters.common import sanitize_ma_name
from cueplayer.ui.song_edit_dialog import format_setlist_number, normalize_timecode

_COL_ORDER = 0
_COL_NAME = 1
_COL_EN = 2
_COL_TC = 3
_COL_BPM = 4
_COL_COUNT = 5

_HEADERS = (
    "曲序",
    "曲名",
    "英文名",
    "Timecode Generator",
    "BPM",
)


@dataclass(frozen=True)
class SetlistSheetRow:
    song_id: str
    order: str
    name: str
    english_name: str
    start_timecode: str
    bpm: str


def format_sheet_order(value: float) -> str:
    """Zero-pad whole setlist numbers (01, 02…) for spreadsheet paste."""
    if abs(value - round(value)) < 1e-9:
        n = int(round(value))
        return f"{n:02d}" if 0 <= n < 100 else str(n)
    return format_setlist_number(value)


def format_sheet_bpm(bpm: float | None) -> str:
    if bpm is None:
        return ""
    if abs(bpm - round(bpm)) < 1e-9:
        return str(int(round(bpm)))
    return f"{bpm:.3f}".rstrip("0").rstrip(".")


def iter_setlist_sheet_songs(project: Project) -> list[Song]:
    """Songs in sidebar display order (main list, then each folder), ignore collapse."""
    songs: list[Song] = []
    for song in project.songs:
        if not song.category_id:
            songs.append(song)
    for category in project.setlist_categories:
        for song in project.songs:
            if song.category_id == category.id:
                songs.append(song)
    return songs


def build_setlist_sheet_rows(project: Project) -> list[SetlistSheetRow]:
    rows: list[SetlistSheetRow] = []
    for song in iter_setlist_sheet_songs(project):
        rows.append(
            SetlistSheetRow(
                song_id=song.id,
                order=format_sheet_order(song.setlist_number),
                name=song.name,
                english_name=(song.ma_export_name or "").strip(),
                start_timecode=song.start_timecode,
                bpm=format_sheet_bpm(song.bpm),
            )
        )
    return rows


def sheet_rows_to_tsv(rows: list[SetlistSheetRow], *, include_header: bool = True) -> str:
    lines: list[str] = []
    if include_header:
        lines.append("\t".join(_HEADERS))
    for row in rows:
        lines.append(
            "\t".join(
                (
                    row.order,
                    row.name,
                    row.english_name,
                    row.start_timecode,
                    row.bpm,
                )
            )
        )
    return "\n".join(lines) + ("\n" if lines else "")


class SetlistSheetPage(QWidget):
    """Tabular setlist for copying song order / names / TC starts into MA3."""

    song_field_changed = Signal()  # name / EN / TC / BPM edited

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project: Project | None = None
        self._suppress = False
        self._song_ids: list[str] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(10)

        title = QLabel("Setlist · Sheet")
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #e6edf3;")
        hint = QLabel(
            "Current setlist as a spreadsheet: order, Chinese name, English/MA name, "
            "Timecode Generator start, BPM. Select cells and Copy (Ctrl+C), or Copy All "
            "for paste into Excel / grandMA3."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8b949e;")
        root.addWidget(title)
        root.addWidget(hint)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.copy_all_button = QPushButton("Copy All")
        self.copy_all_button.setToolTip("Copy the whole table (with headers) as TSV")
        self.copy_selection_button = QPushButton("Copy Selection")
        self.copy_selection_button.setToolTip("Copy selected cells as TSV (Ctrl+C)")
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setToolTip("Reload from the current project setlist")
        for btn in (
            self.copy_all_button,
            self.copy_selection_button,
            self.refresh_button,
        ):
            btn.setFixedHeight(30)
        toolbar.addWidget(self.copy_all_button)
        toolbar.addWidget(self.copy_selection_button)
        toolbar.addWidget(self.refresh_button)
        toolbar.addStretch(1)
        root.addLayout(toolbar)

        self.table = QTableWidget(0, _COL_COUNT)
        self.table.setHorizontalHeaderLabels(list(_HEADERS))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(True)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(_COL_ORDER, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_NAME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(_COL_EN, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(_COL_TC, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_BPM, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setStyleSheet(
            "QTableWidget {"
            "  gridline-color: #3f3f46;"
            "  background: #0c0c0e;"
            "  alternate-background-color: #141416;"
            "  color: #e6edf3;"
            "}"
            "QHeaderView::section {"
            "  background: #1a1a1e;"
            "  color: #e6edf3;"
            "  padding: 6px;"
            "  border: 1px solid #3f3f46;"
            "  font-weight: 600;"
            "}"
        )
        root.addWidget(self.table, stretch=1)

        self.copy_all_button.clicked.connect(self.copy_all)
        self.copy_selection_button.clicked.connect(self.copy_selection)
        self.refresh_button.clicked.connect(self.sync_songs)
        self.table.itemChanged.connect(self._on_item_changed)
        QShortcut(QKeySequence.StandardKey.Copy, self, activated=self.copy_selection)

    def set_project(self, project: Project) -> None:
        self._project = project
        self.sync_songs()

    def sync_songs(self) -> None:
        if self._project is None:
            self._suppress = True
            self.table.setRowCount(0)
            self._song_ids = []
            self._suppress = False
            return
        rows = build_setlist_sheet_rows(self._project)
        self._suppress = True
        self.table.setRowCount(len(rows))
        self._song_ids = [r.song_id for r in rows]
        for r, row in enumerate(rows):
            order_item = QTableWidgetItem(row.order)
            order_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            order_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            )
            order_item.setData(Qt.ItemDataRole.UserRole, row.song_id)

            name_item = QTableWidgetItem(row.name)
            name_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEditable
            )

            en_item = QTableWidgetItem(row.english_name)
            en_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEditable
            )
            en_item.setToolTip("English / MA export name (ASCII; no Chinese in MA XML)")

            tc_item = QTableWidgetItem(row.start_timecode)
            tc_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tc_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEditable
            )
            tc_item.setToolTip("Timecode Generator start for this song (HH:MM:SS:FF)")

            bpm_item = QTableWidgetItem(row.bpm)
            bpm_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            bpm_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEditable
            )

            self.table.setItem(r, _COL_ORDER, order_item)
            self.table.setItem(r, _COL_NAME, name_item)
            self.table.setItem(r, _COL_EN, en_item)
            self.table.setItem(r, _COL_TC, tc_item)
            self.table.setItem(r, _COL_BPM, bpm_item)
        self._suppress = False

    def _song_at_row(self, row: int) -> Song | None:
        if self._project is None or row < 0 or row >= len(self._song_ids):
            return None
        song_id = self._song_ids[row]
        return next((s for s in self._project.songs if s.id == song_id), None)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._suppress or self._project is None or item is None:
            return
        song = self._song_at_row(item.row())
        if song is None:
            return
        col = item.column()
        text = item.text()
        changed = False
        if col == _COL_NAME:
            name = text.strip() or "Untitled Song"
            if song.name != name:
                song.name = name
                changed = True
            if item.text() != name:
                self._suppress = True
                item.setText(name)
                self._suppress = False
        elif col == _COL_EN:
            raw = text.strip()
            ma = sanitize_ma_name(raw, fallback="") if raw else ""
            if raw and not ma:
                QMessageBox.warning(
                    self,
                    "Invalid English/MA Name",
                    "Use letters/numbers (spaces, _ . - allowed); "
                    "Chinese characters will be stripped.",
                )
                self._suppress = True
                item.setText((song.ma_export_name or "").strip())
                self._suppress = False
                return
            new_val = ma or None
            if (song.ma_export_name or None) != new_val:
                song.ma_export_name = new_val
                changed = True
            display = (song.ma_export_name or "").strip()
            if item.text() != display:
                self._suppress = True
                item.setText(display)
                self._suppress = False
        elif col == _COL_TC:
            normalized = normalize_timecode(text, fps=song.fps)
            if normalized is None:
                QMessageBox.warning(
                    self,
                    "Invalid Timecode",
                    "Use HH:MM:SS:FF (frames within the song FPS).",
                )
                self._suppress = True
                item.setText(song.start_timecode)
                self._suppress = False
                return
            if song.start_timecode != normalized:
                song.start_timecode = normalized
                changed = True
            if item.text() != normalized:
                self._suppress = True
                item.setText(normalized)
                self._suppress = False
        elif col == _COL_BPM:
            raw = text.strip()
            if not raw:
                if song.bpm is not None:
                    song.bpm = None
                    changed = True
            else:
                try:
                    value = float(raw.replace(",", "."))
                except ValueError:
                    QMessageBox.warning(self, "Invalid BPM", "Enter a number or leave blank.")
                    self._suppress = True
                    item.setText(format_sheet_bpm(song.bpm))
                    self._suppress = False
                    return
                if value <= 0:
                    QMessageBox.warning(self, "Invalid BPM", "BPM must be greater than 0.")
                    self._suppress = True
                    item.setText(format_sheet_bpm(song.bpm))
                    self._suppress = False
                    return
                if song.bpm != value:
                    song.bpm = value
                    changed = True
                display = format_sheet_bpm(song.bpm)
                if item.text() != display:
                    self._suppress = True
                    item.setText(display)
                    self._suppress = False
        if changed:
            self.song_field_changed.emit()

    def copy_all(self) -> None:
        if self._project is None:
            return
        text = sheet_rows_to_tsv(build_setlist_sheet_rows(self._project))
        QGuiApplication.clipboard().setText(text)
        self.copy_all_button.setToolTip("Copied — paste into Excel / MA3")

    def copy_selection(self) -> None:
        ranges = self.table.selectedRanges()
        if not ranges:
            self.copy_all()
            return
        # Build a rectangular TSV covering the union of selected ranges.
        top = min(r.topRow() for r in ranges)
        bottom = max(r.bottomRow() for r in ranges)
        left = min(r.leftColumn() for r in ranges)
        right = max(r.rightColumn() for r in ranges)
        selected = {
            (idx.row(), idx.column()) for idx in self.table.selectedIndexes()
        }
        lines: list[str] = []
        header_slice = list(_HEADERS)[left : right + 1]
        lines.append("\t".join(header_slice))
        for row in range(top, bottom + 1):
            cells: list[str] = []
            for col in range(left, right + 1):
                if (row, col) not in selected:
                    cells.append("")
                    continue
                item = self.table.item(row, col)
                cells.append(item.text() if item is not None else "")
            lines.append("\t".join(cells))
        QGuiApplication.clipboard().setText("\n".join(lines) + "\n")
