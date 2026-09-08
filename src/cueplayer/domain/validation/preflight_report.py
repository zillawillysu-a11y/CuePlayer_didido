"""Preflight report presentation layer (read-only; no exporters / UI).

Builds a stable, renderable report from a ``ValidationReport`` produced by
``ma_preflight_rules``. Suitable for future UI tables, CLI text, and JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from cueplayer.domain.models import Project
from cueplayer.domain.validation.codes import ValidationCode
from cueplayer.domain.validation.issue import ValidationIssue
from cueplayer.domain.validation.ma_context import (
    MaPreflightContext,
    build_ma_preflight_context,
)
from cueplayer.domain.validation.ma_rules import run_ma_preflight
from cueplayer.domain.validation.report import ValidationReport
from cueplayer.domain.validation.severity import ValidationSeverity


class PreflightCategory(str, Enum):
    """Presentation category for grouped UI / CLI sections."""

    LABELS = "labels"
    SEQUENCES = "sequences"
    EXECUTORS = "executors"
    CUES = "cues"
    SONGS = "songs"
    METADATA = "metadata"
    SUMMARY = "summary"
    OTHER = "other"

    @property
    def rank(self) -> int:
        order = (
            PreflightCategory.LABELS,
            PreflightCategory.SEQUENCES,
            PreflightCategory.EXECUTORS,
            PreflightCategory.CUES,
            PreflightCategory.SONGS,
            PreflightCategory.METADATA,
            PreflightCategory.SUMMARY,
            PreflightCategory.OTHER,
        )
        return order.index(self)


_CODE_CATEGORY: dict[str, PreflightCategory] = {
    "MA001": PreflightCategory.LABELS,
    "MA002": PreflightCategory.LABELS,
    "MA003": PreflightCategory.SEQUENCES,
    "MA004": PreflightCategory.EXECUTORS,
    "MA050": PreflightCategory.SEQUENCES,
    "MA051": PreflightCategory.SONGS,
    "MA052": PreflightCategory.CUES,
    "MA053": PreflightCategory.METADATA,
    "MA150": PreflightCategory.SUMMARY,
    "MA151": PreflightCategory.SUMMARY,
    "MA152": PreflightCategory.SUMMARY,
    "MA153": PreflightCategory.SUMMARY,
}


def category_for_code(code: object) -> PreflightCategory:
    """Map a ValidationCode to a presentation category."""
    raw = str(getattr(code, "value", code) or "").strip().upper()
    return _CODE_CATEGORY.get(raw, PreflightCategory.OTHER)


def _parse_subject(subject: str) -> tuple[str, str]:
    """Split ``kind:id`` subject into (kind, id)."""
    text = str(subject or "").strip()
    if ":" in text:
        kind, _, rest = text.partition(":")
        return kind.strip(), rest.strip()
    return "", text


@dataclass(frozen=True, slots=True)
class PreflightIssueRow:
    """One stable presentation row for UI / CLI / JSON."""

    code: ValidationCode
    severity: ValidationSeverity
    category: PreflightCategory
    message: str
    song_id: str = ""
    song_name: str = ""
    object_kind: str = ""
    object_id: str = ""
    path: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)

    @property
    def object_ref(self) -> str:
        """Human/object reference: ``song:…``, ``mark:…``, or subject remnant."""
        if self.object_kind and self.object_id:
            return f"{self.object_kind}:{self.object_id}"
        if self.object_id:
            return self.object_id
        return ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "severity": self.severity.value,
            "category": self.category.value,
            "message": self.message,
            "song_id": self.song_id,
            "song_name": self.song_name,
            "object_kind": self.object_kind,
            "object_id": self.object_id,
            "object_ref": self.object_ref,
            "path": self.path,
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class PreflightReport:
    """Stable preflight presentation report (never mutates project data)."""

    title: str
    rule_set_id: str
    issues: tuple[PreflightIssueRow, ...]
    source_issue_count: int = 0

    @property
    def errors(self) -> tuple[PreflightIssueRow, ...]:
        return tuple(i for i in self.issues if i.severity is ValidationSeverity.ERROR)

    @property
    def warnings(self) -> tuple[PreflightIssueRow, ...]:
        return tuple(i for i in self.issues if i.severity is ValidationSeverity.WARNING)

    @property
    def information(self) -> tuple[PreflightIssueRow, ...]:
        return tuple(
            i for i in self.issues if i.severity is ValidationSeverity.INFORMATION
        )

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    @property
    def information_count(self) -> int:
        return len(self.information)

    @property
    def has_errors(self) -> bool:
        return self.error_count > 0

    @property
    def has_warnings(self) -> bool:
        return self.warning_count > 0

    def summary(self) -> str:
        label = self.title or "MA Preflight"
        return (
            f"{label}: {self.error_count} error(s), "
            f"{self.warning_count} warning(s), "
            f"{self.information_count} info"
        )

    def grouped_by_severity(self) -> dict[str, tuple[PreflightIssueRow, ...]]:
        """Severity → sorted rows (keys: error / warning / information)."""
        return {
            ValidationSeverity.ERROR.value: self.errors,
            ValidationSeverity.WARNING.value: self.warnings,
            ValidationSeverity.INFORMATION.value: self.information,
        }

    def grouped_by_category(self) -> dict[str, tuple[PreflightIssueRow, ...]]:
        """Category → rows (deterministic category order, rows already sorted)."""
        buckets: dict[str, list[PreflightIssueRow]] = {}
        for row in self.issues:
            buckets.setdefault(row.category.value, []).append(row)
        ordered: dict[str, tuple[PreflightIssueRow, ...]] = {}
        for cat in sorted(PreflightCategory, key=lambda c: c.rank):
            if cat.value in buckets:
                ordered[cat.value] = tuple(buckets[cat.value])
        for key, rows in buckets.items():
            if key not in ordered:
                ordered[key] = tuple(rows)
        return ordered

    def format_text(self) -> str:
        """CLI-oriented plain text (stable ordering)."""
        lines = [self.summary(), ""]
        for severity_key, rows in self.grouped_by_severity().items():
            if not rows:
                continue
            lines.append(f"## {severity_key.upper()}")
            for row in rows:
                ref = row.object_ref or row.song_name or "-"
                lines.append(
                    f"[{severity_key.upper()}] {row.code.value}  "
                    f"({row.category.value})  {row.message}  [{ref}]"
                )
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable dict for future UI / file export."""
        return {
            "title": self.title,
            "rule_set_id": self.rule_set_id,
            "summary": self.summary(),
            "has_errors": self.has_errors,
            "has_warnings": self.has_warnings,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "information_count": self.information_count,
            "issues": [row.to_dict() for row in self.issues],
            "by_severity": {
                key: [r.to_dict() for r in rows]
                for key, rows in self.grouped_by_severity().items()
            },
            "by_category": {
                key: [r.to_dict() for r in rows]
                for key, rows in self.grouped_by_category().items()
            },
        }


