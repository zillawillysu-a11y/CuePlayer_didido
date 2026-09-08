"""Tapping A/B with a complete pair starts a fresh loop."""

from __future__ import annotations

from cueplayer.application.playback_service import PlaybackService
from cueplayer.domain.song_session import SongSession
from cueplayer.ui.main_window import MainWindow


class _FakeTimeline:
    def __init__(self, seconds: float) -> None:
        self._seconds = seconds

    def playhead_seconds(self) -> float:
        return self._seconds


class _FakeEngine:
    def __init__(self) -> None:
        self.loop_a: float | None = None
        self.loop_b: float | None = None
        self.loop_enabled = False
        self._loop_engage = False
        self._playing = False
        self._position = 0.0
        self._duration = 60.0

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def position(self) -> float:
        return self._position

    @property
    def duration(self) -> float:
        return self._duration

    def engage_ab_loop(self, *, seek_if_outside: bool = True) -> None:
        del seek_if_outside
        self._loop_engage = True


class _Host:
    def __init__(self, engine: _FakeEngine, seconds: float) -> None:
        self.engine = engine
        self.playback = PlaybackService(engine, SongSession())  # type: ignore[arg-type]
        self.timeline = _FakeTimeline(seconds)
        self.status = type("S", (), {"showMessage": staticmethod(lambda *a, **k: None)})()

    def _sync_loop_ui(self) -> None:
        return None


def test_set_loop_a_with_complete_pair_clears_b() -> None:
    engine = _FakeEngine()
    engine.loop_a = 10.0
    engine.loop_b = 20.0
    engine.loop_enabled = True
    engine._loop_engage = True
    host = _Host(engine, 40.0)

    MainWindow._set_loop_a(host)  # type: ignore[arg-type]

    assert engine.loop_a == 40.0
    assert engine.loop_b is None
    assert engine.loop_enabled is False


def test_set_loop_b_with_complete_pair_clears_a() -> None:
    engine = _FakeEngine()
    engine.loop_a = 10.0
    engine.loop_b = 20.0
    engine.loop_enabled = True
    engine._loop_engage = True
    host = _Host(engine, 5.0)

    MainWindow._set_loop_b(host)  # type: ignore[arg-type]

    assert engine.loop_b == 5.0
    assert engine.loop_a is None
    assert engine.loop_enabled is False


def test_set_loop_b_after_a_only_forms_pair() -> None:
    engine = _FakeEngine()
    engine.loop_a = 10.0
    host = _Host(engine, 25.0)

    MainWindow._set_loop_b(host)  # type: ignore[arg-type]

    assert engine.loop_a == 10.0
    assert engine.loop_b == 25.0
    assert engine.loop_enabled is True
    assert engine._loop_engage is True
