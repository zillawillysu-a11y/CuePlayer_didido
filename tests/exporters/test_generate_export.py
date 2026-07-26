"""Structural tests for generated MA2/MA3 exporter output."""

from __future__ import annotations

from pathlib import Path

from cueplayer.exporters.common import (
    ExportButtonLane,
    ExportCue,
    MaExportProfile,
    SongExportPlan,
)
from cueplayer.exporters.ma2 import Ma2Exporter
from cueplayer.exporters.ma3 import Ma3Exporter
from cueplayer.exporters.xml_inspect import load_xml_root, xml_tag_local


def _sample_plan(console: str) -> SongExportPlan:
    return SongExportPlan(
        song_name="測試歌曲",
        profile=MaExportProfile(console=console, fps=30.0, page=1, sequence_pool_start=1),
        main_cues=[
            ExportCue(1, "Verse", time_seconds=1.533),
            ExportCue(2, "Chorus", time_seconds=2.567),
            ExportCue(3, "End", time_seconds=4.200),
        ],
        button_lanes=[
            ExportButtonLane(
                lane_index=2,
                display_name="Strobe",
                mark_times_seconds=[1.067, 2.867, 4.633],
            )
        ],
    )


def test_ma2_exporter_writes_expected_semantics(tmp_path: Path) -> None:
    paths = Ma2Exporter().export_to_directory(_sample_plan("ma2"), tmp_path)

    main = load_xml_root(paths["main_sequence"])
    cues = [
        cue
        for cue in main.iter()
        if xml_tag_local(cue.tag) == "Cue" and cue.get("index") in {"1", "2", "3"}
    ]
    assert len(cues) == 3

    button = load_xml_root(paths["button_sequence"])
    assert any(
        cue.get("cue_mode") == "Release"
        for cue in button.iter()
        if xml_tag_local(cue.tag) == "Cue"
    )
    assert any(
        trig.get("type") == "Follow" and trig.get("data_f") == "0.1"
        for trig in button.iter()
        if xml_tag_local(trig.tag) == "Trigger"
    )

    tc = load_xml_root(paths["timecode"])
    commands = {
        event.get("command")
        for event in tc.iter()
        if xml_tag_local(event.tag) == "Event"
    }
    assert "Go" in commands
    assert "Top" in commands
    go_events = [
        event
        for event in tc.iter()
        if xml_tag_local(event.tag) == "Event" and event.get("command") == "Go"
    ]
    assert len(go_events) == 3
    top_events = [
        event
        for event in tc.iter()
        if xml_tag_local(event.tag) == "Event" and event.get("command") == "Top"
    ]
    assert len(top_events) == 3


def test_ma3_exporter_writes_expected_semantics(tmp_path: Path) -> None:
    paths = Ma3Exporter().export_to_directory(_sample_plan("ma3"), tmp_path)

    main = load_xml_root(paths["main_sequence"])
    assert main.tag == "GMA3"
    numbered = [
        cue
        for cue in main.iter()
        if xml_tag_local(cue.tag) == "Cue" and (cue.get("No") or "").strip() in {"1", "2", "3"}
    ]
    assert len(numbered) == 3

    button = load_xml_root(paths["button_sequence"])
    assert any(
        cue.get("TrigType") == "Follow" and cue.get("TrigTime") == "0.100"
        for cue in button.iter()
        if xml_tag_local(cue.tag) == "Cue" and (cue.get("No") or "").strip() == "2"
    )

    tc = load_xml_root(paths["timecode"])
    tokens = {
        cmd.get("ExecToken")
        for cmd in tc.iter()
        if xml_tag_local(cmd.tag) == "RealtimeCmd"
    }
    assert "Go+" in tokens
    assert "Top" in tokens
    go_events = [
        event
        for event in tc.iter()
        if xml_tag_local(event.tag) == "CmdEvent" and event.get("Name") == "Go+"
    ]
    assert len(go_events) == 3
    assert all(event.get("CueDestination", "").startswith("Cue ") for event in go_events)
    top_events = [
        event
        for event in tc.iter()
        if xml_tag_local(event.tag) == "CmdEvent" and event.get("Name") == "Top"
    ]
    assert len(top_events) == 3