def _song_lookup(context: MaPreflightContext | None) -> dict[str, str]:
    if context is None:
        return {}
    return {song.id: song.name for song in context.songs}


def _row_from_issue(
    issue: ValidationIssue,
    *,
    song_names: Mapping[str, str],
) -> PreflightIssueRow:
    kind, oid = _parse_subject(issue.subject)
    details = dict(issue.details or {})
    song_id = str(details.get("song_id") or "")
    song_name = str(details.get("song_name") or "")
    if kind == "song" and oid:
        song_id = song_id or oid
    if not song_name and song_id:
        song_name = str(song_names.get(song_id, ""))
    return PreflightIssueRow(
        code=issue.code,
        severity=issue.severity,
        category=category_for_code(issue.code),
        message=str(issue.message),
        song_id=song_id,
        song_name=song_name,
        object_kind=kind,
        object_id=oid,
        path=str(issue.path or ""),
        details=details,
    )


def _sort_key(row: PreflightIssueRow) -> tuple:
    return (
        row.severity.rank,
        row.category.rank,
        row.code.value,
        row.song_name.casefold(),
        row.song_id,
        row.object_ref,
        row.path,
        row.message,
    )


def build_preflight_report(
    validation_report: ValidationReport,
    *,
    context: MaPreflightContext | None = None,
    title: str | None = None,
) -> PreflightReport:
    """Build a stable presentation report from a raw ``ValidationReport``.

    Does not mutate ``validation_report`` contents beyond reading; never touches
    Project / Song structures.
    """
    song_names = _song_lookup(context)
    rows = [
        _row_from_issue(issue, song_names=song_names)
        for issue in validation_report.sorted_issues()
    ]
    rows_sorted = tuple(sorted(rows, key=_sort_key))
    resolved_title = (
        title
        if title is not None
        else (validation_report.context_label or "MA Preflight")
    )
    return PreflightReport(
        title=str(resolved_title),
        rule_set_id=str(validation_report.rule_set_id or ""),
        issues=rows_sorted,
        source_issue_count=len(validation_report.issues),
    )


def build_preflight_report_for_project(project: Project) -> PreflightReport:
    """Snapshot project → run MA rules → presentation report (read-only)."""
    context = build_ma_preflight_context(project)
    raw = run_ma_preflight(context)
    return build_preflight_report(
        raw,
        context=context,
        title=context.project_name or project.name or "MA Preflight",
    )
