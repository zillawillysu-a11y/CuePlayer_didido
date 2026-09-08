"""Unit tests for MA Preflight validation rule pack (Sprint 6 Task 2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cueplayer.domain.models import Project, Song
from cueplayer.domain.song_variant import SongVariant
from cueplayer.domain.validation import (
    build_ma_preflight_context,
    ma_preflight_rules,
    run_ma_preflight,
)


def _project_two_songs() -> Project:
    project = Project.create("Show", with_song=False)
    a = Song.create("開場")
    a.ma_export_name = "Opening"
    a.note = "VIP"
    a.bpm = 128.0
    b = Song.create("安可")
    b.ma_export_name = "Encore"
    b.note = "end"
    b.bpm = 120.0
    project.songs = [a, b]
    return project


def test_ma_preflight_rules_register_unique_codes() -> None:
    pack = ma_preflight_rules()
    assert pack.rule_set_id == "ma-preflight"
    codes = [r.code.value for r in pack.rules]
    assert len(codes) == len(set(codes))
    assert codes[0] == "MA001"
    assert "MA150" in codes


def test_clean_project_has_info_only_errors_absent(tmp_path: Path) -> None:
    project = _project_two_songs()
    song = project.songs[0]
    song.add_mark(1, 1.0, display_name="Kick")
    song.variants = [SongVariant.create("Main", tmp_path / "a.wav")]
    project.songs[1].add_mark(1, 0.5, display_name="Hit")

    ctx = build_ma_preflight_context(project)
    report = run_ma_preflight(ctx)
    assert report.has_errors is False
    assert report.issues_for_code("MA150")
    assert report.issues_for_code("MA151")
    assert report.issues_for_code("MA152")
    assert report.issues_for_code("MA153")
    assert report.issues_for_code("MA153")[0].details["total"] == 1


def test_invalid_and_missing_ma_export_names() -> None:
    project = Project.create("P", with_song=False)
    bad = Song.create("曲A")
    bad.ma_export_name = "主歌"
    missing = Song.create("曲B")
    missing.ma_export_name = None
    project.songs = [bad, missing]
    # Avoid empty-sequence noise focus: still OK — we assert specific codes.
    report = run_ma_preflight(build_ma_preflight_context(project))
    assert any(i.code.value == "MA001" for i in report.errors)
    assert any(i.code.value == "MA002" for i in report.errors)
    assert project.songs[0].ma_export_name == "主歌"  # unchanged


def test_duplicate_sequence_identifiers() -> None:
    project = Project.create("P", with_song=False)
    a = Song.create("A")
    a.ma_export_name = "Shared"
    b = Song.create("B")
    b.ma_export_name = "shared"  # case-insensitive dup
    # Keep only main lanes so button-label dups do not obscure the assertion.
    for song in (a, b):
        for lane in song.mark_lanes:
            if lane.lane_type != "main":
                lane.export_enabled = False
    project.songs = [a, b]
    report = run_ma_preflight(build_ma_preflight_context(project))
    dups = report.issues_for_code("MA003")
    assert len(dups) == 1
    assert dups[0].severity.value == "error"
    assert "Shared" in dups[0].message or "shared" in dups[0].message.lower()


def test_invalid_executor_and_collision() -> None:
    project = _project_two_songs()
    project.ma_export.main_executor = "nope"
    report = run_ma_preflight(build_ma_preflight_context(project))
    assert any(i.code.value == "MA004" for i in report.errors)

    project.ma_export.main_executor = "1.101"
    project.ma_export.button_executor_start = "1.201"
    project.ma_export.page_per_song = False
    # Two mains share executor 1.101 when page_per_song is False.
    report2 = run_ma_preflight(build_ma_preflight_context(project))
    collisions = [
        i
        for i in report2.issues_for_code("MA004")
        if "multiple sequences" in i.message
    ]
    assert collisions


def test_warnings_empty_disabled_unused_metadata(tmp_path: Path) -> None:
    project = Project.create("P", with_song=False)
    active = Song.create("Active")
    active.ma_export_name = "Active"
    # empty main sequence (no marks)
    disabled = Song.create("Skip")
    disabled.ma_export_name = "Skip"
    disabled.note = "x"
    disabled.bpm = 100.0
    project.songs = [active, disabled]
    project.ma_export.export_song_ids = [active.id]

    # Unused cue: mark on a lane with export disabled
    lane = active.lane_by_index(2)
    assert lane is not None
    lane.export_enabled = False
    active.add_mark(2, 2.0, display_name="Ghost")

    report = run_ma_preflight(build_ma_preflight_context(project))
    assert report.issues_for_code("MA050")  # empty sequence on Active main
    assert report.issues_for_code("MA051")  # Skip excluded
    assert report.issues_for_code("MA052")  # unused cue
    assert report.issues_for_code("MA053")  # Active missing note/bpm
    assert disabled.ma_export_name == "Skip"


def test_context_builder_is_read_only_snapshot() -> None:
    project = _project_two_songs()
    ctx = build_ma_preflight_context(project)
    assert ctx.total_songs == 2
    assert ctx.page_per_song is True
    # Frozen views
    with pytest.raises(Exception):
        ctx.songs[0].name = "mutated"  # type: ignore[misc]


def test_rules_do_not_import_exporters() -> None:
    import cueplayer.domain.validation.ma_rules as ma_rules
    import cueplayer.domain.validation.ma_context as ma_context

    assert "cueplayer.exporters" not in ma_rules.__file__
    src = Path(ma_rules.__file__).read_text(encoding="utf-8")
    src2 = Path(ma_context.__file__).read_text(encoding="utf-8")
    assert "cueplayer.exporters" not in src
    assert "cueplayer.exporters" not in src2
