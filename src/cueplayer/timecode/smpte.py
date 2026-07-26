"""SMPTE timecode parse / format helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Timecode:
    hours: int
    minutes: int
    seconds: int
    frames: int

    def format(self) -> str:
        return f"{self.hours:02d}:{self.minutes:02d}:{self.seconds:02d}:{self.frames:02d}"

    def total_frames(self, fps: float) -> int:
        rate = _frame_rate(fps)
        return (
            ((self.hours * 60 + self.minutes) * 60 + self.seconds) * rate + self.frames
        )


def _frame_rate(fps: float) -> int:
    """Integer frames-per-second used for HH:MM:SS:FF counting (NDF)."""
    if fps <= 0:
        return 30
    # 29.97 NDF still counts 0–29 like 30 fps.
    if abs(fps - 29.97) < 0.02:
        return 30
    return max(1, int(round(fps)))


def parse_timecode(timecode: str) -> Timecode | None:
    raw = timecode.strip().replace(";", ":")
    parts = raw.split(":")
    if len(parts) != 4:
        return None
    try:
        hours, minutes, seconds, frames = (int(p) for p in parts)
    except ValueError:
        return None
    if hours < 0 or not (0 <= minutes < 60 and 0 <= seconds < 60 and frames >= 0):
        return None
    return Timecode(hours, minutes, seconds, frames)


def timecode_to_seconds(timecode: str, fps: float) -> float:
    """Convert HH:MM:SS:FF to absolute seconds (same semantics as export helpers)."""
    tc = parse_timecode(timecode)
    if tc is None:
        return 0.0
    rate = fps if fps > 0 else 30.0
    return tc.hours * 3600.0 + tc.minutes * 60.0 + tc.seconds + tc.frames / rate


def seconds_to_timecode(seconds: float, fps: float) -> Timecode:
    """Absolute seconds → HH:MM:SS:FF at the given fps (non-drop)."""
    rate = _frame_rate(fps)
    real_fps = fps if fps > 0 else 30.0
    total = max(0, int(round(max(0.0, seconds) * real_fps)))
    frames = total % rate
    total //= rate
    secs = total % 60
    total //= 60
    mins = total % 60
    hours = total // 60
    return Timecode(hours % 24, mins, secs, frames)


def add_frames(tc: Timecode, delta_frames: int, fps: float) -> Timecode:
    rate = _frame_rate(fps)
    total = tc.total_frames(fps) + int(delta_frames)
    if total < 0:
        total = 0
    frames = total % rate
    total //= rate
    secs = total % 60
    total //= 60
    mins = total % 60
    hours = (total // 60) % 24
    return Timecode(hours, mins, secs, frames)
