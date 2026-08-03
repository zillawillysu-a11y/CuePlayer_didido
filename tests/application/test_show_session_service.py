"""Unit tests for application.ShowSessionService."""

from __future__ import annotations

import importlib
import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock

from cueplayer.application.playback_service import PlaybackService
from cueplayer.application.show_session_service import ShowSessionService
from cueplayer.domain.models import Project, Song
from cueplayer.domain.song_session import SongSession


class _FakeEngine:
    def __init__(self) -> None:
        self.playing = False
        self._duration = 60.0
        self.calls: list[tuple] = []
        self._song = None
        self.loop_a = None
        self.loop_b = None
        self.loop_enabled = False
        self._loop_engage = False
        self._playing = False
        self._position = 0.0

    @property
    def duration(self) -> float:
        return self._duration

    @property
    def position(self) -> float:
        return self._position

    def quiesce_output(self) -> None:
        self.calls.append(("quiesce_output",))

    def set_song(self, song) -> None:  # noqa: ANN001
        self.calls.append(("set_song", song))
        self._song = song

    def set_song_timebase(self, start_timecode: str, fps: float) -> None:
        self.calls.append(("set_song_timebase", start_timecode, fps))

    def set_buffer(self, buffer) -> None:  # noqa: ANN001
        self.calls.append(("set_buffer", buffer))

    def set_duration(self, seconds: float) -> None:
        self.calls.append(("set_duration", seconds))
        self._duration = float(seconds)

    def clear_loop(self) -> None:
        self.calls.append(("clear_loop",))
        self.loop_a = None
        self.loop_b = None
        self.loop_enabled = False
        self._loop_engage = False


def _make_host(project: Project) -> SimpleNamespace:
    engine = _FakeEngine()
    session = SongSession()
    blank = Song.create("Untitled Song")
    if project.songs:
        session.set_song(project.songs[0])
    playback = PlaybackService(engine, session)  # type: ignore[arg-type]
    host = SimpleNamespace(
        project=project,
        engine=engine,
        playback=playback,
        timeline=MagicMock(),
        monitor=MagicMock(),
        video_sync=MagicMock(),
        transport=MagicMock(),
        status=MagicMock(),
        _audio_load_token=0,
        _song_activate_gen=0,
        _media_warm_active=False,
        _timeline_ltc_exclude=None,
        _blank_song=blank,
        _song_session=session,
        current_song=project.songs[0] if project.songs else blank,
    )
    host._sync_undo_context = MagicMock()
    host._sync_loop_ui = MagicMock()
    host._arm_timeline_audio_loading_placeholder = MagicMock()
    host._apply_project_mark_line_settings = MagicMock()
    host._sync_timeline_geometry = MagicMock()
    host._rebuild_digit_shortcuts = MagicMock()
    host._refresh_output_timecode_clock = MagicMock()
    host._cached_audio_buffer = MagicMock(return_value=None)
    host._apply_loaded_audio = MagicMock()
    host._apply_probed_audio_duration = MagicMock()
    host._load_audio_path = MagicMock()
    host._schedule_video_music_standin = MagicMock()
    host._refresh_window_title = MagicMock()
    host._refresh_status = MagicMock()
    host._sync_timeline_overview = MagicMock()
    host._ensure_video_preview_frame = MagicMock()
    return host


def test_show_session_service_boundary_imports() -> None:
    source = inspect.getsource(
        importlib.import_module("cueplayer.application.show_session_service")
    )
    assert "from cueplayer.ui" not in source
    assert "import cueplayer.ui" not in source
    assert "from cueplayer.application.project_service" not in source
    assert "from cueplayer.application.settings_service" not in source
    assert "from cueplayer.application.event_bus" not in source
    assert "import cueplayer.application.event_bus" not in source


def test_activate_song_at_quiesces_and_prepares(monkeypatch) -> None:  # noqa: ANN001
    project = Project.create("P", with_song=True)
    project.songs.append(project.new_song("Second"))
    host = _make_host(project)
    # Avoid Path.is_file hitting disk — force no-main-audio branch via empty tracks.
    project.songs[1].audio_tracks.clear()
    svc = ShowSessionService(host, host.playback)

    called: list[str] = []
    monkeypatch.setattr(svc, "notify_external_sync", lambda: called.append("ext"))

    svc.activate_song_at(1, stop_playback=True)

    assert ("quiesce_output",) in host.engine.calls
    assert host.current_song is project.songs[1]
    assert any(c[0] == "set_song" for c in host.engine.calls)
    assert any(c[0] == "set_song_timebase" for c in host.engine.calls)
    host.timeline.set_song.assert_called()
    host.video_sync.set_song.assert_called_with(project.songs[1])
    host._schedule_video_music_standin.assert_called_once()
    host.playback.clear_loop  # noqa: B018 — attribute exists
    assert called == ["ext"]


def test_deactivate_and_empty_workspace() -> None:
    project = Project.create("P", with_song=False)
    host = _make_host(project)
    svc = ShowSessionService(host, host.playback)
    svc.apply_empty_workspace()
    host.timeline.set_song.assert_called_with(None)
    host.video_sync.set_song.assert_called_with(None)
    host.monitor.set_song.assert_called_with(None)
    assert ("set_song", None) in host.engine.calls
    host._rebuild_digit_shortcuts.assert_called()


def test_prepare_playback_only_attaches_engine() -> None:
    project = Project.create("P", with_song=True)
    host = _make_host(project)
    svc = ShowSessionService(host, host.playback)
    song = project.songs[0]
    song.start_timecode = "01:02:03:04"
    song.fps = 25.0
    host.engine.calls.clear()
    svc.prepare_playback(song)
    assert ("set_song", song) in host.engine.calls
    assert ("set_song_timebase", "01:02:03:04", 25.0) in host.engine.calls


def test_refresh_waveform_loads_selected_variant_path(tmp_path) -> None:  # noqa: ANN001
    from pathlib import Path

    from cueplayer.domain.models import AudioTrack
    from cueplayer.domain.song_variant import SongVariant

    project = Project.create("P", with_song=True)
    host = _make_host(project)
    svc = ShowSessionService(host, host.playback)
    song = project.songs[0]
    track = tmp_path / "track.wav"
    variant_path = tmp_path / "variant.wav"
    track.write_bytes(b"x")
    variant_path.write_bytes(b"y")
    song.audio_tracks = [AudioTrack(id="main", name="Main", path=track, role="main")]
    variant = SongVariant.create("Alt", variant_path)
    song.variants = [variant]
    song.selected_variant_id = variant.id
    host.current_song = song
    host.playback.session.set_song(song)

    svc.refresh_waveform()

    host._load_audio_path.assert_called()
    args, kwargs = host._load_audio_path.call_args
    assert Path(args[0]) == Path(variant_path)
    assert kwargs.get("replace_track") is False
