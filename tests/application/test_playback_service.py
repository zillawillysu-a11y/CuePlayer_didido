"""Unit tests for domain SongSession and application PlaybackService."""

from __future__ import annotations

from pathlib import Path

import pytest

from cueplayer.application.playback_service import PlaybackService
from cueplayer.domain.models import AudioTrack, Project, Song
from cueplayer.domain.song_session import SongSession
from cueplayer.domain.song_variant import SongVariant


class _FakeEngine:
    def __init__(self) -> None:
        self._playing = False
        self._position = 0.0
        self._duration = 12.0
        self._volume = 1.0
        self._music_volume = 1.0
        self._audio_gain_db = 0.0
        self._mute_music = False
        self.loop_a: float | None = None
        self.loop_b: float | None = None
        self.loop_enabled = False
        self._loop_engage = False
        self.calls: list[tuple] = []

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def position(self) -> float:
        return self._position

    @property
    def duration(self) -> float:
        return self._duration

    def play(self) -> None:
        self.calls.append(("play",))
        self._playing = True

    def pause(self, *, for_scrub: bool = False) -> None:
        self.calls.append(("pause", for_scrub))
        self._playing = False

    def stop(self) -> None:
        self.calls.append(("stop",))
        self._playing = False
        self._position = 0.0

    def seek(self, seconds: float) -> None:
        self.calls.append(("seek", float(seconds)))
        self._position = float(seconds)

    def toggle(self) -> None:
        self.calls.append(("toggle",))
        self._playing = not self._playing

    def nudge(self, delta_seconds: float) -> None:
        self.calls.append(("nudge", float(delta_seconds)))
        self._position = max(0.0, self._position + float(delta_seconds))

    def begin_scrub(self) -> None:
        self.calls.append(("begin_scrub",))
        self._playing = False

    def end_scrub(self) -> None:
        self.calls.append(("end_scrub",))

    def set_volume(self, volume: float) -> None:
        self.calls.append(("set_volume", float(volume)))
        self._volume = float(volume)

    def volume(self) -> float:
        return float(self._volume)

    def set_music_volume(self, volume: float) -> None:
        self.calls.append(("set_music_volume", float(volume)))
        self._music_volume = float(volume)

    def music_volume(self) -> float:
        return float(self._music_volume)

    def set_audio_gain_db(self, gain_db: float) -> None:
        self.calls.append(("set_audio_gain_db", float(gain_db)))
        self._audio_gain_db = float(gain_db)

    def set_music_muted(self, muted: bool) -> None:
        self.calls.append(("set_music_muted", bool(muted)))
        self._mute_music = bool(muted)

    @property
    def music_muted(self) -> bool:
        return bool(self._mute_music)

    def clear_loop(self) -> None:
        self.calls.append(("clear_loop",))
        self.loop_a = None
        self.loop_b = None
        self.loop_enabled = False
        self._loop_engage = False

    def set_loop_enabled(self, enabled: bool) -> None:
        self.calls.append(("set_loop_enabled", bool(enabled)))
        self.loop_enabled = bool(enabled)
        self._loop_engage = bool(enabled)

    def engage_ab_loop(self, *, seek_if_outside: bool = True) -> None:
        self.calls.append(("engage_ab_loop", seek_if_outside))
        self._loop_engage = True


def test_song_session_holds_current_song_and_transport() -> None:
    session = SongSession()
    song = Song.create("A")
    song.duration_seconds = 90.0
    session.set_song(song)
    assert session.current_song is song
    assert session.duration_seconds == 90.0
    session.update_playback_state(playing=True, position_seconds=1.5, duration_seconds=88.0)
    assert session.playing is True
    assert session.position_seconds == 1.5
    assert session.duration_seconds == 88.0


def test_playback_service_delegates_transport_and_syncs_session() -> None:
    session = SongSession()
    song = Song.create("B")
    session.set_song(song)
    engine = _FakeEngine()
    svc = PlaybackService(engine, session)  # type: ignore[arg-type]

    svc.play()
    assert ("play",) in engine.calls
    assert session.playing is True
    assert svc.playing is True

    svc.seek(3.25)
    assert ("seek", 3.25) in engine.calls
    assert session.position_seconds == 3.25

    svc.pause()
    assert session.playing is False

    svc.stop()
    assert ("stop",) in engine.calls
    assert session.position_seconds == 0.0

    svc.toggle()
    assert ("toggle",) in engine.calls


def test_playback_service_set_current_song_does_not_touch_engine() -> None:
    session = SongSession()
    engine = _FakeEngine()
    svc = PlaybackService(engine, session)  # type: ignore[arg-type]
    song = Project.create("P", with_song=True).songs[0]
    svc.set_current_song(song)
    assert session.song is song
    assert engine.calls == []


def test_playback_service_volume_scrub_nudge() -> None:
    session = SongSession()
    engine = _FakeEngine()
    svc = PlaybackService(engine, session)  # type: ignore[arg-type]

    svc.set_volume(0.4)
    assert engine.volume() == 0.4
    svc.set_music_volume(0.55)
    assert engine.music_volume() == 0.55
    svc.set_audio_gain_db(3.0)
    assert ("set_audio_gain_db", 3.0) in engine.calls
    svc.set_music_muted(True)
    assert svc.music_muted is True

    svc.begin_scrub()
    svc.end_scrub()
    assert ("begin_scrub",) in engine.calls
    assert ("end_scrub",) in engine.calls

    engine._position = 5.0
    svc.nudge(-0.5)
    assert session.position_seconds == 4.5


