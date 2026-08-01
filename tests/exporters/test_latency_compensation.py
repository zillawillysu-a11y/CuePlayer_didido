"""Tests for LTC latency + Timecode Offset (CuePoints-style)."""

from __future__ import annotations

from pathlib import Path

from cueplayer.exporters.common import (
    ExportButtonLane,
    ExportCue,
    MaExportProfile,
    SongExportPlan,
    export_event_time_seconds,
    format_ma2_offset_assign,
    format_ma2_offset_frames,
    format_ma3_offset_seconds,
)
from cueplayer.exporters.ma2 import Ma2Exporter
from cueplayer.exporters.ma3 import Ma3Exporter
from cueplayer.exporters.xml_inspect import load_xml_root, xml_tag_local


def test_export_event_time_applies_negative_latency_only() -> None:
    """Song start LTC must NOT be baked into event times."""
    profile = MaExportProfile(
        console="ma3",
        start_offset_seconds=3600.0,
        ltc_latency_compensation_seconds=-0.15,
    )
    assert export_event_time_seconds(2.0, profile) == 1.85
    assert export_event_time_seconds(0.05, profile) == 0.0  # clamped


def test_ma3_offset_formatters() -> None:
    assert format_ma3_offset_seconds(3600.0) == "1h00m00.00"
    assert format_ma3_offset_seconds(7.48) == "7.48"
    assert format_ma2_offset_assign(3600.0) == "1h"
    assert format_ma2_offset_assign(10.0) == "10s"
    assert format_ma2_offset_frames(3600.0, 30.0) == "108000"


def test_ma3_timecode_events_relative_with_offset_attr(tmp_path: Path) -> None:
    plan = SongExportPlan(
        song_name="Offset Test",
        profile=MaExportProfile(
            console="ma3",
            export_mode="timecode_only",
            start_offset_seconds=3600.0,
            timecode_slot=1,
            ltc_latency_compensation_seconds=-0.20,
        ),
        main_cues=[ExportCue(1, "A", time_seconds=2.0)],
        button_lanes=[
            ExportButtonLane(2, "B", mark_times_seconds=[3.0]),
        ],
    )
    paths = Ma3Exporter().export_to_directory(plan, tmp_path)
    root = load_xml_root(paths["timecode"])
    tc = next(el for el in root.iter() if xml_tag_local(el.tag) == "Timecode")
    assert tc.get("OffsetTCSlot") == "1h00m00.00"
    assert tc.get("AutoStart") == "Yes"
    assert tc.get("AutoStop") == "Yes"
    assert tc.get("TCSlot") == "1"
    # Duration stays song-relative (not 3600+)
    assert float(tc.get("Duration", "0")) < 10.0
    times = [
        float(event.get("Time", "0"))
        for event in root.iter()
        if xml_tag_local(event.tag) == "CmdEvent"
    ]
    assert 1.8 in times  # 2.0 - 0.20
    assert 2.8 in times  # 3.0 - 0.20
    assert all(t < 100.0 for t in times)


def test_ma2_timecode_offset_via_macro_not_xml(tmp_path: Path) -> None:
    plan = SongExportPlan(
        song_name="Offset Test",
        profile=MaExportProfile(
            console="ma2",
            export_mode="full",
            fps=30.0,
            start_offset_seconds=3600.0,
            main_sequence_file="offset_test_main.xml",
            timecode_file="offset_test_timecode.xml",
        ),
        main_cues=[ExportCue(1, "A", time_seconds=2.0)],
        button_lanes=[],
    )
    paths = Ma2Exporter().export_to_directory(
        plan, tmp_path, include_macro=True, include_plugin=True
    )
    root = load_xml_root(paths["timecode"])
    tc = next(el for el in root.iter() if xml_tag_local(el.tag) == "Timecode")
    # Offset is Assign-only (golden afternoon TC has no XML offset attr).
    assert tc.get("offset") is None
    assert sum(1 for el in root.iter() if xml_tag_local(el.tag) == "Event") == 1
    # Length = last cue 2s + 1s tail → 90 frames @ 30 FPS (not clamped to event).
    assert int(tc.get("lenght", "0")) == 90
    assert tc.get("frame_format") == "30 FPS"
    times = [
        int(ev.get("time", "0"))
        for ev in root.iter()
        if xml_tag_local(ev.tag) == "Event"
    ]
    assert times == [60]  # 2.0s * 30 FPS, relative
    macro = paths["macro_xml"].read_text(encoding="utf-8")
    assert "/Offset=1h" in macro
    assert "/Length=3s" in macro
    lua = paths["plugin_lua"].read_text(encoding="utf-8")
    assert "/Offset=1h" in lua
    assert "/Length=3s" in lua
    assert 'time="60"' in lua
    assert 'frame_format="30 FPS"' in lua
    assert '/TimeUnit="30 FPS"' in lua
    assert "/TimeUnit=0" not in lua
    assert "/Slot=1" in lua
    assert '/RecordMode="Go"' in lua
    assert 'time="108' not in lua


