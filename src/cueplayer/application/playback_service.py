"""Application service: playback control over the sole sample clock.

Design contract
---------------
**Responsibilities**
- Expose transport (Play / Pause / Stop / Seek / Toggle / Nudge) to the UI.
- Expose volume / mute / music-bed gain / waveform gain to the UI.
- Expose A–B loop state mutations (set A/B, drag region, enable, clear).
- Expose scrub begin / end to the UI.
- Delegate all of the above to ``AudioEngine`` (unchanged implementation).
- Keep ``domain.song_session.SongSession`` transport fields in sync with the engine.

**Non-responsibilities**
- Does not redesign or subclass ``AudioEngine``.
- Does not own Timeline / Waveform widgets or their paint logic.
- Does not own OSC / MIDI / LTC / MTC configuration or device open/close.
- Does not perform full song-activate orchestration (``MainWindow._activate_song``).
- Does not own device sample-rate selection (``AudioEngine._playback_rate``);
  that is an internal PortAudio negotiation, not a UI pitch-rate control.
- Does not own Settings / QSettings / RemoteHost.

**Dependencies**
- ``cueplayer.playback.audio_engine.AudioEngine`` (PlaybackClock + mix)
- ``cueplayer.domain.song_session.SongSession`` (read-model mirror)

**Why this design**
- Strangler: UI talks to one playback façade; engine stays the sole clock and
  source of truth. Session stays a read-only mirror so UI/tests can observe
  transport without racing the audio thread.
"""

from __future__ import annotations

from cueplayer.domain.models import Song
from cueplayer.domain.song_session import SongSession
from cueplayer.playback.audio_engine import AudioEngine


class PlaybackService:
    """Playback façade: UI → this → AudioEngine (+ SongSession snapshot)."""

    def __init__(self, engine: AudioEngine, session: SongSession) -> None:
        self._engine = engine
        self._session = session

    @property
    def engine(self) -> AudioEngine:
        """Underlying sample clock (song-activate / device / LTC still need it)."""
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

    def nudge(self, delta_seconds: float) -> None:
        """Nudge playhead by ``delta_seconds`` (arrow-key frame steps)."""
        self._engine.nudge(float(delta_seconds))
        self.sync_from_engine()

    # --- scrub ---------------------------------------------------------------

    def begin_scrub(self) -> None:
        self._engine.begin_scrub()
        self.sync_from_engine()

    def end_scrub(self) -> None:
        self._engine.end_scrub()
        self.sync_from_engine()

    # --- volume / mute / gain ------------------------------------------------

    def set_volume(self, volume: float) -> None:
        """Master music gain (0…1). Does not affect generated LTC."""
        self._engine.set_volume(float(volume))

    def volume(self) -> float:
        return float(self._engine.volume())

    def set_music_volume(self, volume: float) -> None:
        """Music-bed gain for video/music balance (0…1); never applied to LTC."""
        self._engine.set_music_volume(float(volume))

    def music_volume(self) -> float:
        return float(self._engine.music_volume())

    def set_audio_gain_db(self, gain_db: float) -> None:
        """Per-file waveform gain in dB (−12…+12); does not affect LTC."""
        self._engine.set_audio_gain_db(float(gain_db))

    def set_music_muted(self, muted: bool) -> None:
        """PC music mute (LTC stays)."""
        self._engine.set_music_muted(bool(muted))

    @property
    def music_muted(self) -> bool:
        return bool(self._engine.music_muted)

    # --- A–B loop ------------------------------------------------------------

    @property
    def loop_a(self) -> float | None:
        return self._engine.loop_a

    @property
    def loop_b(self) -> float | None:
        return self._engine.loop_b

    @property
    def loop_enabled(self) -> bool:
        return bool(self._engine.loop_enabled)

    def clear_loop(self) -> None:
        self._engine.clear_loop()

    def set_loop_region(self, a: float | None, b: float | None) -> None:
        """Timeline handle drag — repositions A/B; never seeks playhead."""
        self._engine.loop_a = float(a) if a is not None else None
        self._engine.loop_b = float(b) if b is not None else None
        if (
            self._engine.loop_a is not None
            and self._engine.loop_b is not None
            and abs(self._engine.loop_b - self._engine.loop_a) >= 0.01
        ):
            self._engine.loop_enabled = True
            self._engine.engage_ab_loop(seek_if_outside=False)

    def set_loop_a_at(self, t: float) -> float:
        """Mark A at ``t``. Fresh-pair rule when A+B already formed a loop."""
        t = float(t)
        if self._complete_loop_pair():
            self._engine.loop_b = None
            self._engine.loop_enabled = False
            self._engine._loop_engage = False  # noqa: SLF001 — same as prior MainWindow
        self._engine.loop_a = t
        if self._complete_loop_pair():
            self._engine.loop_enabled = True
            self._engine.engage_ab_loop(seek_if_outside=False)
        return float(self._engine.loop_a)

    def set_loop_b_at(self, t: float) -> float:
        """Mark B at ``t``. Fresh-pair rule when A+B already formed a loop."""
        t = float(t)
        if self._complete_loop_pair():
            self._engine.loop_a = None
            self._engine.loop_enabled = False
            self._engine._loop_engage = False  # noqa: SLF001
        self._engine.loop_b = t
        if self._complete_loop_pair():
            self._engine.loop_enabled = True
            self._engine.engage_ab_loop(seek_if_outside=False)
        return float(self._engine.loop_b)

    def try_set_loop_enabled(self, enabled: bool) -> str | None:
        """Enable/disable loop. Returns a status reason on rejection, else None."""
        if enabled and (self._engine.loop_a is None or self._engine.loop_b is None):
            return "Set point A and B first"
        if enabled and abs((self._engine.loop_b or 0) - (self._engine.loop_a or 0)) < 0.01:
            return "A / B are too close together"
        self._engine.set_loop_enabled(enabled)
        return None

    def _complete_loop_pair(self) -> bool:
        return (
            self._engine.loop_a is not None
            and self._engine.loop_b is not None
            and abs(self._engine.loop_b - self._engine.loop_a) >= 0.01
        )

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
