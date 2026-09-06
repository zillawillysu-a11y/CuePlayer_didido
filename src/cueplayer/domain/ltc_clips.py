"""Per-song LTC clip domain logic (domain only).

A ``Song`` in ``clip_generator`` mode owns ``LtcClip`` windows. Inside a clip
the output timecode is::

    output_tc = clip.start_timecode + (position - clip.timeline_start_seconds)

at the song FPS. Outside every clip the song outputs **no LTC and no MTC**
(UI shows "No TC" / ``--:--:--:--``).

Mutual-exclusion rules (user decision 2026-09-06):
- Creating the first clip switches the song to ``clip_generator`` and stops
  ``full_track_generator``; striped file LTC may not run alongside clips.
- Removing the last clip keeps ``clip_generator`` (or a later manual choice of
  ``off``); the full-track generator is **never** auto-restored.

This module must stay free of Qt, JSON/persistence, and AudioEngine.
"""

from __future__ import annotations

from dataclasses import dataclass

from cueplayer.domain.models import LtcClip, Song
from cueplayer.timecode.smpte import (
    Timecode,
    add_frames,
    parse_timecode,
)

#: Tolerance for boundary comparisons (seconds).
POS_EPS = 1e-6


@dataclass(frozen=True)
class LtcClipTcRange:
    """Absolute TC range a clip emits (start inclusive, end exclusive)."""

    start_tc: Timecode
    end_tc: Timecode
    start_frames: int
    end_frames: int


def sorted_ltc_clips(clips: list[LtcClip]) -> list[LtcClip]:
    """Clips ordered by timeline start (stable for equal starts)."""
    return sorted(clips, key=lambda clip: float(clip.timeline_start_seconds))


def clip_at_position(
    clips: list[LtcClip], position_seconds: float
) -> LtcClip | None:
    """Return the clip covering ``position_seconds`` or ``None``.

    A clip covers ``[start, end]`` at its exact end point (the final boundary
    frame still belongs to it) and ``[start, end)`` otherwise. At an exact
    boundary where one clip ends and another begins, the later clip wins.
    """
    pos = float(position_seconds)
    match: LtcClip | None = None
    for clip in sorted_ltc_clips(clips):
        start = float(clip.timeline_start_seconds)
        end = clip.end_seconds
        if pos < start - POS_EPS or pos > end + POS_EPS:
            continue
        # Later-starting clip wins at shared boundaries.
        if match is None or start >= float(match.timeline_start_seconds):
            match = clip
    if match is None:
        return None
    # Half-open rule, except the last clip's end point is included.
    if pos > match.end_seconds + POS_EPS:
        return None
    return match


def ltc_timecode_at(
    clips: list[LtcClip], fps: float, position_seconds: float
) -> Timecode | None:
    """Output TC at a timeline position, or ``None`` outside every clip.

    ``output_tc = clip.start_timecode + (position - clip.timeline_start_seconds)``
    (frames rounded to the nearest song-FPS frame).
    """
    clip = clip_at_position(clips, position_seconds)
    if clip is None:
        return None
    tc = parse_timecode(clip.start_timecode)
    if tc is None:
        return None
    rate = float(fps) if fps > 0 else 30.0
    offset_frames = int(
        round(max(0.0, float(position_seconds) - float(clip.timeline_start_seconds)) * rate)
    )
    return add_frames(tc, offset_frames, rate)


def ltc_clip_tc_range(clip: LtcClip, fps: float) -> LtcClipTcRange | None:
    """Absolute TC range the clip emits (``None`` if start TC is invalid)."""
    start = parse_timecode(clip.start_timecode)
    if start is None:
        return None
    rate = float(fps) if fps > 0 else 30.0
    span_frames = int(round(max(0.0, float(clip.duration_seconds)) * rate))
    end = add_frames(start, span_frames, rate)
    return LtcClipTcRange(
        start_tc=start,
        end_tc=end,
        start_frames=start.total_frames(rate),
        end_frames=end.total_frames(rate),
    )


