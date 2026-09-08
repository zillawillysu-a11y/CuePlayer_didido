"""Rule protocol, registry, and runner (extensible; read-only)."""

from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable

from cueplayer.domain.validation.codes import ValidationCode
from cueplayer.domain.validation.issue import ValidationIssue
from cueplayer.domain.validation.report import ValidationReport


@runtime_checkable
class ValidationRule(Protocol):
    """One reusable preflight check.

    Implementations must be **read-only** with respect to ``context``:
    they may inspect attributes but must not assign into project structures.
    """

    @property
    def code(self) -> ValidationCode:
        """Primary code this rule emits (may emit only this code)."""

    @property
    def title(self) -> str:
        """Short English title for docs / UI."""

    def evaluate(self, context: object) -> Sequence[ValidationIssue]:
        """Return zero or more issues for ``context`` (never mutate it)."""


class ValidationRuleSet:
    """Ordered registry of validation rules.

    Registration strategy
    ---------------------
    - Rules are registered explicitly (no import-time side effects required).
    - Duplicate primary codes raise ``ValueError`` (one rule owns one code).
    - ``run`` evaluates rules in registration order and aggregates issues.
    - Future Task 2 packs MA rules into a factory (e.g. ``ma_export_rules()``).
    """

    def __init__(self, *, rule_set_id: str = "") -> None:
        self._rule_set_id = str(rule_set_id or "")
        self._rules: list[ValidationRule] = []
        self._codes: set[str] = set()

    @property
    def rule_set_id(self) -> str:
        return self._rule_set_id

    @property
    def rules(self) -> tuple[ValidationRule, ...]:
        return tuple(self._rules)

    def __len__(self) -> int:
        return len(self._rules)

    def register(self, rule: ValidationRule) -> None:
        code = rule.code.value
        if code in self._codes:
            raise ValueError(f"rule code already registered: {code}")
        self._codes.add(code)
        self._rules.append(rule)

    def register_many(self, rules: Sequence[ValidationRule]) -> None:
        for rule in rules:
            self.register(rule)

    def run(self, context: object, *, context_label: str = "") -> ValidationReport:
        """Evaluate all rules; never mutates ``context``."""
        report = ValidationReport(
            context_label=str(context_label or ""),
            rule_set_id=self._rule_set_id,
        )
        for rule in self._rules:
            issues = rule.evaluate(context)
            if issues:
                report.extend(issues)
        return report


def run_validation(
    rules: Sequence[ValidationRule] | ValidationRuleSet,
    context: object,
    *,
    context_label: str = "",
    rule_set_id: str = "",
) -> ValidationReport:
    """Run a rule set or ad-hoc rule sequence against ``context``."""
    if isinstance(rules, ValidationRuleSet):
        return rules.run(context, context_label=context_label)
    pack = ValidationRuleSet(rule_set_id=rule_set_id)
    pack.register_many(rules)
    return pack.run(context, context_label=context_label)
