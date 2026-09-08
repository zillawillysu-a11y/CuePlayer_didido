"""Single validation finding (read-only)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from cueplayer.domain.validation.codes import ValidationCode, coerce_validation_code
from cueplayer.domain.validation.severity import ValidationSeverity, coerce_severity


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One preflight finding. Never mutates project data.

    Fields
    ------
    code
        Stable ``ValidationCode`` (e.g. MA001).
    severity
        Error / Warning / Information.
    message
        Operator-facing English summary (no Chinese required in MA labels context).
    subject
        Optional stable subject id (mark id, sequence key, song id).
    path
        Optional dotted path for UI focus (``marks[0].ma_export_name``).
    details
        Optional structured extras for tests / UI (counts, offending values).
    """

    code: ValidationCode
    severity: ValidationSeverity
    message: str
    subject: str = ""
    path: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)

    def with_details(self, **extra: Any) -> ValidationIssue:
        """Return a copy with merged details (immutable helper)."""
        merged = dict(self.details)
        merged.update(extra)
        return ValidationIssue(
            code=self.code,
            severity=self.severity,
            message=self.message,
            subject=self.subject,
            path=self.path,
            details=merged,
        )


def make_issue(
    code: object,
    severity: object,
    message: str,
    *,
    subject: str = "",
    path: str = "",
    details: Mapping[str, Any] | None = None,
) -> ValidationIssue:
    """Convenience factory with coercion for code/severity."""
    return ValidationIssue(
        code=coerce_validation_code(code),
        severity=coerce_severity(severity),
        message=str(message),
        subject=str(subject or ""),
        path=str(path or ""),
        details=dict(details or {}),
    )
