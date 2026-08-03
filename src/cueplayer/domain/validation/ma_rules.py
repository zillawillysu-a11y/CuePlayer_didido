"""MA Preflight validation rule pack (MVP) — read-only, deterministic.

Does not import exporters, parse XML, or mutate Project / Song data.
"""

from __future__ import annotations

from collections import defaultdict

from cueplayer.domain.validation.codes import ValidationCode
from cueplayer.domain.validation.issue import ValidationIssue, make_issue
from cueplayer.domain.validation.ma_context import MaPreflightContext
from cueplayer.domain.validation.ma_names import (
    has_non_ascii,
    is_blank,
    is_valid_ma_export_name,
    normalize_sequence_key,
    parse_executor_ref,
)
from cueplayer.domain.validation.report import ValidationReport
from cueplayer.domain.validation.rules import ValidationRuleSet
from cueplayer.domain.validation.severity import ValidationSeverity


def _ctx(context: object) -> MaPreflightContext:
    if not isinstance(context, MaPreflightContext):
        raise TypeError(
            f"MA rules expect MaPreflightContext, got {type(context).__name__}"
        )
    return context


# --- Errors ------------------------------------------------------------------


class DuplicateSequenceRule:
    code = ValidationCode("MA003")
    title = "Duplicate Sequence identifiers"

    def evaluate(self, context: object) -> list[ValidationIssue]:
        ctx = _ctx(context)
        groups: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for song in ctx.included_songs:
            for seq in song.sequences:
                key = normalize_sequence_key(seq.label)
                if not key:
                    continue
                groups[key].append((seq.key, seq.label))
        issues: list[ValidationIssue] = []
        for key, items in sorted(groups.items()):
            if len(items) < 2:
                continue
            keys = [k for k, _ in items]
            issues.append(
                make_issue(
                    self.code,
                    ValidationSeverity.ERROR,
                    f"Duplicate Sequence identifier {items[0][1]!r}",
                    subject=f"sequence:{key}",
                    path="sequences",
                    details={"keys": keys, "label": items[0][1], "count": len(items)},
                )
            )
        return issues


class InvalidMaExportNameRule:
    code = ValidationCode("MA001")
    title = "Invalid MA Export Name"

    def evaluate(self, context: object) -> list[ValidationIssue]:
        ctx = _ctx(context)
        issues: list[ValidationIssue] = []
        for song in ctx.included_songs:
            raw = song.ma_export_name
            if is_blank(raw):
                continue  # covered by MissingRequiredExportLabelRule
            if not is_valid_ma_export_name(raw):
                reason = "non-ASCII" if has_non_ascii(raw) else "illegal characters"
                issues.append(
                    make_issue(
                        self.code,
                        ValidationSeverity.ERROR,
                        f"Song MA Export Name has {reason}",
                        subject=f"song:{song.id}",
                        path="song.ma_export_name",
                        details={"value": raw, "song_name": song.name},
                    )
                )
            for cue in song.cues:
                if not cue.export_enabled or is_blank(cue.ma_export_name):
                    continue
                if not is_valid_ma_export_name(cue.ma_export_name):
                    reason = (
                        "non-ASCII"
                        if has_non_ascii(cue.ma_export_name)
                        else "illegal characters"
                    )
                    issues.append(
                        make_issue(
                            self.code,
                            ValidationSeverity.ERROR,
                            f"Cue MA Export Name has {reason}",
                            subject=f"mark:{cue.mark_id}",
                            path="marks.ma_export_name",
                            details={
                                "value": cue.ma_export_name,
                                "display_name": cue.display_name,
                                "song_id": song.id,
                            },
                        )
                    )
        return issues


