"""Excel-like Set List Sheet — order / names / Timecode / Note for MA paste."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QKeySequence, QShortcut
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
from cueplayer.exporters.show_patch import SongPatchSlot, build_show_patch
from cueplayer.ui.song_edit_dialog import (
    format_setlist_number,
    normalize_timecode,
    parse_setlist_number,
)

_COL_ORDER = 0
_COL_NAME = 1
_COL_EN = 2
_COL_SEQ = 3
_COL_CUE_ID = 4
_COL_TC = 5
_COL_BPM = 6
_COL_NOTE = 7
_COL_COUNT = 8

_HEADERS = (
    "曲序",
    "曲名",
    "英文名",
    "Seq",
    "Cue ID",
    "Timecode Generator",
    "BPM",
    "Note",
)

_ROLE_KIND = int(Qt.ItemDataRole.UserRole) + 1
_ROLE_CATEGORY_ID = int(Qt.ItemDataRole.UserRole) + 2

_FOLDER_BG = QColor("#1a1a28")
_FOLDER_FG = QColor("#a5b4fc")


@dataclass(frozen=True)
class SetlistSheetRow:
    kind: str  # "song" | "folder"
    song_id: str | None = None
    category_id: str | None = None
    order: str = ""
    name: str = ""
    english_name: str = ""
    start_timecode: str = ""
    bpm: str = ""
    seq: str = ""
    cue_id: str = ""
    note: str = ""
    collapsed: bool = False

    @property
    def is_folder(self) -> bool:
        return self.kind == "folder"


def folder_row_label(name: str, *, collapsed: bool) -> str:
    arrow = "▸" if collapsed else "▾"
    return f"{arrow} {name}"


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
    """Songs in sidebar display order (main list, then each folder)."""
    songs: list[Song] = []
    for song in project.songs:
        if not song.category_id:
            songs.append(song)
    for category in project.setlist_categories:
        for song in project.songs:
            if song.category_id == category.id:
                songs.append(song)
    return songs


def build_sheet_patch_lookup(project: Project) -> dict[str, SongPatchSlot]:
    """MA Sequence pool + Cue ID per song (same order as the sheet / Export chain)."""
    ordered = iter_setlist_sheet_songs(project)
    if not ordered:
        return {}
    slots = build_show_patch(ordered, project.ma_export)
    return {slot.song.id: slot for slot in slots}


def build_setlist_sheet_rows(project: Project) -> list[SetlistSheetRow]:
    """Sidebar order: main-list songs, then each Folder header + its songs."""
    patch = build_sheet_patch_lookup(project)
    rows: list[SetlistSheetRow] = []
    for song in project.songs:
        if song.category_id:
            continue
        rows.append(_song_row(song, patch.get(song.id)))
    for category in project.setlist_categories:
        rows.append(
            SetlistSheetRow(
                kind="folder",
                category_id=category.id,
                name=category.name.strip() or "Folder",
                collapsed=bool(category.collapsed),
            )
        )
        if category.collapsed:
            continue
        for song in project.songs:
            if song.category_id == category.id:
                rows.append(_song_row(song, patch.get(song.id)))
    return rows


def _song_row(song: Song, slot: SongPatchSlot | None = None) -> SetlistSheetRow:
    seq = str(slot.main_sequence) if slot is not None else ""
    cue_id = slot.main_sequence_name if slot is not None else ""
    return SetlistSheetRow(
        kind="song",
        song_id=song.id,
        order=format_sheet_order(song.setlist_number),
        name=song.name,
        english_name=(song.ma_export_name or "").strip(),
        start_timecode=song.start_timecode,
        bpm=format_sheet_bpm(song.bpm),
        seq=seq,
        cue_id=cue_id,
        note=(song.note or "").strip(),
    )


def sheet_rows_to_tsv(rows: list[SetlistSheetRow], *, include_header: bool = True) -> str:
    lines: list[str] = []
    if include_header:
        lines.append("\t".join(_HEADERS))
    for row in rows:
        if row.is_folder:
            lines.append(
                "\t".join(
                    ("", folder_row_label(row.name, collapsed=row.collapsed), "", "", "", "", "", "")
                )
            )
            continue
        lines.append(
            "\t".join(
                (
                    row.order,
                    row.name,
                    row.english_name,
                    row.seq,
                    row.cue_id,
                    row.start_timecode,
                    row.bpm,
                    row.note,
                )
            )
        )
    return "\n".join(lines) + ("\n" if lines else "")


class SetlistSheetPage(QWidget):
    """Tabular Set List Sheet for copying song order / names / TC / notes into MA3."""

    song_field_changed = Signal()  # order / name / EN / TC / BPM / Note edited
    folder_toggle_requested = Signal(str)  # category id — syncs with left Setlist

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project: Project | None = None
        self._suppress = False
        self._song_ids: list[str | None] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(10)

        title = QLabel("Set List Sheet")
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #e6edf3;")
        hint = QLabel(
            "Spreadsheet of the current show: 曲序, 曲名, 英文名, Seq, Cue ID "
            "(MA Main Sequence), Timecode Generator, BPM, Note. Click ▸/▾ Folder "
            "rows to expand or collapse (synced with the left Setlist). Drag column "
            "edges to resize. Double-click cells to edit. Copy All / Ctrl+C for "
            "Excel / grandMA3."
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
        header.setSectionsMovable(False)
        header.setStretchLastSection(True)
        header.setMinimumSectionSize(40)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.resizeSection(_COL_ORDER, 64)
        header.resizeSection(_COL_NAME, 180)
        header.resizeSection(_COL_EN, 160)
        header.resizeSection(_COL_SEQ, 56)
        header.resizeSection(_COL_CUE_ID, 160)
        header.resizeSection(_COL_TC, 140)
        header.resizeSection(_COL_BPM, 56)
        header.resizeSection(_COL_NOTE, 180)
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
        self.table.cellClicked.connect(self._on_cell_clicked)
        QShortcut(QKeySequence.StandardKey.Copy, self, activated=self.copy_selection)

    def set_project(self, project: Project) -> None:
        self._project = project
        self.sync_songs()

    def sync_songs(self) -> None:
        if self._project is None:
            self._suppress = True
            self.table.clearSpans()
            self.table.setRowCount(0)
            self._song_ids = []
            self._suppress = False
            return
        rows = build_setlist_sheet_rows(self._project)
        self._suppress = True
        self.table.clearSpans()
        self.table.setRowCount(len(rows))
        self._song_ids = [r.song_id for r in rows]
        for r, row in enumerate(rows):
            if row.is_folder:
                self._fill_folder_row(r, row)
                continue
            self._fill_song_row(r, row)
        self._suppress = False

    def _fill_folder_row(self, r: int, row: SetlistSheetRow) -> None:
        label = folder_row_label(row.name, collapsed=row.collapsed)
        item = QTableWidgetItem(label)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        item.setData(_ROLE_KIND, "folder")
        item.setData(_ROLE_CATEGORY_ID, row.category_id or "")
        item.setBackground(QBrush(_FOLDER_BG))
        item.setForeground(QBrush(_FOLDER_FG))
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        item.setToolTip(
            "Click ▸/▾ to expand or collapse this folder (same as left Setlist)"
        )
        self.table.setItem(r, _COL_ORDER, item)
        self.table.setSpan(r, _COL_ORDER, 1, _COL_COUNT)

    def _on_cell_clicked(self, row: int, _col: int) -> None:
        item = self.table.item(row, _COL_ORDER)
        if item is None or item.data(_ROLE_KIND) != "folder":
            return
        category_id = item.data(_ROLE_CATEGORY_ID)
        if category_id:
            self.folder_toggle_requested.emit(str(category_id))

    def _fill_song_row(self, r: int, row: SetlistSheetRow) -> None:
        order_item = QTableWidgetItem(row.order)
        order_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        order_item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsEditable
        )
        order_item.setData(Qt.ItemDataRole.UserRole, row.song_id)
        order_item.setData(_ROLE_KIND, "song")
        order_item.setToolTip("Setlist number (0.5 supported) — double-click to edit")

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

        seq_item = QTableWidgetItem(row.seq)
        seq_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        seq_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        seq_item.setToolTip("MA Sequence pool number (Main track — matches Export page)")

        cue_item = QTableWidgetItem(row.cue_id)
        cue_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        cue_item.setToolTip("MA Main Sequence name (e.g. SongName_Main)")

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

        note_item = QTableWidgetItem(row.note)
        note_item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsEditable
        )
        note_item.setToolTip("Free-text production note (not written into MA XML)")

        self.table.setItem(r, _COL_ORDER, order_item)
        self.table.setItem(r, _COL_NAME, name_item)
        self.table.setItem(r, _COL_EN, en_item)
        self.table.setItem(r, _COL_SEQ, seq_item)
        self.table.setItem(r, _COL_CUE_ID, cue_item)
        self.table.setItem(r, _COL_TC, tc_item)
        self.table.setItem(r, _COL_BPM, bpm_item)
        self.table.setItem(r, _COL_NOTE, note_item)

    def _song_at_row(self, row: int) -> Song | None:
        if self._project is None or row < 0 or row >= len(self._song_ids):
            return None
        song_id = self._song_ids[row]
        if not song_id:
            return None
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
        if col == _COL_ORDER:
            parsed = parse_setlist_number(text)
            if parsed is None:
                QMessageBox.warning(
                    self,
                    "Invalid 曲序",
                    "Enter a number such as 1, 01, or 0.5.",
                )
                self._suppress = True
                item.setText(format_sheet_order(song.setlist_number))
                self._suppress = False
                return
            if song.setlist_number != parsed:
                song.setlist_number = parsed
                changed = True
            display = format_sheet_order(song.setlist_number)
            if item.text() != display:
                self._suppress = True
                item.setText(display)
                self._suppress = False
        elif col == _COL_NAME:
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
        elif col == _COL_NOTE:
            note = text.strip()
            if (song.note or "") != note:
                song.note = note
                changed = True
            if item.text() != note:
                self._suppress = True
                item.setText(note)
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
            kind_item = self.table.item(row, _COL_ORDER)
            is_folder = (
                kind_item is not None
                and kind_item.data(_ROLE_KIND) == "folder"
            )
            if is_folder:
                label = kind_item.text() if kind_item is not None else ""
                for col in range(left, right + 1):
                    if (row, col) not in selected and col != left:
                        cells.append("")
                    elif col == left:
                        cells.append(label)
                    else:
                        cells.append("")
                lines.append("\t".join(cells))
                continue
            for col in range(left, right + 1):
                if (row, col) not in selected:
                    cells.append("")
                    continue
                cell = self.table.item(row, col)
                cells.append(cell.text() if cell is not None else "")
            lines.append("\t".join(cells))
        QGuiApplication.clipboard().setText("\n".join(lines) + "\n")
