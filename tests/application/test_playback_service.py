"""Unit tests for domain SongSession and application PlaybackService."""

from __future__ import annotations

from cueplayer.application.playback_service import PlaybackService
from cueplayer.domain.models import Project, Song
from cueplayer.domain.song_session import SongSession


class _FakeEngine:
    def __init__(self) -> None:
        self._playing = False
        self._position = 0.0
        self._duration = 12.0
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
