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


def _sample_plan(console: str, *, mode: str = "full") -> SongExportPlan:
    return SongExportPlan(
        song_name="測試歌曲",
        profile=MaExportProfile(
            console=console,
            fps=30.0,
            page=1,
            sequence_pool_start=1,
            main_executor="1.101",
            export_mode=mode,  # type: ignore[arg-type]
        ),
        main_cues=[
            ExportCue(1, "Verse", time_seconds=1.533),
            ExportCue(2, "Chorus", time_seconds=2.567),
            ExportCue(3, "End", time_seconds=4.200),
        ],
        button_lanes=[
            ExportButtonLane(
                lane_index=2,
                display_name="Strobe",
                executor="1.201",
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
    assert paths["plugin_xml"].is_file()
    tc_text = paths["timecode"].read_text(encoding="utf-8")
    assert "CuePlayer_Main 1.101" in tc_text
    assert "CuePlayer_Button 1.201" in tc_text or "1.201" in tc_text
    assert paths["plugin_lua"].is_file()
    assert paths["macro_xml"].is_file()
    plugin_xml = paths["plugin_xml"].read_text(encoding="utf-8")
    assert 'luafile="cueplayer_export.lua"' in plugin_xml
    assert "ComponentLua" not in plugin_xml
    lua = paths["plugin_lua"].read_text(encoding="utf-8")
    assert "return Start, Cleanup" in lua
    assert "Assign Sequence" in lua
    assert "At Exec" in lua
    macro_xml = paths["macro_xml"].read_text(encoding="utf-8")
    assert "CuePlayer Export" in macro_xml
    assert "Macroline" in macro_xml or "macroline" in macro_xml.lower()


def test_ma3_exporter_writes_expected_semantics(tmp_path: Path) -> None:
    paths = Ma3Exporter().export_to_directory(_sample_plan("ma3"), tmp_path)

    main = load_xml_root(paths["main_sequence"])
    assert main.tag == "GMA3"
    sequ = next(el for el in main.iter() if xml_tag_local(el.tag) == "Sequence")
    assert sequ.get("SoftLTP") == "Yes"
    assert sequ.get("UseExecutorTime") == "Yes"
    numbered = [
        cue
        for cue in main.iter()
        if xml_tag_local(cue.tag) == "Cue" and (cue.get("No") or "").strip() in {"1", "2", "3"}
    ]
    assert len(numbered) == 3
    assert all(cue.get("Name") is None for cue in numbered)

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

    macro = load_xml_root(paths["macro"])
    commands = [
        line.get("Command", "")
        for line in macro.iter()
        if xml_tag_local(line.tag) == "MacroLine"
    ]
    assert any("Import Sequence" in cmd for cmd in commands)
    assert any(cmd.startswith("Assign Sequence") and "At Page" in cmd for cmd in commands)
    assert any(cmd.startswith("Assign Go+") for cmd in commands)
    assert any(cmd.startswith("Assign Top") for cmd in commands)
    assert any("Import Timecode" in cmd for cmd in commands)


def test_timecode_only_skips_sequence_files(tmp_path: Path) -> None:
    ma2_paths = Ma2Exporter().export_to_directory(
        _sample_plan("ma2", mode="timecode_only"), tmp_path / "ma2"
    )
    ma3_paths = Ma3Exporter().export_to_directory(
        _sample_plan("ma3", mode="timecode_only"), tmp_path / "ma3"
    )
    assert "timecode" in ma2_paths and ma2_paths["timecode"].is_file()
    assert "main_sequence" not in ma2_paths
    assert "plugin_xml" not in ma2_paths
    assert "timecode" in ma3_paths and ma3_paths["timecode"].is_file()
    assert "main_sequence" not in ma3_paths
    assert "macro" not in ma3_paths