def test_ma2_timecode_length_past_last_cue(tmp_path: Path) -> None:
    """Last cue must not sit on Length edge — media or +1s tail wins."""
    from cueplayer.exporters.common import MA_TIMECODE_TAIL_SECONDS, timecode_span_seconds

    short = SongExportPlan(
        song_name="Edge",
        profile=MaExportProfile(console="ma2", fps=30.0, timecode_file="edge_tc.xml"),
        main_cues=[ExportCue(1, "A", time_seconds=10.0), ExportCue(2, "B", time_seconds=20.0)],
        button_lanes=[],
        duration_seconds=20.0,  # same as last cue
    )
    assert timecode_span_seconds(short) == 20.0 + MA_TIMECODE_TAIL_SECONDS
    paths = Ma2Exporter().export_to_directory(short, tmp_path, include_plugin=True)
    root = load_xml_root(paths["timecode"])
    tc = next(el for el in root.iter() if xml_tag_local(el.tag) == "Timecode")
    assert int(tc.get("lenght", "0")) == 630  # 21s * 30
    assert "/Length=21s" in paths["plugin_lua"].read_text(encoding="utf-8")

    long = SongExportPlan(
        song_name="Full",
        profile=MaExportProfile(console="ma2", fps=30.0),
        main_cues=[ExportCue(1, "A", time_seconds=10.0)],
        button_lanes=[],
        duration_seconds=60.0,
    )
    assert timecode_span_seconds(long) == 60.0


def test_ma2_timecode_uses_fps_frames_not_centiseconds(tmp_path: Path) -> None:
    """
    Regression: XML time/lenght as centiseconds + Import default 30 FPS
    stretched everything ×100/30 (song ~4:14 → ~14:00; cue 1.947 → 6.5).
    """
    plan = SongExportPlan(
        song_name="Stretch",
        profile=MaExportProfile(
            console="ma2",
            export_mode="full",
            fps=30.0,
            start_offset_seconds=3600.0,
            main_sequence_file="stretch_main.xml",
            timecode_file="stretch_timecode.xml",
        ),
        main_cues=[
            ExportCue(1, "A", time_seconds=1.947),
            ExportCue(2, "B", time_seconds=8.204),
            ExportCue(3, "C", time_seconds=20.830),
        ],
        button_lanes=[],
        duration_seconds=4 * 60 + 13.749,
    )
    paths = Ma2Exporter().export_to_directory(plan, tmp_path, include_plugin=True)
    root = load_xml_root(paths["timecode"])
    tc = next(el for el in root.iter() if xml_tag_local(el.tag) == "Timecode")
    assert tc.get("frame_format") == "30 FPS"
    assert int(tc.get("lenght", "0")) == 7612  # ~4:13.73 @ 30 FPS
    times = [
        int(ev.get("time", "0"))
        for ev in root.iter()
        if xml_tag_local(ev.tag) == "Event"
    ]
    assert times == [58, 246, 625]
    # Must NOT be old centisecond stamps (194.7→195, etc.)
    assert 195 not in times and 820 not in times and 2083 not in times
    lua = paths["plugin_lua"].read_text(encoding="utf-8")
    assert lua.index('Import "') < lua.index('/TimeUnit="30 FPS"')
    assert "Store Timecode" not in lua
    assert "/TimeUnit=0" not in lua
    assert "/Length=253.75s" in lua  # song duration, past last cue


def test_ma3_timecode_duration_uses_song_not_last_cue(tmp_path: Path) -> None:
    plan = SongExportPlan(
        song_name="Dur",
        profile=MaExportProfile(console="ma3", export_mode="timecode_only"),
        main_cues=[ExportCue(1, "A", time_seconds=5.0), ExportCue(2, "B", time_seconds=10.0)],
        button_lanes=[],
        duration_seconds=30.0,
    )
    paths = Ma3Exporter().export_to_directory(plan, tmp_path)
    root = load_xml_root(paths["timecode"])
    tc = next(el for el in root.iter() if el.tag == "Timecode" or str(el.tag).endswith("Timecode"))
    assert tc.get("Duration") == "30.00"
    assert tc.get("Cursor") == "30.00"


def test_ma3_timecode_all_cue_destinations_named(tmp_path: Path) -> None:
    """Regression: cue 4+ get ValCueDestination; Object uses correct seq pool index."""
    plan = SongExportPlan(
        song_name="Five",
        profile=MaExportProfile(
            console="ma3",
            export_mode="timecode_only",
            sequence_pool_start=7,
            main_sequence_name="Five_Main",
            data_pool="Default",
        ),
        main_cues=[ExportCue(i, f"C{i}", time_seconds=float(i)) for i in range(1, 6)],
        button_lanes=[],
    )
    paths = Ma3Exporter().export_to_directory(plan, tmp_path)
    root = load_xml_root(paths["timecode"])
    dests = sorted(
        cmd.get("ValCueDestination", "")
        for cmd in root.iter()
        if xml_tag_local(cmd.tag) == "RealtimeCmd"
    )
    # Pool 7 → index 6; cue N → N*1000
    assert dests == [
        "0.5.6.1000",
        "0.5.6.2000",
        "0.5.6.3000",
        "0.5.6.4000",
        "0.5.6.5000",
    ]
    objs = {
        cmd.get("Object")
        for cmd in root.iter()
        if xml_tag_local(cmd.tag) == "RealtimeCmd"
    }
    assert objs == {"13.13.0.5.6"}