class MissingRequiredExportLabelRule:
    code = ValidationCode("MA002")
    title = "Missing required export labels"

    def evaluate(self, context: object) -> list[ValidationIssue]:
        ctx = _ctx(context)
        issues: list[ValidationIssue] = []
        for song in ctx.included_songs:
            if is_blank(song.ma_export_name):
                issues.append(
                    make_issue(
                        self.code,
                        ValidationSeverity.ERROR,
                        "Song is missing MA Export Name",
                        subject=f"song:{song.id}",
                        path="song.ma_export_name",
                        details={"song_name": song.name},
                    )
                )
        return issues


class InvalidExecutorAssignmentRule:
    code = ValidationCode("MA004")
    title = "Invalid Executor assignments"

    def evaluate(self, context: object) -> list[ValidationIssue]:
        ctx = _ctx(context)
        issues: list[ValidationIssue] = []
        for field_name, raw in (
            ("main_executor", ctx.main_executor),
            ("button_executor_start", ctx.button_executor_start),
        ):
            if parse_executor_ref(raw) is None:
                issues.append(
                    make_issue(
                        self.code,
                        ValidationSeverity.ERROR,
                        f"Invalid executor reference for {field_name}",
                        subject=f"settings:{field_name}",
                        path=f"ma_export.{field_name}",
                        details={"value": raw},
                    )
                )

        seen: dict[str, list[str]] = defaultdict(list)
        for song in ctx.included_songs:
            for seq in song.sequences:
                parsed = parse_executor_ref(seq.executor)
                if parsed is None:
                    issues.append(
                        make_issue(
                            self.code,
                            ValidationSeverity.ERROR,
                            f"Sequence {seq.label!r} has invalid executor {seq.executor!r}",
                            subject=f"sequence:{seq.key}",
                            path="sequence.executor",
                            details={"executor": seq.executor, "label": seq.label},
                        )
                    )
                    continue
                seen[seq.executor].append(seq.key)

        for executor, keys in sorted(seen.items()):
            if len(keys) < 2:
                continue
            issues.append(
                make_issue(
                    self.code,
                    ValidationSeverity.ERROR,
                    f"Executor {executor} assigned to multiple sequences",
                    subject=f"executor:{executor}",
                    path="executors",
                    details={"executor": executor, "sequences": keys},
                )
            )
        return issues


# --- Warnings ----------------------------------------------------------------


class EmptySequenceRule:
    code = ValidationCode("MA050")
    title = "Empty Sequence"

    def evaluate(self, context: object) -> list[ValidationIssue]:
        ctx = _ctx(context)
        issues: list[ValidationIssue] = []
        for song in ctx.included_songs:
            for seq in song.sequences:
                if seq.cue_count > 0:
                    continue
                issues.append(
                    make_issue(
                        self.code,
                        ValidationSeverity.WARNING,
                        f"Sequence {seq.label!r} has no cues",
                        subject=f"sequence:{seq.key}",
                        path="sequence.cues",
                        details={
                            "label": seq.label,
                            "kind": seq.kind,
                            "song_id": song.id,
                        },
                    )
                )
        return issues


class DisabledSongRule:
    code = ValidationCode("MA051")
    title = "Disabled Song"

    def evaluate(self, context: object) -> list[ValidationIssue]:
        ctx = _ctx(context)
        issues: list[ValidationIssue] = []
        for song in ctx.songs:
            if song.export_included:
                continue
            issues.append(
                make_issue(
                    self.code,
                    ValidationSeverity.WARNING,
                    f"Song {song.name!r} is excluded from export",
                    subject=f"song:{song.id}",
                    path="ma_export.export_song_ids",
                    details={"song_name": song.name},
                )
            )
        return issues


class UnusedCueRule:
    code = ValidationCode("MA052")
    title = "Unused Cue"

    def evaluate(self, context: object) -> list[ValidationIssue]:
        ctx = _ctx(context)
        issues: list[ValidationIssue] = []
        for song in ctx.included_songs:
            for cue in song.cues:
                if cue.export_enabled:
                    continue
                issues.append(
                    make_issue(
                        self.code,
                        ValidationSeverity.WARNING,
                        "Cue is on a non-export lane (unused for MA export)",
                        subject=f"mark:{cue.mark_id}",
                        path="marks",
                        details={
                            "lane_index": cue.lane_index,
                            "display_name": cue.display_name,
                            "song_id": song.id,
                        },
                    )
                )
        return issues


