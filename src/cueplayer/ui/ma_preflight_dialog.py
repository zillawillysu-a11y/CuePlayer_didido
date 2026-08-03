"""MA Preflight dialog — read-only presentation of ``PreflightReport`` (MVP).

Consumes a pre-built ``PreflightReport`` only. Does not run validation rules,
import exporters, or mutate project data. Navigation is signaled to the host.

Export gate presentation lives in ``present_export_preflight_gate`` — allow/deny
is decided from ``ValidationReport`` (application gate), not inside exporters.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cueplayer.application.ma_preflight_export_gate import (
    MaPreflightExportGateResult,
    export_allowed_from_validation,
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

    Modes
    -----
    ``review``
        Tools menu — Close only.
    ``export_gate``
        Before export — Cancel; Continue Export when ``can_continue`` is True
        (no errors). Errors never offer Continue.

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
        *,
        mode: str = "review",
        can_continue: bool = False,
    ) -> None:
        super().__init__(parent)
        if not isinstance(report, PreflightReport):
            raise TypeError(
                f"MaPreflightDialog requires PreflightReport, got {type(report).__name__}"
            )
        self._report = report
        self._rows: tuple[PreflightIssueRow, ...] = report.issues
        self._mode = str(mode or "review").strip().lower() or "review"
        self._can_continue = bool(can_continue) and self._mode == "export_gate"

        title = "MA Preflight — Export" if self._mode == "export_gate" else "MA Preflight"
        self.setWindowTitle(title)
        self.resize(820, 480)

        layout = QVBoxLayout(self)

        summary_title = QLabel(report.summary())
        summary_title.setObjectName("preflightSummaryTitle")
        summary_title.setWordWrap(True)
        summary_title.setStyleSheet("font-weight: 600; font-size: 13px;")
        layout.addWidget(summary_title)

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

        if self._mode == "export_gate" and not self._can_continue:
            hint_text = (
                "Export blocked: fix errors before exporting. "
                "Double-click a row to jump to the related Song or mark when possible. "
                "No auto-fix."
            )
        elif self._mode == "export_gate":
            hint_text = (
                "Review warnings and information, then Continue Export or Cancel. "
                "Double-click a row to jump to the related Song or mark when possible. "
                "No auto-fix."
            )
        else:
            hint_text = (
                "Read-only validation. Double-click a row to jump to the related "
                "Song or mark when possible. No auto-fix."
            )
        hint = QLabel(hint_text)
        hint.setObjectName("preflightHint")
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

        self.continue_btn: QPushButton | None = None
        if self._mode == "export_gate":
            buttons = QDialogButtonBox()
            cancel_btn = buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
            cancel_btn.clicked.connect(self.reject)
            if self._can_continue:
                self.continue_btn = buttons.addButton(
                    "Continue Export", QDialogButtonBox.ButtonRole.AcceptRole
                )
                self.continue_btn.setObjectName("preflightContinueExport")
                self.continue_btn.clicked.connect(self.accept)
            else:
                close_btn = buttons.addButton(QDialogButtonBox.StandardButton.Close)
                close_btn.clicked.connect(self.reject)
        else:
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

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def can_continue(self) -> bool:
        return self._can_continue

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


def present_export_preflight_gate(
    gate: MaPreflightExportGateResult,
    parent: QWidget | None = None,
    *,
    on_navigate: Callable[[str, str, str], None] | None = None,
) -> bool:
    """Present Preflight UI for export; return True if export may proceed.

    Allow/deny is computed from ``gate.validation`` (``ValidationReport``).
    The dialog only presents ``gate.presentation``.
    """
    if not isinstance(gate, MaPreflightExportGateResult):
        raise TypeError(
            "present_export_preflight_gate requires MaPreflightExportGateResult, "
            f"got {type(gate).__name__}"
        )
    # Policy from ValidationReport only.
    allowed = export_allowed_from_validation(gate.validation)
    if not gate.show_dialog:
        return allowed

    dialog = MaPreflightDialog(
        gate.presentation,
        parent,
        mode="export_gate",
        can_continue=allowed,
    )
    if on_navigate is not None:
        dialog.navigate_requested.connect(on_navigate)
    result = dialog.exec()
    if not allowed:
        return False
    return result == QDialog.DialogCode.Accepted
