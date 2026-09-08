"""RemoteHost boundary: bridge must not duck-type MainWindow privates."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from cueplayer.ports.remote_host import RemoteEnginePort, RemoteHost
from cueplayer.web_remote.main_window_remote_host import MainWindowRemoteHost


ROOT = Path(__file__).resolve().parents[2]
BRIDGE = ROOT / "src" / "cueplayer" / "web_remote" / "bridge.py"
ADAPTER = ROOT / "src" / "cueplayer" / "web_remote" / "main_window_remote_host.py"


def test_bridge_has_no_host_private_attribute_access() -> None:
    source = BRIDGE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    banned: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            # Allow self._* (bridge internals) and module-level privates.
            if isinstance(node.value, ast.Name) and node.value.id == "host":
                banned.append(f"host.{node.attr}")
            if (
                isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "self"
                and node.value.attr == "_host"
                and node.attr.startswith("_")
            ):
                banned.append(f"self._host.{node.attr}")
    assert banned == [], f"bridge still touches host privates: {banned}"


def test_bridge_has_no_engine_private_attribute_access() -> None:
    source = BRIDGE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    banned: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or not node.attr.startswith("_"):
            continue
        # engine._video_mixer / _playback_rate / _song
        if isinstance(node.value, ast.Name) and node.value.id == "engine":
            banned.append(f"engine.{node.attr}")
    assert banned == [], f"bridge still touches engine privates: {banned}"


def test_bridge_does_not_reference_monitor_timeline_status_attrs() -> None:
    source = BRIDGE.read_text(encoding="utf-8")
    for needle in ("host.monitor.", "host.timeline.", "host.status."):
        assert needle not in source


def test_adapter_file_is_the_only_main_window_private_shim() -> None:
    assert ADAPTER.is_file()
    source = ADAPTER.read_text(encoding="utf-8")
    assert "_mark_dirty" in source
    assert "MainWindowRemoteHost" in source


def test_remote_host_protocols_are_runtime_checkable() -> None:
    assert getattr(RemoteHost, "_is_runtime_protocol", False) is True
    assert getattr(RemoteEnginePort, "_is_runtime_protocol", False) is True


def test_bridge_transport_seek_uses_song_time_api() -> None:
    """Bridge must not call engine.seek — Song Time goes through RemoteHost."""
    source = BRIDGE.read_text(encoding="utf-8")
    assert "engine.seek(" not in source
    assert "host.engine.seek(" not in source
    assert "seek_song_time" in source
    assert "song_position" in source


def test_main_window_remote_host_seek_song_time_maps_offset(tmp_path) -> None:  # noqa: ANN001
    from pathlib import Path
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from cueplayer.application.playback_service import PlaybackService
    from cueplayer.domain.models import Song
    from cueplayer.domain.song_session import SongSession
    from cueplayer.domain.song_variant import SongVariant

    class _Eng:
        def __init__(self) -> None:
            self.calls: list[tuple] = []
            self._position = 0.0
            self.playing = False
            self.duration = 60.0
            self.loop_a = None
            self.loop_b = None
            self.loop_enabled = False

        @property
        def position(self) -> float:
            return self._position

        def seek(self, seconds: float) -> None:
            self.calls.append(("seek", float(seconds)))
            self._position = float(seconds)

        def play(self) -> None:
            self.playing = True

        def pause(self, *, for_scrub: bool = False) -> None:
            self.playing = False

        def nudge(self, delta: float) -> None:
            self.seek(self._position + float(delta))

        def clear_loop(self) -> None:
            self.loop_a = self.loop_b = None
            self.loop_enabled = False

        def set_loop_enabled(self, enabled: bool) -> None:
            self.loop_enabled = bool(enabled)

        def engage_ab_loop(self, *, seek_if_outside: bool = True) -> None:
            pass

    engine = _Eng()
    session = SongSession()
    playback = PlaybackService(engine, session)  # type: ignore[arg-type]
    song = Song.create("曲")
    variant = SongVariant.create("Alt", Path(tmp_path) / "a.wav", anchor_offset=0.5)
    song.variants = [variant]
    song.selected_variant_id = variant.id
    session.set_song(song)
    window = SimpleNamespace(playback=playback, engine=engine, project=MagicMock(), current_song=song)
    host = MainWindowRemoteHost(window)
    host.seek_song_time(10.0)
    assert ("seek", 9.5) in engine.calls
    assert host.song_position() == pytest.approx(10.0)
    assert host.song_to_engine_time(10.0) == pytest.approx(9.5)
