"""Domain session state for the active song and transport snapshot.

Design contract
---------------
**Responsibilities**
- Hold the current ``Song`` reference (or ``None`` / blank stand-in at UI layer).
- Hold a read model of playback: playing flag, playhead position, duration.
- Provide small mutators used by ``PlaybackService`` / UI to keep the snapshot fresh.

**Non-responsibilities**
- Not a sample clock — ``AudioEngine`` remains the only playback clock.
- Does not call PortAudio, decode video, or drive Timeline/Waveform widgets.
- Does not own Project setlist membership or undo.
- Not the ``ports.SongSession`` Protocol (activate/refresh seam); that stays in ports.

**Dependencies**
- ``cueplayer.domain.models.Song`` only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cueplayer.domain.models import Song


@dataclass
class SongSession:
    """Active-song + transport snapshot (domain read model)."""

    _song: Song | None = field(default=None, repr=False)
    playing: bool = False
    position_seconds: float = 0.0
    duration_seconds: float = 0.0

    @property
    def song(self) -> Song | None:
        """Currently active song, if any."""
        return self._song

    @property
    def current_song(self) -> Song | None:
        """Alias for ``song`` (explicit naming from the Sprint 2 contract)."""
        return self._song

    def set_song(self, song: Song | None) -> None:
        """Point the session at ``song`` without touching the audio engine."""
        self._song = song
        if song is not None:
            # Prefer song duration until the engine reports a loaded buffer duration.
            self.duration_seconds = float(getattr(song, "duration_seconds", 0.0) or 0.0)

    def clear_song(self) -> None:
        self._song = None

    def update_playback_state(
        self,
        *,
        playing: bool | None = None,
        position_seconds: float | None = None,
        duration_seconds: float | None = None,
    ) -> None:
        """Patch transport fields (typically mirrored from ``AudioEngine``)."""
        if playing is not None:
            self.playing = bool(playing)
        if position_seconds is not None:
            self.position_seconds = max(0.0, float(position_seconds))
        if duration_seconds is not None:
            self.duration_seconds = max(0.0, float(duration_seconds))
