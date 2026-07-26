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
