"""MA Preflight — validation domain framework (read-only).

This package defines reusable report / issue / severity / code types and a
rule-registration runner. It must stay free of Qt, persistence I/O,
AudioEngine, and ``cueplayer.exporters`` (validation is independent of XML
generation).

Task 2: MA rule pack (``ma_rules`` / ``ma_context``).
Task 3: Preflight report builder (``preflight_report``).
"""

from __future__ import annotations

from cueplayer.domain.validation.codes import (
    ValidationCode,
    coerce_validation_code,
    is_valid_code_format,
)
from cueplayer.domain.validation.issue import ValidationIssue, make_issue
from cueplayer.domain.validation.ma_context import (
    MaPreflightContext,
    build_ma_preflight_context,
)
from cueplayer.domain.validation.ma_rules import ma_preflight_rules, run_ma_preflight
from cueplayer.domain.validation.preflight_report import (
    PreflightCategory,
    PreflightIssueRow,
    PreflightReport,
    build_preflight_report,
    build_preflight_report_for_project,
    category_for_code,
)
from cueplayer.domain.validation.report import ValidationReport
from cueplayer.domain.validation.rules import (
    ValidationRule,
    ValidationRuleSet,
    run_validation,
)
from cueplayer.domain.validation.severity import ValidationSeverity, coerce_severity

__all__ = [
    "MaPreflightContext",
    "PreflightCategory",
    "PreflightIssueRow",
    "PreflightReport",
    "ValidationCode",
    "ValidationIssue",
    "ValidationReport",
    "ValidationRule",
    "ValidationRuleSet",
    "ValidationSeverity",
    "build_ma_preflight_context",
    "build_preflight_report",
    "build_preflight_report_for_project",
    "category_for_code",
    "coerce_severity",
    "coerce_validation_code",
    "is_valid_code_format",
    "ma_preflight_rules",
    "make_issue",
    "run_ma_preflight",
    "run_validation",
]
