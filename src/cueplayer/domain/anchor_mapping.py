"""Anchor mapping between Song Time and Variant Time (domain only).

Song Time is the canonical timeline for cues, markers, Timeline UI, and
executors. Variant Time is the media-file playhead for one ``SongVariant``.

``SongVariant.anchor_offset`` (seconds) is applied **only** through this
module. Playback / Timeline / Waveform must not invent a second formula.

Convention
----------
Positive ``anchor_offset`` means the variant media is delayed on the song
timeline: media sample ``0`` aligns with song time ``+offset``.

Formulas (always)::

    variant_time = song_time - anchor_offset
    song_time    = variant_time + anchor_offset

This module must stay free of Qt, persistence I/O, and AudioEngine.
"""

from __future__ import annotations

import math
from typing import Protocol


class SupportsAnchorOffset(Protocol):
    """Minimal surface for ``resolve_anchor_offset(..., variant=…)``."""

    @property
    def anchor_offset(self) -> float: ...


def coerce_anchor_offset(value: object) -> float:
    """Normalize an offset to a finite float seconds value (default ``0.0``)."""
    if value is None:
        return 0.0
    try:
        offset = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(offset):
        return 0.0
    return offset


def resolve_anchor_offset(
    offset: float | None = None,
    *,
    variant: SupportsAnchorOffset | None = None,
) -> float:
    """Pick offset from an explicit value, else ``variant.anchor_offset``, else 0."""
    if offset is not None:
        return coerce_anchor_offset(offset)
    if variant is not None:
        return coerce_anchor_offset(getattr(variant, "anchor_offset", 0.0))
    return 0.0


def song_to_variant_time(
    song_time: float,
    offset: float | None = None,
    *,
    variant: SupportsAnchorOffset | None = None,
) -> float:
    """Map Song Time → Variant Time.

    ``variant_time = song_time - anchor_offset``.
    Does not clamp to media duration (callers decide edge policy).
    """
    return float(song_time) - resolve_anchor_offset(offset, variant=variant)


def variant_to_song_time(
    variant_time: float,
    offset: float | None = None,
    *,
    variant: SupportsAnchorOffset | None = None,
) -> float:
    """Map Variant Time → Song Time.

    ``song_time = variant_time + anchor_offset``.
    Does not clamp to song duration (callers decide edge policy).
    """
    return float(variant_time) + resolve_anchor_offset(offset, variant=variant)


def offset_from_anchors(song_anchor: float, variant_anchor: float) -> float:
    """Compute ``anchor_offset`` so ``variant_anchor`` aligns with ``song_anchor``.

    Inverse of the mapping convention::

        variant_time = song_time - offset
        ⇒ offset = song_anchor - variant_anchor

    Result is coerced to a finite float (same rules as ``coerce_anchor_offset``).
    """
    return coerce_anchor_offset(float(song_anchor) - float(variant_anchor))


def clamp_non_negative(time_seconds: float) -> float:
    """Utility for future playback: reject times before media/song origin."""
    return max(0.0, float(time_seconds))


def variant_time_in_media(
    variant_time: float,
    *,
    media_duration: float | None = None,
) -> bool:
    """True when ``variant_time`` lies in ``[0, media_duration)`` if duration known.

    When ``media_duration`` is ``None``, only requires ``variant_time >= 0``.
    """
    t = float(variant_time)
    if t < 0.0:
        return False
    if media_duration is None:
        return True
    dur = float(media_duration)
    if not math.isfinite(dur) or dur < 0.0:
        return False
    return t < dur or (dur == 0.0 and t == 0.0)
