"""MA Preflight export gate — application orchestration (no Qt, no exporters).

Fresh ValidationReport every call. Export allow/deny uses ValidationReport only;
PreflightReport is built for UI presentation and is never required by exporters.
"""

from __future__ import annotations

from dataclasses import dataclass

from cueplayer.domain.models import Project
from cueplayer.domain.validation.ma_context import build_ma_preflight_context
from cueplayer.domain.validation.ma_rules import run_ma_preflight
from cueplayer.domain.validation.preflight_report import (
    PreflightReport,
    build_preflight_report,
)
from cueplayer.domain.validation.report import ValidationReport


@dataclass(frozen=True, slots=True)
class MaPreflightExportGateResult:
    """One fresh preflight evaluation for an export attempt.

    ``validation`` is the sole source of allow/deny policy.
    ``presentation`` is for UI only.
    """

    validation: ValidationReport
    presentation: PreflightReport

    @property
    def has_issues(self) -> bool:
        return bool(self.validation.issues)

    @property
    def has_errors(self) -> bool:
        return bool(self.validation.has_errors)

    @property
    def has_warnings(self) -> bool:
        return bool(self.validation.has_warnings)

    @property
    def allow_export(self) -> bool:
        """Errors block export by default; warnings/info do not."""
        return export_allowed_from_validation(self.validation)

    @property
    def show_dialog(self) -> bool:
        """Show Preflight UI when any issue exists (info included)."""
        return should_show_preflight_dialog(self.validation)


def export_allowed_from_validation(validation: ValidationReport) -> bool:
    """Export policy from ``ValidationReport`` only (no presentation layer)."""
    if not isinstance(validation, ValidationReport):
        raise TypeError(
            "export_allowed_from_validation requires ValidationReport, "
            f"got {type(validation).__name__}"
        )
    return not validation.has_errors


def should_show_preflight_dialog(validation: ValidationReport) -> bool:
    """True when the Preflight dialog should appear before export."""
    if not isinstance(validation, ValidationReport):
        raise TypeError(
            "should_show_preflight_dialog requires ValidationReport, "
            f"got {type(validation).__name__}"
        )
    return len(validation.issues) > 0


def evaluate_ma_preflight_for_export(project: Project) -> MaPreflightExportGateResult:
    """Run a fresh MA Preflight for export — never caches prior results."""
    context = build_ma_preflight_context(project)
    validation = run_ma_preflight(context)
    presentation = build_preflight_report(
        validation,
        context=context,
        title=context.project_name or project.name or "MA Preflight",
    )
    return MaPreflightExportGateResult(
        validation=validation,
        presentation=presentation,
    )
