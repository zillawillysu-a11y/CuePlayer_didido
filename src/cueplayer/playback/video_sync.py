"""Video clip playback synced to the audio sample clock.

CuePlayer has exactly one playback clock: `AudioEngine`'s sample position.
This controller never runs its own timer — the UI feeds it `update_position()`
whenever the engine reports a new position (see MainWindow), and it looks up
which clip (if any) should be showing at that song-timeline time, decodes
the matching source frame, and hands it back for the Preview / Clean Output
widgets to paint. No independent video clock, no second player.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from time import monotonic

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal, Qt

from cueplayer.diagnostics import perf as perf_diag
from cueplayer.diagnostics import video_sm_trace as sm_trace
from cueplayer.domain.models import (
    VIDEO_DECODE_QUALITY_MAX_HEIGHT,
    Song,
    VideoClip,
    VideoDecodeQuality,
    video_clip_crossfade_weight,
)
from cueplayer.media.scrub_frame_cache import ScrubFrameCache
from cueplayer.media.video_loader import MediaDecoder, open_media_decoder

# While scrubbing with a warm ScrubFrameCache, lookups are cheap — allow a
# higher emit rate so Preview tracks the drag. Cold cache / live decode still
# falls back to this interval as a safety cap when we must touch PyAV.
_MAX_SCRUB_DECODE_HZ = 24.0
_MIN_SCRUB_DECODE_INTERVAL = 1.0 / _MAX_SCRUB_DECODE_HZ

# AudioEngine's master clock ticks position_changed at ~60Hz (16ms poll —
# see AudioEngine._poll) so it can drive smooth timeline playhead motion,
# but no display can show video faster than ~display refresh rate anyway.
# During playback (see set_playing()), cap actual decode+emit work to this
# rate so the (Preview + Clean Output) QImage copy / repaint cost — which
# runs on the UI thread same as timeline paint/input — can't fire faster
# than a real frame, on top of VideoDecoder's own duplicate-AVFrame cache
# (see video_loader.py) which already skips the colorspace conversion when
# the underlying source frame hasn't advanced. Together these are what keep
# the timeline (scroll/zoom/mark edit/playhead) responsive while a video
# clip is playing. MainWindow also queues video decode behind the playhead
# update so PyAV work cannot stall timeline paint. Paused click-seeks use a
# lighter trailing-edge throttle (_MIN_SEEK_DECODE_INTERVAL) so rapid jumps
# only decode the latest land frame.
#
# Play decode used to run on the UI thread (throttled). Sprint 8 Task 2 moves
# scrub-cold and play-time live decode onto a single latest-wins worker with
# *dedicated* decoders (never shared with the UI land-frame path) so Timeline
# drag/playhead paint are not stalled by PyAV. Scrub-end / paused land still
# use a one-shot sync decode for frame accuracy.
#
# Cap Preview/Clean emit rate for UI-thread budget. Frame *selection* still
# follows the file's own timestamps (source FPS); this only limits how often
# we convert+paint. 30 Hz is the target for smooth Clean Output; when the
# Video Track lane is open (timeline paint + clip waveforms share the UI
# thread) we drop to the heavy budget so playhead motion stays usable.
_MAX_PLAY_DECODE_HZ = 30.0
_MAX_PLAY_DECODE_HZ_HEAVY = 24.0
_MIN_PLAY_DECODE_INTERVAL = 1.0 / _MAX_PLAY_DECODE_HZ
_MIN_PLAY_DECODE_INTERVAL_HEAVY = 1.0 / _MAX_PLAY_DECODE_HZ_HEAVY

# Rapid click-seeks while paused used to decode every land frame on the UI
# thread immediately. When ``av_path_lock`` was already held by mixer/standin
# work, that stacked into a frozen UI + stuttering audio. Trailing-edge
# throttle keeps only the latest jump.
_MAX_SEEK_DECODE_HZ = 12.0
_MIN_SEEK_DECODE_INTERVAL = 1.0 / _MAX_SEEK_DECODE_HZ

# Scrub live preview (Round 3): Timeline stays pointer-follow; video samples
# the latest target at a controlled rate. Do NOT decode every mouse-move.
_SCRUB_PREVIEW_HZ = 16.0  # target band 12–20 FPS
_SCRUB_PREVIEW_INTERVAL_MS = max(50, int(round(1000.0 / _SCRUB_PREVIEW_HZ)))
_SCRUB_PAUSE_PRIORITY_MS = 45  # pause-in-drag → decode latest immediately
_SCRUB_MIN_TARGET_DELTA_S = 1.0 / 48.0  # skip decode if target barely moved

_UNSET = object()

# Async worker never blocks > this on av_path_lock (drop frame / retry later).
_ASYNC_LOCK_TIMEOUT_S = 0.05
_ASYNC_SCRUB_LOCK_TIMEOUT_S = 0.08
_ASYNC_LAND_LOCK_TIMEOUT_S = 0.35
# Optional brief sync attempt on release (UI must never wait longer).
_SYNC_LAND_LOCK_TIMEOUT_S = 0.05
# How near a cached preview/poster must be to count as "relevant" on release.
_RELEASE_RELEVANT_TOLERANCE_S = 0.35
_FRAME_TOLERANCE_S = 0.05
# Round 5: bounded land retries (count + wall deadline). Never 100+ retries.
_LAND_RETRY_MS = 40
_LAND_MAX_RETRIES = 5
_LAND_DEADLINE_S = 0.50
_EMPTY_DECODE_RESET_AFTER = 3
_RESUME_WATCHDOG_MS = 400
_RESUME_RECOVERY_MS = 400
# Round 6: present preview frames within this of the current pointer target.
_PREVIEW_PRESENT_TOLERANCE_S = 0.75
# Only cancel an in-flight scrub preview when the pointer jumped this far.
_PREVIEW_CANCEL_DELTA_S = 2.0
# Round 8: present a completed play frame if its Song Time is within this of
# the current AudioEngine Song Time (do not use generation equality).
_PLAYBACK_LATENESS_TOLERANCE_S = 0.35

PIPELINE_MODE = "async_latest_wins"
SCRUB_PREVIEW_TARGET_FPS = _SCRUB_PREVIEW_HZ


class VideoPipelineState:
    """Explicit Video schedule ownership (Sprint 8 Task 2 Round 4+)."""

    PLAYBACK = "PLAYBACK"
    SCRUB_PREVIEW = "SCRUB_PREVIEW"
    FINAL_LANDING = "FINAL_LANDING"
    RESUME_PLAYBACK = "RESUME_PLAYBACK"


class ReleaseTargetKind:
    """Explicit Song Time → media target outcomes (Round 5)."""

    VALID_MEDIA_TARGET = "VALID_MEDIA_TARGET"
    TIMELINE_GAP = "TIMELINE_GAP"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    MISSING_MEDIA = "MISSING_MEDIA"
    INVALID_CLIP = "INVALID_CLIP"


@dataclass(frozen=True)
class ReleaseTarget:
    kind: str
    song_seconds: float
    media_seconds: float | None = None
    clip_id: str | None = None
    reason: str = ""

    @property
    def is_valid(self) -> bool:
        return (
            self.kind == ReleaseTargetKind.VALID_MEDIA_TARGET
            and self.media_seconds is not None
            and self.clip_id is not None
        )


class VideoSyncController(QObject):
    frame_changed = Signal(object)  # np.ndarray (H, W, 3) RGB24, or None for intentional gap
    active_clip_changed = Signal(object)  # VideoClip | None
    overlap_warning = Signal(str)
    # Worker → UI (Queued): (request_gen, song_time_seconds, frame|None, kind, empty_reason, scrub_session)
    _async_frame_ready = Signal(int, float, object, str, str, int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._song: Song | None = None
        self._decoders: dict[str, MediaDecoder] = {}
        self._decoder_paths: dict[str, Path] = {}
        # Dedicated decoders for the async worker only — never shared with UI.
        # Round 6: separate play vs scrub/land decoder maps so scrub seeks do
        # not leave the sequential playback decoder at a distant EOF/seek point.
        self._worker_decoders: dict[str, MediaDecoder] = {}
        self._worker_decoder_paths: dict[str, Path] = {}
        self._scrub_worker_decoders: dict[str, MediaDecoder] = {}
        self._scrub_worker_decoder_paths: dict[str, Path] = {}
        self._worker_lock = Lock()
        self._active_clip_id: str | None = None
        self._warned_overlap_keys: set[frozenset[str]] = set()
        self._decode_quality: VideoDecodeQuality = "full"
        self._decode_max_height: int | None = None
        # When both the embedded Preview panel and Clean Output window are
        # hidden, skip all decode work so playback/editing stays light on CPU
        # (see MainWindow._sync_video_output_active).
        self._video_output_active = True
        self._last_position_seconds: float | None = None
        self._scrubbing = False
        self._playing = False
        # When True (Video Track visible), use the heavier play-decode budget.
        self._timeline_video_heavy = False
        self._min_play_decode_interval = _MIN_PLAY_DECODE_INTERVAL
        # Trailing-edge throttle state, active while scrubbing or playing
        # (see _MIN_SCRUB_DECODE_INTERVAL / _MIN_PLAY_DECODE_INTERVAL above):
        # a skipped request is remembered and flushed shortly after, so the
        # last position asked for — e.g. right where the user releases the
        # mouse, or the position at the moment playback stops — is always
        # the one decoded and shown, never a stale throttled stand-in.
        self._last_decode_time = 0.0
        self._pending_clip: VideoClip | None = None
        self._pending_seconds: float | None = None
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.timeout.connect(self._flush_pending)
        # See _emit_frame(): lets identical consecutive frames (the common
        # case between two decoded source frames during playback) skip the
        # signal emit — and the Preview/Clean Output QImage copy + repaint
        # that follows it — entirely. _UNSET (not None) so the very first
        # emit always goes through, even if that first frame is None.
        self._last_emitted_frame: object = _UNSET
        # Sparse RGB posters for scrub — filled off-thread so drag never
        # pays PyAV seek on the UI thread (see scrub_frame_cache.py).
        self._scrub_cache = ScrubFrameCache()
        # Defer scrub preload so a click-seek (press+release) does not start
        # a background PyAV open on the same path as the live land-frame
        # decode — that race showed as an hourglass then hard-crashed with
        # Clean Output open.
        self._scrub_preload_timer = QTimer(self)
        self._scrub_preload_timer.setSingleShot(True)
        self._scrub_preload_timer.setInterval(100)
        self._scrub_preload_timer.timeout.connect(self._maybe_preload_scrub)
        # When True, skip live PyAV during play so VideoAudioMixer can own
        # ``av_path_lock`` without a rising Preview stutter before each seam.
        self._defer_live_decode: Callable[[], bool] | None = None
        # Latest-wins async live decode (play + scrub preview + land).
        # Queue depth is always 0 or 1: overwrite request fields; never stack jobs.
        self._async_req_gen = 0
        self._async_req_seconds = 0.0
        self._async_inflight = False
        self._async_lock_timeout = _ASYNC_LOCK_TIMEOUT_S
        self._async_req_kind = "play"  # play | scrub_preview | land
        self._async_req_session = 0  # scrub session captured at schedule
        self._async_req_started_mono = 0.0
        self._async_req_id = 0
        self._async_req_media_session = 0
        self._async_pool = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="video-live-decode"
        )
        self._async_frame_ready.connect(
            self._on_async_frame_ready, Qt.ConnectionType.QueuedConnection
        )
        # Scrub preview scheduler — samples latest target at ~16 Hz.
        self._scrub_target_seconds = 0.0
        self._scrub_last_requested_seconds: float | None = None
        self._scrub_session_gen = 0
        self._preview_request_seq = 0
        # Round 8 generation scopes (playback must not starve on clock ticks).
        self._media_session_gen = 0
        self._playback_request_seq = 0
        self._play_pending_seconds: float | None = None
        self._worker_idle_since_mono: float | None = None
        self._scrub_land_pending = False
        self._scrub_release_mono = 0.0
        self._scrub_preview_presented = 0
        self._scrub_preview_present_times: list[float] = []
        self._min_present_seconds: float | None = None
        # Round 4 — explicit pipeline state + resume transaction.
        self._pipeline_state = VideoPipelineState.PLAYBACK
        self._pre_scrub_was_playing = False
        self._release_target_song_time: float | None = None
        self._release_target_media_time: float | None = None
        self._final_land_generation = 0
        self._playback_resume_generation = 0
        self._decoder_position_established = False
        self._final_land_pending = False
        self._resume_pending = False
        self._resume_required = False
        self._resume_recovery_attempted = False
        self._land_retry_count = 0
        self._land_request_mono = 0.0
        self._land_worker_start_mono = 0.0
        self._land_deadline_mono = 0.0
        self._last_scrub_preview_seconds: float | None = None
        self._last_presented_song_seconds: float | None = None
        self._last_valid_frame: np.ndarray | None = None
        self._last_valid_frame_mono = 0.0
        self._last_valid_frame_song_seconds: float | None = None
        self._resume_started_mono = 0.0
        self._resume_first_engine_noted = False
        self._release_target: ReleaseTarget | None = None
        self._scrub_transaction_id = 0
        self._final_land_transaction_id = 0
        self._resume_transaction_id = 0
        self._empty_decode_streak = 0
        self._worker_reset_count = 0
        self._play_decoder_reset_pending = False
        self._scrub_preview_timer = QTimer(self)
        self._scrub_preview_timer.setInterval(_SCRUB_PREVIEW_INTERVAL_MS)
        self._scrub_preview_timer.timeout.connect(self._on_scrub_preview_tick)
        self._scrub_pause_timer = QTimer(self)
        self._scrub_pause_timer.setSingleShot(True)
        self._scrub_pause_timer.setInterval(_SCRUB_PAUSE_PRIORITY_MS)
        self._scrub_pause_timer.timeout.connect(self._on_scrub_pause_priority)
        self._land_retry_timer = QTimer(self)
        self._land_retry_timer.setSingleShot(True)
        self._land_retry_timer.setInterval(_LAND_RETRY_MS)
        self._land_retry_timer.timeout.connect(self._retry_final_land_if_pending)
        self._resume_watchdog = QTimer(self)
        self._resume_watchdog.setSingleShot(True)
        self._resume_watchdog.setInterval(_RESUME_WATCHDOG_MS)
        self._resume_watchdog.timeout.connect(self._on_resume_watchdog)
        # Prove which pipeline the Windows desk build is running.
        perf_diag.note("video.pipeline_mode", PIPELINE_MODE)
        perf_diag.note("video.pipeline_state", self._pipeline_state)
        perf_diag.note("video.worker_pool", "video-live-decode:1")
        perf_diag.note("video.scrub.preview_target_fps", SCRUB_PREVIEW_TARGET_FPS)
        perf_diag.note("video.decoder_contexts", "play+scrub")

    def _media_time_for_song(self, song_seconds: float | None) -> float | None:
        if song_seconds is None or self._song is None:
            return None
        clip = self._song.active_video_clip_at(float(song_seconds))
        if clip is None:
            return None
        try:
            return float(clip.source_time_for(float(song_seconds)))
        except Exception:
            return None

    def _sm_trace(self, event: str, **kwargs: object) -> None:
        """Round 7 state-machine breadcrumb (perf-gated)."""
        if "state" not in kwargs:
            kwargs["state"] = self._pipeline_state
        if "generation" not in kwargs:
            kwargs["generation"] = int(self._async_req_gen)
        if "session_gen" not in kwargs:
            kwargs["session_gen"] = int(self._scrub_session_gen)
        if "inflight" not in kwargs:
            kwargs["inflight"] = bool(self._async_inflight)
        if "request_id" not in kwargs and self._async_req_id:
            kwargs["request_id"] = int(self._async_req_id)
        sm_trace.trace(event, **kwargs)  # type: ignore[arg-type]

    def _sm_worker_runtime(
        self,
        runtime: str,
        *,
        request_id: int | None = None,
        reason: str | None = None,
        song_time: float | None = None,
        kind: str | None = None,
    ) -> None:
        sm_trace.set_worker_runtime(
            runtime,
            request_id=request_id if request_id is not None else (
                int(self._async_req_id) if self._async_req_id else None
            ),
            reason=reason,
            pipeline_state=self._pipeline_state,
            generation=int(self._async_req_gen),
            song_time=song_time,
            kind=kind,
        )

    def is_scrubbing(self) -> bool:
        return bool(self._scrubbing)

    def pipeline_state(self) -> str:
        return str(self._pipeline_state)

    def engine_video_gated(self) -> bool:
        """True while scrub preview or final-land owns the schedule (block engine)."""
        return self._pipeline_state in (
            VideoPipelineState.SCRUB_PREVIEW,
            VideoPipelineState.FINAL_LANDING,
        )

    def pipeline_mode(self) -> str:
        return PIPELINE_MODE

    def scrub_preview_target_fps(self) -> float:
        return float(SCRUB_PREVIEW_TARGET_FPS)

    def _set_pipeline_state(self, state: str) -> None:
        if state == self._pipeline_state:
            return
        prev = self._pipeline_state
        self._pipeline_state = state
        now = monotonic()
        perf_diag.note("video.pipeline_state", state)
        perf_diag.note("video.pipeline_state.prev", prev)
        perf_diag.note("video.pipeline_state.changed_at", now)
        perf_diag.count(f"video.pipeline_state.to.{state}")

    def _cancel_scrub_resume_transaction(self, *, reason: str = "cancel") -> None:
        """Invalidate land/resume state (new scrub, song switch, track change)."""
        self._land_retry_timer.stop()
        self._resume_watchdog.stop()
        if self._final_land_pending:
            perf_diag.count("video.scrub.final_land_superseded")
        if self._resume_pending:
            perf_diag.note("video.scrub.resume_cancel_reason", reason)
            perf_diag.count("video.scrub.resume_cancel")
        self._scrub_land_pending = False
        self._final_land_pending = False
        self._resume_pending = False
        self._decoder_position_established = False
        self._release_target_song_time = None
        self._release_target_media_time = None
        self._release_target = None
        self._land_retry_count = 0
        self._land_deadline_mono = 0.0
        self._empty_decode_streak = 0
        self._min_present_seconds = None
        perf_diag.count("video.scrub.min_present_seconds_cleared")
        perf_diag.note("video.scrub.min_present_seconds_value", None)

    def set_defer_live_decode(self, check: Callable[[], bool] | None) -> None:
        """Optional gate: skip play-time frame decode while ``check()`` is True."""
        self._defer_live_decode = check

    def decode_quality(self) -> VideoDecodeQuality:
        return self._decode_quality

    def video_output_active(self) -> bool:
        return self._video_output_active

    def set_video_output_active(self, active: bool) -> None:
        """Enable/disable frame decode+emit (Preview / Clean Output visibility).

        Audio playback and embedded clip audio are unaffected — only the RGB
        preview path is gated. When re-enabled, the frame at the last
        `update_position()` is decoded immediately.

        Scrub posters are *not* preloaded here: kicking the scrub worker
        while opening Clean Output contended on ``av_path_lock`` with the
        live frame decode and made the whole UI feel sluggish. Scrub ladders
        build on ``set_scrubbing(True)`` instead.
        """
        active = bool(active)
        if active == self._video_output_active:
            return
        self._video_output_active = active
        if not active:
            self._invalidate_async_requests()
            self._cancel_pending()
            self._close_all_decoders()
            self._scrub_cache.clear()
            return
        song = self._song
        seconds = self._last_position_seconds
        if song is None or seconds is None:
            return
        self._maybe_warn_overlap(song, seconds)
        primary = song.active_video_clip_at(seconds)
        self._set_active(primary.id if primary else None)
        self._last_decode_time = 0.0
        # Defer the first frame so Clean Output can show/paint immediately
        # instead of blocking the UI thread on a contended av_path_lock
        # (waveform workers on long rehearsal files).
        QTimer.singleShot(0, self._decode_last_position_if_active)

    def set_timeline_video_heavy(self, heavy: bool) -> None:
        """Lower play-decode Hz when the Video Track lane is open.

        Timeline playhead + clip waveforms share the UI thread with Preview /
        Clean paint. Keep 30 Hz when the lane is hidden; use 24 Hz when open.
        """
        heavy = bool(heavy)
        if heavy == self._timeline_video_heavy:
            return
        self._timeline_video_heavy = heavy
        self._min_play_decode_interval = (
            _MIN_PLAY_DECODE_INTERVAL_HEAVY if heavy else _MIN_PLAY_DECODE_INTERVAL
        )

    def set_scrubbing(self, active: bool, *, was_playing: bool | None = None) -> None:
        """Call from the timeline's scrub_started/scrub_ended signals.

        Drag: Timeline stays pointer-follow; a ~16 Hz latest-wins scrub
        preview scheduler updates Video without sync PyAV on mouse-move.
        Release: invalidate older generations, show nearest relevant frame
        immediately, then exclusive high-priority exact land on the worker.
        """
        active = bool(active)
        if active == self._scrubbing:
            return
        self._scrubbing = active
        if active:
            self._cancel_scrub_resume_transaction(reason="new_scrub")
            self._invalidate_async_requests()
            self._scrub_session_gen += 1
            self._scrub_transaction_id += 1
            self._preview_request_seq = 0
            self._play_pending_seconds = None
            self._scrub_preview_presented = 0
            self._scrub_preview_present_times = []
            perf_diag.note(
                "video.scrub.transaction_id", self._scrub_transaction_id
            )
            perf_diag.note("video.scrub.session_generation", self._scrub_session_gen)
            perf_diag.note(
                "video.scrub_transaction_generation", self._scrub_session_gen
            )
            self._scrub_last_requested_seconds = None
            self._last_scrub_preview_seconds = None
            if was_playing is None:
                was_playing = bool(self._playing)
            self._pre_scrub_was_playing = bool(was_playing)
            perf_diag.note(
                "video.scrub.pre_scrub_was_playing", self._pre_scrub_was_playing
            )
            self._set_pipeline_state(VideoPipelineState.SCRUB_PREVIEW)
            self._sm_trace(
                "SCRUB_PREVIEW_ENTER",
                song_time=self._last_position_seconds,
                media_time=self._media_time_for_song(self._last_position_seconds),
                extra={
                    "pre_scrub_was_playing": self._pre_scrub_was_playing,
                    "transaction_id": self._scrub_transaction_id,
                },
            )
            if self._last_position_seconds is not None:
                self._scrub_target_seconds = float(self._last_position_seconds)
            if self._video_output_active and self._song is not None:
                self._scrub_preload_timer.start()
                self._scrub_preview_timer.start()
        else:
            self._scrub_preload_timer.stop()
            self._scrub_preview_timer.stop()
            self._scrub_pause_timer.stop()
            self._finalize_scrub_release()

    def _resolve_release_target(self, song: Song, seconds: float) -> ReleaseTarget:
        """Map Song Time to an explicit media-target outcome (never ambiguous None)."""
        seconds = float(seconds)
        if not np.isfinite(seconds):
            return ReleaseTarget(
                ReleaseTargetKind.OUT_OF_RANGE,
                song_seconds=seconds,
                reason="non_finite_song_time",
            )
        clips = [c for c in song.video_clips if not c.hidden]
        if not clips:
            return ReleaseTarget(
                ReleaseTargetKind.TIMELINE_GAP,
                song_seconds=seconds,
                reason="no_visible_clips",
            )
        primary = song.active_video_clip_at(seconds)
        if primary is None:
            starts = [c.start_seconds for c in clips]
            ends = [c.end_seconds for c in clips]
            if seconds < min(starts) - 1e-6:
                return ReleaseTarget(
                    ReleaseTargetKind.OUT_OF_RANGE,
                    song_seconds=seconds,
                    reason="before_first_clip",
                )
            if seconds >= max(ends) - 1e-6:
                return ReleaseTarget(
                    ReleaseTargetKind.OUT_OF_RANGE,
                    song_seconds=seconds,
                    reason="after_last_clip",
                )
            return ReleaseTarget(
                ReleaseTargetKind.TIMELINE_GAP,
                song_seconds=seconds,
                reason="gap_between_clips",
            )
        path = Path(primary.path)
        try:
            exists = path.exists()
        except OSError:
            exists = False
        if not exists:
            return ReleaseTarget(
                ReleaseTargetKind.MISSING_MEDIA,
                song_seconds=seconds,
                clip_id=primary.id,
                reason="path_missing",
            )
        try:
            media_t = float(primary.source_time_for(seconds))
        except Exception as exc:  # noqa: BLE001
            return ReleaseTarget(
                ReleaseTargetKind.INVALID_CLIP,
                song_seconds=seconds,
                clip_id=primary.id,
                reason=f"source_time_error:{type(exc).__name__}",
            )
        if not np.isfinite(media_t) or media_t < 0.0:
            # Clamp tiny negatives; reject absurd values.
            if np.isfinite(media_t) and -1e-3 <= media_t < 0.0:
                media_t = 0.0
            else:
                return ReleaseTarget(
                    ReleaseTargetKind.INVALID_CLIP,
                    song_seconds=seconds,
                    clip_id=primary.id,
                    reason="invalid_media_time",
                )
        src_dur = primary.source_duration_seconds
        if src_dur is not None and float(src_dur) > 0.0:
            # Allow seek at/near EOF; clamp slightly inside for decoder friendliness.
            if media_t > float(src_dur):
                media_t = max(0.0, float(src_dur) - 1e-3)
        return ReleaseTarget(
            ReleaseTargetKind.VALID_MEDIA_TARGET,
            song_seconds=seconds,
            media_seconds=media_t,
            clip_id=primary.id,
            reason="ok",
        )

    def _finalize_scrub_release(self) -> None:
        """Exclusive final-land after mouse release (UI never waits on PyAV).

        Round 5: enter FINAL_LANDING only with an explicit target outcome.
        Invalid/gap targets resolve immediately — no decode retry storm.
        """
        song = self._song
        seconds = self._last_position_seconds
        release_mono = monotonic()
        self._scrub_release_mono = release_mono
        self._land_retry_count = 0
        self._empty_decode_streak = 0
        self._land_deadline_mono = release_mono + _LAND_DEADLINE_S
        self._final_land_transaction_id = int(self._scrub_transaction_id)
        perf_diag.note(
            "video.scrub.final_land_transaction_id", self._final_land_transaction_id
        )
        self._set_pipeline_state(VideoPipelineState.FINAL_LANDING)
        perf_diag.count("video.scrub.final_land_requests")
        perf_diag.note("video.scrub.release_timestamp", release_mono)
        # Drop all in-flight scrub-preview / play results from before release.
        self._invalidate_async_requests()
        perf_diag.count("video.scrub.old_generation_drop_after_release")
        self._flush_timer.stop()
        self._pending_clip = None
        self._pending_seconds = None
        self._decoder_position_established = False
        self._resume_pending = False
        if not self._video_output_active or song is None or seconds is None:
            self._final_land_pending = False
            self._scrub_land_pending = False
            self._set_pipeline_state(VideoPipelineState.PLAYBACK)
            return

        seconds = float(seconds)
        target = self._resolve_release_target(song, seconds)
        self._release_target = target
        self._release_target_song_time = float(target.song_seconds)
        self._release_target_media_time = (
            float(target.media_seconds) if target.media_seconds is not None else None
        )
        self._min_present_seconds = float(target.song_seconds)
        perf_diag.note("video.scrub.min_present_seconds_value", self._min_present_seconds)
        perf_diag.note("video.scrub.release_target_kind", target.kind)
        perf_diag.note("video.scrub.release_target_reason", target.reason)
        perf_diag.note("video.scrub.release_target_song_time", target.song_seconds)
        # Always note media time explicitly (None only for non-valid outcomes).
        perf_diag.note(
            "video.scrub.release_target_media_time",
            target.media_seconds if target.is_valid else f"n/a:{target.kind}",
        )
        if target.clip_id:
            perf_diag.note("video.scrub.release_target_clip_id", target.clip_id)

        self._maybe_warn_overlap(song, seconds)
        if target.clip_id:
            self._set_active(target.clip_id)
        else:
            self._set_active(None)

        # Immediate relevant frame (no PyAV) — never accidental black.
        first_src = self._present_immediate_release_frame(
            song, seconds, release_mono, target=target
        )
        perf_diag.note("video.scrub.final_land_first_relevant_source", first_src)
        if first_src in ("preview_cache", "poster_cache", "keep_last"):
            perf_diag.count("video.scrub.final_land_cache_hit")
        elif first_src in ("none", "gap_keep_last", "intentional_gap"):
            perf_diag.count("video.scrub.final_land_cache_miss")

        if not target.is_valid:
            # No decode retries for gap / missing / invalid / out-of-range.
            perf_diag.count(f"video.scrub.release_outcome.{target.kind}")
            self._resolve_non_valid_release(target)
            return

        self._scrub_land_pending = True
        self._final_land_pending = True
        self._schedule_final_land(float(target.song_seconds))

    def _note_land_complete_metrics(self) -> None:
        """Split land outcomes so paused/gap are not Resume failures."""
        target = self._release_target
        if target is not None and not target.is_valid:
            if target.kind == ReleaseTargetKind.TIMELINE_GAP:
                perf_diag.count("video.scrub.final_land_completed_gap")
            elif target.kind == ReleaseTargetKind.OUT_OF_RANGE:
                perf_diag.count("video.scrub.final_land_completed_out_of_range")
            else:
                perf_diag.count(f"video.scrub.final_land_completed_{target.kind.lower()}")
            if self._pre_scrub_was_playing:
                perf_diag.count("video.scrub.resume_required")
            else:
                perf_diag.count("video.scrub.resume_not_required")
            return
        if self._pre_scrub_was_playing:
            perf_diag.count("video.scrub.final_land_completed_playing")
            perf_diag.count("video.scrub.resume_required")
        else:
            perf_diag.count("video.scrub.final_land_completed_paused")
            perf_diag.count("video.scrub.resume_not_required")

    def _resolve_non_valid_release(self, target: ReleaseTarget) -> None:
        """Exit FINAL_LANDING without a decode retry loop."""
        self._final_land_pending = False
        self._scrub_land_pending = False
        self._land_retry_timer.stop()
        self._decoder_position_established = True
        perf_diag.count("video.scrub.final_land_completed")
        perf_diag.note("video.scrub.final_land_completed_without_exact", target.kind)
        self._note_land_complete_metrics()
        if self._pre_scrub_was_playing:
            self._enter_resume_playback()
        else:
            self._set_pipeline_state(VideoPipelineState.PLAYBACK)
            self._resume_pending = False
            self._resume_required = False

    def _present_immediate_release_frame(
        self,
        song: Song,
        seconds: float,
        release_mono: float,
        *,
        target: ReleaseTarget,
    ) -> str:
        """Show nearest relevant cached frame on release. Never accidental black."""
        tol = _RELEASE_RELEVANT_TOLERANCE_S
        preview_t = self._last_scrub_preview_seconds

        def _note_relevant(src: str) -> str:
            perf_diag.record_ms(
                "video.scrub.final_land_first_relevant_ms",
                (monotonic() - release_mono) * 1000.0,
            )
            return src

        # Gap / out-of-range / missing: keep last valid frame (no black flash).
        if not target.is_valid:
            if self._last_valid_frame is not None:
                return _note_relevant("gap_keep_last")
            # No prior frame — intentional empty only when nothing was ever shown.
            self._emit_frame(None, allow_clear=True, reason=f"intentional:{target.kind}")
            return _note_relevant("intentional_gap")

        if (
            preview_t is not None
            and abs(float(preview_t) - seconds) <= tol
            and self._is_valid_frame_array(self._last_emitted_frame)
        ):
            return _note_relevant("preview_cache")
        poster = self._scrub_composite(song, seconds)
        if self._is_valid_frame_array(poster):
            self._emit_frame(poster)
            self._last_presented_song_seconds = seconds
            return _note_relevant("poster_cache")
        if (
            self._last_presented_song_seconds is not None
            and abs(float(self._last_presented_song_seconds) - seconds) <= tol
            and self._last_valid_frame is not None
        ):
            return _note_relevant("keep_last")
        if self._last_valid_frame is not None:
            # Prefer last valid over clearing to black while exact land runs.
            return _note_relevant("keep_last")
        return _note_relevant("none")

    def _schedule_final_land(self, seconds: float) -> None:
        """Queue exclusive land; replaces any older land target."""
        if self._pipeline_state != VideoPipelineState.FINAL_LANDING:
            return
        if self._release_target is not None and not self._release_target.is_valid:
            return
        if self._final_land_pending and self._async_req_kind == "land":
            if abs(float(seconds) - float(self._async_req_seconds)) > 1e-6:
                perf_diag.count("video.scrub.final_land_superseded")
        self._land_request_mono = monotonic()
        req_id = sm_trace.next_request_id()
        self._sm_trace(
            "FINAL_LAND_REQUEST",
            song_time=seconds,
            media_time=self._media_time_for_song(seconds),
            request_id=req_id,
            kind="land",
            scheduler="schedule_final_land",
        )
        self._request_async_live_frame(
            seconds,
            kind="land",
            lock_timeout=_ASYNC_LAND_LOCK_TIMEOUT_S,
            force=True,
            request_id=req_id,
            scheduler="schedule_final_land",
        )
        self._final_land_generation = int(self._async_req_gen)
        perf_diag.note("video.scrub.final_land_generation", self._final_land_generation)

    def _land_budget_exhausted(self) -> bool:
        if self._land_retry_count >= _LAND_MAX_RETRIES:
            return True
        if self._land_deadline_mono > 0.0 and monotonic() >= self._land_deadline_mono:
            return True
        return False

    def _retry_final_land_if_pending(self) -> None:
        if (
            self._pipeline_state != VideoPipelineState.FINAL_LANDING
            or not self._final_land_pending
            or not self._video_output_active
        ):
            return
        if self._release_target is not None and not self._release_target.is_valid:
            self._resolve_non_valid_release(self._release_target)
            return
        target = self._release_target_song_time
        if target is None:
            self._fail_final_land_recoverable(reason="missing_song_target")
            return
        if self._land_budget_exhausted():
            perf_diag.count("video.scrub.final_land_deadline_exit")
            self._fail_final_land_recoverable(reason="retry_deadline")
            return
        self._land_retry_count += 1
        perf_diag.count("video.scrub.final_land_retry")
        perf_diag.note("video.scrub.final_land_retry_count", self._land_retry_count)
        # Bounded decoder reset after repeated empties.
        if (
            self._empty_decode_streak >= _EMPTY_DECODE_RESET_AFTER
            and self._release_target is not None
            and self._release_target.clip_id
        ):
            self._reset_worker_decoder(self._release_target.clip_id)
            self._empty_decode_streak = 0
        self._schedule_final_land(float(target))

    def _fail_final_land_recoverable(self, *, reason: str) -> None:
        """Exit FINAL_LANDING after bounded failure; restore play scheduling."""
        self._final_land_pending = False
        self._scrub_land_pending = False
        self._land_retry_timer.stop()
        self._decoder_position_established = True
        perf_diag.note("video.scrub.resume_failed_reason", reason)
        perf_diag.count("video.scrub.final_land_recoverable_failure")
        perf_diag.count("video.scrub.final_land_completed")
        self._note_land_complete_metrics()
        if self._pre_scrub_was_playing:
            self._enter_resume_playback()
        else:
            self._set_pipeline_state(VideoPipelineState.PLAYBACK)
            self._resume_pending = False
            self._resume_required = False

    def _enter_resume_playback(self) -> None:
        self._playback_resume_generation += 1
        self._resume_transaction_id = int(self._final_land_transaction_id)
        self._resume_pending = True
        self._resume_required = True
        self._resume_recovery_attempted = False
        self._resume_started_mono = monotonic()
        self._resume_first_engine_noted = False
        # Ensure play scheduling treats us as playing even if playing_changed
        # has not been delivered yet after end_scrub().
        if self._pre_scrub_was_playing:
            self._playing = True
        self._set_pipeline_state(VideoPipelineState.RESUME_PLAYBACK)
        perf_diag.count("video.scrub.resume_started")
        perf_diag.note(
            "video.scrub.resume_transaction_id", self._resume_transaction_id
        )
        perf_diag.note(
            "video.scrub.resume_generation", self._playback_resume_generation
        )
        if self._release_target_song_time is not None:
            self._min_present_seconds = float(self._release_target_song_time)
            perf_diag.note(
                "video.scrub.min_present_seconds_value", self._min_present_seconds
            )
        # Round 8: FINAL_LAND_PRESENT → immediately submit exactly one play decode.
        land_t = self._release_target_song_time
        sm_trace.mark_resume_begin()
        self._sm_trace(
            "RESUME_BEGIN",
            song_time=land_t,
            media_time=(
                float(self._release_target_media_time)
                if self._release_target_media_time is not None
                else self._media_time_for_song(land_t)
            ),
            scheduler="enter_resume_playback",
            extra={
                "resume_transaction_id": self._resume_transaction_id,
                "ms_since_land_present": sm_trace.gap_ms_since_land_present(),
            },
        )
        perf_diag.count("video.scrub.post_land_submit_attempt")
        perf_diag.count("post_land_submit_attempt")
        self._play_pending_seconds = None
        if land_t is None:
            perf_diag.count("video.scrub.post_land_submit_skipped")
            perf_diag.note(
                "video.scrub.post_land_submit_skipped_reason", "missing_land_target"
            )
            perf_diag.note("post_land_submit_skipped_reason", "missing_land_target")
            self._sm_trace(
                "DISCARD",
                reason="post_land_submit_skipped:missing_land_target",
                scheduler="enter_resume_playback",
            )
        elif not self._video_output_active:
            perf_diag.count("video.scrub.post_land_submit_skipped")
            perf_diag.note(
                "video.scrub.post_land_submit_skipped_reason", "output_inactive"
            )
            perf_diag.note("post_land_submit_skipped_reason", "output_inactive")
            self._sm_trace(
                "DISCARD",
                reason="post_land_submit_skipped:output_inactive",
                scheduler="enter_resume_playback",
            )
        else:
            before_id = int(self._async_req_id)
            self._last_decode_time = 0.0
            self._request_async_live_frame(
                float(land_t),
                kind="play",
                lock_timeout=_ASYNC_LOCK_TIMEOUT_S,
                force=True,
                scheduler="enter_resume_playback",
            )
            submitted = bool(self._async_inflight) and self._async_req_kind == "play"
            advanced = int(self._async_req_id) != before_id
            if submitted or advanced:
                perf_diag.count("video.scrub.post_land_submit_success")
                perf_diag.count("post_land_submit_success")
                perf_diag.note("video.scrub.post_land_submit_skipped_reason", None)
                perf_diag.note("post_land_submit_skipped_reason", None)
                self._sm_trace(
                    "SCHEDULE_NEXT_PLAY",
                    song_time=float(land_t),
                    media_time=self._media_time_for_song(float(land_t)),
                    request_id=int(self._async_req_id),
                    kind="play",
                    scheduler="enter_resume_playback",
                    reason="post_land_submit_success",
                    extra={
                        "media_session_generation": self._media_session_gen,
                        "scrub_transaction_generation": self._scrub_session_gen,
                        "playback_request_sequence": self._playback_request_seq,
                    },
                )
            else:
                perf_diag.count("video.scrub.post_land_submit_skipped")
                perf_diag.note(
                    "video.scrub.post_land_submit_skipped_reason",
                    "request_did_not_advance",
                )
                perf_diag.note(
                    "post_land_submit_skipped_reason", "request_did_not_advance"
                )
                self._sm_trace(
                    "DISCARD",
                    song_time=land_t,
                    reason="post_land_submit_skipped:request_did_not_advance",
                    scheduler="enter_resume_playback",
                )
        self._resume_watchdog.start(_RESUME_WATCHDOG_MS)

    def _on_resume_watchdog(self) -> None:
        """Recover if resume has not presented a post-land playback frame."""
        if self._pipeline_state != VideoPipelineState.RESUME_PLAYBACK:
            return
        if not self._resume_pending:
            return
        perf_diag.count("video.scrub.resume_timeout")
        self._recover_resume_playback()

    def _recover_resume_playback(self) -> None:
        """Reset play decoder and seek to current clock — do not stay frozen."""
        perf_diag.count("video.scrub.resume_recovery_started")
        perf_diag.note("video.scrub.resume_recovery_reason", "decoder_reset_seek")
        # Invalidate first so in-flight play work drops, then reset only when idle.
        self._invalidate_async_requests()
        if not self._async_inflight:
            self._close_play_worker_decoders()
        else:
            # Worker still finishing — reopen on next schedule after result drops.
            self._play_decoder_reset_pending = True
        song = self._song
        t = self._last_position_seconds
        if t is None:
            t = self._release_target_song_time
        if song is not None and t is not None and self._video_output_active:
            recover_t0 = monotonic()
            self._request_async_live_frame(
                float(t),
                kind="play",
                lock_timeout=_ASYNC_LAND_LOCK_TIMEOUT_S,
                force=True,
                scheduler="resume_watchdog_recovery",
            )
            perf_diag.record_ms(
                "video.scrub.playback_decoder_ready_ms",
                (monotonic() - recover_t0) * 1000.0,
            )
        if not self._resume_recovery_attempted:
            self._resume_recovery_attempted = True
            self._resume_watchdog.start(_RESUME_RECOVERY_MS)
            return
        # Bound freeze: leave RESUME even if decode still empty.
        self._complete_resume(reason="recovery")

    def _complete_resume(self, *, reason: str = "frame") -> None:
        if self._pipeline_state != VideoPipelineState.RESUME_PLAYBACK:
            return
        self._resume_watchdog.stop()
        self._resume_pending = False
        self._resume_required = False
        if self._resume_started_mono > 0.0:
            elapsed = (monotonic() - self._resume_started_mono) * 1000.0
            perf_diag.record_ms("video.scrub.resume_first_present_ms", elapsed)
            if reason == "frame":
                perf_diag.record_ms("video.scrub.resume_first_decode_ms", elapsed)
                perf_diag.record_ms(
                    "video.scrub.first_playback_frame_after_resume_ms", elapsed
                )
        if self._release_target_media_time is not None:
            perf_diag.note(
                "video.scrub.decoder_timestamp_at_first_resume",
                float(self._release_target_media_time),
            )
        self._set_pipeline_state(VideoPipelineState.PLAYBACK)
        # Mutual exclusion: completed XOR recovered (Windows invariant).
        if reason == "recovery":
            perf_diag.count("video.scrub.resume_recovered")
            perf_diag.count("video.scrub.resume_recovery_completed")
        else:
            perf_diag.count("video.scrub.resume_completed")
        perf_diag.note("video.scrub.resume_complete_reason", reason)
        self._min_present_seconds = None
        perf_diag.count("video.scrub.min_present_seconds_cleared")
        perf_diag.note("video.scrub.min_present_seconds_value", None)

    def _complete_final_land(self, seconds: float, frame: np.ndarray) -> None:
        """Exact land presented → establish decoder position → resume or pause."""
        present_t0 = monotonic()
        self._emit_frame(frame)
        self._last_presented_song_seconds = float(seconds)
        if self._land_request_mono > 0.0:
            perf_diag.record_ms(
                "video.scrub.final_land_present_ms",
                (monotonic() - present_t0) * 1000.0,
            )
        self._final_land_pending = False
        self._scrub_land_pending = False
        self._land_retry_timer.stop()
        self._decoder_position_established = True
        self._empty_decode_streak = 0
        perf_diag.count("video.scrub.final_land_presented")
        perf_diag.count("video.scrub.final_land_completed")
        self._note_land_complete_metrics()
        sm_trace.mark_land_present()
        self._sm_trace(
            "FINAL_LAND_PRESENT",
            song_time=float(seconds),
            media_time=(
                float(self._release_target_media_time)
                if self._release_target_media_time is not None
                else self._media_time_for_song(seconds)
            ),
            kind="land",
            scheduler="complete_final_land",
            extra={
                "pre_scrub_was_playing": self._pre_scrub_was_playing,
                "transaction_id": self._final_land_transaction_id,
            },
        )
        perf_diag.note("video.scrub.final_presented_song_time", float(seconds))
        if self._release_target_media_time is not None:
            perf_diag.note(
                "video.scrub.decoder_timestamp_after_land",
                float(self._release_target_media_time),
            )
        if self._scrub_release_mono > 0.0:
            elapsed = (monotonic() - self._scrub_release_mono) * 1000.0
            perf_diag.record_ms("video.scrub.final_land_exact_ms", elapsed)
            perf_diag.record_ms("video.scrub.resume_first_frame_ms", elapsed)
        if self._release_target_song_time is not None:
            self._min_present_seconds = float(self._release_target_song_time)
        else:
            self._min_present_seconds = float(seconds)
        perf_diag.note(
            "video.scrub.min_present_seconds_value", self._min_present_seconds
        )
        perf_diag.note("video.worker_inflight_after_land", bool(self._async_inflight))
        if self._pre_scrub_was_playing:
            self._enter_resume_playback()
        else:
            self._set_pipeline_state(VideoPipelineState.PLAYBACK)
            self._resume_pending = False
            self._resume_required = False
            self._playback_resume_generation += 1

    def _maybe_preload_scrub(self) -> None:
        if not self._scrubbing or not self._video_output_active:
            return
        song = self._song
        if song is None:
            return
        self._scrub_cache.preload(list(song.video_clips))

    def _decode_last_position_if_active(self) -> None:
        if not self._video_output_active:
            return
        song = self._song
        seconds = self._last_position_seconds
        if song is None or seconds is None:
            return
        self._invalidate_async_requests()
        self._decode_and_emit(
            song, seconds, lock_timeout=_SYNC_LAND_LOCK_TIMEOUT_S
        )

    def land_frame_at(self, seconds: float | None = None) -> None:
        """Decode+emit one frame now, ignoring seek/play throttle.

        Used after ``set_song`` / project open so Preview is not stuck black
        until the user opens Clean Output (which used to be the only path
        that re-armed decode when output was already marked active).
        """
        if seconds is not None:
            self._last_position_seconds = float(seconds)
        if not self._video_output_active:
            return
        song = self._song
        pos = self._last_position_seconds
        if song is None or pos is None:
            return
        self._invalidate_async_requests()
        self._flush_timer.stop()
        self._pending_clip = None
        self._pending_seconds = None
        self._last_decode_time = 0.0
        self._maybe_warn_overlap(song, float(pos))
        primary = song.active_video_clip_at(float(pos))
        self._set_active(primary.id if primary else None)
        self._decode_and_emit(
            song, float(pos), lock_timeout=_SYNC_LAND_LOCK_TIMEOUT_S
        )

    def set_playing(self, active: bool) -> None:
        """Call from AudioEngine.playing_changed.

        While playing, decode work is throttled to _MAX_PLAY_DECODE_HZ and
        runs on the latest-wins worker (dedicated decoders). Without the
        throttle + off-UI decode, every ~16ms position_changed tick would
        stall the same thread that paints the timeline. Stop lands with a
        one-shot sync decode for frame accuracy.
        """
        active = bool(active)
        if active == self._playing:
            return
        self._playing = active
        if not active:
            # Do not invalidate an in-flight exclusive final-land.
            if self._pipeline_state == VideoPipelineState.FINAL_LANDING:
                self._flush_timer.stop()
                return
            # Playback just stopped: land on the exact final position, not
            # a throttled / in-flight async stand-in.
            self._invalidate_async_requests()
            self._flush_timer.stop()
            self._flush_pending()

    def set_decode_quality(self, quality: VideoDecodeQuality) -> None:
        """Cap decoded frame height (preview + Clean Output share one decode
        path — see AGENTS.md "no second independent video player" — so this
        affects both at once). "full" restores source resolution."""
        max_height = VIDEO_DECODE_QUALITY_MAX_HEIGHT.get(quality)
        if quality == self._decode_quality:
            return
        self._decode_quality = quality
        self._decode_max_height = max_height
        # Cached decoders were opened for the old cap; drop them so the next
        # frame request reopens at the new one. Scrub posters use their own
        # fixed height — leave that cache warm.
        self._close_all_decoders()

    def set_song(self, song: Song | None) -> None:
        self._song = song
        self._media_session_gen += 1
        perf_diag.note("video.media_session_generation", self._media_session_gen)
        self._invalidate_async_requests()
        self._play_pending_seconds = None
        self._cancel_pending()
        self._scrub_preview_timer.stop()
        self._scrub_pause_timer.stop()
        self._cancel_scrub_resume_transaction(reason="song_switch")
        self._scrubbing = False
        self._set_pipeline_state(VideoPipelineState.PLAYBACK)
        self._close_all_decoders()
        self._scrub_cache.clear()
        self._warned_overlap_keys.clear()
        self._set_active(None)
        self._last_valid_frame = None
        self._last_valid_frame_mono = 0.0
        self._last_valid_frame_song_seconds = None
        self._last_emitted_frame = _UNSET  # force this emit through even if unchanged
        self._emit_frame(None, allow_clear=True, reason="song_switch")
        # Do not preload scrub ladders here — song switch + Clean Output used
        # to start a PyAV storm that blocked live decode via av_path_lock.

    def refresh(self) -> None:
        """Call after clips are added / removed / re-pathed."""
        if self._song is None:
            self._close_all_decoders()
            self._scrub_cache.clear()
            return
        valid_ids = {clip.id for clip in self._song.video_clips}
        for clip_id in list(self._decoders):
            if clip_id not in valid_ids:
                self._decoders.pop(clip_id).close()
                self._decoder_paths.pop(clip_id, None)
                self._scrub_cache.drop_clip(clip_id)
        with self._worker_lock:
            for clip_id in list(self._worker_decoders):
                if clip_id not in valid_ids:
                    self._worker_decoders.pop(clip_id).close()
                    self._worker_decoder_paths.pop(clip_id, None)
            for clip_id in list(self._scrub_worker_decoders):
                if clip_id not in valid_ids:
                    self._scrub_worker_decoders.pop(clip_id).close()
                    self._scrub_worker_decoder_paths.pop(clip_id, None)
        # Only refresh scrub posters if the user is mid-drag; otherwise wait
        # for the next scrub_started to avoid contending with live decode.
        if self._scrubbing and self._video_output_active:
            self._scrub_cache.preload(list(self._song.video_clips))

    def update_position(self, seconds: float, *, source: str = "engine") -> None:
        """Schedule video for Song Time ``seconds``.

        Canonical sources (exactly one during normal play):
        - ``source="engine"`` — MainWindow position fan-out (AudioEngine clock)
        - ``source="scrub"`` — Timeline scrub_preview_requested while dragging
        """
        perf_diag.count("video.update_position.calls")
        perf_diag.count(f"video.schedule.source.{source}")
        perf_diag.note("video.pipeline_mode", PIPELINE_MODE)
        perf_diag.note("video.pipeline_state", self._pipeline_state)

        # Scrub / final-land own Video: gate engine BEFORE mutating last position
        # (otherwise a late clock tick can overwrite the release target).
        if source == "engine":
            if (
                self._scrubbing
                or self._pipeline_state == VideoPipelineState.SCRUB_PREVIEW
            ):
                perf_diag.count("video.scrub.engine_requests_gated_during_scrub")
                return
            if self._pipeline_state == VideoPipelineState.FINAL_LANDING:
                perf_diag.count("video.scrub.engine_requests_blocked_during_land")
                return

        self._last_position_seconds = float(seconds)

        if (
            source == "engine"
            and self._decoder_position_established
            and self._pipeline_state == VideoPipelineState.RESUME_PLAYBACK
            and self._resume_started_mono > 0.0
            and not self._resume_first_engine_noted
        ):
            self._resume_first_engine_noted = True
            perf_diag.record_ms(
                "video.scrub.resume_first_engine_request_ms",
                (monotonic() - self._resume_started_mono) * 1000.0,
            )
            # Engine is advancing — resume is live even before next unique frame.
            # Watchdog still covers decode stalls; first play present also completes.

        if not self._video_output_active:
            return
        song = self._song
        if song is None:
            self._cancel_pending()
            self._set_active(None)
            self._emit_frame(None, allow_clear=True, reason="no_song")
            return

        self._maybe_warn_overlap(song, seconds)

        clips = song.active_video_clips_at(seconds)
        if not clips:
            self._cancel_pending()
            self._set_active(None)
            # Scrub / final-land: never clear a valid preview on a timeline gap.
            if (
                self._scrubbing
                or self._pipeline_state
                in (
                    VideoPipelineState.SCRUB_PREVIEW,
                    VideoPipelineState.FINAL_LANDING,
                )
            ):
                perf_diag.count("video.empty_decode.reason.timeline_gap")
                return
            # Playback into a gap: intentional no-media (allow clear).
            self._emit_frame(None, allow_clear=True, reason="timeline_gap_playback")
            return

        primary = song.active_video_clip_at(seconds)
        self._set_active(primary.id if primary else None)

        # --- SCRUB PREVIEW POLICY (canonical source=scrub while dragging) ---
        # Raw mouse events only update the target + optional cheap posters.
        # Live PyAV is driven by the scrub preview timer / pause-priority.
        if self._scrubbing or self._pipeline_state == VideoPipelineState.SCRUB_PREVIEW:
            if source == "scrub":
                perf_diag.count("video.scrub.raw_position_events")
            self._scrub_target_seconds = float(seconds)
            self._pending_clip = primary
            self._pending_seconds = seconds
            # Warm posters follow at preview cadence (not every raw mouse event —
            # QImage convert still runs on the UI thread).
            frame = self._scrub_composite(song, seconds)
            now = monotonic()
            if frame is not None and (
                self._last_decode_time <= 0.0
                or (now - self._last_decode_time) >= (1.0 / _SCRUB_PREVIEW_HZ)
            ):
                self._last_decode_time = now
                self._emit_frame(frame)
                self._note_preview_presented(float(seconds))
            # Restart pause-priority: when the pointer settles, decode now.
            if self._video_output_active:
                self._scrub_pause_timer.start()
                if not self._scrub_preview_timer.isActive():
                    self._scrub_preview_timer.start()
            return

        # During FINAL_LANDING non-engine paths should not schedule play either.
        if self._pipeline_state == VideoPipelineState.FINAL_LANDING:
            perf_diag.count("video.scrub.engine_requests_dropped_during_land")
            return

        # Round 8: PLAYBACK / RESUME — pending-latest, no gen starvation.
        if self._playing or self._pipeline_state == VideoPipelineState.RESUME_PLAYBACK:
            self._schedule_playback_target(
                float(seconds),
                scheduler=(
                    "update_position_playing"
                    if source == "engine"
                    else f"update_position_{source}"
                ),
            )
            return

        min_interval = self._current_min_decode_interval()
        if min_interval > 0.0:
            now = monotonic()
            elapsed = now - self._last_decode_time
            if self._last_decode_time > 0.0 and elapsed < min_interval:
                self._pending_clip = primary
                self._pending_seconds = seconds
                if not self._flush_timer.isActive():
                    remaining_ms = max(1, int((min_interval - elapsed) * 1000))
                    self._flush_timer.start(remaining_ms)
                return

        # Mixer window decode in flight: keep the last frame instead of
        # fighting for ``av_path_lock`` (felt as gradually rising卡顿).
        if self._playing and self._defer_live_decode is not None:
            try:
                if bool(self._defer_live_decode()):
                    self._pending_clip = primary
                    self._pending_seconds = seconds
                    return
            except Exception:
                pass

        self._pending_clip = primary
        self._pending_seconds = seconds
        self._decode_and_emit(song, seconds, lock_timeout=_SYNC_LAND_LOCK_TIMEOUT_S)

    def _schedule_playback_target(
        self,
        seconds: float,
        *,
        scheduler: str,
        force: bool = False,
    ) -> None:
        """Schedule sequential playback decode (Round 8 pending-latest policy).

        Invariant: if PLAYBACK/RESUME, playing, worker IDLE, no pending work,
        a valid engine update must submit immediately.
        """
        seconds = float(seconds)
        if not self._video_output_active:
            self._note_play_schedule_skip(
                seconds, reason="output_inactive", scheduler=scheduler
            )
            return
        song = self._song
        if song is not None:
            primary = song.active_video_clip_at(seconds)
            self._pending_clip = primary
            self._pending_seconds = seconds
            self._set_active(primary.id if primary else None)
        if self._defer_live_decode is not None and self._playing and not force:
            try:
                if bool(self._defer_live_decode()):
                    self._play_pending_seconds = seconds
                    perf_diag.note("video.playback.pending_latest_target", seconds)
                    self._note_play_schedule_skip(
                        seconds, reason="defer_live_decode", scheduler=scheduler
                    )
                    return
            except Exception:
                pass

        # Worker busy with play: keep one pending latest — do not invalidate.
        if (
            self._async_inflight
            and self._async_req_kind == "play"
            and not force
        ):
            self._play_pending_seconds = seconds
            self._playback_request_seq += 1
            perf_diag.note("video.playback.pending_latest_target", seconds)
            perf_diag.note(
                "video.playback.request_sequence", self._playback_request_seq
            )
            self._sm_trace(
                "SCHEDULE_NEXT_PLAY",
                song_time=seconds,
                media_time=self._media_time_for_song(seconds),
                kind="play",
                scheduler=scheduler,
                reason="pending_latest_only",
                extra={"playback_request_sequence": self._playback_request_seq},
            )
            return

        # Worker busy with scrub/land: cannot steal without force.
        if self._async_inflight and self._async_req_kind != "play" and not force:
            self._play_pending_seconds = seconds
            perf_diag.note("video.playback.pending_latest_target", seconds)
            self._note_play_schedule_skip(
                seconds,
                reason=f"worker_busy_{self._async_req_kind}",
                scheduler=scheduler,
            )
            return

        # Idle: submit immediately (ignore play-rate throttle when idle —
        # throttle caused engine_fanout_post_land logs without request_id advance).
        if self._worker_idle_since_mono is not None:
            idle_ms = (monotonic() - self._worker_idle_since_mono) * 1000.0
            perf_diag.record_ms("video.playback.worker_idle_without_request_ms", idle_ms)
            self._worker_idle_since_mono = None
        self._play_pending_seconds = None
        self._last_decode_time = monotonic()
        self._request_async_live_frame(
            seconds,
            kind="play",
            lock_timeout=_ASYNC_LOCK_TIMEOUT_S,
            force=force,
            scheduler=scheduler,
        )

    def _note_play_schedule_skip(
        self, seconds: float, *, reason: str, scheduler: str
    ) -> None:
        """Engine/fan-out observed but intentionally did not submit (Round 8)."""
        perf_diag.count(f"video.playback.schedule_skip.{reason}")
        gap = sm_trace.gap_ms_since_land_present()
        if gap is not None and gap < 2000.0:
            self._sm_trace(
                "SCHEDULE_NEXT_PLAY",
                song_time=seconds,
                kind="play",
                scheduler=scheduler,
                reason=f"skip:{reason}",
                inflight=bool(self._async_inflight),
                extra={
                    "ms_since_land_present": gap,
                    "worker_runtime": sm_trace.worker_runtime(),
                    "request_id_unchanged": True,
                },
            )

    def _on_scrub_preview_tick(self) -> None:
        """Sample latest scrub target at controlled preview FPS."""
        if not self._scrubbing or not self._video_output_active:
            self._scrub_preview_timer.stop()
            return
        perf_diag.count("video.scrub.preview_ticks")
        self._request_scrub_preview_decode(priority=False)

    def _on_scrub_pause_priority(self) -> None:
        """Pointer paused mid-drag — decode the latest target immediately."""
        if not self._scrubbing or not self._video_output_active:
            return
        perf_diag.count("video.scrub.pause_priority_requests")
        self._request_scrub_preview_decode(priority=True)

    def _request_scrub_preview_decode(self, *, priority: bool) -> None:
        song = self._song
        if song is None:
            return
        target = float(self._scrub_target_seconds)
        last = self._scrub_last_requested_seconds
        if (
            not priority
            and last is not None
            and abs(target - last) < _SCRUB_MIN_TARGET_DELTA_S
        ):
            return
        # Prefer posters when warm (skip PyAV).
        poster = self._scrub_composite(song, target)
        if poster is not None:
            self._last_decode_time = monotonic()
            self._scrub_last_requested_seconds = target
            self._emit_frame(poster)
            self._note_preview_presented(target)
            return
        self._scrub_last_requested_seconds = target
        perf_diag.count("video.scrub.preview_requests")
        self._last_decode_time = monotonic()
        req_id = sm_trace.next_request_id()
        self._sm_trace(
            "SCRUB_PREVIEW_REQUEST",
            song_time=target,
            media_time=self._media_time_for_song(target),
            request_id=req_id,
            kind="scrub_preview",
            extra={"priority": bool(priority)},
        )
        self._request_async_live_frame(
            target,
            kind="scrub_preview",
            lock_timeout=_ASYNC_SCRUB_LOCK_TIMEOUT_S,
            request_id=req_id,
        )

    def _current_min_decode_interval(self) -> float:
        """Minimum seconds between actual decode+emit work. Scrubbing takes
        priority over playing (both can briefly be true: dragging the
        playhead pauses the engine without firing playing_changed — see
        AudioEngine.begin_scrub/pause(for_scrub=True)). Idle/paused seeks
        still coalesce so rapid mouse jumps cannot stack PyAV on the UI
        thread while mixer/standin hold ``av_path_lock``."""
        if self._scrubbing:
            return _MIN_SCRUB_DECODE_INTERVAL
        if self._playing:
            return float(self._min_play_decode_interval)
        return _MIN_SEEK_DECODE_INTERVAL

    def _scrub_composite(self, song: Song, seconds: float) -> np.ndarray | None:
        """Nearest scrub-cache frames for the active clip(s), or None if cold."""
        clips = song.active_video_clips_at(seconds)
        if not clips:
            return None
        weighted: list[tuple[VideoClip, float]] = []
        for clip in clips:
            weight = video_clip_crossfade_weight(clip, seconds, song.video_clips)
            if weight > 1e-6:
                weighted.append((clip, weight))
        if not weighted:
            return None
        if len(weighted) == 1:
            clip, _weight = weighted[0]
            if clip.media_kind == "still":
                decoder = self._decoder_for(clip)
                if decoder is None:
                    return None
                try:
                    return decoder.frame_at(clip.source_time_for(seconds))
                except Exception:
                    return None
            return self._scrub_cache.nearest(clip.id, clip.source_time_for(seconds))
        total_weight = sum(w for _clip, w in weighted)
        composite: np.ndarray | None = None
        for clip, weight in weighted:
            if clip.media_kind == "still":
                decoder = self._decoder_for(clip)
                try:
                    frame = decoder.frame_at(clip.source_time_for(seconds)) if decoder else None
                except Exception:
                    frame = None
            else:
                frame = self._scrub_cache.nearest(clip.id, clip.source_time_for(seconds))
            if frame is None:
                continue
            scaled = frame.astype(np.float32) * (weight / total_weight)
            composite = scaled if composite is None else composite + scaled
        if composite is None:
            return None
        return np.clip(composite, 0, 255).astype(np.uint8)

    def _decode_and_emit(
        self,
        song: Song,
        seconds: float,
        *,
        lock_timeout: float | None = _SYNC_LAND_LOCK_TIMEOUT_S,
    ) -> None:
        with perf_diag.span("video.decode.sync"):
            self._last_decode_time = monotonic()
            self._pending_clip = None
            self._pending_seconds = None
            frame = self._decode_frame_array(
                song, seconds, worker=False, lock_timeout=lock_timeout
            )
            if frame is not None:
                self._emit_frame(frame)
                return
            # Contended lock / cold miss: do not paint black or block for seconds —
            # follow up on the async worker (latest-wins).
            if lock_timeout is not None and self._video_output_active:
                perf_diag.count("video.sync_land_fallback_async")
                self._request_async_live_frame(
                    seconds, kind="land", lock_timeout=_ASYNC_LAND_LOCK_TIMEOUT_S
                )
                return
            # Keep last valid frame — do not clear on empty sync decode.
            perf_diag.count("video.async_empty_keep_last")
            perf_diag.count("video.empty_decode.reason.sync_empty")

    def _invalidate_async_requests(self) -> None:
        """Bump generation so in-flight worker results are discarded."""
        self._async_req_gen += 1
        perf_diag.count("video.async_invalidate")

    def _request_async_live_frame(
        self,
        seconds: float,
        *,
        kind: str = "play",
        lock_timeout: float = _ASYNC_LOCK_TIMEOUT_S,
        force: bool = False,
        request_id: int | None = None,
        scheduler: str | None = None,
    ) -> None:
        """Latest-wins schedule: overwrite pending time; at most one worker job.

        Round 6 scrub preview policy: while a scrub_preview decode is in flight,
        only update the latest target — do **not** bump generation (that caused
        160 requests → 3 presents). After the in-flight decode completes, the
        worker redoes if the target moved. Far jumps may cancel.
        """
        kind = str(kind)
        # Critical priority: land cannot be overwritten by play/preview.
        if (
            not force
            and self._pipeline_state == VideoPipelineState.FINAL_LANDING
            and kind != "land"
        ):
            if kind == "play":
                perf_diag.count("video.scrub.engine_requests_dropped_during_land")
                perf_diag.count("video.scrub.final_land_overwritten_attempts")
                self._sm_trace(
                    "DISCARD",
                    song_time=seconds,
                    kind=kind,
                    reason="engine_during_final_landing",
                    scheduler=scheduler or "unknown",
                )
            return
        if (
            not force
            and self._final_land_pending
            and kind != "land"
            and self._pipeline_state == VideoPipelineState.FINAL_LANDING
        ):
            perf_diag.count("video.scrub.final_land_overwritten_attempts")
            self._sm_trace(
                "DISCARD",
                song_time=seconds,
                kind=kind,
                reason="final_land_pending",
                scheduler=scheduler or "unknown",
            )
            return

        # Scrub preview coalesce: update target only — keep in-flight gen alive.
        if (
            kind == "scrub_preview"
            and self._async_inflight
            and self._async_req_kind == "scrub_preview"
            and not force
        ):
            prev = float(self._async_req_seconds)
            self._async_req_seconds = float(seconds)
            self._async_lock_timeout = float(lock_timeout)
            perf_diag.count("video.async_coalesce")
            perf_diag.count("video.scrub.preview_coalesced")
            # Far jump: cancel expensive obsolete seek.
            if abs(float(seconds) - prev) >= _PREVIEW_CANCEL_DELTA_S:
                self._async_req_gen += 1
                self._preview_request_seq += 1
                perf_diag.count("video.scrub.preview_reject_reason.far_cancel")
                self._sm_trace(
                    "DISCARD",
                    song_time=seconds,
                    kind=kind,
                    reason="far_cancel_inflight",
                    extra={"prev_song_time": prev},
                )
            return

        # Round 8 play: while a play decode is in flight, keep one pending
        # latest target — do NOT bump generation (that starved presentation).
        if (
            kind == "play"
            and self._async_inflight
            and self._async_req_kind == "play"
            and not force
        ):
            self._play_pending_seconds = float(seconds)
            self._playback_request_seq += 1
            perf_diag.count("video.async_coalesce")
            perf_diag.count("video.playback.inflight_supersede_count")
            perf_diag.note("video.playback.pending_latest_target", float(seconds))
            perf_diag.note(
                "video.playback.request_sequence", self._playback_request_seq
            )
            self._sm_trace(
                "SCHEDULE_NEXT_PLAY",
                song_time=seconds,
                media_time=self._media_time_for_song(seconds),
                kind="play",
                scheduler=scheduler or "request_async_live_frame",
                reason="pending_latest_only",
                extra={"playback_request_sequence": self._playback_request_seq},
            )
            return

        # Bump generation only for scrub/land (or forced play that must cancel
        # non-play work). Ordinary play must not invalidate in-flight play.
        if kind != "play":
            self._async_req_gen += 1
        elif force and self._async_inflight and self._async_req_kind != "play":
            self._async_req_gen += 1
            perf_diag.count("video.playback.inflight_supersede_count")
        elif force and self._async_inflight and self._async_req_kind == "play":
            # Force play while play inflight: replace target, keep same gen so
            # the in-flight result can still present if within lateness.
            self._async_req_seconds = float(seconds)
            self._async_lock_timeout = float(lock_timeout)
            self._playback_request_seq += 1
            if request_id is None:
                request_id = sm_trace.next_request_id()
            self._async_req_id = int(request_id)
            perf_diag.note(
                "video.playback.request_sequence", self._playback_request_seq
            )
            self._sm_trace(
                "SCHEDULE_NEXT_PLAY",
                song_time=seconds,
                request_id=int(request_id),
                kind="play",
                scheduler=scheduler or "request_async_live_frame",
                reason="force_replace_inflight_target",
            )
            return

        if kind == "scrub_preview":
            self._preview_request_seq += 1
        if kind == "play":
            self._playback_request_seq += 1
            perf_diag.note(
                "video.playback.request_sequence", self._playback_request_seq
            )
        self._async_req_seconds = float(seconds)
        self._async_req_kind = kind
        self._async_lock_timeout = float(lock_timeout)
        self._async_req_session = int(self._scrub_session_gen)
        self._async_req_media_session = int(self._media_session_gen)
        self._async_req_started_mono = monotonic()
        if request_id is None:
            request_id = sm_trace.next_request_id()
        self._async_req_id = int(request_id)
        sm_trace.set_current_request_id(int(request_id))
        if kind == "land":
            self._land_request_mono = monotonic()
        if (
            kind == "play"
            and self._play_decoder_reset_pending
            and not self._async_inflight
        ):
            self._play_decoder_reset_pending = False
            self._close_play_worker_decoders()

        # Round 7/8: who schedules play after land / during resume.
        if kind == "play":
            who = scheduler or "request_async_live_frame"
            coalesce = bool(self._async_inflight)
            gap = sm_trace.gap_ms_since_land_present()
            in_resume = self._pipeline_state == VideoPipelineState.RESUME_PLAYBACK
            if in_resume or force or (
                gap is not None and (coalesce or float(gap) < 2000.0)
            ):
                self._sm_trace(
                    "SCHEDULE_NEXT_PLAY",
                    song_time=seconds,
                    media_time=self._media_time_for_song(seconds),
                    request_id=int(request_id),
                    kind="play",
                    scheduler=who,
                    reason=("coalesce_worker_busy" if coalesce else "submit_or_idle"),
                    extra={
                        "force": bool(force),
                        "pipeline_state": self._pipeline_state,
                        "ms_since_land_present": gap,
                        "ms_since_resume_begin": sm_trace.gap_ms_since_resume_begin(),
                        "playback_request_sequence": self._playback_request_seq,
                        "media_session_generation": self._media_session_gen,
                        "scrub_transaction_generation": self._scrub_session_gen,
                    },
                )

        perf_diag.count("video.async_schedule")
        perf_diag.note("video.worker_inflight", True)
        if self._async_inflight:
            perf_diag.count("video.async_coalesce")
            if kind == "scrub_preview":
                perf_diag.count("video.scrub.preview_coalesced")
            return
        self._async_inflight = True
        self._worker_idle_since_mono = None
        self._async_pool.submit(self._async_worker_loop)

    def _async_worker_loop(self) -> None:
        """Decode on a background thread with dedicated decoders (never UI pool)."""
        gen = self._async_req_gen
        try:
            while True:
                gen = self._async_req_gen
                seconds = float(self._async_req_seconds)
                kind = self._async_req_kind
                lock_timeout = float(self._async_lock_timeout)
                session = int(self._async_req_session)
                media_session = int(self._async_req_media_session)
                song = self._song
                frame: np.ndarray | None = None
                empty_reason = ""
                decode_t0 = monotonic()
                use_scrub_decoder = kind in ("scrub_preview", "land")
                req_id = int(self._async_req_id)
                if kind == "land":
                    self._land_worker_start_mono = decode_t0
                    if self._land_request_mono > 0.0:
                        perf_diag.record_ms(
                            "video.scrub.final_land_worker_queue_wait_ms",
                            (decode_t0 - self._land_request_mono) * 1000.0,
                        )
                    self._sm_trace(
                        "FINAL_LAND_DECODE_BEGIN",
                        song_time=seconds,
                        media_time=self._media_time_for_song(seconds),
                        generation=gen,
                        request_id=req_id,
                        kind="land",
                    )
                if kind == "scrub_preview" and self._async_req_started_mono > 0.0:
                    perf_diag.record_ms(
                        "video.scrub.preview_worker_busy_ms",
                        (decode_t0 - self._async_req_started_mono) * 1000.0,
                    )
                # Generation check before expensive seek/decode.
                # Round 8: ordinary play does not bump _async_req_gen, so a
                # mismatch here means scrub/song/stop invalidate — cancel.
                if gen != self._async_req_gen:
                    perf_diag.count("video.async_stale_drop")
                    self._sm_worker_runtime(
                        sm_trace.WorkerRuntime.CANCELLED,
                        request_id=req_id,
                        reason="generation_mismatch_before_decode",
                        song_time=seconds,
                        kind=kind,
                    )
                    self._sm_trace(
                        "STALE_DROP",
                        song_time=seconds,
                        generation=gen,
                        request_id=req_id,
                        kind=kind,
                        reason="generation_mismatch_before_decode",
                        extra={"current_gen": int(self._async_req_gen)},
                    )
                    if kind == "scrub_preview":
                        perf_diag.count("video.scrub.preview_stale_drop")
                        perf_diag.count(
                            "video.scrub.preview_reject_reason.generation_mismatch"
                        )
                    elif kind == "land":
                        perf_diag.count("video.scrub.final_land_superseded")
                    elif kind == "play":
                        # Not ordinary clock — scrub/song/stop invalidate.
                        perf_diag.count(
                            "video.playback.frame_drop.reason.session_changed"
                            if session != self._scrub_session_gen
                            or media_session != self._media_session_gen
                            else "video.playback.frame_drop.reason.generation_mismatch"
                        )
                        perf_diag.count("video.playback.decode_starved")
                    continue
                if song is None:
                    empty_reason = "no_song"
                elif not self._video_output_active:
                    empty_reason = "output_inactive"
                else:
                    if kind == "land":
                        tgt = self._release_target
                        if tgt is not None and not tgt.is_valid:
                            empty_reason = f"invalid_target:{tgt.kind}"
                        elif song.active_video_clip_at(seconds) is None:
                            empty_reason = "timeline_gap"
                    if not empty_reason:
                        try:
                            # SEEKING/DECODING transitions are recorded inside
                            # MediaDecoder.frame_at when CUEPLAYER_PERF=1.
                            self._sm_worker_runtime(
                                sm_trace.WorkerRuntime.SEEKING,
                                request_id=req_id,
                                reason="worker_enter_decode",
                                song_time=seconds,
                                kind=kind,
                            )
                            with perf_diag.span("video.decode.async"):
                                frame = self._decode_frame_array(
                                    song,
                                    seconds,
                                    worker=True,
                                    lock_timeout=lock_timeout,
                                    stale_on_timeout=(kind != "land"),
                                    scrub_decoder=use_scrub_decoder,
                                )
                        except Exception as exc:  # noqa: BLE001
                            frame = None
                            empty_reason = f"decode_exception:{type(exc).__name__}"
                        if kind == "land":
                            perf_diag.record_ms(
                                "video.scrub.final_land_decode_ms",
                                (monotonic() - decode_t0) * 1000.0,
                            )
                            self._sm_trace(
                                "FINAL_LAND_DECODE_DONE",
                                song_time=seconds,
                                media_time=self._media_time_for_song(seconds),
                                generation=gen,
                                request_id=req_id,
                                kind="land",
                                reason=empty_reason or (
                                    "ok" if frame is not None else "empty"
                                ),
                                extra={
                                    "decode_ms": (monotonic() - decode_t0) * 1000.0,
                                    "has_frame": frame is not None,
                                },
                            )
                        if frame is None and not empty_reason:
                            empty_reason = self._classify_empty_decode(
                                song, seconds, kind=kind
                            )
                # Generation / session check after decode.
                # Round 8: play never bumps gen on clock ticks, so mismatch means
                # real invalidate (scrub/song/stop) — drop. Lateness is applied on UI.
                emit_frame = False
                if gen != self._async_req_gen:
                    perf_diag.count("video.async_stale_drop")
                    self._sm_worker_runtime(
                        sm_trace.WorkerRuntime.CANCELLED,
                        request_id=req_id,
                        reason="generation_mismatch_after_decode",
                        song_time=seconds,
                        kind=kind,
                    )
                    self._sm_trace(
                        "STALE_DROP",
                        song_time=seconds,
                        generation=gen,
                        request_id=req_id,
                        kind=kind,
                        reason="generation_mismatch_after_decode",
                        extra={"current_gen": int(self._async_req_gen)},
                    )
                    if kind == "scrub_preview":
                        perf_diag.count("video.scrub.preview_stale_drop")
                        latest = float(self._async_req_seconds)
                        if (
                            session == self._scrub_session_gen
                            and abs(seconds - latest)
                            <= _PREVIEW_PRESENT_TOLERANCE_S
                        ):
                            emit_frame = True
                        else:
                            perf_diag.count(
                                "video.scrub.preview_superseded_after_decode"
                            )
                    elif kind == "land":
                        perf_diag.count("video.scrub.final_land_superseded")
                    elif kind == "play":
                        perf_diag.count(
                            "video.playback.frame_drop.reason.session_changed"
                            if session != self._scrub_session_gen
                            or media_session != self._media_session_gen
                            else "video.playback.frame_drop.reason.generation_mismatch"
                        )
                        perf_diag.count("video.playback.decode_starved")
                    elif self._scrub_land_pending or self._final_land_pending:
                        perf_diag.count(
                            "video.scrub.old_generation_drop_after_release"
                        )
                else:
                    emit_frame = True
                    if kind == "play":
                        perf_diag.count("video.playback.decode_completed")

                if emit_frame:
                    perf_diag.count("video.async_decoded")
                    self._sm_worker_runtime(
                        sm_trace.WorkerRuntime.WAITING_FRAME,
                        request_id=req_id,
                        reason="decode_done_queued_to_ui",
                        song_time=seconds,
                        kind=kind,
                    )
                    self._async_frame_ready.emit(
                        gen, seconds, frame, kind, empty_reason or "", session
                    )

                # Scrub preview: redo newest target without invalidating session.
                if (
                    kind == "scrub_preview"
                    and self._async_req_kind == "scrub_preview"
                    and self._scrubbing
                    and abs(float(self._async_req_seconds) - seconds)
                    >= _SCRUB_MIN_TARGET_DELTA_S
                ):
                    if self._async_req_gen == gen:
                        perf_diag.count("video.async_redecode")
                        continue
                # Round 8 play: process one pending latest target after complete.
                if kind == "play" and self._play_pending_seconds is not None:
                    pending = float(self._play_pending_seconds)
                    self._play_pending_seconds = None
                    self._async_req_seconds = pending
                    self._async_req_kind = "play"
                    self._async_req_session = int(self._scrub_session_gen)
                    self._async_req_media_session = int(self._media_session_gen)
                    self._playback_request_seq += 1
                    self._async_req_id = sm_trace.next_request_id()
                    sm_trace.set_current_request_id(int(self._async_req_id))
                    perf_diag.count("video.async_redecode")
                    perf_diag.note(
                        "video.playback.request_sequence", self._playback_request_seq
                    )
                    perf_diag.note("video.playback.pending_latest_target", None)
                    self._sm_trace(
                        "SCHEDULE_NEXT_PLAY",
                        song_time=pending,
                        request_id=int(self._async_req_id),
                        kind="play",
                        scheduler="worker_pending_drain",
                        reason="pending_latest_after_complete",
                        extra={
                            "playback_request_sequence": self._playback_request_seq,
                        },
                    )
                    continue
                if self._async_req_gen == gen or (
                    kind == "play" and self._async_req_kind == "play"
                ):
                    break
                perf_diag.count("video.async_redecode")
        finally:
            self._async_inflight = False
            perf_diag.note("video.worker_inflight", False)
            # Never close PyAV containers from the worker finally — UI owns reset.
            if self._play_pending_seconds is not None and self._video_output_active:
                self._async_inflight = True
                perf_diag.note("video.worker_inflight", True)
                pending = float(self._play_pending_seconds)
                self._play_pending_seconds = None
                self._async_req_seconds = pending
                self._async_req_kind = "play"
                self._async_req_session = int(self._scrub_session_gen)
                self._async_req_media_session = int(self._media_session_gen)
                self._playback_request_seq += 1
                self._async_req_id = sm_trace.next_request_id()
                sm_trace.set_current_request_id(int(self._async_req_id))
                perf_diag.note(
                    "video.playback.request_sequence", self._playback_request_seq
                )
                perf_diag.note("video.playback.pending_latest_target", None)
                self._async_pool.submit(self._async_worker_loop)
            elif self._async_req_gen != gen and self._video_output_active:
                self._async_inflight = True
                perf_diag.note("video.worker_inflight", True)
                self._async_pool.submit(self._async_worker_loop)
            else:
                self._worker_idle_since_mono = monotonic()
                # Leave WAITING_FRAME until UI presents; if nothing queued, idle.
                if sm_trace.worker_runtime() not in (
                    sm_trace.WorkerRuntime.WAITING_FRAME,
                    sm_trace.WorkerRuntime.PRESENTING,
                ):
                    self._sm_worker_runtime(
                        sm_trace.WorkerRuntime.IDLE,
                        reason="worker_loop_exit",
                    )

    def _classify_empty_decode(
        self, song: Song, seconds: float, *, kind: str
    ) -> str:
        """Best-effort empty-decode reason for diagnostics (UI thread or worker)."""
        clip = song.active_video_clip_at(seconds)
        if clip is None:
            return "timeline_gap"
        try:
            if not Path(clip.path).exists():
                return "missing_media"
        except OSError:
            return "missing_media"
        if kind == "land":
            return "lock_or_seek_empty"
        return "decode_empty"

    def _on_async_frame_ready(
        self,
        gen: int,
        seconds: float,
        frame: object,
        kind: str = "play",
        empty_reason: str = "",
        scrub_session: int = -1,
    ) -> None:
        kind = str(kind or self._async_req_kind)
        session_ok = (
            scrub_session < 0 or int(scrub_session) == int(self._scrub_session_gen)
        )

        # Round 6 preview: accept in-session frames within tolerance even if
        # gen advanced (coalesce / far-cancel after decode started).
        if kind == "scrub_preview" and self._scrubbing:
            if not session_ok:
                perf_diag.count("video.scrub.preview_generation_mismatch")
                perf_diag.count("video.scrub.preview_reject_reason.session_changed")
                return
            if gen != self._async_req_gen:
                if abs(float(seconds) - float(self._scrub_target_seconds)) > (
                    _PREVIEW_PRESENT_TOLERANCE_S
                ):
                    perf_diag.count("video.scrub.preview_stale_drop")
                    perf_diag.count(
                        "video.scrub.preview_reject_reason.beyond_tolerance"
                    )
                    return
                perf_diag.count("video.scrub.preview_superseded_after_decode")
                # Fall through — still present within tolerance.
        elif kind == "play":
            # Round 8: ordinary clock does not bump _async_req_gen. A gen
            # mismatch means scrub/song/stop invalidate — drop. Also apply
            # timestamp lateness when gen still matches.
            if not session_ok:
                perf_diag.count("video.playback.frame_drop.reason.session_changed")
                perf_diag.count("video.playback.decode_starved")
                self._sm_trace(
                    "STALE_DROP",
                    song_time=float(seconds),
                    generation=int(gen),
                    kind="play",
                    reason="session_changed",
                    extra={"scrub_transaction_generation": self._scrub_session_gen},
                )
                return
            if gen != self._async_req_gen:
                perf_diag.count("video.async_stale_drop")
                perf_diag.count(
                    "video.playback.frame_drop.reason.generation_mismatch"
                )
                perf_diag.count("video.playback.decode_starved")
                self._sm_trace(
                    "STALE_DROP",
                    song_time=float(seconds),
                    generation=int(gen),
                    kind="play",
                    reason="invalidate_generation_mismatch",
                    extra={"current_gen": int(self._async_req_gen)},
                )
                return
            engine_t = self._last_position_seconds
            if engine_t is not None:
                lateness = float(engine_t) - float(seconds)
                if lateness > _PLAYBACK_LATENESS_TOLERANCE_S:
                    perf_diag.count("video.playback.frame_drop.reason.too_late")
                    perf_diag.count("video.playback.decode_starved")
                    self._sm_trace(
                        "STALE_DROP",
                        song_time=float(seconds),
                        kind="play",
                        reason="too_late",
                        extra={
                            "engine_song_time": float(engine_t),
                            "lateness_s": lateness,
                            "tolerance_s": _PLAYBACK_LATENESS_TOLERANCE_S,
                        },
                    )
                    return
            if (
                self._pipeline_state != VideoPipelineState.RESUME_PLAYBACK
                and self._last_presented_song_seconds is not None
                and float(seconds)
                < float(self._last_presented_song_seconds) - _FRAME_TOLERANCE_S
            ):
                perf_diag.count(
                    "video.playback.frame_drop.reason.newer_already_presented"
                )
                self._sm_trace(
                    "STALE_DROP",
                    song_time=float(seconds),
                    kind="play",
                    reason="newer_already_presented",
                    extra={
                        "last_presented": float(self._last_presented_song_seconds),
                    },
                )
                return
        elif gen != self._async_req_gen:
            perf_diag.count("video.async_stale_drop")
            self._sm_trace(
                "STALE_DROP",
                song_time=float(seconds),
                generation=int(gen),
                kind=kind,
                reason="ui_generation_mismatch",
                extra={"current_gen": int(self._async_req_gen)},
            )
            if self._final_land_pending or self._scrub_land_pending or not self._scrubbing:
                perf_diag.count("video.scrub.old_generation_drop_after_release")
            else:
                perf_diag.count("video.scrub.preview_stale_drop")
            return
        if not self._video_output_active:
            return

        # Late exact-land must not overwrite a newer resumed playback frame.
        if kind == "land" and self._pipeline_state in (
            VideoPipelineState.PLAYBACK,
            VideoPipelineState.RESUME_PLAYBACK,
        ):
            if self._decoder_position_established and not self._final_land_pending:
                if (
                    self._last_presented_song_seconds is not None
                    and float(seconds)
                    < float(self._last_presented_song_seconds) - _FRAME_TOLERANCE_S
                ):
                    perf_diag.count("video.scrub.old_generation_drop_after_release")
                    return

        # Soft floor: reject frames before release target (stale play pipeline).
        if self._min_present_seconds is not None and kind != "scrub_preview":
            if float(seconds) < float(self._min_present_seconds) - _FRAME_TOLERANCE_S:
                if self._pipeline_state in (
                    VideoPipelineState.RESUME_PLAYBACK,
                    VideoPipelineState.PLAYBACK,
                ):
                    perf_diag.count("video.scrub.valid_frames_rejected_after_land")
                    if self._decoder_position_established:
                        perf_diag.count(
                            "video.scrub.engine_requests_blocked_after_land"
                        )
                    self._sm_trace(
                        "DISCARD",
                        song_time=float(seconds),
                        kind=kind,
                        reason="before_min_present_seconds",
                        extra={
                            "min_present_seconds": float(self._min_present_seconds),
                        },
                    )
                else:
                    perf_diag.count("video.scrub.old_generation_drop_after_release")
                    self._sm_trace(
                        "STALE_DROP",
                        song_time=float(seconds),
                        kind=kind,
                        reason="old_generation_before_min_present",
                    )
                return

        # Prefer a warm scrub poster over a failed/None async result while dragging.
        if self._scrubbing and self._song is not None and kind != "land":
            poster = self._scrub_composite(self._song, float(seconds))
            if self._is_valid_frame_array(poster):
                self._last_decode_time = monotonic()
                self._emit_frame(poster)
                self._note_preview_presented(float(seconds))
                return

        # Empty / invalid frame handling — never accidental black.
        if frame is None or not self._is_valid_frame_array(frame):
            reason = empty_reason or (
                "zero_size" if frame is not None else "decode_empty"
            )
            perf_diag.count("video.async_empty_keep_last")
            perf_diag.count(f"video.empty_decode.reason.{reason}")
            if frame is not None and not self._is_valid_frame_array(frame):
                perf_diag.count("video.zero_size_frame_rejected")
            self._empty_decode_streak += 1
            if self._last_valid_frame_mono > 0.0:
                age_ms = (monotonic() - self._last_valid_frame_mono) * 1000.0
                perf_diag.note("video.last_valid_frame_age_ms", age_ms)
                if self._last_valid_frame_song_seconds is not None:
                    dist_ms = (
                        abs(float(seconds) - float(self._last_valid_frame_song_seconds))
                        * 1000.0
                    )
                    perf_diag.note(
                        "video.last_valid_frame_distance_from_target_ms", dist_ms
                    )

            if kind == "land" and self._final_land_pending:
                if reason in (
                    "timeline_gap",
                    "missing_media",
                    "invalid_target:TIMELINE_GAP",
                    "invalid_target:OUT_OF_RANGE",
                    "invalid_target:MISSING_MEDIA",
                    "invalid_target:INVALID_CLIP",
                    "no_song",
                ) or reason.startswith("invalid_target:"):
                    if self._release_target is not None:
                        self._resolve_non_valid_release(self._release_target)
                    else:
                        self._fail_final_land_recoverable(reason=reason)
                    return
                if self._land_budget_exhausted():
                    perf_diag.count("video.scrub.final_land_deadline_exit")
                    self._fail_final_land_recoverable(reason="retry_deadline")
                    return
                if not self._land_retry_timer.isActive():
                    self._land_retry_timer.start(_LAND_RETRY_MS)
                return
            return

        assert isinstance(frame, np.ndarray)
        self._empty_decode_streak = 0
        self._last_decode_time = monotonic()

        if kind == "land" and self._final_land_pending:
            if (
                self._release_target_song_time is not None
                and abs(float(seconds) - float(self._release_target_song_time)) > 0.5
            ):
                if self._land_budget_exhausted():
                    self._fail_final_land_recoverable(reason="target_drift")
                    return
                perf_diag.count("video.scrub.final_land_retry")
                self._schedule_final_land(float(self._release_target_song_time))
                return
            self._sm_worker_runtime(
                sm_trace.WorkerRuntime.PRESENTING,
                request_id=int(self._async_req_id) if self._async_req_id else None,
                reason="final_land_present",
                song_time=float(seconds),
                kind="land",
            )
            self._complete_final_land(float(seconds), frame)
            # Round 8: post-land play submit may already be SEEKING — never
            # overwrite that with IDLE (Windows saw false scheduler-stopped).
            if not bool(self._async_inflight):
                self._sm_worker_runtime(
                    sm_trace.WorkerRuntime.IDLE,
                    reason="after_final_land_present",
                    song_time=float(seconds),
                    kind="land",
                )
            return

        self._sm_worker_runtime(
            sm_trace.WorkerRuntime.PRESENTING,
            reason=f"present_{kind}",
            song_time=float(seconds),
            kind=kind,
        )
        self._emit_frame(frame)
        self._last_presented_song_seconds = float(seconds)
        if self._scrubbing or kind == "scrub_preview":
            self._note_preview_presented(float(seconds))
            if self._async_req_started_mono > 0.0:
                perf_diag.record_ms(
                    "video.scrub.preview_request_to_present_ms",
                    (monotonic() - self._async_req_started_mono) * 1000.0,
                )
        elif kind == "play":
            perf_diag.count("video.playback.frame_accept")
            perf_diag.count("video.playback.decode_presented")
            is_first = sm_trace.consume_first_play_pending()
            event = "FIRST_PLAY_FRAME" if is_first else "PLAY_PRESENT"
            self._sm_trace(
                event,
                song_time=float(seconds),
                media_time=self._media_time_for_song(seconds),
                kind="play",
                extra={
                    "ms_since_land_present": sm_trace.gap_ms_since_land_present(),
                    "ms_since_resume_begin": sm_trace.gap_ms_since_resume_begin(),
                    "pipeline_state": self._pipeline_state,
                    "playback_request_sequence": self._playback_request_seq,
                    "media_session_generation": self._media_session_gen,
                    "scrub_transaction_generation": self._scrub_session_gen,
                },
            )

        # RESUME_PLAYBACK → PLAYBACK after first valid post-release frame.
        if self._pipeline_state == VideoPipelineState.RESUME_PLAYBACK and kind == "play":
            self._complete_resume(reason="frame")
        # Worker may already be decoding pending-latest — do not force IDLE.
        if not bool(self._async_inflight):
            self._sm_worker_runtime(
                sm_trace.WorkerRuntime.IDLE,
                reason=f"after_present_{kind}",
                song_time=float(seconds),
                kind=kind,
            )

    def _note_preview_presented(self, seconds: float) -> None:
        self._last_scrub_preview_seconds = float(seconds)
        self._last_presented_song_seconds = float(seconds)
        perf_diag.count("video.scrub.preview_presented")
        self._scrub_preview_presented += 1
        self._sm_trace(
            "SCRUB_PREVIEW_PRESENT",
            song_time=float(seconds),
            media_time=self._media_time_for_song(seconds),
            kind="scrub_preview",
        )
        now = monotonic()
        self._scrub_preview_present_times.append(now)
        # Keep ~2s window for effective FPS.
        cutoff = now - 2.0
        self._scrub_preview_present_times = [
            t for t in self._scrub_preview_present_times if t >= cutoff
        ]
        n = len(self._scrub_preview_present_times)
        if n >= 2:
            span = self._scrub_preview_present_times[-1] - self._scrub_preview_present_times[0]
            if span > 1e-3:
                fps = (n - 1) / span
                perf_diag.note("video.scrub.preview_effective_fps", round(fps, 2))

    def _is_valid_frame_array(self, frame: object) -> bool:
        if frame is None or frame is _UNSET:
            return False
        if not isinstance(frame, np.ndarray):
            return False
        if frame.ndim < 2:
            return False
        h = int(frame.shape[0])
        w = int(frame.shape[1])
        if h <= 0 or w <= 0:
            return False
        if frame.ndim >= 3 and int(frame.shape[2]) < 3:
            return False
        return True

    def _reset_worker_decoder(self, clip_id: str) -> None:
        """Bounded recovery: recreate scrub worker decoder after repeated empties."""
        with self._worker_lock:
            old = self._scrub_worker_decoders.pop(clip_id, None)
            self._scrub_worker_decoder_paths.pop(clip_id, None)
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
        self._worker_reset_count += 1
        perf_diag.count("video.decoder_reset.worker")
        perf_diag.count("video.scrub.preview_decoder_reset")
        perf_diag.note("video.decoder_reset.clip_id", clip_id)
        perf_diag.note("video.decoder_reset.count", self._worker_reset_count)

    def _decode_frame_array(
        self,
        song: Song,
        seconds: float,
        *,
        worker: bool,
        lock_timeout: float | None = None,
        stale_on_timeout: bool = True,
        scrub_decoder: bool = False,
    ) -> np.ndarray | None:
        """Decode RGB frame at song time. ``worker=True`` uses dedicated decoders."""
        clips = song.active_video_clips_at(seconds)
        if not clips:
            return None
        weighted: list[tuple[VideoClip, float]] = []
        for clip in clips:
            weight = video_clip_crossfade_weight(clip, seconds, song.video_clips)
            if weight > 1e-6:
                weighted.append((clip, weight))
        if not weighted:
            return None

        def _frame_for(clip: VideoClip) -> np.ndarray | None:
            if not worker:
                decoder = self._decoder_for(clip)
            elif scrub_decoder:
                decoder = self._scrub_worker_decoder_for(clip)
            else:
                decoder = self._worker_decoder_for(clip)
            if decoder is None:
                return None
            try:
                return decoder.frame_at(
                    clip.source_time_for(seconds),
                    lock_timeout=lock_timeout,
                    stale_on_timeout=stale_on_timeout,
                )
            except Exception:
                return None

        if len(weighted) == 1:
            return _frame_for(weighted[0][0])
        dominant = max(weighted, key=lambda item: item[1])
        if dominant[1] / max(1e-9, sum(w for _c, w in weighted)) >= 0.98:
            return _frame_for(dominant[0])
        total_weight = sum(w for _clip, w in weighted)
        composite: np.ndarray | None = None
        for clip, weight in weighted:
            frame = _frame_for(clip)
            if frame is None:
                continue
            scaled = frame.astype(np.float32) * (weight / total_weight)
            composite = scaled if composite is None else composite + scaled
        if composite is None:
            return None
        return np.clip(composite, 0, 255).astype(np.uint8)

    def _emit_frame(
        self,
        frame: np.ndarray | None,
        *,
        allow_clear: bool = False,
        reason: str = "",
    ) -> None:
        """Present a frame. Never accidentally clear a valid preview to black.

        Identical-object skip keeps Preview/Clean from repainting the same
        ndarray every engine tick. ``allow_clear=True`` is only for intentional
        gap / song-switch / no-media states.
        """
        if frame is None:
            if not allow_clear and self._is_valid_frame_array(self._last_emitted_frame):
                perf_diag.count("video.black_present.attempt")
                perf_diag.note(
                    "video.preview_cleared.reason", f"rejected:{reason or 'none'}"
                )
                return
            if frame is self._last_emitted_frame:
                return
            self._last_emitted_frame = None
            perf_diag.count("video.emit.calls")
            if allow_clear:
                perf_diag.note("video.preview_cleared.reason", reason or "intentional")
            self.frame_changed.emit(None)
            return
        if not self._is_valid_frame_array(frame):
            perf_diag.count("video.zero_size_frame_rejected")
            perf_diag.count("video.black_present.attempt")
            return
        if frame is self._last_emitted_frame:
            return
        self._last_emitted_frame = frame
        self._last_valid_frame = frame
        self._last_valid_frame_mono = monotonic()
        if self._last_position_seconds is not None:
            self._last_valid_frame_song_seconds = float(self._last_position_seconds)
        perf_diag.count("video.emit.calls")
        self.frame_changed.emit(frame)

    def _flush_pending(self) -> None:
        clip, seconds = self._pending_clip, self._pending_seconds
        if clip is None or seconds is None or self._song is None:
            return
        if self._pipeline_state == VideoPipelineState.FINAL_LANDING:
            self._pending_clip = None
            self._pending_seconds = None
            return
        if self._song.video_clip_by_id(clip.id) is None:
            self._pending_clip = None
            self._pending_seconds = None
            return
        if self._scrubbing or self._playing:
            self._last_decode_time = monotonic()
            kind = "scrub_preview" if self._scrubbing else "play"
            timeout = (
                _ASYNC_SCRUB_LOCK_TIMEOUT_S if self._scrubbing else _ASYNC_LOCK_TIMEOUT_S
            )
            self._request_async_live_frame(
                float(seconds), kind=kind, lock_timeout=timeout
            )
            return
        self._decode_and_emit(
            self._song, float(seconds), lock_timeout=_SYNC_LAND_LOCK_TIMEOUT_S
        )

    def _cancel_pending(self) -> None:
        self._flush_timer.stop()
        self._pending_clip = None
        self._pending_seconds = None

    def _set_active(self, clip_id: str | None) -> None:
        if clip_id == self._active_clip_id:
            return
        self._active_clip_id = clip_id
        clip = self._song.video_clip_by_id(clip_id) if (clip_id and self._song) else None
        self.active_clip_changed.emit(clip)

    def _decoder_for(self, clip: VideoClip) -> MediaDecoder | None:
        cached_path = self._decoder_paths.get(clip.id)
        if cached_path == clip.path and clip.id in self._decoders:
            return self._decoders[clip.id]
        old = self._decoders.pop(clip.id, None)
        if old is not None:
            old.close()
        try:
            decoder = open_media_decoder(clip.path, max_decode_height=self._decode_max_height)
        except Exception:
            self._decoder_paths.pop(clip.id, None)
            return None
        self._decoders[clip.id] = decoder
        self._decoder_paths[clip.id] = clip.path
        return decoder

    def _worker_decoder_for(self, clip: VideoClip) -> MediaDecoder | None:
        """Open/reuse the sequential *playback* worker decoder."""
        with self._worker_lock:
            cached_path = self._worker_decoder_paths.get(clip.id)
            if cached_path == clip.path and clip.id in self._worker_decoders:
                return self._worker_decoders[clip.id]
            old = self._worker_decoders.pop(clip.id, None)
            if old is not None:
                try:
                    old.close()
                except Exception:
                    pass
            try:
                decoder = open_media_decoder(
                    clip.path, max_decode_height=self._decode_max_height
                )
            except Exception:
                self._worker_decoder_paths.pop(clip.id, None)
                return None
            self._worker_decoders[clip.id] = decoder
            self._worker_decoder_paths[clip.id] = clip.path
            return decoder

    def _scrub_worker_decoder_for(self, clip: VideoClip) -> MediaDecoder | None:
        """Open/reuse the scrub-preview / final-land worker decoder."""
        with self._worker_lock:
            cached_path = self._scrub_worker_decoder_paths.get(clip.id)
            if cached_path == clip.path and clip.id in self._scrub_worker_decoders:
                return self._scrub_worker_decoders[clip.id]
            old = self._scrub_worker_decoders.pop(clip.id, None)
            if old is not None:
                try:
                    old.close()
                except Exception:
                    pass
            try:
                decoder = open_media_decoder(
                    clip.path, max_decode_height=self._decode_max_height
                )
            except Exception:
                self._scrub_worker_decoder_paths.pop(clip.id, None)
                return None
            self._scrub_worker_decoders[clip.id] = decoder
            self._scrub_worker_decoder_paths[clip.id] = clip.path
            return decoder

    def _maybe_warn_overlap(self, song: Song, seconds: float) -> None:
        active_here = [c for c in song.video_clips if not c.hidden and c.contains(seconds)]
        if len(active_here) <= 1:
            return
        key = frozenset(c.id for c in active_here)
        if key in self._warned_overlap_keys:
            return
        self._warned_overlap_keys.add(key)
        names = ", ".join(c.name for c in active_here)
        self.overlap_warning.emit(
            f"Overlapping video clips at {seconds:.2f}s ({names}) — auto crossfade applied."
        )

    def _close_play_worker_decoders(self) -> None:
        with self._worker_lock:
            for decoder in self._worker_decoders.values():
                try:
                    decoder.close()
                except Exception:
                    pass
            self._worker_decoders.clear()
            self._worker_decoder_paths.clear()

    def _close_scrub_worker_decoders(self) -> None:
        with self._worker_lock:
            for decoder in self._scrub_worker_decoders.values():
                try:
                    decoder.close()
                except Exception:
                    pass
            self._scrub_worker_decoders.clear()
            self._scrub_worker_decoder_paths.clear()

    def _close_worker_decoders(self) -> None:
        self._close_play_worker_decoders()
        self._close_scrub_worker_decoders()

    def _close_all_decoders(self) -> None:
        for decoder in self._decoders.values():
            decoder.close()
        self._decoders.clear()
        self._decoder_paths.clear()
        self._close_worker_decoders()

    def shutdown(self) -> None:
        """Stop timers and the live-decode pool (tests / app teardown)."""
        for timer in (
            self._flush_timer,
            self._scrub_preload_timer,
            self._scrub_preview_timer,
            self._scrub_pause_timer,
            self._land_retry_timer,
            self._resume_watchdog,
        ):
            try:
                timer.stop()
            except Exception:
                pass
        self._scrubbing = False
        self._final_land_pending = False
        self._scrub_land_pending = False
        self._resume_pending = False
        self._invalidate_async_requests()
        self._async_inflight = False
        self._pipeline_state = VideoPipelineState.PLAYBACK
        try:
            self._async_pool.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            # Python <3.9 cancel_futures
            self._async_pool.shutdown(wait=False)
        except Exception:
            pass
        self._close_all_decoders()
        self._scrub_cache.clear()