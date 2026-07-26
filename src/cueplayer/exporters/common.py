"""Shared helpers for grandMA exporters."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

ConsoleFamily = Literal["ma2", "ma3"]
ExportMode = Literal["full", "timecode_only"]


_SAFE_RE = re.compile(r"[^A-Za-z0-9 _.-]+")
_SPACE_RE = re.compile(r"\s+")


def sanitize_ma_name(name: str, *, fallback: str) -> str:
    """
    Produce an MA-safe ASCII label.

    Chinese / punctuation is stripped. Empty results fall back to the provided id.
    Never invent translated English here — callers choose Cue ID / manual / later providers.
    """
    cleaned = _SAFE_RE.sub("", name).strip()
    cleaned = _SPACE_RE.sub(" ", cleaned)
    cleaned = cleaned.strip(" ._-+")
    return cleaned if cleaned else fallback


def parse_page_executor(value: str) -> tuple[int, int]:
    """Parse '1.101' into (page, executor)."""
    text = value.strip()
    if "." in text:
        page_s, exec_s = text.split(".", 1)
        return int(page_s), int(exec_s)
    return 1, int(text)


def export_event_time_seconds(mark_time_seconds: float, profile: MaExportProfile) -> float:
    """
    Convert a CuePlayer mark time into MA Timecode event time.

    Applies song start offset plus LTC/console latency compensation.
    Compensation is typically negative (e.g. -0.10 / -0.20) so events fire
    earlier and land on beat when MA is triggered by LTC.
    """
    t = (
        mark_time_seconds
        + profile.start_offset_seconds
        + profile.ltc_latency_compensation_seconds
    )
    return max(0.0, t)


@dataclass
class ExportCue:
    cue_number: float
    display_name: str
    ma_export_name: str | None = None
    time_seconds: float = 0.0

    def resolved_ma_name(self) -> str:
        if self.ma_export_name and self.ma_export_name.strip():
            return sanitize_ma_name(self.ma_export_name, fallback=f"Cue{self.cue_number:g}")
        return sanitize_ma_name(self.display_name, fallback=f"Cue{self.cue_number:g}")


@dataclass
class ExportButtonLane:
    lane_index: int
    display_name: str
    ma_export_name: str | None = None
    executor: str = "1.201"
    mark_times_seconds: list[float] = field(default_factory=list)

    def resolved_ma_name(self) -> str:
        fallback = f"Button{self.lane_index}"
        if self.ma_export_name and self.ma_export_name.strip():
            return sanitize_ma_name(self.ma_export_name, fallback=fallback)
        return sanitize_ma_name(self.display_name, fallback=fallback)


@dataclass
class MaExportProfile:
    console: ConsoleFamily
    sequence_pool_start: int = 1
    timecode_pool: int = 1
    page: int = 1
    main_executor: str = "1.101"
    timecode_slot: int = 1
    fps: float = 30.0
    start_offset_seconds: float = 0.0
    # Negative = fire earlier (CuePoints "Global Latency Negative Offset").
    # Typical live LTC→MA lag: -0.10 ~ -0.20.
    ltc_latency_compensation_seconds: float = 0.0
    data_pool: str = "Default"  # MA3
    button_follow_seconds: float = 0.1  # hidden internal default
    export_mode: ExportMode = "full"
    main_sequence_name: str = "CuePlayer_Main"
    button_sequence_name: str = "CuePlayer_Button"
    timecode_name: str = "CuePlayer_TC"
    # Filenames used by macros/plugins when importing from library folders.
    main_sequence_file: str = "cueplayer_test_main.xml"
    button_sequence_file: str = "cueplayer_test_button.xml"
    timecode_file: str = "cueplayer_test_timecode.xml"


@dataclass
class SongExportPlan:
    song_name: str
    profile: MaExportProfile
    main_cues: list[ExportCue] = field(default_factory=list)
    button_lanes: list[ExportButtonLane] = field(default_factory=list)
