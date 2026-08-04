"""Application service: show / song activation orchestration.

Design contract
---------------
**Responsibilities**
- Activate a setlist song onto playback + UI surfaces (timeline, waveform path,
  video sync, cue monitor deferral).
- Deactivate / clear surfaces when the setlist is empty.
- Prepare playback attachment (``engine.set_song`` + timebase) for the active song.
- Coordinate timeline / waveform / video refresh steps during activate.
- Reserve ``notify_external_sync`` as a future MA3 / OSC extension point (no-op).

**Non-responsibilities**
- Does not own play/pause/stop/seek/volume/loop (``PlaybackService``).
- Does not own project new/open/save or dirty (``ProjectService``).
- Does not own machine QSettings (``SettingsService``).
- Does not redesign AudioEngine, Timeline, Waveform, or Video decode.
- Does not introduce an Event Bus.
- Does not own PortAudio device open details beyond calling existing engine APIs
  (``quiesce_output``, ``set_buffer``, ``set_duration``).

**Dependencies**
- ``cueplayer.ports.show_host.ShowHost`` (explicit host Protocol; MainWindow today)
- ``cueplayer.application.playback_service.PlaybackService`` (loop clear only)
- ``cueplayer.media.audio_disk_cache.load_cached_waveform_peaks``
- ``PySide6.QtCore.QTimer`` (deferred cue-monitor rebuild — same as prior UI)

**Why this design**
- Strangler: move activate orchestration out of MainWindow while keeping the
  identical step order and host-owned media caches / loaders.
- ShowSession may coordinate multiple services later (MA3/OSC) without pulling
  project lifecycle or transport control into this type.
- Host is typed as ``ShowHost`` (not ``Any``) so alternate hosts (Web / Remote /
  headless) can satisfy the same contract without duck-typing MainWindow.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer

from cueplayer.application.playback_service import PlaybackService
from cueplayer.diagnostics import perf as perf_diag
from cueplayer.domain.models import Song
from cueplayer.media.audio_disk_cache import load_cached_waveform_peaks
from cueplayer.ports.show_host import ShowHost


class ShowSessionService:
    """Coordinates song activate / deactivate across playback + UI surfaces."""

    def __init__(self, host: ShowHost, playback: PlaybackService) -> None:
        self._host = host
        self._playback = playback

    @property
    def host(self) -> ShowHost:
        return self._host

    @property
    def playback(self) -> PlaybackService:
        return self._playback

    # --- activate / deactivate -----------------------------------------------

    def activate_song_at(self, index: int, *, stop_playback: bool = True) -> None:
        """Activate ``project.songs[index]`` — same behavior as former MainWindow path."""
        h = self._host
        if index < 0 or index >= len(h.project.songs):
            return
        with perf_diag.span("activate.song.total", index=index):
            # Align Anchors preview must not survive a song switch.
            if self._playback.anchor_preview_active:
                self._playback.end_anchor_preview(restore_entry=False)
            h._audio_load_token += 1
            h._song_activate_gen += 1
            activate_gen = h._song_activate_gen
            # Tear down PortAudio + video decode before swapping song media.
            # Leaving the stream open (pause/stop alone) races PyAV close with the
            # audio callback and is a common mid-play / song-switch hard crash.
            with perf_diag.span("activate.quiesce"):
                if stop_playback or bool(getattr(h.engine, "playing", False)):
                    h.engine.quiesce_output()
            h.current_song = h.project.songs[index]
            h._sync_undo_context()
            self._playback.clear_loop()
            h._sync_loop_ui()
            h.timeline.clear_selection(emit=False)
            h.monitor.set_selected_mark_ids([])
            # Arm Loading before set_song paints — otherwise the Music lane flashes
            # "Open audio…" while the first long video/audio decode is still queued.
            with perf_diag.span("activate.arm_placeholder"):
                h._arm_timeline_audio_loading_placeholder(h.current_song)
            with perf_diag.span("activate.timeline"):
                self.refresh_timeline()
            # Cue List rebuild is relatively heavy — defer so Setlist selection
            # + timeline swap paint first (feels like an instant song switch).
            QTimer.singleShot(
                0,
                lambda g=activate_gen, song=h.current_song: self._activate_song_monitor(
                    g, song
                ),
            )
            with perf_diag.span("activate.video_bind"):
                self.refresh_video()
            with perf_diag.span("activate.engine_attach"):
                self.prepare_playback(h.current_song)
            action = getattr(h, "_show_video_track_action", None)
            if action is not None:
                action.blockSignals(True)
                action.setChecked(bool(h.project.show_video_track))
                action.blockSignals(False)
            # Keep timeline eye in sync with project-global preference across songs.
            h.timeline.set_show_video_track(h.project.show_video_track, emit=False)
            with perf_diag.span("activate.geometry_chrome"):
                h._sync_timeline_geometry()
                h._rebuild_digit_shortcuts()
                h._refresh_output_timecode_clock(0.0)
            self._prepare_waveform_and_audio(h.current_song)
            with perf_diag.span("activate.chrome"):
                h._refresh_window_title()
                h._refresh_status()
                h._sync_timeline_overview()
            with perf_diag.span("activate.video_land"):
                h._ensure_video_preview_frame()
            self.notify_external_sync()
        # Developer log (no-op when CUEPLAYER_PERF off).
        if perf_diag.is_enabled():
            song_name = getattr(h.current_song, "name", "") or ""
            path = perf_diag.flush_report(label=f"after-activate:{song_name}")
            status = getattr(h, "status", None)
            if path is not None and status is not None and hasattr(status, "showMessage"):
                status.showMessage(f"Perf log updated: {path}", 4000)

    def deactivate_song(self) -> None:
        """Clear song attachment on timeline / monitor / video / engine."""
        h = self._host
        h.timeline.clear_selection(emit=False)
        h.timeline.set_song(None)
        h.timeline.set_audio(None)
        h.timeline.set_audio_loading(False)
        h.timeline.set_ltc_audio(None)
        h.monitor.set_song(None)
        h.monitor.set_selected_mark_ids([])
        h.video_sync.set_song(None)
        h.engine.set_song(None)
        h.engine.set_buffer(None)
        h.engine.set_duration(60.0)
        self._playback.clear_loop()
        h._sync_loop_ui()
        h.transport.set_times(0.0, h.engine.duration)
        h.monitor.set_position(0.0, h.engine.duration)

    def apply_empty_workspace(self) -> None:
        """Blank setlist workspace after deactivate (digit shortcuts + chrome)."""
        h = self._host
        self.deactivate_song()
        h._rebuild_digit_shortcuts()
        h._refresh_window_title()
        h._refresh_status()
        h._sync_timeline_overview()
        h._ensure_video_preview_frame()
        self.notify_external_sync()

    # --- prepare / refresh coordination --------------------------------------

    def prepare_playback(self, song: Song) -> None:
        """Attach ``song`` to the engine sample clock (not transport play/pause)."""
        h = self._host
        h.engine.set_song(song)
        h.engine.set_song_timebase(song.start_timecode, song.fps)

    def refresh_timeline(self) -> None:
        """Re-bind timeline song + project mark-line chrome."""
        h = self._host
        h.timeline.set_song(h.current_song)
        h._apply_project_mark_line_settings()

    def refresh_video(self) -> None:
        """Re-bind video sync to the current song."""
        h = self._host
        h.video_sync.set_song(h.current_song)

    def refresh_waveform(self) -> None:
        """Re-run waveform/audio arming for the current song (activate path)."""
        self._prepare_waveform_and_audio(self._host.current_song)

    def notify_external_sync(self) -> None:
        """Future MA3 / OSC synchronization hook — intentionally empty for now."""
        return None

    # --- internals -----------------------------------------------------------

    def _activate_song_monitor(self, gen: int, song: Song) -> None:
        h = self._host
        if gen != h._song_activate_gen or song is not h.current_song:
            return
        with perf_diag.span("activate.monitor_deferred"):
            h.monitor.set_song(song)

    def _prepare_waveform_and_audio(self, song: Song) -> None:
        """Coordinate Music-lane waveform + async PCM load (host owns loaders)."""
        h = self._host
        with perf_diag.span("activate.waveform_arm"):
            audio_path = self._playback.resolve_active_audio_path(song)
            if audio_path is not None and audio_path.is_file():
                # RAM only — never sync-load .npz on the UI thread (that hitch
                # was the main Setlist song-switch stall after warm).
                cached = h._cached_audio_buffer(audio_path)
                if cached is not None:
                    perf_diag.note("activate.waveform_path", "ram_hit")
                    h.timeline.set_audio_loading(False)
                    h._apply_loaded_audio(
                        cached,
                        audio_path,
                        mark_dirty=False,
                        replace_track=False,
                        refresh_song_widgets=False,
                    )
                else:
                    h.engine.set_buffer(None)
                    h._timeline_ltc_exclude = None
                    h._apply_probed_audio_duration(audio_path, song=song)
                    # Peaks sidecar paints the Music lane immediately after restart
                    # while full PCM (or full .npz) loads for playback.
                    peaks = load_cached_waveform_peaks(audio_path)
                    if peaks is not None:
                        perf_diag.note("activate.waveform_path", "peaks_hit")
                        h.timeline.set_audio_loading(False)
                        h.timeline.set_audio(peaks, reset_view=False)
                        if not h._media_warm_active:
                            h.status.showMessage(
                                f"Waveform ready — loading audio… ({audio_path.name})", 0
                            )
                    else:
                        perf_diag.note("activate.waveform_path", "cold")
                        h.timeline.set_audio_loading(True, audio_path.name)
                    h._load_audio_path(
                        audio_path,
                        mark_dirty=False,
                        replace_track=False,
                        bump_token=False,
                        keep_waveform=peaks is not None,
                    )
            else:
                perf_diag.note("activate.waveform_path", "standin_or_empty")
                h.engine.set_buffer(None)
                h._timeline_ltc_exclude = None
                h.timeline.set_ltc_audio(None)
                h.engine.set_duration(song.duration_seconds)
                h.transport.set_times(0.0, h.engine.duration)
                h.monitor.set_position(0.0, h.engine.duration)
                if audio_path is not None:
                    h.timeline.set_audio(None)
                    h.timeline.set_audio_loading(False)
                    h.status.showMessage(
                        f"Audio file not found: {audio_path} "
                        "(File → Relink Missing Media…)",
                        5000,
                    )
                else:
                    # No music file — show embedded video audio in the Music lane.
                    h._schedule_video_music_standin()
