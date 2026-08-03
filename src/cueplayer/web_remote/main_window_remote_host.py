"""Adapter: MainWindow → ports.RemoteHost (all private access stays here)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cueplayer.domain.models import Project, Song
from cueplayer.ports.clock import PlaybackClock
from cueplayer.ports.remote_host import RemoteEnginePort, RemoteHost


class MainWindowRemoteHost:
    """Structural ``RemoteHost`` wrapping ``MainWindow`` without exposing it to bridge."""

    def __init__(self, window: Any) -> None:
        self._window = window

    # --- identity ------------------------------------------------------------

    @property
    def project(self) -> Project:
        return self._window.project

    @property
    def current_song(self) -> Song:
        return self._window.current_song

    def get_playback_clock(self) -> PlaybackClock:
        return self._window.engine

    def get_project(self) -> Project | None:
        return self._window.project

    def get_current_song(self) -> Song | None:
        return self._window.current_song

    @property
    def engine(self) -> RemoteEnginePort:
        return self._window.engine

    # --- dirty / chrome ------------------------------------------------------

    def mark_dirty(self) -> None:
        self._window._mark_dirty()

    def refresh_marks_ui(self) -> None:
        self._window._refresh_marks_ui()

    def refresh_output_timecode_clock(self) -> None:
        self._window._refresh_output_timecode_clock()

    def refresh_timecode_status(self) -> None:
        self._window._refresh_timecode_status()

    def show_status(self, message: str, timeout_ms: int = 2500) -> None:
        self._window.status.showMessage(message, timeout_ms)

    # --- loop ----------------------------------------------------------------

    def set_loop_a(self) -> None:
        self._window._set_loop_a()

    def set_loop_b(self) -> None:
        self._window._set_loop_b()

    def clear_loop(self) -> None:
        self._window._clear_loop()

    def set_loop_enabled(self, enabled: bool) -> None:
        self._window._set_loop_enabled(enabled)

    # --- setlist -------------------------------------------------------------

    def activate_song(self, index: int, *, stop_playback: bool = False) -> None:
        self._window._activate_song(index, stop_playback=stop_playback)

    def rebuild_song_list(self, select_indexes: list[int] | None = None) -> None:
        self._window._rebuild_song_list(select_indexes=select_indexes)

    def selected_song_indexes(self) -> list[int]:
        return list(self._window._selected_song_indexes() or [])

    # --- marks ---------------------------------------------------------------

    def add_mark(self, lane_index: int) -> None:
        self._window._add_mark(lane_index)

    def delete_marks(self, mark_ids: list[str]) -> None:
        self._window._delete_marks(mark_ids)

    def on_note_changed(self, mark_id: str, old: str, new: str) -> None:
        self._window._on_note_changed(mark_id, old, new)

    def on_cue_id_changed(self, mark_id: str, old_id: str, new_id: str) -> None:
        self._window._on_cue_id_changed(mark_id, old_id, new_id)

    def push_song_undo(self, command: Any) -> None:
        self._window._push_song_undo(command)

    def rebuild_digit_shortcuts(self) -> None:
        self._window._rebuild_digit_shortcuts()

    def apply_timeline_song_display_settings(self) -> None:
        self._window.timeline.apply_song_display_settings()

    def apply_now_display_settings(self) -> None:
        self._window.monitor.apply_now_display_settings()

    def configure_output_timecode_clock(self, *, visible: bool, color: str) -> None:
        self._window.monitor.configure_output_timecode_clock(
            visible=visible, color=color
        )

    def configure_output_quick_toggles(self, *, visible: bool) -> None:
        self._window.monitor.configure_output_quick_toggles(visible=visible)

    def sync_output_quick_toggles(self, audio_output: Any) -> None:
        self._window.monitor.sync_output_quick_toggles(audio_output)

    # --- waveform / listen ---------------------------------------------------

    def song_has_main_audio_file(self) -> bool:
        return bool(self._window._song_has_main_audio_file())

    def timeline_display_audio(self) -> Any:
        timeline = getattr(self._window, "timeline", None)
        if timeline is None:
            return None
        display = getattr(timeline, "_audio", None)
        if (
            display is not None
            and getattr(display, "peak_levels", None)
            and getattr(display, "mono", None) is not None
        ):
            return display
        return None

    def video_standin_buffer(self) -> Any:
        window = self._window
        cache = getattr(window, "_video_standin_cache", None)
        clip_fn = getattr(window, "_primary_video_clip_for_standin", None)
        key_fn = getattr(window, "_video_standin_cache_key", None)
        if not cache or not callable(clip_fn) or not callable(key_fn):
            return None
        clip = clip_fn()
        if clip is None:
            return None
        key = key_fn(
            clip,
            timeline_duration=float(window.current_song.duration_seconds),
        )
        if key is None or key not in cache:
            return None
        return cache[key]

    def schedule_video_music_standin(self) -> None:
        self._window._schedule_video_music_standin()

    def ltc_channel_for_song(self, song: Song) -> int | None:
        return self._window._ltc_channel_for_song(song)

    def main_audio_path_for_song(self, song: Song) -> Path | None:
        return self._window._main_audio_path_for_song(song)

    def waveform_for_timeline(self, buffer: Any, path: Path, exclude: int | None) -> Any:
        return self._window._waveform_for_timeline(buffer, path, exclude)

    def timeline_audio_loading(self) -> bool:
        timeline = getattr(self._window, "timeline", None)
        if timeline is None:
            return False
        loader = getattr(timeline, "audio_loading", None)
        return bool(callable(loader) and loader())

    def video_listen_stereo(
        self, start_seconds: float, out_frames: int, out_rate: int
    ) -> Any:
        import numpy as np

        engine = self._window.engine
        mixer = getattr(engine, "_video_mixer", None)
        if mixer is None or bool(getattr(mixer, "muted", False)):
            return None
        song = getattr(engine, "_song", None)
        clips = list(getattr(song, "video_clips", None) or []) if song is not None else []
        if not clips:
            return None
        play_sr = int(getattr(engine, "_playback_rate", 0) or 0)
        if play_sr <= 0:
            play_sr = max(1, int(out_rate))
        dur = float(out_frames) / float(max(1, int(out_rate)))
        n_play = int(max(1, round(dur * float(play_sr))))
        start_frame = int(max(0, round(float(start_seconds) * float(play_sr))))
        try:
            stereo = mixer.chunk_at(start_frame, n_play)
        except Exception:  # noqa: BLE001
            return None
        if stereo is None:
            return None
        arr = np.asarray(stereo, dtype=np.float32)
        if arr.size == 0:
            return None
        return arr

    def video_listen_unavailable_reason(self) -> str:
        engine = self._window.engine
        mixer = getattr(engine, "_video_mixer", None)
        song = getattr(engine, "_song", None)
        has_clips = bool(getattr(song, "video_clips", None) or [])
        if mixer is not None and bool(getattr(mixer, "muted", False)):
            return "video_muted"
        if not has_clips:
            return "no_video"
        return "decoding_video"

    def current_song_has_video_clips(self) -> bool:
        song = getattr(self._window.engine, "_song", None)
        if song is None:
            song = self._window.current_song
        return bool(getattr(song, "video_clips", None) or [])

    def playback_sample_rate(self) -> int:
        engine = self._window.engine
        return int(getattr(engine, "_playback_rate", 0) or 0)

    def sync_video_output_active(self) -> None:
        sync = getattr(self._window, "_sync_video_output_active", None)
        if callable(sync):
            sync()


def assert_is_remote_host(host: RemoteHost) -> RemoteHost:
    """Typing helper for construction sites."""
    return host
