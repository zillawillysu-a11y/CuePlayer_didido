"""Missing Media Relink dialog — rematch audio/video files after a move."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cueplayer.domain.media_relink import (
    MissingMediaRef,
    apply_relink,
    relink_from_folder,
    scan_missing_media,
)
from cueplayer.domain.models import Project


class MissingMediaRelinkDialog(QDialog):
    """List missing media; relink one file or match a whole folder by basename."""

    def __init__(
        self,
        project: Project,
        parent: QWidget | None = None,
        *,
        initial_dir: str | Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Relink Missing Media")
        self.resize(720, 420)
        self._project = project
        self._initial_dir = str(initial_dir or "")
        self._missing: list[MissingMediaRef] = []
        self._changed = False

        layout = QVBoxLayout(self)
        self.hint = QLabel(
            "These media files are missing from disk. "
            "Relink a single file, or pick a folder to match by file name "
            "(works when you moved a whole media bundle)."
        )
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #a1a1aa;")
        layout.addWidget(self.hint)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Song", "Type", "Name", "Expected path"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnWidth(0, 140)
        self.table.setColumnWidth(1, 64)
        self.table.setColumnWidth(2, 140)
        layout.addWidget(self.table, stretch=1)

        row = QHBoxLayout()
        self.relink_file_btn = QPushButton("Relink File…")
        self.relink_file_btn.setToolTip("Pick a new file for the selected row")
        self.relink_folder_btn = QPushButton("Relink Folder…")
        self.relink_folder_btn.setToolTip(
            "Scan a folder (recursive) and rematch by basename"
        )
        self.refresh_btn = QPushButton("Rescan")
        row.addWidget(self.relink_file_btn)
        row.addWidget(self.relink_folder_btn)
        row.addWidget(self.refresh_btn)
        row.addStretch(1)
        layout.addLayout(row)

        self.status = QLabel("")
        self.status.setStyleSheet("color: #8b949e;")
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_btn is not None:
            close_btn.clicked.connect(self.accept)
        layout.addWidget(buttons)

        self.relink_file_btn.clicked.connect(self._relink_selected_file)
        self.relink_folder_btn.clicked.connect(self._relink_folder)
        self.refresh_btn.clicked.connect(self._rescan)
        self.table.doubleClicked.connect(lambda _idx: self._relink_selected_file())

        self._rescan()

    @property
    def changed(self) -> bool:
        return self._changed

    def _rescan(self) -> None:
        self._missing = scan_missing_media(self._project)
        self.table.setRowCount(0)
        for ref in self._missing:
            row = self.table.rowCount()
            self.table.insertRow(row)
            kind_label = "Audio" if ref.kind == "audio" else "Video"
            values = (ref.song_name, kind_label, ref.item_name, str(ref.path))
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, ref)
                self.table.setItem(row, col, item)
        n = len(self._missing)
        if n == 0:
            self.status.setText("All media files found.")
            self.relink_file_btn.setEnabled(False)
            self.relink_folder_btn.setEnabled(False)
        else:
            self.status.setText(f"{n} missing file(s).")
            self.relink_file_btn.setEnabled(True)
            self.relink_folder_btn.setEnabled(True)
        if self.table.rowCount() > 0:
            self.table.selectRow(0)

    def _selected_ref(self) -> MissingMediaRef | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        if item is None:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        return data if isinstance(data, MissingMediaRef) else None

    def _relink_selected_file(self) -> None:
        ref = self._selected_ref()
        if ref is None:
            QMessageBox.information(self, "Relink", "Select a missing file first.")
            return
        if ref.kind == "audio":
            filt = "Audio (*.wav *.flac *.ogg *.mp3 *.aiff *.aif);;All Files (*.*)"
        else:
            filt = (
                "Video / Image (*.mp4 *.mov *.mkv *.avi *.webm *.png *.jpg *.jpeg "
                "*.tif *.tiff *.bmp *.webp);;All Files (*.*)"
            )
        start = self._initial_dir or str(ref.path.parent)
        path_str, _ = QFileDialog.getOpenFileName(
            self, f"Relink {ref.item_name}", start, filt
        )
        if not path_str:
            return
        new_path = Path(path_str)
        if apply_relink(self._project, ref, new_path):
            self._changed = True
            self._initial_dir = str(new_path.parent)
            self._rescan()
            self.status.setText(f"Relinked → {new_path.name}")

    def _relink_folder(self) -> None:
        if not self._missing:
            return
        start = self._initial_dir or ""
        folder = QFileDialog.getExistingDirectory(
            self, "Choose folder containing media", start
        )
        if not folder:
            return
        folder_path = Path(folder)
        result = relink_from_folder(self._project, list(self._missing), folder_path)
        if result.linked:
            self._changed = True
            self._initial_dir = str(folder_path)
        self._rescan()
        parts = [f"Linked {len(result.linked)}"]
        if result.ambiguous:
            parts.append(f"{len(result.ambiguous)} ambiguous (same name twice)")
        if result.unmatched:
            parts.append(f"{len(result.unmatched)} unmatched")
        self.status.setText(" · ".join(parts))
        if result.ambiguous:
            names = ", ".join(r.basename for r in result.ambiguous[:8])
            extra = "…" if len(result.ambiguous) > 8 else ""
            QMessageBox.information(
                self,
                "Ambiguous names",
                "These basenames matched more than one file in the folder "
                f"(relink them one by one):\n\n{names}{extra}",
            )
