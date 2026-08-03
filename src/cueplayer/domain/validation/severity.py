"""Validation severity levels for preflight reports."""

from __future__ import annotations

from enum import Enum


class ValidationSeverity(str, Enum):
    """Three-tier severity for preflight issues.

    ERROR
        Blocks a safe export recommendation (UI may still allow force-export later).
    WARNING
        Export may succeed but operator should review.
    INFORMATION
        Informational only (counts, mode notes, hints).
    """

    ERROR = "error"
    WARNING = "warning"
    INFORMATION = "information"

    @property
    def rank(self) -> int:
        """Sort key: Error (0) < Warning (1) < Information (2)."""
        return {
            ValidationSeverity.ERROR: 0,
            ValidationSeverity.WARNING: 1,
            ValidationSeverity.INFORMATION: 2,
        }[self]


def coerce_severity(value: object) -> ValidationSeverity:
    """Normalize a severity string/enum; unknown values become WARNING."""
    if isinstance(value, ValidationSeverity):
        return value
    raw = str(value or "").strip().lower()
    for item in ValidationSeverity:
        if item.value == raw or item.name.lower() == raw:
            return item
    return ValidationSeverity.WARNING
