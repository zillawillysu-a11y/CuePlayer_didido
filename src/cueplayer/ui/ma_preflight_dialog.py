"""MA Preflight dialog — read-only presentation of ``PreflightReport`` (MVP).

Consumes a pre-built ``PreflightReport`` only. Does not run validation rules,
import exporters, or mutate project data. Navigation is signaled to the host.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cueplayer.domain.validation.preflight_report import (
    PreflightIssueRow,
    PreflightReport,
)

_ROLE_ROW = Qt.ItemDataRole.UserRole


def format_issue_target(row: PreflightIssueRow) -> str:
    """Human Song / Object column text for a presentation row."""
    parts: list[str] = []
    if row.song_name.strip():
        parts.append(row.song_name.strip())
    elif row.song_id.strip() and row.object_kind != "song":
        parts.append(row.song_id.strip())
    ref = row.object_ref
    if ref:
        if row.object_kind == "song" and row.song_name:
            # Song name already shown; avoid redundant song:id.
            pass
        else:
            parts.append(ref)
    return " · ".join(parts) if parts else "—"


def navigation_target(row: PreflightIssueRow) -> tuple[str, str, str] | None:
    """Return ``(song_id, object_kind, object_id)`` when navigation is possible.

    Project / settings / executor-only / summary rows return ``None``.
    """
    kind = (row.object_kind or "").strip().lower()
    oid = (row.object_id or "").strip()
    song_id = (row.song_id or "").strip()

    if kind == "song" and oid:
        return oid, "song", oid
    if kind == "mark" and oid:
        if not song_id:
            return None
        return song_id, "mark", oid
    if kind == "sequence":
        if song_id:
            return song_id, "sequence", oid
        # Keys are ``{song_id}:main`` / ``{song_id}:button:…``.
        if ":" in oid:
            return oid.split(":", 1)[0], "sequence", oid
        return None
    if song_id:
        return song_id, kind or "song", oid or song_id
    return None


class MaPreflightDialog(QDialog):
    """Modal read-only MA Preflight report viewer.

    Signals
    -------
    navigate_requested(song_id, object_kind, object_id)
        Emitted on double-click when a navigable Song / object is available.
    """

    navigate_requested = Signal(str, str, str)

    def __init__(
        self,
        report: PreflightReport,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if not isinstance(report, PreflightReport):
            raise TypeError(
                f"MaPreflightDialog requires PreflightReport, got {type(report).__name__}"
            )
        self._report = report
        self._rows: tuple[PreflightIssueRow, ...] = report.issues

        self.setWindowTitle("MA Preflight")
        self.resize(820, 480)

        layout = QVBoxLayout(self)

        title = QLabel(report.summary())
        title.setObjectName("preflightSummaryTitle")
        title.setWordWrap(True)
        title.setStyleSheet("font-weight: 600; font-size: 13px;")
        layout.addWidget(title)

        summary_row = QHBoxLayout()
        self.error_count_label = QLabel(f"Errors: {report.error_count}")
        self.error_count_label.setObjectName("preflightErrorCount")
        self.warning_count_label = QLabel(f"Warnings: {report.warning_count}")
        self.warning_count_label.setObjectName("preflightWarningCount")
        self.info_count_label = QLabel(f"Information: {report.information_count}")
        self.info_count_label.setObjectName("preflightInfoCount")
        self.error_count_label.setStyleSheet("color: #f85149;")
        self.warning_count_label.setStyleSheet("color: #d29922;")
        self.info_count_label.setStyleSheet("color: #8b949e;")
        summary_row.addWidget(self.error_count_label)
        summary_row.addWidget(self.warning_count_label)
        summary_row.addWidget(self.info_count_label)
        summary_row.addStretch(1)
        layout.addLayout(summary_row)

        hint = QLabel(
            "Read-only validation. Double-click a row to jump to the related "
            "Song or mark when possible. No auto-fix."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8b949e;")
        layout.addWidget(hint)

        self.table = QTableWidget(0, 4)
        self.table.setObjectName("preflightIssueTable")
        self.table.setHorizontalHeaderLabels(
            ["Code", "Severity", "Song / Object", "Message"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnWidth(0, 72)
        self.table.setColumnWidth(1, 100)
        self.table.setColumnWidth(2, 200)
        layout.addWidget(self.table, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_btn is not None:
            close_btn.clicked.connect(self.accept)
        layout.addWidget(buttons)

        self.table.doubleClicked.connect(self._on_double_clicked)
        self._populate()

    @property
    def report(self) -> PreflightReport:
        return self._report

    def _populate(self) -> None:
        self.table.setRowCount(0)
        for row in self._rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            values = (
                row.code.value,
                row.severity.value,
                format_issue_target(row),
                row.message,
            )
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setData(_ROLE_ROW, row)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, col, item)

    def _row_at(self, table_row: int) -> PreflightIssueRow | None:
        if table_row < 0 or table_row >= self.table.rowCount():
            return None
        item = self.table.item(table_row, 0)
        if item is None:
            return None
        data = item.data(_ROLE_ROW)
        return data if isinstance(data, PreflightIssueRow) else None

    def _on_double_clicked(self, index) -> None:  # noqa: ANN001
        row = self._row_at(index.row())
        if row is None:
            return
        target = navigation_target(row)
        if target is None:
            return
        song_id, kind, oid = target
        self.navigate_requested.emit(song_id, kind, oid)
