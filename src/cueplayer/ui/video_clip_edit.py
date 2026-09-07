"""Timeline video-clip edit math (drag / trim / add defaults)."""

from __future__ import annotations


def clip_start_after_body_drag(start0: float, dt_seconds: float) -> float:
    """
    Move a clip (its whole body, not a trim handle) on the timeline.

    Moving never touches trim/source state — it only repositions the clip,
    and it clamps hard at song 0: the clip cannot be dragged to a negative
    start. Continuing to drag left past 0 just holds the clip at 0 with no
    jitter (matches the multi-select group-move clamp in timeline_widget).
    """
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