def test_playback_service_loop_region_and_fresh_pair() -> None:
    session = SongSession()
    engine = _FakeEngine()
    svc = PlaybackService(engine, session)  # type: ignore[arg-type]

    svc.set_loop_region(1.0, 4.0)
    assert svc.loop_a == 1.0
    assert svc.loop_b == 4.0
    assert svc.loop_enabled is True
    assert ("engage_ab_loop", False) in engine.calls

    # Fresh-pair: tapping A again clears B when a complete loop exists.
    a = svc.set_loop_a_at(2.5)
    assert a == 2.5
    assert svc.loop_b is None
    assert svc.loop_enabled is False

    svc.set_loop_b_at(5.0)
    assert svc.loop_enabled is True

    assert svc.try_set_loop_enabled(True) is None
    svc.clear_loop()
    assert svc.loop_a is None
    assert svc.try_set_loop_enabled(True) == "Set point A and B first"

    svc.set_loop_region(1.0, 1.005)
    assert svc.try_set_loop_enabled(True) == "A / B are too close together"


def test_resolve_active_audio_path_legacy_tracks(tmp_path: Path) -> None:
    session = SongSession()
    engine = _FakeEngine()
    svc = PlaybackService(engine, session)  # type: ignore[arg-type]
    song = Song.create("曲")
    path = tmp_path / "床.wav"
    song.audio_tracks = [AudioTrack(id="main", name="Main", path=path, role="main")]
    session.set_song(song)
    assert svc.resolve_active_audio_path() == Path(path)
    assert svc.active_variant() is None


def test_resolve_active_audio_path_selected_variant(tmp_path: Path) -> None:
    session = SongSession()
    engine = _FakeEngine()
    svc = PlaybackService(engine, session)  # type: ignore[arg-type]
    song = Song.create("曲")
    track = tmp_path / "track.wav"
    variant_path = tmp_path / "variant.wav"
    song.audio_tracks = [AudioTrack(id="main", name="Main", path=track, role="main")]
    variant = SongVariant.create("Alt", variant_path)
    song.variants = [variant]
    song.selected_variant_id = variant.id
    assert svc.resolve_active_audio_path(song) == Path(variant_path)
    assert svc.active_variant(song) is variant


def test_resolve_active_audio_path_none_without_song() -> None:
    session = SongSession()
    engine = _FakeEngine()
    svc = PlaybackService(engine, session)  # type: ignore[arg-type]
    assert svc.resolve_active_audio_path() is None
    assert svc.active_variant() is None


def test_seek_identity_without_anchor_offset(tmp_path: Path) -> None:
    session = SongSession()
    engine = _FakeEngine()
    svc = PlaybackService(engine, session)  # type: ignore[arg-type]
    song = Song.create("曲")
    path = tmp_path / "a.wav"
    variant = SongVariant.create("Main", path, anchor_offset=0.0)
    song.variants = [variant]
    song.selected_variant_id = variant.id
    session.set_song(song)
    svc.seek(4.0)
    assert ("seek", 4.0) in engine.calls
    assert svc.position == 4.0
    assert session.position_seconds == 4.0


def test_seek_converts_song_time_to_variant_time(tmp_path: Path) -> None:
    session = SongSession()
    engine = _FakeEngine()
    svc = PlaybackService(engine, session)  # type: ignore[arg-type]
    song = Song.create("曲")
    variant = SongVariant.create("Alt", tmp_path / "b.wav", anchor_offset=0.5)
    song.variants = [variant]
    song.selected_variant_id = variant.id
    session.set_song(song)
    svc.seek(10.0)
    assert ("seek", 9.5) in engine.calls
    assert engine._position == 9.5
    assert svc.position == pytest.approx(10.0)
    assert session.position_seconds == pytest.approx(10.0)


def test_loop_region_stores_variant_time_on_engine(tmp_path: Path) -> None:
    session = SongSession()
    engine = _FakeEngine()
    svc = PlaybackService(engine, session)  # type: ignore[arg-type]
    song = Song.create("曲")
    variant = SongVariant.create("Alt", tmp_path / "c.wav", anchor_offset=1.0)
    song.variants = [variant]
    song.selected_variant_id = variant.id
    session.set_song(song)
    svc.set_loop_region(2.0, 5.0)
    assert engine.loop_a == pytest.approx(1.0)
    assert engine.loop_b == pytest.approx(4.0)
    assert svc.loop_a == pytest.approx(2.0)
    assert svc.loop_b == pytest.approx(5.0)


def test_legacy_song_without_variants_seek_unchanged(tmp_path: Path) -> None:
    session = SongSession()
    engine = _FakeEngine()
    svc = PlaybackService(engine, session)  # type: ignore[arg-type]
    song = Song.create("曲")
    song.audio_tracks = [
        AudioTrack(id="main", name="Main", path=tmp_path / "x.wav", role="main")
    ]
    session.set_song(song)
    assert svc.active_anchor_offset() == 0.0
    svc.seek(3.25)
    assert ("seek", 3.25) in engine.calls
    assert svc.position == pytest.approx(3.25)
