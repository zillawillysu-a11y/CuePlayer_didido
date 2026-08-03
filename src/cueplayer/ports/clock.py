"""Playback sample-clock boundary.

Implemented today by ``cueplayer.playback.audio_engine.AudioEngine``.
Audio sample position remains the sole master clock (see ``AGENTS.md``).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from cueplayer.domain.models import Song


@runtime_checkable
class PlaybackClock(Protocol):
    """Master timeline clock driven by audio sample position."""

    @property
    def position(self) -> float:
        """Playhead seconds on the song timeline."""
        ...

    @property
    def duration(self) -> float:
        """Loaded media duration in seconds (0 if empty)."""
        ...

    @property
    def playing(self) -> bool:
        """True while the engine is actively advancing the playhead."""
        ...

    def play(self) -> None:
        """Start or resume playback from the current position."""
        ...

    def pause(self, *, for_scrub: bool = False) -> None:
        """Pause playback. ``for_scrub`` mirrors AudioEngine's scrub pause."""
        ...

    def stop(self) -> None:
        """Stop and reset transport per engine policy."""
        ...

    def seek(self, seconds: float) -> None:
        """Move the playhead to ``seconds`` on the song timeline."""
        ...

    def set_song(self, song: Song | None) -> None:
        """Attach or clear the active song (clips, LTC mode, cue notes)."""
        ...
