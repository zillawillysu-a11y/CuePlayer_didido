"""Application service: playback control over the sole sample clock.

Design contract
---------------
**Responsibilities**
- Expose transport (Play / Pause / Stop / Seek / Toggle / Nudge) to the UI.
- Expose volume / mute / music-bed gain / waveform gain to the UI.
- Expose A–B loop state mutations (set A/B, drag region, enable, clear).
- Expose scrub begin / end to the UI.
- Convert Song Time ↔ Variant Time via ``domain.anchor_mapping`` so
  ``AudioEngine`` receives **Variant Time only** on seek / loop points.
- Hold an ephemeral Align Anchors **preview** offset (never project data).
- Delegate transport to ``AudioEngine`` (unchanged implementation).
- Keep ``domain.song_session.SongSession`` transport fields in sync (Song Time).

**Non-responsibilities**
- Does not redesign or subclass ``AudioEngine``.
- Does not own Timeline / Waveform widgets or their paint logic.
- Does not own OSC / MIDI / LTC / MTC configuration or device open/close.
- Does not perform full song-activate orchestration (``MainWindow._activate_song``).
- Does not own device sample-rate selection (``AudioEngine._playback_rate``);
  that is an internal PortAudio negotiation, not a UI pitch-rate control.
- Does not own Settings / QSettings / RemoteHost.
- Does not invent a second offset formula (only ``anchor_mapping``).
- Does not commit ``SongVariant.anchor_offset`` (Align Apply / undo owns that).

**Dependencies**
- ``cueplayer.playback.audio_engine.AudioEngine`` (PlaybackClock + mix)
- ``cueplayer.domain.song_session.SongSession`` (read-model mirror)
- ``cueplayer.domain.anchor_mapping`` (Song ↔ Variant time)

**Why this design**
- Strangler: UI talks to one playback façade; engine stays the sole clock and
  source of truth. Session stays a read-only mirror so UI/tests can observe
  transport without racing the audio thread. Anchor offsets never move cues.
"""

from __future__ import annotations

from pathlib import Path

from cueplayer.domain.anchor_mapping import (
    coerce_anchor_offset,
    resolve_anchor_offset,
    song_to_variant_time,
    variant_to_song_time,
)
from cueplayer.domain.models import Song
from cueplayer.domain.song_session import SongSession
from cueplayer.domain.song_variant import SongVariant
from cueplayer.playback.audio_engine import AudioEngine


