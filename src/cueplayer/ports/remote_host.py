"""Web Remote host boundary.

Web Remote (``web_remote.bridge``) must talk only through this surface —
never MainWindow private ``_`` attributes.

Design notes
------------
**Why this port exists**
- Explicit, typed boundary for LAN remote clients (today: one HTTP/WebRTC bridge).
- Enables alternate remote clients / headless hosts without duck-typing UI.

**Subsystem ownership (who implements the behavior behind each member)**
- Domain project/song reads → Project / Song (UI session)
- Playback clock + transport / mute / loop → AudioEngine (+ PlaybackService for loops)
- Song activate / setlist refresh → ShowSessionService / MainWindow setlist helpers
- Marks / undo / dirty → MainWindow mark editing helpers
- Waveform / listen buffers → timeline display + media caches (host-owned)
- Display / timecode chrome → cue monitor + project flags
- Audio output toggles → project.audio_output + audio_prefs + engine.apply

**Intentionally excluded**
- Full MainWindow (menus, dialogs, BPM jobs, export, settings dialogs)
- ShowSession internals / ShowHost private loader tokens
- EventBus
- Networking (HTTP/WebRTC stay in ``web_remote``)
- Redesigning Remote feature set (ops remain the same; only the call path changes)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from cueplayer.domain.models import Project, Song
from cueplayer.ports.clock import PlaybackClock


@runtime_checkable
class RemoteEnginePort(Protocol):
    """Public playback-engine surface needed for remote state / transport.

    Why: remote polls position/duration/loops and issues seek/play without
    importing ``AudioEngine``. Subsystem: playback adapter (AudioEngine today).
    """

    playing: bool
    position: float
    duration: float
    loop_a: float | None
    loop_b: float | None
    loop_enabled: bool
    buffer: Any
    music_muted: bool

    def play(self) -> None:
        ...

    def pause(self, *, for_scrub: bool = False) -> None:
        ...

    def seek(self, seconds: float) -> None:
        ...

    def set_music_muted(self, muted: bool) -> None:
        ...

    def apply_audio_settings(self, settings: Any) -> str | None:
        ...

    def output_timecode_state(self, position: float) -> Any:
        ...


@runtime_checkable
class RemoteHost(Protocol):
    """Public host API exposed to the LAN Web Remote bridge."""

    # --- identity / domain ---------------------------------------------------

    @property
    def project(self) -> Project:
        """Active show project. Owner: UI session / ProjectService path."""
        ...

    @property
    def current_song(self) -> Song:
        """Song on the timeline. Owner: domain SongSession via MainWindow."""
        ...

    def get_playback_clock(self) -> PlaybackClock:
        """Sole sample clock. Owner: AudioEngine."""
        ...

    def get_project(self) -> Project | None:
        """Optional project accessor (compat). Owner: UI session."""
        ...

    def get_current_song(self) -> Song | None:
        """Optional song accessor (compat). Owner: SongSession."""
        ...

    @property
    def engine(self) -> RemoteEnginePort:
        """Typed engine surface for remote state builders. Owner: playback."""
        ...

    # --- dirty / chrome refresh ----------------------------------------------

    def mark_dirty(self) -> None:
        """Mark project dirty. Owner: ProjectService via MainWindow."""
        ...

    def refresh_marks_ui(self) -> None:
        """Repaint marks / cue list. Owner: MainWindow mark UI."""
        ...

    def refresh_output_timecode_clock(self) -> None:
        """Refresh LTC/MTC clock widget. Owner: MainWindow timecode chrome."""
        ...

    def refresh_timecode_status(self) -> None:
        """Refresh TC status line. Owner: MainWindow timecode chrome."""
        ...

    def show_status(self, message: str, timeout_ms: int = 2500) -> None:
        """Status-bar message. Owner: MainWindow status bar."""
        ...

    # --- loop (UI chrome + engine) -------------------------------------------

    def set_loop_a(self) -> None:
        """Mark A at playhead. Owner: PlaybackService / MainWindow loop UI."""
        ...

    def set_loop_b(self) -> None:
        """Mark B at playhead. Owner: PlaybackService / MainWindow loop UI."""
        ...

    def clear_loop(self) -> None:
        """Clear A–B loop. Owner: PlaybackService / MainWindow loop UI."""
        ...

    def set_loop_enabled(self, enabled: bool) -> None:
        """Enable/disable A–B loop. Owner: PlaybackService / MainWindow."""
        ...

    # --- setlist / activate --------------------------------------------------

    def activate_song(self, index: int, *, stop_playback: bool = False) -> None:
        """Activate setlist song. Owner: ShowSessionService."""
        ...

    def rebuild_song_list(self, select_indexes: list[int] | None = None) -> None:
        """Refresh setlist table selection. Owner: MainWindow setlist UI."""
        ...

    def selected_song_indexes(self) -> list[int]:
        """Current setlist selection indexes. Owner: MainWindow setlist UI."""
        ...

    # --- marks / lanes -------------------------------------------------------

    def add_mark(self, lane_index: int) -> None:
        """Add mark on lane at playhead. Owner: MainWindow mark editing."""
        ...

    def delete_marks(self, mark_ids: list[str]) -> None:
        """Delete marks by id. Owner: MainWindow mark editing."""
        ...

    def on_note_changed(self, mark_id: str, old: str, new: str) -> None:
        """Persist note edit + undo. Owner: MainWindow mark editing."""
        ...

    def on_cue_id_changed(self, mark_id: str, old_id: str, new_id: str) -> None:
        """Persist cue-id edit + undo. Owner: MainWindow mark editing."""
        ...

    def push_song_undo(self, command: Any) -> None:
        """Push undo command for current song. Owner: MainWindow undo stack."""
        ...

    def rebuild_digit_shortcuts(self) -> None:
        """Rebuild digit hotkeys after lane shortcut edits. Owner: MainWindow."""
        ...

    def apply_timeline_song_display_settings(self) -> None:
        """Apply lane display flags to timeline. Owner: timeline widget."""
        ...

    def apply_now_display_settings(self) -> None:
        """Apply NOW card visibility. Owner: cue monitor."""
        ...

    def configure_output_timecode_clock(self, *, visible: bool, color: str) -> None:
        """Show/hide output TC clock. Owner: cue monitor."""
        ...

    def configure_output_quick_toggles(self, *, visible: bool) -> None:
        """Show/hide output quick toggles. Owner: cue monitor."""
        ...

    def sync_output_quick_toggles(self, audio_output: Any) -> None:
        """Sync toggle chips to audio settings. Owner: cue monitor."""
        ...

    # --- waveform / listen helpers (host-owned caches) -----------------------

    def song_has_main_audio_file(self) -> bool:
        """True when current song has a resolvable main music file."""
        ...

    def timeline_display_audio(self) -> Any:
        """Music-lane display buffer (may be video stand-in). Owner: timeline."""
        ...

    def video_standin_buffer(self) -> Any:
        """RAM video-audio stand-in if present. Owner: MainWindow stand-in cache."""
        ...

    def schedule_video_music_standin(self) -> None:
        """Nudge desktop to build video Music-lane stand-in."""
        ...

    def ltc_channel_for_song(self, song: Song) -> int | None:
        """Detected/file LTC channel index for waveform strip. Owner: MainWindow."""
        ...

    def main_audio_path_for_song(self, song: Song) -> Path | None:
        """Main music path for song, if any. Owner: MainWindow media helpers."""
        ...

    def waveform_for_timeline(self, buffer: Any, path: Path, exclude: int | None) -> Any:
        """LTC-stripped waveform buffer for display. Owner: MainWindow."""
        ...

    def timeline_audio_loading(self) -> bool:
        """True while Music lane shows Loading. Owner: timeline."""
        ...

    def video_listen_stereo(
        self, start_seconds: float, out_frames: int, out_rate: int
    ) -> Any:
        """Video-clip stereo chunk for remote listen (no music file). Owner: mixer."""
        ...

    def video_listen_unavailable_reason(self) -> str:
        """Client reason when video listen is not ready (muted / no clip / decoding)."""
        ...

    def current_song_has_video_clips(self) -> bool:
        """True when the active song has timeline video clips (listen / preview)."""
        ...

    def playback_sample_rate(self) -> int:
        """Engine playback rate used for video listen resampling."""
        ...

    def sync_video_output_active(self) -> None:
        """Keep desktop decode alive while remote preview is wanted."""
        ...
