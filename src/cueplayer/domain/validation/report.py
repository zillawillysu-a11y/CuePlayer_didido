"""Aggregated validation report (read-only collection of issues)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Iterator

from cueplayer.domain.validation.codes import ValidationCode, coerce_validation_code
from cueplayer.domain.validation.issue import ValidationIssue
from cueplayer.domain.validation.severity import ValidationSeverity


@dataclass
class ValidationReport:
    """Result of running a rule set against a context.

    The report is a pure data carrier. Building/appending issues does not
    mutate the validated project/export context.
    """

    issues: list[ValidationIssue] = field(default_factory=list)
    context_label: str = ""
    rule_set_id: str = ""

    def add(self, issue: ValidationIssue) -> None:
        """Append one issue (report mutation only — never project mutation)."""
        self.issues.append(issue)

    def extend(self, issues: Iterable[ValidationIssue]) -> None:
        for issue in issues:
            self.add(issue)

    def __iter__(self) -> Iterator[ValidationIssue]:
        return iter(self.issues)

    def __len__(self) -> int:
        return len(self.issues)

    def __bool__(self) -> bool:
        """True when the report contains any issues."""
        return bool(self.issues)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity is ValidationSeverity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity is ValidationSeverity.WARNING]

    @property
    def information(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity is ValidationSeverity.INFORMATION]

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

    def issues_for_code(self, code: object) -> list[ValidationIssue]:
        wanted = coerce_validation_code(code)
        return [i for i in self.issues if i.code == wanted]

    def sorted_issues(self) -> list[ValidationIssue]:
        """Severity rank, then code, then subject/path/message."""
        return sorted(
            self.issues,
            key=lambda i: (
                i.severity.rank,
                i.code.value,
                i.subject,
                i.path,
                i.message,
            ),
        )

    def summary(self) -> str:
        """One-line operator summary."""
        label = self.context_label or "validation"
        return (
            f"{label}: {self.error_count} error(s), "
            f"{self.warning_count} warning(s), "
            f"{self.information_count} info"
        )

    def codes(self) -> list[ValidationCode]:
        """Distinct codes in report order of first appearance."""
        seen: set[str] = set()
        out: list[ValidationCode] = []
        for issue in self.issues:
            if issue.code.value not in seen:
                seen.add(issue.code.value)
                out.append(issue.code)
        return out
