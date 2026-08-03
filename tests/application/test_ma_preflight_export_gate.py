"""Application tests for MA Preflight export gate (Sprint 6 Task 5)."""

from __future__ import annotations

import pytest

from cueplayer.application.ma_preflight_export_gate import (
    evaluate_ma_preflight_for_export,
    export_allowed_from_validation,
    should_show_preflight_dialog,
)
from cueplayer.domain.models import Project, Song
from cueplayer.domain.validation import ValidationReport, make_issue


def test_export_allowed_from_validation_policy() -> None:
    clean = ValidationReport()
    assert export_allowed_from_validation(clean) is True

    warnings_only = ValidationReport()
    warnings_only.add(
        make_issue("MA050", "warning", "empty", subject="sequence:s1:main")
    )
    assert export_allowed_from_validation(warnings_only) is True

    with_errors = ValidationReport()
    with_errors.add(make_issue("MA002", "error", "missing", subject="song:s1"))
    assert export_allowed_from_validation(with_errors) is False


def test_should_show_dialog_when_any_issue() -> None:
    empty = ValidationReport()
    assert should_show_preflight_dialog(empty) is False
    info = ValidationReport()
    info.add(make_issue("MA150", "information", "songs", subject="project:songs"))
    assert should_show_preflight_dialog(info) is True


def test_evaluate_fresh_and_blocks_errors() -> None:
    project = Project.create("Show")
    project.songs.clear()
    bad = Song.create("開場")
    bad.ma_export_name = ""  # MA002 error
    project.songs.append(bad)

    gate1 = evaluate_ma_preflight_for_export(project)
    assert gate1.has_errors is True
    assert gate1.allow_export is False
    assert gate1.show_dialog is True
    assert gate1.validation.has_errors is True
    assert gate1.presentation.has_errors is True

    # Fresh call — distinct report objects (no cache).
    gate2 = evaluate_ma_preflight_for_export(project)
    assert gate1.validation is not gate2.validation
    assert gate1.presentation is not gate2.presentation


def test_evaluate_allows_warnings_and_info() -> None:
    project = Project.create("Show")
    project.songs.clear()
    song = Song.create("Opening")
    song.ma_export_name = "Opening"
    # No main marks → MA050 warning; info MA150+ always present.
    project.songs.append(song)

    gate = evaluate_ma_preflight_for_export(project)
    assert gate.has_errors is False
    assert gate.allow_export is True
    assert gate.show_dialog is True
    assert gate.validation.information_count >= 1
    assert gate.presentation.information_count >= 1


def test_gate_rejects_non_validation_report() -> None:
    with pytest.raises(TypeError):
        export_allowed_from_validation("nope")  # type: ignore[arg-type]
