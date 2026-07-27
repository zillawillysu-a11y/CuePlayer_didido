"""Timeline video-clip edit math (drag / trim / add defaults)."""

from __future__ import annotations


def clip_start_after_body_drag(start0: float, dt_seconds: float) -> float:
    """Move a clip on the timeline; only the song start (0s) is a hard edge."""
    return max(0.0, start0 + dt_seconds)


def clip_duration_after_right_trim(
    dur0: float,
    dt_seconds: float,
    *,
    source_in_seconds: float,
    source_duration_seconds: float | None,
    min_duration: float = 0.05,
) -> float:
    """Extend or shorten the right edge; cap at source media length when known."""
    max_dur = float("inf")
    if source_duration_seconds is not None and source_duration_seconds > 0:
        max_dur = max(min_duration, source_duration_seconds - source_in_seconds)
    return min(max(min_duration, dur0 + dt_seconds), max_dur)


def default_video_clip_duration(
    source_duration: float,
    song_duration: float,
    start_seconds: float,
    *,
    min_duration: float = 0.2,
) -> float:
    """Initial clip length when adding — fits the song, user can extend later."""
    remaining = max(min_duration, song_duration - max(0.0, start_seconds))
    return min(max(min_duration, source_duration), remaining)
