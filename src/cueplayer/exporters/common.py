"""Shared helpers for grandMA exporters."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

ConsoleFamily = Literal["ma2", "ma3"]


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
    data_pool: str = "Default"  # MA3
    button_follow_seconds: float = 0.1  # hidden internal default


@dataclass
class SongExportPlan:
    song_name: str
    profile: MaExportProfile
    main_cues: list[ExportCue] = field(default_factory=list)
    button_lanes: list[ExportButtonLane] = field(default_factory=list)
