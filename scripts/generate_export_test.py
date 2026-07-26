"""Generate sample MA2/MA3 XML for onPC import testing."""

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


def _plan(console: str) -> SongExportPlan:
    return SongExportPlan(
        song_name="CuePlayer Import Test",
        profile=MaExportProfile(
            console=console,  # type: ignore[arg-type]
            fps=30.0,
            page=1,
            sequence_pool_start=1,
            timecode_pool=1,
            main_executor="1.101",
            start_offset_seconds=0.0,
            export_mode="full",
            main_sequence_file="cueplayer_test_main.xml",
            button_sequence_file="cueplayer_test_button.xml",
            timecode_file="cueplayer_test_timecode.xml",
        ),
        main_cues=[
            ExportCue(1, "Verse", time_seconds=2.0),
            ExportCue(2, "Chorus", time_seconds=4.0),
            ExportCue(3, "End", time_seconds=6.0),
        ],
        button_lanes=[
            ExportButtonLane(
                lane_index=2,
                display_name="CuePlayer_Button",
                executor="1.201",
                mark_times_seconds=[3.0, 5.0, 7.0],
            )
        ],
    )


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    out_ma2 = root / "fixtures" / "export_test" / "ma2"
    out_ma3 = root / "fixtures" / "export_test" / "ma3"
    Ma2Exporter().export_to_directory(_plan("ma2"), out_ma2)
    Ma3Exporter().export_to_directory(_plan("ma3"), out_ma3)

    print("Generated:")
    for folder in (out_ma2, out_ma3):
        print(folder)
        for path in sorted(folder.iterdir()):
            if path.is_file():
                print(f"  - {path.name} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
