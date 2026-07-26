"""Tests for LTC latency compensation on MA export times."""

from __future__ import annotations

from pathlib import Path

from cueplayer.exporters.common import (
    ExportButtonLane,
    ExportCue,
    MaExportProfile,
    SongExportPlan,
    export_event_time_seconds,
)
from cueplayer.exporters.ma3 import Ma3Exporter
from cueplayer.exporters.xml_inspect import load_xml_root, xml_tag_local


def test_export_event_time_applies_negative_latency() -> None:
    profile = MaExportProfile(
        console="ma3",
        start_offset_seconds=0.0,
        ltc_latency_compensation_seconds=-0.15,
    )
    assert export_event_time_seconds(2.0, profile) == 1.85
    assert export_event_time_seconds(0.05, profile) == 0.0  # clamped


def test_ma3_timecode_events_shift_earlier_with_compensation(tmp_path: Path) -> None:
    plan = SongExportPlan(
        song_name="Latency Test",
        profile=MaExportProfile(
            console="ma3",
            export_mode="timecode_only",
            ltc_latency_compensation_seconds=-0.20,
        ),
        main_cues=[ExportCue(1, "A", time_seconds=2.0)],
        button_lanes=[
            ExportButtonLane(2, "B", mark_times_seconds=[3.0]),
        ],
    )
    paths = Ma3Exporter().export_to_directory(plan, tmp_path)
    root = load_xml_root(paths["timecode"])
    times = [
        float(event.get("Time", "0"))
        for event in root.iter()
        if xml_tag_local(event.tag) == "CmdEvent"
    ]
    assert 1.8 in times  # 2.0 - 0.20
    assert 2.8 in times  # 3.0 - 0.20
