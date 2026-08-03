"""Application service: transport control over the sole sample clock.

Design contract
---------------
**Responsibilities**
- Expose Play / Pause / Stop / Seek / Toggle to the UI.
- Delegate those calls to ``AudioEngine`` (unchanged implementation).
- Keep ``domain.song_session.SongSession`` transport fields in sync with the engine.

**Non-responsibilities**
- Does not redesign or subclass ``AudioEngine``.
- Does not own Timeline, Waveform, video sync, scrub gestures, volume, loop, LTC/MTC/MIDI.
- Does not perform full song-activate orchestration (setlist → timeline/monitor/video);
  ``MainWindow._activate_song`` still coordinates those surfaces.
- Does not open/close PortAudio devices beyond what ``AudioEngine`` already does.

**Dependencies**
- ``cueplayer.playback.audio_engine.AudioEngine`` (PlaybackClock implementation)
- ``cueplayer.domain.song_session.SongSession``
"""

from __future__ import annotations

from cueplayer.domain.models import Song
from cueplayer.domain.song_session import SongSession
from cueplayer.playback.audio_engine import AudioEngine


class PlaybackService:
    """Thin transport façade: UI → this → AudioEngine (+ SongSession snapshot)."""

    def __init__(self, engine: AudioEngine, session: SongSession) -> None:
        self._engine = engine
        self._session = session

    @property
    def engine(self) -> AudioEngine:
        """Underlying sample clock (for advanced wiring that must stay on the engine)."""
        return self._engine

    @property
    def session(self) -> SongSession:
        return self._session

    # --- transport -----------------------------------------------------------

    def play(self) -> None:
        self._engine.play()
        self.sync_from_engine()

    def pause(self, *, for_scrub: bool = False) -> None:
        self._engine.pause(for_scrub=for_scrub)
        self.sync_from_engine()

    def stop(self) -> None:
        self._engine.stop()
        self.sync_from_engine()

    def seek(self, seconds: float) -> None:
        self._engine.seek(float(seconds))
        self.sync_from_engine()

    def toggle(self) -> None:
        self._engine.toggle()
        self.sync_from_engine()

    # --- session mirrors -----------------------------------------------------

    def set_current_song(self, song: Song | None) -> None:
        """Update session current song only (engine ``set_song`` stays with activate)."""
        self._session.set_song(song)

    def sync_from_engine(self) -> None:
        """Copy playing / position / duration from the engine into ``SongSession``."""
        self._session.update_playback_state(
            playing=bool(self._engine.playing),
            position_seconds=float(self._engine.position),
            duration_seconds=float(self._engine.duration),
        )

    @property
    def playing(self) -> bool:
        return bool(self._engine.playing)

    @property
    def position(self) -> float:
        return float(self._engine.position)

    @property
    def duration(self) -> float:
        return float(self._engine.duration)
