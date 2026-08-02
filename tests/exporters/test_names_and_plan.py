"""MA export name and plan tests (no golden XML required)."""

from __future__ import annotations

from cueplayer.exporters.common import (
    ExportButtonLane,
    ExportCue,
    MaExportProfile,
    SongExportPlan,
    sanitize_ma_name,
)
from cueplayer.exporters.ma2 import Ma2Exporter
from cueplayer.exporters.ma3 import Ma3Exporter


def test_sanitize_strips_chinese_and_falls_back() -> None:
    # Chinese → pinyin (kept as ASCII label); spaces → underscores for MA2.
    assert sanitize_ma_name("主歌 Verse", fallback="Cue1") == "ZhuGe_Verse"
    assert sanitize_ma_name("第一首歌", fallback="Cue1") == "DiYiShouGe"
    assert sanitize_ma_name("  Hook-1  ", fallback="Cue1") == "Hook-1"
    assert sanitize_ma_name("Mark 4", fallback="B") == "Mark_4"
    # No CJK / no ASCII left after strip → fallback
    assert sanitize_ma_name("!!!", fallback="Cue1") == "Cue1"


def test_split_ma_cue_number_fractional() -> None:
    from cueplayer.exporters.common import (
        format_ma2_cue_link_name,
        format_ma2_timecode_step,
        format_ma3_cue_no_attr,
        format_ma_cue_number,
        ma2_timecode_cue_nos,
        ma3_cue_destination_handle,
        split_ma_cue_number,
    )

    assert split_ma_cue_number(4.0) == (4, 0)
    assert split_ma_cue_number(4.1) == (4, 100)
    assert split_ma_cue_number(1.01) == (1, 10)
    assert format_ma_cue_number(4.1) == "4.1"
    assert format_ma3_cue_no_attr(4.1) == "4.100"
    assert ma3_cue_destination_handle(4.1) == 4100
    assert ma3_cue_destination_handle(1) == 1000
    assert format_ma2_cue_link_name(14.1) == "Cue 14.1"
    assert format_ma2_timecode_step(14.0) == "14"
    # Timecode Cue Nos use sequence index, not Cue ID (15th cue may be 14.1).
    assert ma2_timecode_cue_nos(5, 15) == [1, 5, 15]
    assert ma2_timecode_cue_nos(1, 1) == [1, 1, 1]
    from cueplayer.exporters.common import (
        ExportCue,
        MaExportProfile,
        SongExportPlan,
        ma2_phantom_cue_delete_range,
    )

    phantom_plan = SongExportPlan(
        song_name="P",
        profile=MaExportProfile(console="ma2"),
        main_cues=[
            ExportCue(float(i), f"C{i}", time_seconds=float(i))
            for i in list(range(1, 45)) + [14.1, 15.1, 16.1, 17.1, 18.1, 19.1, 20.1, 21.1, 22.1]
        ],
        button_lanes=[],
    )
    # 44 + 9 fractions = 53 cues, max ID 44 → phantom 45..53
    assert ma2_phantom_cue_delete_range(phantom_plan) == (45, 53)


def test_manual_ma_export_name_wins() -> None:
    cue = ExportCue(
        cue_number=1,
        display_name="副歌",
        ma_export_name="Chorus",
        time_seconds=12.0,
    )
    assert cue.resolved_ma_name() == "Chorus"
    assert cue.cue_name_for_export() == "Chorus"


def test_cue_name_for_export_uses_note() -> None:
    assert ExportCue(1, "Verse", time_seconds=1.0).cue_name_for_export() == "Verse"
    assert ExportCue(2, "主歌", time_seconds=2.0).cue_name_for_export() == "ZhuGe"
    assert ExportCue(3, "Cue 3", time_seconds=3.0).cue_name_for_export() is None
    assert ExportCue(4, "", time_seconds=4.0).cue_name_for_export() is None
    # Sequential placeholder must not become Store label when Cue ID is fractional.
    assert ExportCue(14.1, "Cue 15", time_seconds=1.0).cue_name_for_export() is None
    assert ExportCue(15.0, "Cue_16", time_seconds=1.0).cue_name_for_export() is None
    assert ExportCue(14.1, "Cue 14.1", time_seconds=1.0).cue_name_for_export() is None