class MissingOptionalMetadataRule:
    code = ValidationCode("MA053")
    title = "Missing optional metadata"

    def evaluate(self, context: object) -> list[ValidationIssue]:
        ctx = _ctx(context)
        issues: list[ValidationIssue] = []
        for song in ctx.included_songs:
            missing: list[str] = []
            if is_blank(song.note):
                missing.append("note")
            if song.bpm is None:
                missing.append("bpm")
            if not missing:
                continue
            issues.append(
                make_issue(
                    self.code,
                    ValidationSeverity.WARNING,
                    f"Song {song.name!r} missing optional metadata: {', '.join(missing)}",
                    subject=f"song:{song.id}",
                    path="song",
                    details={"missing": missing, "song_name": song.name},
                )
            )
        return issues


# --- Information -------------------------------------------------------------


class TotalSongsInfoRule:
    code = ValidationCode("MA150")
    title = "Total Songs"

    def evaluate(self, context: object) -> list[ValidationIssue]:
        ctx = _ctx(context)
        return [
            make_issue(
                self.code,
                ValidationSeverity.INFORMATION,
                f"Total songs: {ctx.total_songs} ({ctx.total_included_songs} included)",
                subject="project:songs",
                details={
                    "total": ctx.total_songs,
                    "included": ctx.total_included_songs,
                },
            )
        ]


class TotalSequencesInfoRule:
    code = ValidationCode("MA151")
    title = "Total Sequences"

    def evaluate(self, context: object) -> list[ValidationIssue]:
        ctx = _ctx(context)
        return [
            make_issue(
                self.code,
                ValidationSeverity.INFORMATION,
                f"Total sequences (included songs): {ctx.total_sequences}",
                subject="project:sequences",
                details={"total": ctx.total_sequences},
            )
        ]


class TotalExecutorsInfoRule:
    code = ValidationCode("MA152")
    title = "Total Executors"

    def evaluate(self, context: object) -> list[ValidationIssue]:
        ctx = _ctx(context)
        return [
            make_issue(
                self.code,
                ValidationSeverity.INFORMATION,
                f"Total distinct executors (included): {ctx.total_executors}",
                subject="project:executors",
                details={"total": ctx.total_executors},
            )
        ]


class TotalVariantsInfoRule:
    code = ValidationCode("MA153")
    title = "Total Variants"

    def evaluate(self, context: object) -> list[ValidationIssue]:
        ctx = _ctx(context)
        return [
            make_issue(
                self.code,
                ValidationSeverity.INFORMATION,
                f"Total variants: {ctx.total_variants}",
                subject="project:variants",
                details={"total": ctx.total_variants},
            )
        ]


def ma_preflight_rules() -> ValidationRuleSet:
    """Register the MVP MA Preflight rule pack (deterministic order)."""
    pack = ValidationRuleSet(rule_set_id="ma-preflight")
    pack.register_many(
        [
            InvalidMaExportNameRule(),
            MissingRequiredExportLabelRule(),
            DuplicateSequenceRule(),
            InvalidExecutorAssignmentRule(),
            EmptySequenceRule(),
            DisabledSongRule(),
            UnusedCueRule(),
            MissingOptionalMetadataRule(),
            TotalSongsInfoRule(),
            TotalSequencesInfoRule(),
            TotalExecutorsInfoRule(),
            TotalVariantsInfoRule(),
        ]
    )
    return pack


def run_ma_preflight(context: MaPreflightContext) -> ValidationReport:
    """Convenience: run the MVP pack against a preflight context."""
    return ma_preflight_rules().run(
        context, context_label=context.project_name or "MA Preflight"
    )