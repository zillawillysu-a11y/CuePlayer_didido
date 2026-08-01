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
            page_name="CuePlayer",
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
                sequence_pool=2,
                sequence_name="CuePlayer_Button",
                sequence_file="cueplayer_test_button.xml",
            )
        ],
    )


def test_ma2_exporter_writes_expected_semantics(tmp_path: Path) -> None:
    paths = Ma2Exporter().export_to_directory(
        _sample_plan("ma2"), tmp_path, include_macro=True
    )

    main = load_xml_root(paths["main_sequence"])
    cues = [
        cue
        for cue in main.iter()
        if xml_tag_local(cue.tag) == "Cue" and cue.get("index") in {"1", "2", "3"}
    ]
    assert len(cues) == 3
    # MA2 CuePart must stay nameless (golden shape) so Import keeps cues.
    assert all(
        cue_part.get("name") is None
        for cue_part in main.iter()
        if xml_tag_local(cue_part.tag) == "CuePart"
    )

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
    tc_el = next(el for el in tc.iter() if xml_tag_local(el.tag) == "Timecode")
    assert tc_el.get("offset") is None
    assert tc_el.get("index") == "0"  # pool 1 → 0-based index
    assert sum(1 for el in tc.iter() if xml_tag_local(el.tag) == "Event") >= 4
    tc_text = paths["timecode"].read_text(encoding="utf-8")
    # CuePoints: Object name is sequence name only; Nos = 30, pagepool, page, exec
    assert 'name="CuePlayer_Main"' in tc_text
    assert "<No>30</No>" in tc_text and "<No>101</No>" in tc_text
    assert "CuePlayer_Button" in tc_text
    assert paths["macro_xml"].is_file()
    assert "plugin_xml" not in paths
    macro_xml = paths["macro_xml"].read_text(encoding="utf-8")
    assert "CuePlayer cueplayer_test" in macro_xml
    assert "Macroline" in macro_xml or "macroline" in macro_xml.lower()
    # Setup Macro: Store cues + Timecode options (Endless Repeat / Keep Playbacks / …).
    # Timecode XML Import still comes from the show Plugin.
    assert "Store Sequence" in macro_xml
    assert "At Page 1." in macro_xml
    assert "Assign Top Executor" in macro_xml
    assert 'Import "' not in macro_xml
    assert "/Offset=" in macro_xml
    assert 'Runs="Endless Repeat"' in macro_xml
    assert 'SwitchOff="Keep Playbacks"' in macro_xml
    assert 'StatusCall="Off"' in macro_xml
    assert 'WhenStopping="Rewind"' in macro_xml
    assert 'AutoStart="Off"' in macro_xml
    assert 'TimeUnit="1/100 Seconds"' not in macro_xml
    assert '/TimeUnit="30 FPS"' in macro_xml
    assert "/TimeUnit=0" not in macro_xml
    assert "/Slot=1" in macro_xml
    assert '/RecordMode="Go"' in macro_xml
    assert "/Slot=Intern" not in macro_xml


def test_ma3_exporter_writes_expected_semantics(tmp_path: Path) -> None:
    paths = Ma3Exporter().export_to_directory(_sample_plan("ma3"), tmp_path)

    assert paths["main_sequence"].parent.name == "sequences"
    assert paths["timecode"].parent.name == "timecodes"
    assert paths["macro"].parent.name == "macros"

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
    # Sample plan Notes (Verse / Chorus / End) become Cue Names.
    by_no = {(c.get("No") or "").strip(): c.get("Name") for c in numbered}
    assert by_no["1"] == "Verse"
    assert by_no["2"] == "Chorus"
    assert by_no["3"] == "End"

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

    # Cue destinations use numeric handles (golden fixture style).
    dests = [
        cmd.get("ValCueDestination", "")
        for cmd in tc.iter()
        if xml_tag_local(cmd.tag) == "RealtimeCmd"
    ]
    assert any(d.endswith(".1000") for d in dests)
    assert any(d.startswith("0.5.") for d in dests)

    macro = load_xml_root(paths["macro"])
    commands = [
        line.get("Command", "")
        for line in macro.iter()
        if xml_tag_local(line.tag) == "MacroLine"
    ]
    assert any("Import Sequence" in cmd for cmd in commands)
    assert any(cmd == 'Label Page 1 "CuePlayer"' for cmd in commands)
    assert any(cmd == "Store Page 1" for cmd in commands)
    # Cue names live in Sequence XML (pinyin) — not per-cue Label lines (keeps macro short).
    assert not any("Label Sequence 1 Cue " in cmd for cmd in commands)
    assert any(cmd.startswith("Assign Sequence") and "At Page" in cmd for cmd in commands)
    assert any(cmd.startswith("Assign Go+") for cmd in commands)
    assert any(cmd.startswith("Assign Top") for cmd in commands)
    assert any("Import Timecode" in cmd for cmd in commands)
    assert any('Property "OffsetTCSlot"' in cmd for cmd in commands)
    assert any('Property "FrameReadout" "Seconds"' in cmd for cmd in commands)
    assert any('Property "AutoStart" "Yes"' in cmd for cmd in commands)
    assert any('Property "AutoStop" "Yes"' in cmd for cmd in commands)
    assert any('Property "Playback and Record" "Manual Events"' in cmd for cmd in commands)

    # Named cues in XML (Name before No).
    assert numbered[0].get("Name") == "Verse"
    part1 = next(
        p for p in numbered[0] if xml_tag_local(p.tag) == "Part"
    )
    assert part1.get("Name") == "Verse"


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
