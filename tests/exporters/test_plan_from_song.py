"""Tests for Song → SongExportPlan adapter."""

from __future__ import annotations

from cueplayer.domain.models import Song
from cueplayer.exporters.ma2 import Ma2Exporter
from cueplayer.exporters.plan_from_song import (
    build_export_plan,
    plan_summary_text,
    timecode_to_seconds,
)


def test_timecode_to_seconds() -> None:
    assert abs(timecode_to_seconds("01:00:00:00", 30.0) - 3600.0) < 1e-6
    assert abs(timecode_to_seconds("00:00:01:15", 30.0) - 1.5) < 1e-6


def test_build_export_plan_from_song(tmp_path) -> None:
    song = Song.create("測試歌曲")
    song.ma_export_name = "TestSong"
    song.start_timecode = "01:00:00:00"
    song.fps = 30.0
    song.add_mark(1, 1.5, "Verse")
    song.add_mark(1, 3.0, "Chorus")
    song.add_mark(2, 2.0)
    song.add_mark(2, 4.0)

    plan = build_export_plan(song, console="ma2", button_executor_start="1.201")
    assert plan.song_name == "TestSong"
    assert plan.profile.page_name == "TestSong"
    assert len(plan.main_cues) == 2
    assert plan.main_cues[0].time_seconds == 1.5
    assert plan.main_cues[0].cue_number == 1.0
    assert plan.main_cues[1].cue_number == 2.0
    assert abs(plan.profile.start_offset_seconds - 3600.0) < 1e-6
    assert len(plan.button_lanes) == 1
    assert plan.button_lanes[0].executor == "1.201"
    assert plan.button_lanes[0].mark_times_seconds == [2.0, 4.0]
    assert "Main cues 2" in plan_summary_text(plan)

    paths = Ma2Exporter().export_to_directory(plan, tmp_path, include_macro=True)
    assert paths["timecode"].is_file()
    assert paths["main_sequence"].is_file()
    # Install macro labels the Page with English song name.
    macro = paths["macro_xml"].read_text(encoding="utf-8")
    assert 'Label Page 1 "TestSong"' in macro
    assert "/Offset=1h" in macro


def test_build_export_plan_uses_main_cue_ids() -> None:
    """MA Sequence/Timecode must keep the user's Cue IDs (including fractions)."""
    song = Song.create("Song")
    a = song.add_mark(1, 1.0, "A")
    b = song.add_mark(1, 2.0, "B")
    c = song.add_mark(1, 3.0, "C")
    a.main_cue_id = "1"
    b.main_cue_id = "4.1"
    c.main_cue_id = "5"
    # Gap (deleted 2/3/4) must survive export — do not renumber 1,2,3.
    plan = build_export_plan(song, console="ma3")
    assert [cue.cue_number for cue in plan.main_cues] == [1.0, 4.1, 5.0]
    assert [cue.time_seconds for cue in plan.main_cues] == [1.0, 2.0, 3.0]