class PlaybackService:
    """Playback façade: UI (Song Time) → mapping → AudioEngine (Variant Time)."""

    def __init__(self, engine: AudioEngine, session: SongSession) -> None:
        self._engine = engine
        self._session = session
        # Ephemeral Align Anchors preview — never written to SongVariant.
        self._preview_anchor_offset: float | None = None

    @property
    def engine(self) -> AudioEngine:
        """Underlying sample clock (song-activate / device / LTC still need it)."""
        return self._engine

    @property
    def session(self) -> SongSession:
        return self._session

    # --- active variant (media path for the sole clock) ----------------------

    def resolve_active_audio_path(self, song: Song | None = None) -> Path | None:
        """Return the media path that should feed ``AudioEngine`` for ``song``.

        Resolution order (path only; time mapping is separate):
        1. ``song.selected_audio_path()`` when an enabled audio variant exists
        2. Legacy main / first ``audio_tracks`` entry

        Does not check whether the file exists on disk.
        """
        target = song if song is not None else self._session.song
        if target is None:
            return None
        return target.active_audio_path()

    def active_variant(self, song: Song | None = None) -> SongVariant | None:
        """Return the enabled selected variant for ``song``, if any."""
        target = song if song is not None else self._session.song
        if target is None:
            return None
        return target.selected_variant()

    # --- anchor mapping (Song Time ↔ Variant / engine Time) ------------------

    def active_anchor_offset(self, song: Song | None = None) -> float:
        """Effective mapping offset: preview (if active) else applied variant offset."""
        if self._preview_anchor_offset is not None:
            return coerce_anchor_offset(self._preview_anchor_offset)
        return resolve_anchor_offset(variant=self.active_variant(song))

    def committed_anchor_offset(self, song: Song | None = None) -> float:
        """``SongVariant.anchor_offset`` only — ignores ephemeral preview."""
        return resolve_anchor_offset(variant=self.active_variant(song))

    @property
    def anchor_preview_active(self) -> bool:
        return self._preview_anchor_offset is not None

    @property
    def preview_anchor_offset(self) -> float | None:
        """Ephemeral preview offset, or ``None`` when not previewing."""
        if self._preview_anchor_offset is None:
            return None
        return coerce_anchor_offset(self._preview_anchor_offset)

    def begin_anchor_preview(self, offset: float) -> None:
        """Start (or refresh) temporary mapping with ``offset`` — no project write.

        Preserves Song Time playhead and rematerializes A–B loop Song Times.
        """
        song_pos = float(self.position)
        loop_a = self.loop_a
        loop_b = self.loop_b
        loop_enabled = bool(self.loop_enabled)
        self._preview_anchor_offset = coerce_anchor_offset(offset)
        self._rematerialize_song_transport(
            song_pos, loop_a, loop_b, loop_enabled=loop_enabled
        )

    def update_anchor_preview(self, offset: float) -> None:
        """Update active preview offset; starts a session if none is active."""
        self.begin_anchor_preview(offset)

    def end_anchor_preview(self) -> None:
        """Exit preview and restore committed-offset mapping — no project write."""
        if self._preview_anchor_offset is None:
            return
        song_pos = float(self.position)
        loop_a = self.loop_a
        loop_b = self.loop_b
        loop_enabled = bool(self.loop_enabled)
        self._preview_anchor_offset = None
        self._rematerialize_song_transport(
            song_pos, loop_a, loop_b, loop_enabled=loop_enabled
        )

    def _rematerialize_song_transport(
        self,
        song_position: float,
        loop_a: float | None,
        loop_b: float | None,
        *,
        loop_enabled: bool,
    ) -> None:
        """Re-apply Song Time transport after the effective offset changes."""
        if loop_a is not None or loop_b is not None:
            self.set_loop_region(loop_a, loop_b)
            # set_loop_region may auto-enable; honour prior enabled flag.
            if not loop_enabled:
                self._engine.set_loop_enabled(False)
            elif self._complete_loop_pair():
                self._engine.set_loop_enabled(True)
                self._engine.engage_ab_loop(seek_if_outside=False)
        self.seek(float(song_position))

    def song_to_engine_time(self, song_time: float, song: Song | None = None) -> float:
        """Song Time → Variant Time for ``AudioEngine`` (via ``anchor_mapping``)."""
        return song_to_variant_time(
            float(song_time), offset=self.active_anchor_offset(song)
        )

    def engine_to_song_time(self, engine_time: float, song: Song | None = None) -> float:
        """Variant / engine Time → Song Time (via ``anchor_mapping``)."""
        return variant_to_song_time(
            float(engine_time), offset=self.active_anchor_offset(song)
        )

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
        """Seek to Song Time ``seconds``; engine receives Variant Time only."""
        self._engine.seek(self.song_to_engine_time(seconds))
        self.sync_from_engine()

    def toggle(self) -> None:
        self._engine.toggle()
        self.sync_from_engine()

    def nudge(self, delta_seconds: float) -> None:
        """Nudge playhead by Song Time delta (equal to Variant delta for constant offset)."""
        # Engine nudge uses media position + delta; constant offset ⇒ Δsong == Δvariant.
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

    # --- A–B loop (Song Time at the façade; Variant Time on the engine) ------

    @property
    def loop_a(self) -> float | None:
        raw = self._engine.loop_a
        if raw is None:
            return None
        return self.engine_to_song_time(float(raw))

    @property
    def loop_b(self) -> float | None:
        raw = self._engine.loop_b
        if raw is None:
            return None
        return self.engine_to_song_time(float(raw))

    @property
    def loop_enabled(self) -> bool:
        return bool(self._engine.loop_enabled)

    def clear_loop(self) -> None:
        self._engine.clear_loop()

    def set_loop_region(self, a: float | None, b: float | None) -> None:
        """Timeline handle drag — Song Time A/B; never seeks playhead."""
        self._engine.loop_a = (
            self.song_to_engine_time(float(a)) if a is not None else None
        )
        self._engine.loop_b = (
            self.song_to_engine_time(float(b)) if b is not None else None
        )
        if (
            self._engine.loop_a is not None
            and self._engine.loop_b is not None
            and abs(self._engine.loop_b - self._engine.loop_a) >= 0.01
        ):
            self._engine.loop_enabled = True
            self._engine.engage_ab_loop(seek_if_outside=False)

    def set_loop_a_at(self, t: float) -> float:
        """Mark A at Song Time ``t``. Fresh-pair rule when A+B already formed a loop."""
        t = float(t)
        if self._complete_loop_pair():
            self._engine.loop_b = None
            self._engine.loop_enabled = False
            self._engine._loop_engage = False  # noqa: SLF001 — same as prior MainWindow
        self._engine.loop_a = self.song_to_engine_time(t)
        if self._complete_loop_pair():
            self._engine.loop_enabled = True
            self._engine.engage_ab_loop(seek_if_outside=False)
        return float(self.loop_a) if self.loop_a is not None else t

    def set_loop_b_at(self, t: float) -> float:
        """Mark B at Song Time ``t``. Fresh-pair rule when A+B already formed a loop."""
        t = float(t)
        if self._complete_loop_pair():
            self._engine.loop_a = None
            self._engine.loop_enabled = False
            self._engine._loop_engage = False  # noqa: SLF001
        self._engine.loop_b = self.song_to_engine_time(t)
        if self._complete_loop_pair():
            self._engine.loop_enabled = True
            self._engine.engage_ab_loop(seek_if_outside=False)
        return float(self.loop_b) if self.loop_b is not None else t

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
        """Copy playing / position / duration; session position is Song Time."""
        self._session.update_playback_state(
            playing=bool(self._engine.playing),
            position_seconds=self.engine_to_song_time(float(self._engine.position)),
            duration_seconds=float(self._engine.duration),
        )

    @property
    def playing(self) -> bool:
        return bool(self._engine.playing)

    @property
    def position(self) -> float:
        """Playhead in Song Time (engine position mapped through anchor_mapping)."""
        return self.engine_to_song_time(float(self._engine.position))

    @property
    def duration(self) -> float:
        return float(self._engine.duration)
