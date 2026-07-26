"""grandMA3 exporter scaffold.

Generation is intentionally incomplete until golden XML fixtures from
grandMA3 2.3.2 are collected at the company machine.
"""

from __future__ import annotations

from pathlib import Path

from cueplayer.exporters.common import SongExportPlan


MA3_TARGET_VERSION = "2.3.2"


class Ma3Exporter:
    target_version = MA3_TARGET_VERSION

    def export_plan_summary(self, plan: SongExportPlan) -> dict:
        return {
            "console": "ma3",
            "target_version": self.target_version,
            "song_name": plan.song_name,
            "main_cue_count": len(plan.main_cues),
            "button_lane_count": len(plan.button_lanes),
            "button_event_count": sum(len(lane.mark_times_seconds) for lane in plan.button_lanes),
            "sequence_pool_start": plan.profile.sequence_pool_start,
            "timecode_pool": plan.profile.timecode_pool,
            "data_pool": plan.profile.data_pool,
            "note": (
                "XML generation waits for fixtures/ma3 golden files from onPC "
                f"{self.target_version}."
            ),
        }

    def write_placeholder_readme(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "EXPORT_STATUS.txt"
        path.write_text(
            "Ma3Exporter scaffold only. Drop golden XML into this folder per docs/spikes/MA_GOLDEN_XML.md.\n",
            encoding="utf-8",
        )
        return path
