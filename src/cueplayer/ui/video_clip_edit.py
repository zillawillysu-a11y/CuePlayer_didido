"""Timeline video-clip edit math (drag / trim / add defaults)."""

from __future__ import annotations

# Generous pre-roll window for alignment (clip can start before song 0).
_MIN_CLIP_START_SECONDS = -600.0
# Soft snap at song 0 — park here unless the user deliberately drags past.
_SNAP_AT_ZERO_SECONDS = 0.12


def clip_start_after_body_drag(
    start0: float,
    dt_seconds: float,
    *,
    snap_seconds: float = _SNAP_AT_ZERO_SECONDS,
    min_start_seconds: float = _MIN_CLIP_START_SECONDS,
) -> float:
    """
    Move a clip on the timeline.

    Clips may start *before* song 0 for pre-roll alignment. Song 0 has a soft
    magnetic snap: when near zero the clip parks at 0 until the user drags
    deliberately past the snap zone (left → negative, right → positive).
    """
    raw = start0 + dt_seconds
    raw = max(min_start_seconds, raw)
    snap = max(0.02, float(snap_seconds))
    if abs(raw) >= snap:
        return raw
    # Inside the snap well around 0.
    if start0 < -snap:
        # Coming back from negative pre-roll — latch at 0.
        return 0.0
    if start0 > snap:
        # Approaching 0 from the right — latch at 0.
        return 0.0
    # Already in the snap well (typically parked at 0).
    if dt_seconds < 0 and raw <= -snap:
        return raw
    if dt_seconds > 0 and raw >= snap:
        return raw
    return 0.0


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
