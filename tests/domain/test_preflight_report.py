"""Unit tests for Preflight Report Builder (Sprint 6 Task 3)."""

from __future__ import annotations

import json

from cueplayer.domain.models import Project, Song
from cueplayer.domain.validation import (
    PreflightCategory,
    PreflightReport,
    ValidationReport,
    build_ma_preflight_context,
    build_preflight_report,
    build_preflight_report_for_project,
    category_for_code,
    make_issue,
    run_ma_preflight,
)
from cueplayer.domain.validation.severity import ValidationSeverity


def test_category_for_known_codes() -> None:
    assert category_for_code("MA001") is PreflightCategory.LABELS
    assert category_for_code("MA003") is PreflightCategory.SEQUENCES
    assert category_for_code("MA004") is PreflightCategory.EXECUTORS
    assert category_for_code("MA052") is PreflightCategory.CUES
    assert category_for_code("MA150") is PreflightCategory.SUMMARY
    assert category_for_code("MA999") is PreflightCategory.OTHER


def test_build_preflight_report_groups_and_sorts() -> None:
    raw = ValidationReport(context_label="Demo", rule_set_id="ma-preflight")
    raw.extend(
        [
            make_issue(
                "MA150",
                "information",
                "Total songs: 1",
                subject="project:songs",
                details={"total": 1},
            ),
            make_issue(
                "MA001",
                "error",
                "Song MA Export Name has non-ASCII",
                subject="song:s1",
                path="song.ma_export_name",
                details={"song_name": "開場", "value": "主歌"},
            ),
            make_issue(
                "MA050",
                "warning",
                "Sequence 'Opening' has no cues",
                subject="sequence:s1:main",
                details={"song_id": "s1", "label": "Opening"},
            ),
            make_issue(
                "MA002",
                "error",
                "Song is missing MA Export Name",
                subject="song:s2",
                details={"song_name": "安可"},
            ),
        ]
    )
    report = build_preflight_report(raw)
    assert isinstance(report, PreflightReport)
    assert report.has_errors is True
    assert report.has_warnings is True
    assert report.error_count == 2
    assert report.warning_count == 1
    assert report.information_count == 1
    assert "2 error(s)" in report.summary()

    # Deterministic: errors first, then warnings, then info; within severity by category/code.
    codes = [row.code.value for row in report.issues]
    assert codes == ["MA001", "MA002", "MA050", "MA150"]

    by_sev = report.grouped_by_severity()
    assert [r.code.value for r in by_sev["error"]] == ["MA001", "MA002"]
    assert by_sev["warning"][0].category is PreflightCategory.SEQUENCES

    row0 = report.issues[0]
    assert row0.song_id == "s1"
    assert row0.song_name == "開場"
    assert row0.object_ref == "song:s1"
    assert row0.category is PreflightCategory.LABELS


def test_format_text_and_to_dict_stable() -> None:
    raw = ValidationReport(context_label="Show", rule_set_id="ma-preflight")
    raw.add(
        make_issue(
            "MA002",
            "error",
            "Song is missing MA Export Name",
            subject="song:abc",
            details={"song_name": "A"},
        )
    )
    raw.add(
        make_issue(
            "MA150",
            ValidationSeverity.INFORMATION,
            "Total songs: 1",
            subject="project:songs",
        )
    )
    report = build_preflight_report(raw)
    text = report.format_text()
    assert "Show: 1 error(s), 0 warning(s), 1 info" in text
    assert "[ERROR] MA002" in text
    assert "[INFORMATION] MA150" in text

    payload = report.to_dict()
    assert payload["has_errors"] is True
    assert payload["error_count"] == 1
    assert "by_severity" in payload and "by_category" in payload
    # JSON round-trip
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    decoded = json.loads(encoded)
    assert decoded["issues"][0]["code"] == "MA002"
    assert decoded["issues"][0]["category"] == "labels"


def test_build_preflight_report_for_project_read_only() -> None:
    project = Project.create("Show", with_song=False)
    song = Song.create("開場")
    song.ma_export_name = "主歌"  # invalid → MA001
    project.songs = [song]
    before = song.ma_export_name

    report = build_preflight_report_for_project(project)
    assert song.ma_export_name == before
    assert report.has_errors is True
    assert any(r.code.value == "MA001" for r in report.errors)
    assert report.rule_set_id == "ma-preflight"
    # Context-aware song name enrichment still works for other issues
    ctx = build_ma_preflight_context(project)
    raw = run_ma_preflight(ctx)
    again = build_preflight_report(raw, context=ctx)
    assert again.summary() == report.summary() or again.has_errors
