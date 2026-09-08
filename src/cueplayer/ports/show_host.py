"""Show-session host boundary (UI / headless surfaces for activation).

``ShowSessionService`` coordinates song activate/deactivate against this
port — not against an implicit duck-typed ``MainWindow``.

Design notes
------------
**Why this port exists**
- Explicit boundary for activate orchestration (static typing + alternate hosts).
- Keeps widget/cache/loader ownership outside the application service.

**Intentionally excluded from this Protocol**
- Full ``MainWindow`` surface (menus, dialogs, undo stacks, setlist edits, BPM,
  media-warm jobs, RemoteHost bridge, settings UI, export).
- Transport play/pause/seek/volume (``PlaybackService`` / ``PlaybackClock``).
- Project new/open/save (``ProjectService``).
- Machine QSettings (``SettingsService``).
- Optional video-track QAction sync (``getattr(host, "_show_video_track_action")``)
  remains a soft optional on the host — not required for activate correctness.

Nested surface Protocols list only methods ``ShowSessionService`` actually calls.
Private ``_`` members mirror today's MainWindow names so the service body stays
unchanged (no redesign this task).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from cueplayer.domain.models import Project, Song


@runtime_checkable
class ShowHostEngine(Protocol):
    """Sample-clock / mix attach surface used during activate/deactivate.

    Why: service must quiesce output, attach song/timebase, and clear buffers
    without importing ``AudioEngine``.
    """

    playing: bool
    duration: float

    def quiesce_output(self) -> None:
        """Stop PortAudio + video decode before swapping song media."""
        ...

    def set_song(self, song: Song | None) -> None:
        """Attach or clear the active song on the clock / mixer."""
        ...

    def set_song_timebase(self, start_timecode: str, fps: float) -> None:
        """Align LTC/MTC timebase to the song."""
        ...

    def set_buffer(self, buffer: Any) -> None:
        """Install or clear the PCM buffer (``None`` while loading)."""
        ...

    def set_duration(self, seconds: float) -> None:
        """Set timeline length when no buffer is armed."""
        ...


@runtime_checkable
class ShowHostTimeline(Protocol):
    """Timeline / waveform lane surface for song + audio display.

    Why: activate must re-bind song, clear selection, and arm waveform/LTC
    placeholders without owning timeline paint code.
    """

    def clear_selection(self, *, emit: bool = True) -> None:
        ...

    def set_song(self, song: Song | None) -> None:
        ...

    def set_audio(self, audio: Any, *, reset_view: bool = True) -> None:
        ...

    def set_audio_loading(self, loading: bool, label: str = "") -> None:
        ...

    def set_ltc_audio(self, audio: Any) -> None:
        ...

    def set_show_video_track(self, visible: bool, *, emit: bool = True) -> None:
        ...


@runtime_checkable
class ShowHostMonitor(Protocol):
    """Cue / NOW monitor surface.

    Why: selection clear + deferred ``set_song`` + transport position display.
    """

    def set_selected_mark_ids(self, ids: list[str]) -> None:
        ...

    def set_song(self, song: Song | None) -> None:
        ...

    def set_position(self, seconds: float, duration: float) -> None:
        ...


@runtime_checkable
class ShowHostVideoSync(Protocol):
    """Sample-locked video controller surface.

    Why: video must follow the same song attach as the audio clock.
    """

    def set_song(self, song: Song | None) -> None:
        ...


@runtime_checkable
class ShowHostTransport(Protocol):
    """Transport time readout surface (not play/pause control)."""

    def set_times(self, position: float, duration: float) -> None:
        ...


@runtime_checkable
class ShowHostStatus(Protocol):
    """Status-bar messaging during waveform load / missing media."""

    def showMessage(self, message: str, timeout: int = 0) -> None:
        ...


@runtime_checkable
class ShowHost(Protocol):
    """Minimal host required by ``ShowSessionService``.

    Implemented today by ``ui.main_window.MainWindow``. Future hosts may include
    Web UI, Remote UI, or headless runners that supply the same surfaces.
    """

    # --- domain / session state ----------------------------------------------

    project: Project
    """Active show project (setlist + ``show_video_track`` flag)."""

    current_song: Song
    """Song currently bound to the session (may be a blank stand-in)."""

    # --- surfaces ------------------------------------------------------------

    engine: ShowHostEngine
    """Sole sample clock / mix attach point."""

    timeline: ShowHostTimeline
    """Timeline + Music-lane waveform surface."""

    monitor: ShowHostMonitor
    """Cue list / NOW monitor."""

    video_sync: ShowHostVideoSync
    """Sample-locked video output controller."""

    transport: ShowHostTransport
    """Transport time labels (not PlaybackService transport buttons)."""

    status: ShowHostStatus
    """Status bar for load / missing-file messages."""

    # --- activate generation / load tokens (host-owned) ----------------------

    _audio_load_token: int
    """Bump cancels in-flight UI audio loads when switching songs."""

    _song_activate_gen: int
    """Generation counter so deferred monitor set_song can be ignored."""

    _timeline_ltc_exclude: int | None
    """LTC channel excluded from Music-lane display while loading."""

    _media_warm_active: bool
    """When True, suppress redundant waveform status spam during warm."""

    # --- host helpers (names match MainWindow; no redesign this task) --------

    def _sync_undo_context(self) -> None:
        """Keep undo stack pointed at the newly current song."""
        ...

    def _sync_loop_ui(self) -> None:
        """Mirror engine A–B loop state onto transport + timeline chrome."""
        ...

    def _arm_timeline_audio_loading_placeholder(self, song: Song) -> None:
        """Show Loading on Music lane before ``set_song`` paints empty."""
        ...

    def _apply_project_mark_line_settings(self) -> None:
        """Apply project mark-line chrome to the timeline."""
        ...

    def _push_ltc_mode_to_timeline(self) -> None:
        """Sync the timeline's LTC source mode from the active song (display)."""
        ...

    def _sync_timeline_geometry(self) -> None:
        """Relayout timeline after video-track visibility / song swap."""
        ...

    def _rebuild_digit_shortcuts(self) -> None:
        """Rebuild mark hotkeys for the active song's lanes."""
        ...

    def _refresh_output_timecode_clock(self, position: float | None = None) -> None:
        """Refresh LTC/MTC output clock readout after seek/reset."""
        ...

    def _cached_audio_buffer(self, path: Path) -> Any:
        """Return RAM-cached PCM for ``path``, or ``None`` (never sync-load)."""
        ...

    def _apply_loaded_audio(
        self,
        buffer: Any,
        path: Path,
        *,
        mark_dirty: bool = True,
        replace_track: bool = True,
        refresh_song_widgets: bool = True,
    ) -> None:
        """Apply a ready PCM buffer to engine + timeline."""
        ...

    def _apply_probed_audio_duration(self, path: Path, *, song: Song | None = None) -> None:
        """Probe duration for UI while full PCM is still loading."""
        ...

    def _load_audio_path(
        self,
        path: Path,
        *,
        mark_dirty: bool = True,
        replace_track: bool = True,
        bump_token: bool = True,
        keep_waveform: bool = False,
    ) -> None:
        """Async-load PCM for playback; host owns executors / tokens."""
        ...

    def _schedule_video_music_standin(self) -> None:
        """When no music file, schedule embedded video-audio Music-lane stand-in."""
        ...

    def _refresh_window_title(self) -> None:
        """Update window title for the active song / dirty state."""
        ...

    def _refresh_status(self) -> None:
        """Refresh status-bar song / mark summary."""
        ...

    def _sync_timeline_overview(self) -> None:
        """Sync overview strip after song / duration changes."""
        ...

    def _ensure_video_preview_frame(self) -> None:
        """Ensure video preview shows a frame for the new song position."""
        ...
