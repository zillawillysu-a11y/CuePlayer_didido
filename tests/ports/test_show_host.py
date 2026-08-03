"""Tests for ports.ShowHost (explicit ShowSession host boundary)."""

from __future__ import annotations

import ast
from pathlib import Path

import cueplayer.ports as ports
from cueplayer.domain.models import Project, Song
from cueplayer.ports.show_host import (
    ShowHost,
    ShowHostEngine,
    ShowHostMonitor,
    ShowHostStatus,
    ShowHostTimeline,
    ShowHostTransport,
    ShowHostVideoSync,
)


def test_show_host_exported_from_ports_package() -> None:
    assert "ShowHost" in ports.__all__
    assert ports.ShowHost is ShowHost


def test_show_host_nested_surfaces_are_runtime_checkable() -> None:
    for cls in (
        ShowHost,
        ShowHostEngine,
        ShowHostTimeline,
        ShowHostMonitor,
        ShowHostVideoSync,
        ShowHostTransport,
        ShowHostStatus,
    ):
        assert getattr(cls, "_is_runtime_protocol", False) is True


def test_show_host_module_stays_ports_pure() -> None:
    source = Path("src/cueplayer/ports/show_host.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {
        "cueplayer.ui",
        "cueplayer.playback",
        "cueplayer.media",
        "cueplayer.persistence",
        "cueplayer.exporters",
        "cueplayer.web_remote",
        "cueplayer.application",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not any(
                node.module == pkg or node.module.startswith(pkg + ".")
                for pkg in forbidden
            ), node.module


class _StubEngine:
    playing = False
    duration = 60.0

    def quiesce_output(self) -> None:
        return None

    def set_song(self, song: Song | None) -> None:
        return None

    def set_song_timebase(self, start_timecode: str, fps: float) -> None:
        return None

    def set_buffer(self, buffer: object) -> None:
        return None

    def set_duration(self, seconds: float) -> None:
        return None


class _StubTimeline:
    def clear_selection(self, *, emit: bool = True) -> None:
        return None

    def set_song(self, song: Song | None) -> None:
        return None

    def set_audio(self, audio: object, *, reset_view: bool = True) -> None:
        return None

    def set_audio_loading(self, loading: bool, label: str = "") -> None:
        return None

    def set_ltc_audio(self, audio: object) -> None:
        return None

    def set_show_video_track(self, visible: bool, *, emit: bool = True) -> None:
        return None


class _StubMonitor:
    def set_selected_mark_ids(self, ids: list[str]) -> None:
        return None

    def set_song(self, song: Song | None) -> None:
        return None

    def set_position(self, seconds: float, duration: float) -> None:
        return None


class _StubVideoSync:
    def set_song(self, song: Song | None) -> None:
        return None


class _StubTransport:
    def set_times(self, position: float, duration: float) -> None:
        return None


class _StubStatus:
    def showMessage(self, message: str, timeout: int = 0) -> None:
        return None


class _StubShowHost:
    """Minimal structural implementer of ``ShowHost`` (headless-style)."""

    def __init__(self) -> None:
        self.project = Project.create("Stub", with_song=True)
        self.current_song = self.project.songs[0]
        self.engine = _StubEngine()
        self.timeline = _StubTimeline()
        self.monitor = _StubMonitor()
        self.video_sync = _StubVideoSync()
        self.transport = _StubTransport()
        self.status = _StubStatus()
        self._audio_load_token = 0
        self._song_activate_gen = 0
        self._timeline_ltc_exclude: int | None = None
        self._media_warm_active = False

    def _sync_undo_context(self) -> None:
        return None

    def _sync_loop_ui(self) -> None:
        return None

    def _arm_timeline_audio_loading_placeholder(self, song: Song) -> None:
        return None

    def _apply_project_mark_line_settings(self) -> None:
        return None

    def _sync_timeline_geometry(self) -> None:
        return None

    def _rebuild_digit_shortcuts(self) -> None:
        return None

    def _refresh_output_timecode_clock(self, position: float | None = None) -> None:
        return None

    def _cached_audio_buffer(self, path: Path) -> object | None:
        return None

    def _apply_loaded_audio(
        self,
        buffer: object,
        path: Path,
        *,
        mark_dirty: bool = True,
        replace_track: bool = True,
        refresh_song_widgets: bool = True,
    ) -> None:
        return None

    def _apply_probed_audio_duration(self, path: Path, *, song: Song | None = None) -> None:
        return None

    def _load_audio_path(
        self,
        path: Path,
        *,
        mark_dirty: bool = True,
        replace_track: bool = True,
        bump_token: bool = True,
        keep_waveform: bool = False,
    ) -> None:
        return None

    def _schedule_video_music_standin(self) -> None:
        return None

    def _refresh_window_title(self) -> None:
        return None

    def _refresh_status(self) -> None:
        return None

    def _sync_timeline_overview(self) -> None:
        return None

    def _ensure_video_preview_frame(self) -> None:
        return None


def test_stub_host_satisfies_show_host_protocol() -> None:
    host = _StubShowHost()
    assert isinstance(host, ShowHost)
    assert isinstance(host.engine, ShowHostEngine)
    assert isinstance(host.timeline, ShowHostTimeline)
