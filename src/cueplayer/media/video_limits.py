"""Safety caps for long / heavy video sources (rehearsal recordings, etc.).

Hour-long files must never kick off multi-hundred-MB PCM waveform jobs or
scrub ladders that hold ``av_path_lock`` while Clean Output tries to decode
on the UI thread — that pattern freezes the machine and can hard-crash.
"""

from __future__ import annotations

from pathlib import Path

from cueplayer.domain.models import VideoClip

# Source or clip span at/above this is treated as "heavy": skip background
# waveform + scrub preload (those fight Preview/Clean for av_path_lock).
# Embedded clip *audio* still loads via sliding windows — silence is worse
# than a short background decode.
HEAVY_VIDEO_SECONDS = 10 * 60.0

# Absolute ceiling for any embedded-video PCM decode (mixer + waveforms).
# Lower than the old 15-minute cap so a stretched rehearsal clip cannot
# allocate ~300MB+ float32 while the UI needs the same path for Preview.
MAX_VIDEO_AUDIO_DECODE_SECONDS = 5 * 60.0

# Sliding-window size for heavy rehearsal clips (mixer advances this as the
# playhead moves so audio is not limited to the first minute). Keep short:
# rapid mouse seeks used to queue many 120s decodes under ``av_path_lock``
# and freeze Preview + the UI audio poll.
HEAVY_VIDEO_AUDIO_DECODE_SECONDS = 30.0

# Warn (and prefer safer preview) when the file itself is this long.
LONG_SOURCE_WARN_SECONDS = 30 * 60.0

# Optional size hint for the same warning dialog.
LONG_SOURCE_WARN_BYTES = 300 * 1024 * 1024


def clip_source_span_seconds(clip: VideoClip) -> float:
    return max(0.0, float(clip.source_span_seconds or clip.duration_seconds or 0.0))


def clip_source_duration_seconds(clip: VideoClip) -> float:
    if clip.source_duration_seconds is not None:
        return max(0.0, float(clip.source_duration_seconds))
    return clip_source_span_seconds(clip)


def clip_is_heavy(clip: VideoClip) -> bool:
    """True when background PyAV on this clip risks starving Preview/Clean."""
    if getattr(clip, "media_kind", "video") == "still":
        return False
    return (
        clip_source_span_seconds(clip) >= HEAVY_VIDEO_SECONDS
        or clip_source_duration_seconds(clip) >= HEAVY_VIDEO_SECONDS
    )


def audio_decode_cap_for_clip(clip: VideoClip) -> float:
    if clip_is_heavy(clip):
        return HEAVY_VIDEO_AUDIO_DECODE_SECONDS
    return MAX_VIDEO_AUDIO_DECODE_SECONDS


def source_needs_long_video_warning(
    *, duration_seconds: float, path: Path | None = None
) -> bool:
    if duration_seconds >= LONG_SOURCE_WARN_SECONDS:
        return True
    if path is None:
        return False
    try:
        return path.stat().st_size >= LONG_SOURCE_WARN_BYTES
    except OSError:
        return False
