"""Embedded video-audio PCM boundary for the sample-clock mixer.

Adapters wrap ``get_video_audio`` / loaders; the playback mixer remains the
consumer under ``AudioEngine``'s callback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class VideoAudioSource(Protocol):
    """Provide decoded PCM for a video file path (cached or fresh)."""

    def get_video_audio(self, path: Path) -> Any | None:
        """Return a buffer object with ``sample_rate`` / ``samples``, or ``None``."""
        ...
