"""grandMA2 exporter scaffold.

Generation is intentionally incomplete until golden XML fixtures from
grandMA2 3.9.61.5 are collected at the company machine.
"""

from __future__ import annotations

from pathlib import Path

from cueplayer.exporters.common import SongExportPlan


MA2_TARGET_VERSION = "3.9.61.5"


class Ma2Exporter:
    target_version = MA2_TARGET_VERSION

    def export_plan_summary(self, plan: SongExportPlan) -> dict:
        return {
            "console": "ma2",
            "target_version": self.target_version,
            "song_name": plan.song_name,
            "main_cue_count": len(plan.main_cues),
            "button_lane_count": len(plan.button_lanes),
            "button_event_count": sum(len(lane.mark_times_seconds) for lane in plan.button_lanes),
            "sequence_pool_start": plan.profile.sequence_pool_start,
            "timecode_pool": plan.profile.timecode_pool,
            "note": (
                "XML generation waits for fixtures/ma2 golden files from onPC "
                f"{self.target_version}."
            ),
        }

    def write_placeholder_readme(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "EXPORT_STATUS.txt"
        path.write_text(
            "Ma2Exporter scaffold only. Drop golden XML into this folder per docs/spikes/MA_GOLDEN_XML.md.\n",
            encoding="utf-8",
        )
        return path