def test_build_export_plan_fractional_ids_do_not_fake_sequential_names() -> None:
    from cueplayer.domain.models import Song
    from cueplayer.exporters.plan_from_song import build_export_plan

    song = Song.create("Song")
    marks = []
    for i, (t, cid) in enumerate(
        [
            (1.0, "14"),
            (2.0, "14.1"),
            (3.0, "15"),
            (4.0, "15.1"),
        ],
        start=1,
    ):
        m = song.add_mark(1, t)  # empty Note
        m.main_cue_id = cid
        marks.append(m)
    # Poison: simulate old plan_from_song sequential display (should still export clean).
    marks[1].display_name = "Cue 15"
    marks[2].display_name = "Cue 16"
    marks[3].display_name = "Cue 17"

    plan = build_export_plan(song, console="ma2")
    assert [c.cue_number for c in plan.main_cues] == [14.0, 14.1, 15.0, 15.1]
    assert all(c.cue_name_for_export() is None for c in plan.main_cues)

    cmds = Ma2Exporter().install_commands_for_plan(plan)
    store = [c for c in cmds if c.startswith("Store Sequence 1 Cue")]
    label = [c for c in cmds if c.startswith("Label Sequence 1 Cue")]
    assert store == [
        "Store Sequence 1 Cue 14 /noconfirm",
        "Store Sequence 1 Cue 14.1 /noconfirm",
        "Store Sequence 1 Cue 15 /noconfirm",
        "Store Sequence 1 Cue 15.1 /noconfirm",
    ]
    assert 'Label Sequence 1 Cue 14.1 "Cue 14.1"' in label
    assert 'Label Sequence 1 Cue 15.1 "Cue 15.1"' in label
    assert not any("Cue_15" in c or "Cue_16" in c or "Cue_17" in c for c in cmds)

    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        paths = Ma2Exporter().export_to_directory(plan, Path(d), include_plugin=True)
        tc = paths["timecode"].read_text(encoding="utf-8")
        assert 'name="Cue 14.1"' in tc
        assert 'name="Cue 15.1"' in tc
        assert 'step="14.1"' not in tc
        assert 'step="4294967295"' in tc
        compact = tc.replace("\n", "").replace(" ", "")
        # Cue 14.1 is the 2nd Store'd cue → Nos third = 2 (index), not Cue ID 14.
        assert "<No>1</No><No>1</No><No>2</No>" in compact
        # Cue 15 is the 3rd → index 3 (writing Cue ID 15 would wrongly hit index 15).
        assert "<No>1</No><No>1</No><No>3</No>" in compact
        lua = paths["plugin_lua"].read_text(encoding="utf-8")
        assert "Store Timecode" not in lua
        assert "At Timecode" in lua
        # 14, 14.1, 15, 15.1 → max ID 15, count 4 → no phantom delete
        assert "Delete Sequence" not in lua or "Thru" not in lua

def test_exporter_summaries_include_target_versions() -> None:
    plan = SongExportPlan(
        song_name="測試歌曲",
        profile=MaExportProfile(console="ma3"),
        main_cues=[ExportCue(1, "Intro", time_seconds=0.0)],
        button_lanes=[
            ExportButtonLane(
                lane_index=2,
                display_name="Strobe",
                mark_times_seconds=[1.0, 2.0, 3.0],
            )
        ],
    )
    ma2 = Ma2Exporter().export_plan_summary(plan)
    ma3 = Ma3Exporter().export_plan_summary(plan)
    assert ma2["target_version"] == "3.9.61.5"
    assert ma3["target_version"] == "2.3.2"
    assert ma2["main_cue_count"] == 1
    assert ma3["button_event_count"] == 3