def validate_ltc_clips(
    clips: list[LtcClip],
    fps: float,
    song_duration_seconds: float,
) -> tuple[list[str], list[str]]:
    """Structural validation for a song's LTC clips.

    Returns ``(errors, warnings)``.

    Errors (must fix before use):
    - clip starts before 0 or ends after the song duration;
    - clip duration <= 0;
    - start timecode does not parse.

    Warnings (allowed, but flagged for the exporter / UI):
    - overlapping timeline ranges;
    - overlapping or backwards (regressed) absolute TC ranges — a later clip
      whose TC start lies inside an earlier clip's TC range.
    """
    errors: list[str] = []
    warnings: list[str] = []
    duration = max(0.0, float(song_duration_seconds))

    for clip in clips:
        label = clip.id[:8]
        if float(clip.duration_seconds) <= 0:
            errors.append(f"LTC clip {label}: duration must be > 0")
        if float(clip.timeline_start_seconds) < -POS_EPS:
            errors.append(f"LTC clip {label}: start is before 0:00")
        if clip.end_seconds > duration + POS_EPS:
            errors.append(
                f"LTC clip {label}: ends after song end "
                f"({clip.end_seconds:.3f}s > {duration:.3f}s)"
            )
        if parse_timecode(clip.start_timecode) is None:
            errors.append(
                f"LTC clip {label}: invalid start timecode "
                f"'{clip.start_timecode}'"
            )

    ordered = sorted_ltc_clips(clips)
    for i in range(len(ordered)):
        for j in range(i + 1, len(ordered)):
            a, b = ordered[i], ordered[j]
            if float(b.timeline_start_seconds) < a.end_seconds - POS_EPS:
                warnings.append(
                    f"LTC clips {a.id[:8]} and {b.id[:8]} overlap on the "
                    f"timeline"
                )
            range_a = ltc_clip_tc_range(a, fps)
            range_b = ltc_clip_tc_range(b, fps)
            if range_a is None or range_b is None:
                continue
            if range_b.start_frames < range_a.end_frames:
                warnings.append(
                    f"LTC clips {a.id[:8]} and {b.id[:8]} have overlapping or "
                    f"backwards TC ranges ({range_a.start_tc.format()}–"
                    f"{range_a.end_tc.format()} vs {range_b.start_tc.format()}-"
                    f"{range_b.end_tc.format()})"
                )
    return errors, warnings


def add_ltc_clip(
    song: Song,
    *,
    timeline_start_seconds: float,
    duration_seconds: float,
    start_timecode: str,
) -> LtcClip:
    """Add an LTC clip to the song and switch it to ``clip_generator``.

    Mutual exclusion: the first clip stops the full-track generator, and
    striped file LTC may not run alongside clips — the song mode becomes
    ``clip_generator`` unconditionally.
    """
    clip = LtcClip.create(
        timeline_start_seconds=timeline_start_seconds,
        duration_seconds=duration_seconds,
        start_timecode=start_timecode,
    )
    song.ltc_clips.append(clip)
    song.ltc_clips = sorted_ltc_clips(song.ltc_clips)
    song.ltc_source_mode = "clip_generator"
    return clip


def remove_ltc_clip(song: Song, clip_id: str) -> bool:
    """Remove one LTC clip by id.

    Removing the last clip keeps the song in ``clip_generator`` (no TC is
    emitted until the user manually re-enables a source); the full-track
    generator is never auto-restored.
    """
    before = len(song.ltc_clips)
    song.ltc_clips = [clip for clip in song.ltc_clips if clip.id != clip_id]
    return len(song.ltc_clips) < before


def resolved_song_ltc_source_mode(
    song: Song,
    *,
    project_ltc_source: str,
    ltc_enabled: bool = True,
) -> str:
    """Resolve the effective per-song LTC source mode.

    Explicit modes (``striped_file`` / ``full_track_generator`` /
    ``clip_generator`` / ``off``) win. The legacy default ``auto`` mirrors the
    pre-clip behavior driven by project ``AudioOutputSettings``:

    - generator            → full_track_generator
    - auto / source sides  → striped_file (stripe detect / fixed side)
    - ltc disabled         → off
    """
    mode = str(song.ltc_source_mode or "auto").strip().lower()
    if mode in ("striped_file", "full_track_generator", "clip_generator", "off"):
        return mode
    if not ltc_enabled:
        return "off"
    if str(project_ltc_source or "auto").strip().lower() == "generator":
        return "full_track_generator"
    return "striped_file"
