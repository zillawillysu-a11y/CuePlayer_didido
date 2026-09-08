"""MA2/MA3 regression coverage for LTC clip_generator export mapping."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from cueplayer.domain.models import LtcClip, Song
from cueplayer.exporters.ma2 import Ma2Exporter
from cueplayer.exporters.ma3 import Ma3Exporter
from cueplayer.exporters.plan_from_song import build_export_plan
from cueplayer.exporters.xml_inspect import load_xml_root, xml_tag_local


ROOT = Path(__file__).resolve().parents[2]


def _clip(clip_id: str, start: float, duration: float, tc: str) -> LtcClip:
    return LtcClip(
        id=clip_id,
        timeline_start_seconds=start,
        duration_seconds=duration,
        start_timecode=tc,
    )


def _boundary_song() -> Song:
    song = Song.create("Clip 測試")
    song.ma_export_name = "ClipTest"
    song.duration_seconds = 40.0
    song.fps = 30.0
    song.ltc_source_mode = "clip_generator"
    song.ltc_clips = [
        _clip("clipAAAA1111", 10.0, 10.0, "01:00:00:00"),
        _clip("clipBBBB2222", 20.0, 10.0, "10:00:00:00"),
    ]
    for t, name in [
        (5.0, "Before"),
        (10.0, "ExactStart"),
        (15.0, "InsideA"),
        (20.0, "AdjacentBoundary"),
        (30.0, "ExactEnd"),
    ]:
        song.add_mark(1, t, name)
    song.add_mark(2, 25.0, "ButtonInside")
    song.add_mark(2, 35.0, "ButtonOutside")
    return song


def _ma2_events(path: Path) -> list[tuple[str, str]]:
    root = load_xml_root(path)
    return [
        (event.get("command", ""), event.get("time", ""))
        for event in root.iter()
        if xml_tag_local(event.tag) == "Event"
    ]


def _ma3_events(path: Path) -> list[tuple[str, str]]:
    root = load_xml_root(path)
    return [
        (event.get("Name", ""), event.get("Time", ""))
        for event in root.iter()
        if xml_tag_local(event.tag) == "CmdEvent"
    ]


@pytest.mark.parametrize("console", ["ma2", "ma3"])
def test_clip_generator_plan_keeps_cues_and_maps_boundaries(console: str) -> None:
    plan = build_export_plan(_boundary_song(), console=console)  # type: ignore[arg-type]

    assert len(plan.main_cues) == 5
    assert [cue.emit_timecode_event for cue in plan.main_cues] == [
        False,
        True,
        True,
        True,
        False,
    ]
    assert [cue.timecode_event_seconds for cue in plan.main_cues] == [
        None,
        3600.0,
        3605.0,
        36000.0,
        None,
    ]
    assert plan.button_lanes[0].mark_times_seconds == [25.0, 35.0]
    assert plan.button_lanes[0].timecode_event_times_seconds == [36005.0]
    assert plan.profile.start_offset_seconds == 0.0
    assert plan.warnings == [
        "Song Clip 測試: out-of-clip Mark Main Cue 1 at 5.000s; "
        "Sequence Cue exported, Timecode Event omitted",
        "Song Clip 測試: out-of-clip Mark Main Cue 5 at 30.000s; "
        "Sequence Cue exported, Timecode Event omitted",
        "Song Clip 測試: out-of-clip Mark Mark 2 #2 at 35.000s; "
        "Sequence Cue exported, Timecode Event omitted",
    ]


@pytest.mark.parametrize("console", ["ma2", "ma3"])
def test_clip_generator_golden_timecode_and_single_object(
    console: str, tmp_path: Path
) -> None:
    plan = build_export_plan(_boundary_song(), console=console)  # type: ignore[arg-type]
    exporter = Ma2Exporter() if console == "ma2" else Ma3Exporter()
    paths = exporter.export_to_directory(plan, tmp_path / console)

    actual = _ma2_events(paths["timecode"]) if console == "ma2" else _ma3_events(paths["timecode"])
    fixture = ROOT / "fixtures" / console / "clip_generator_timecode.xml"
    expected = _ma2_events(fixture) if console == "ma2" else _ma3_events(fixture)
    assert actual == expected

    root = load_xml_root(paths["timecode"])
    assert sum(1 for el in root.iter() if xml_tag_local(el.tag) == "Timecode") == 1
    if console == "ma2":
        show_root = ET.fromstring(exporter.build_show_timecode_xml([plan]))
        assert sum(
            1 for el in show_root.iter() if xml_tag_local(el.tag) == "Timecode"
        ) == 1
        assert [
            (event.get("command", ""), event.get("time", ""))
            for event in show_root.iter()
            if xml_tag_local(event.tag) == "Event"
        ] == expected
    main = load_xml_root(paths["main_sequence"])
    exported_cues = []
    for cue in main.iter():
        if xml_tag_local(cue.tag) != "Cue":
            continue
        if console == "ma2" and cue.get("index") in {"1", "2", "3", "4", "5"}:
            exported_cues.append(cue)
        if console == "ma3" and (cue.get("No") or "").strip() in {
            "1", "2", "3", "4", "5"
        }:
            exported_cues.append(cue)
    assert len(exported_cues) == 5
    if console == "ma3":
        cue_names = {cue.get("Name") for cue in exported_cues}
        assert "Before" in cue_names
        assert "ExactEnd" in cue_names


def test_clip_generator_backward_overlap_and_duplicate_warn_but_export(
    tmp_path: Path,
) -> None:
    song = Song.create("Warnings Song")
    song.ma_export_name = "WarningsSong"
    song.duration_seconds = 40.0
    song.ltc_source_mode = "clip_generator"
    song.ltc_clips = [
        _clip("forwardA1111", 0.0, 10.0, "10:00:00:00"),
        _clip("backward2222", 10.0, 10.0, "02:00:00:00"),
        _clip("overlap3333", 20.0, 10.0, "02:00:05:00"),
    ]
    song.add_mark(1, 10.0, "MainDuplicate")
    song.add_mark(2, 10.0, "ButtonDuplicate")

    plan = build_export_plan(song, console="ma2")
    assert any("backward TC range" in warning for warning in plan.warnings)
    assert any("overlapping TC ranges" in warning for warning in plan.warnings)
    assert any(
        "duplicate resulting Timecode Event at 02:00:00:00" in warning
        and "Main Cue 1" in warning
        and "Mark 2 #1" in warning
        for warning in plan.warnings
    )
    paths = Ma2Exporter().export_to_directory(plan, tmp_path)
    assert len(_ma2_events(paths["timecode"])) == 2


def test_full_track_and_legacy_modes_keep_existing_event_math(tmp_path: Path) -> None:
    for mode in ("full_track_generator", "striped_file", "auto"):
        song = Song.create(mode)
        song.ma_export_name = mode
        song.ltc_source_mode = mode
        song.start_timecode = "01:00:00:00"
        song.add_mark(1, 1.5, "Legacy")
        plan = build_export_plan(song, console="ma2")
        assert plan.profile.start_offset_seconds == 3600.0
        assert plan.main_cues[0].timecode_event_seconds is None
        assert plan.main_cues[0].emit_timecode_event is True
        assert plan.warnings == []
        paths = Ma2Exporter().export_to_directory(plan, tmp_path / mode)
        assert ("Go", "45") in _ma2_events(paths["timecode"])
