"""Unit tests for MA Export Preflight validation domain (Task 1)."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from cueplayer.domain.validation import (
    ValidationCode,
    ValidationIssue,
    ValidationReport,
    ValidationRuleSet,
    ValidationSeverity,
    coerce_severity,
    coerce_validation_code,
    is_valid_code_format,
    make_issue,
    run_validation,
)


def test_validation_code_format_and_properties() -> None:
    code = ValidationCode("ma001")
    assert code.value == "MA001"
    assert code.prefix == "MA"
    assert code.number == 1
    assert is_valid_code_format("MA999")
    assert not is_valid_code_format("M1")
    assert not is_valid_code_format("ma-001")
    with pytest.raises(ValueError):
        ValidationCode("bad")
    assert coerce_validation_code("TC042").value == "TC042"


def test_severity_coercion_and_rank() -> None:
    assert coerce_severity("ERROR") is ValidationSeverity.ERROR
    assert coerce_severity("warning") is ValidationSeverity.WARNING
    assert coerce_severity("information") is ValidationSeverity.INFORMATION
    assert coerce_severity("nope") is ValidationSeverity.WARNING
    assert ValidationSeverity.ERROR.rank < ValidationSeverity.WARNING.rank
    assert ValidationSeverity.WARNING.rank < ValidationSeverity.INFORMATION.rank


def test_make_issue_and_report_aggregation() -> None:
    report = ValidationReport(context_label="Song A", rule_set_id="ma-preflight")
    report.add(
        make_issue(
            "MA001",
            "error",
            "MA Export Name contains illegal characters",
            subject="mark:kick",
            path="marks[0].ma_export_name",
            details={"value": "主歌"},
        )
    )
    report.add(
        make_issue(
            "MA010",
            ValidationSeverity.WARNING,
            "Duplicate executor assignment",
            subject="executor:1.1",
        )
    )
    report.add(
        make_issue(
            "MA100",
            "information",
            "Export mode is timecode_only",
        )
    )

    assert report.has_errors is True
    assert report.has_warnings is True
    assert report.error_count == 1
    assert report.warning_count == 1
    assert report.information_count == 1
    assert report.summary() == "Song A: 1 error(s), 1 warning(s), 1 info"
    assert [c.value for c in report.codes()] == ["MA001", "MA010", "MA100"]
    ordered = report.sorted_issues()
    assert ordered[0].severity is ValidationSeverity.ERROR
    assert ordered[-1].severity is ValidationSeverity.INFORMATION
    assert report.issues_for_code("MA001")[0].details["value"] == "主歌"


@dataclass
class _FakeContext:
    """Mutable stand-in; rules must not write to it."""

    labels: list[str] = field(default_factory=list)
    mutated: bool = False


class _EmptyLabelRule:
    code = ValidationCode("MA001")
    title = "Empty MA label"

    def evaluate(self, context: object) -> list[ValidationIssue]:
        assert isinstance(context, _FakeContext)
        issues: list[ValidationIssue] = []
        for index, label in enumerate(context.labels):
            if not str(label).strip():
                issues.append(
                    make_issue(
                        self.code,
                        ValidationSeverity.ERROR,
                        "MA Export Name is empty",
                        subject=f"label:{index}",
                        path=f"labels[{index}]",
                    )
                )
        return issues


class _InfoCountRule:
    code = ValidationCode("MA100")
    title = "Label count"

    def evaluate(self, context: object) -> list[ValidationIssue]:
        assert isinstance(context, _FakeContext)
        return [
            make_issue(
                self.code,
                ValidationSeverity.INFORMATION,
                f"{len(context.labels)} label(s) in context",
                details={"count": len(context.labels)},
            )
        ]


class _MutatingRule:
    """Illegal rule used only to document the contract in tests — not registered."""

    code = ValidationCode("MA999")
    title = "Bad"

    def evaluate(self, context: object) -> list[ValidationIssue]:
        assert isinstance(context, _FakeContext)
        context.mutated = True
        return []


def test_rule_set_registration_and_run_read_only() -> None:
    ctx = _FakeContext(labels=["Cue1", "", "Cue3"])
    rules = ValidationRuleSet(rule_set_id="ma-preflight-example")
    rules.register(_EmptyLabelRule())
    rules.register(_InfoCountRule())

    with pytest.raises(ValueError, match="already registered"):
        rules.register(_EmptyLabelRule())

    report = rules.run(ctx, context_label="Demo Song")
    assert ctx.mutated is False
    assert report.rule_set_id == "ma-preflight-example"
    assert report.error_count == 1
    assert report.information_count == 1
    assert report.errors[0].subject == "label:1"

    # Ad-hoc runner
    again = run_validation(
        [_EmptyLabelRule(), _InfoCountRule()],
        ctx,
        context_label="Demo Song",
        rule_set_id="adhoc",
    )
    assert again.error_count == 1
    assert ctx.mutated is False


def test_example_validation_report_shape() -> None:
    """Canonical example report shape for docs / Task 2 consumers."""
    report = ValidationReport(context_label="開場", rule_set_id="ma-preflight")
    report.extend(
        [
            make_issue(
                "MA001",
                "error",
                "MA Export Name contains non-ASCII characters",
                subject="mark:m1",
                path="marks[0].ma_export_name",
                details={"value": "主歌A", "display_name": "主歌"},
            ),
            make_issue(
                "MA010",
                "warning",
                "Executor 1.201 already used by another sequence",
                subject="executor:1.201",
                details={"sequence": "TopBtn_2"},
            ),
            make_issue(
                "MA100",
                "information",
                "Export mode: full (sequences + timecode)",
                details={"mode": "full"},
            ),
        ]
    )
    assert report.has_errors
    assert len(report.sorted_issues()) == 3
    assert "1 error(s)" in report.summary()
