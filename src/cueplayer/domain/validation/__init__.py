"""MA Export Preflight — validation domain framework (read-only).

This package defines reusable report / issue / severity / code types and a
rule-registration runner. It must stay free of Qt, persistence I/O,
AudioEngine, and ``cueplayer.exporters`` (validation is independent of XML
generation).

Concrete MA rules land in Task 2; this Task 1 ships the framework only.
"""

from __future__ import annotations

from cueplayer.domain.validation.codes import (
    ValidationCode,
    coerce_validation_code,
    is_valid_code_format,
)
from cueplayer.domain.validation.issue import ValidationIssue, make_issue
from cueplayer.domain.validation.report import ValidationReport
from cueplayer.domain.validation.rules import (
    ValidationRule,
    ValidationRuleSet,
    run_validation,
)
from cueplayer.domain.validation.severity import ValidationSeverity, coerce_severity

__all__ = [
    "ValidationCode",
    "ValidationIssue",
    "ValidationReport",
    "ValidationRule",
    "ValidationRuleSet",
    "ValidationSeverity",
    "coerce_severity",
    "coerce_validation_code",
    "is_valid_code_format",
    "make_issue",
    "run_validation",
]
