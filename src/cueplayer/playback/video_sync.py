"""Video clip playback synced to the audio sample clock.

CuePlayer has exactly one playback clock: `AudioEngine`'s sample position.
This controller never runs its own timer — the UI feeds it `update_position()`
whenever the engine reports a new position (see MainWindow), and it looks up
which clip (if any) should be showing at that song-timeline time, decodes
the matching source frame, and hands it back for the Preview / Clean Output
widgets to paint. No independent video clock, no second player.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal

from cueplayer.domain.models import (
    VIDEO_DECODE_QUALITY_MAX_HEIGHT,
    Song,
    VideoClip,
    VideoDecodeQuality,
    video_clip_crossfade_weight,
)
from cueplayer.media.scrub_frame_cache import ScrubFrameCache
from cueplayer.media.video_loader import MediaDecoder, open_media_decoder
from cueplayer.util.thread_priority import lower_background_thread_priority

# While scrubbing with a warm ScrubFrameCache, lookups are cheap — allow a
# higher emit rate so Preview tracks the drag. Cold cache / live decode still
# falls back to this interval as a safety cap when we must touch PyAV.
_MAX_SCRUB_DECODE_HZ = 24.0
_MIN_SCRUB_DECODE_INTERVAL = 1.0 / _MAX_SCRUB_DECODE_HZ

# AudioEngine's master clock ticks position_changed at ~60Hz (16ms poll —
# see AudioEngine._poll) so it can drive smooth timeline playhead motion,
# but no display can show video faster than ~display refresh rate anyway.
# During playback (see set_playing()), cap actual decode+emit work to this
# rate so Preview/Clean Output paint cannot fire faster than a real frame.
# Live play decode runs on a worker thread (see _schedule_play_decode) so
# PyAV seek/colorspace does not stall the UI thread that paints the timeline
# and Clean Output. Paused/stopped ticks stay sync + unthrottled for
# frame-accurate seeks.
_MAX_PLAY_DECODE_HZ = 24.0
_MIN_PLAY_DECODE_INTERVAL = 1.0 / _MAX_PLAY_DECODE_HZ

_UNSET = object()


@dataclass(frozen=True)
class _PlayDecodeLayer:
    clip_id: str
    path: Path
    source_seconds: float
    weight: float


@dataclass(frozen=True)
class _PlayDecodeJob:
    layers: tuple[_PlayDecodeLayer, ...]
    max_height: int | None


class VideoSyncController(QObject):
    frame_changed = Signal(object)  # np.ndarray (H, W, 3) RGB24, or None for black
    active_clip_changed = Signal(object)  # VideoClip | None
    overlap_warning = Signal(str)
    # Worker → UI thread (QueuedConnection by default across threads).
    _play_frame_ready = Signal(object, int)  # frame | None, generation

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._song: Song | None = None
        self._decoders: dict[str, MediaDecoder] = {}
        self._decoder_paths: dict[str, Path] = {}
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
        # Play-path decode worker: own MediaDecoder cache (never touch UI
        # _decoders from this thread). Coalesce to latest pending job.
        self._play_decode_gen = 0
        self._play_lock = threading.Lock()
        self._play_pending: tuple[_PlayDecodeJob, int] | None = None
        self._play_running = False
        self._worker_decoders: dict[str, MediaDecoder] = {}
        self._worker_decoder_paths: dict[str, Path] = {}
        self._play_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="vid-play"
        )
        self._play_frame_ready.connect(self._on_play_frame_ready)

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
            self._cancel_pending()
            self._invalidate_play_decode()
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
        self._decode_and_emit(song, seconds)

    def set_scrubbing(self, active: bool) -> None:
        """Call from the timeline's scrub_started/scrub_ended signals.

        While dragging, Preview/Clean prefer the prebuilt scrub-frame cache
        (no UI-thread PyAV seek). On release, flush the exact land frame via
        the live decoder.
        """
        active = bool(active)
        if active == self._scrubbing:
            return
        self._scrubbing = active
        if active:
            # Kick / refresh preload for whatever is on the song right now.
            song = self._song
            if song is not None and self._video_output_active:
                self._scrub_cache.preload(list(song.video_clips))
        else:
            # Scrub just ended: make sure the exact release-point frame —
            # not a sparse scrub poster — is what's on screen.
            self._flush_timer.stop()
            self._flush_pending(force_sync=True)

    def set_playing(self, active: bool) -> None:
        """Call from AudioEngine.playing_changed.

        While playing, decode work is throttled to _MAX_PLAY_DECODE_HZ and
        runs on a background worker so PyAV does not stall the UI thread.
        Paused/stopped ticks stay sync (frame-accurate for seeks).
        """
        active = bool(active)
        if active == self._playing:
            return
        self._playing = active
        if not active:
            # Drop in-flight play jobs; land the exact final position sync.
            self._invalidate_play_decode()
            self._flush_timer.stop()
            if self._pending_seconds is not None:
                self._flush_pending(force_sync=True)
            elif (
                self._video_output_active
                and self._song is not None
                and self._last_position_seconds is not None
            ):
                self._decode_and_emit(
                    self._song, self._last_position_seconds, force_sync=True
                )

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
        self._cancel_pending()
        self._invalidate_play_decode()
        self._close_all_decoders()
        self._scrub_cache.clear()
        self._warned_overlap_keys.clear()
        self._set_active(None)
        self._last_emitted_frame = _UNSET  # force this emit through even if unchanged
        self._emit_frame(None)
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
        # Only refresh scrub posters if the user is mid-drag; otherwise wait
        # for the next scrub_started to avoid contending with live decode.
        if self._scrubbing and self._video_output_active:
            self._scrub_cache.preload(list(self._song.video_clips))

    def update_position(self, seconds: float) -> None:
        """Call on every AudioEngine.position_changed tick (the master clock)."""
        self._last_position_seconds = float(seconds)
        if not self._video_output_active:
            return
        song = self._song
        if song is None:
            self._cancel_pending()
            self._set_active(None)
            self._emit_frame(None)
            return

        self._maybe_warn_overlap(song, seconds)

        clips = song.active_video_clips_at(seconds)
        if not clips:
            self._cancel_pending()
            self._set_active(None)
            self._emit_frame(None)
            return

        primary = song.active_video_clip_at(seconds)
        self._set_active(primary.id if primary else None)

        # Scrub: prefer prebuilt posters (no UI-thread PyAV seek). If the
        # ladder is still cold, fall through to the throttled live path.
        if self._scrubbing:
            self._pending_clip = primary
            self._pending_seconds = seconds
            frame = self._scrub_composite(song, seconds)
            if frame is not None:
                self._last_decode_time = monotonic()
                self._emit_frame(frame)
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

        self._decode_and_emit(song, seconds)

    def _current_min_decode_interval(self) -> float:
        """Minimum seconds between actual decode+emit work. Scrubbing takes
        priority over playing (both can briefly be true: dragging the
        playhead pauses the engine without firing playing_changed — see
        AudioEngine.begin_scrub/pause(for_scrub=True))."""
        if self._scrubbing:
            return _MIN_SCRUB_DECODE_INTERVAL
        if self._playing:
            return _MIN_PLAY_DECODE_INTERVAL
        return 0.0

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
        self, song: Song, seconds: float, *, force_sync: bool = False
    ) -> None:
        self._last_decode_time = monotonic()
        self._pending_clip = None
        self._pending_seconds = None
        # During play, keep PyAV off the UI thread (Clean Output + timeline).
        # Seek / stop / scrub-end pass force_sync=True for frame-accurate land.
        if self._playing and not self._scrubbing and not force_sync:
            job = self._snapshot_play_job(song, seconds)
            if job is None:
                self._emit_frame(None)
                return
            self._schedule_play_decode(job)
            return
        frame = self._decode_frame_ui(song, seconds)
        self._emit_frame(frame)

    def _snapshot_play_job(self, song: Song, seconds: float) -> _PlayDecodeJob | None:
        clips = song.active_video_clips_at(seconds)
        if not clips:
            return None
        layers: list[_PlayDecodeLayer] = []
        for clip in clips:
            weight = video_clip_crossfade_weight(clip, seconds, song.video_clips)
            if weight <= 1e-6:
                continue
            layers.append(
                _PlayDecodeLayer(
                    clip_id=clip.id,
                    path=Path(clip.path),
                    source_seconds=float(clip.source_time_for(seconds)),
                    weight=float(weight),
                )
            )
        if not layers:
            return None
        return _PlayDecodeJob(
            layers=tuple(layers),
            max_height=self._decode_max_height,
        )

    def _schedule_play_decode(self, job: _PlayDecodeJob) -> None:
        self._play_decode_gen += 1
        gen = self._play_decode_gen
        with self._play_lock:
            self._play_pending = (job, gen)
            if self._play_running:
                return
            self._play_running = True
        self._play_executor.submit(self._drain_play_decode)

    def _drain_play_decode(self) -> None:
        lower_background_thread_priority()
        while True:
            with self._play_lock:
                item = self._play_pending
                self._play_pending = None
                if item is None:
                    self._play_running = False
                    return
            job, gen = item
            try:
                frame = self._worker_decode_job(job)
            except Exception:
                frame = None
            self._play_frame_ready.emit(frame, gen)

    def _on_play_frame_ready(self, frame: object, gen: int) -> None:
        if gen != self._play_decode_gen:
            return
        if not self._playing or not self._video_output_active:
            return
        self._last_decode_time = monotonic()
        self._emit_frame(frame if isinstance(frame, np.ndarray) else None)

    def _invalidate_play_decode(self) -> None:
        self._play_decode_gen += 1
        with self._play_lock:
            self._play_pending = None
        self._play_executor.submit(self._worker_close_all)

    def _worker_close_all(self) -> None:
        for decoder in self._worker_decoders.values():
            try:
                decoder.close()
            except Exception:
                pass
        self._worker_decoders.clear()
        self._worker_decoder_paths.clear()

    def _worker_decoder_for(
        self, clip_id: str, path: Path, max_height: int | None
    ) -> MediaDecoder | None:
        cached_path = self._worker_decoder_paths.get(clip_id)
        if cached_path == path and clip_id in self._worker_decoders:
            return self._worker_decoders[clip_id]
        old = self._worker_decoders.pop(clip_id, None)
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
        try:
            decoder = open_media_decoder(path, max_decode_height=max_height)
        except Exception:
            self._worker_decoder_paths.pop(clip_id, None)
            return None
        self._worker_decoders[clip_id] = decoder
        self._worker_decoder_paths[clip_id] = path
        return decoder

    def _worker_decode_job(self, job: _PlayDecodeJob) -> np.ndarray | None:
        if not job.layers:
            return None
        if len(job.layers) == 1:
            layer = job.layers[0]
            decoder = self._worker_decoder_for(layer.clip_id, layer.path, job.max_height)
            if decoder is None:
                return None
            try:
                return decoder.frame_at(layer.source_seconds)
            except Exception:
                return None
        total_weight = sum(layer.weight for layer in job.layers)
        composite: np.ndarray | None = None
        for layer in job.layers:
            decoder = self._worker_decoder_for(layer.clip_id, layer.path, job.max_height)
            if decoder is None:
                continue
            try:
                frame = decoder.frame_at(layer.source_seconds)
            except Exception:
                frame = None
            if frame is None:
                continue
            scaled = frame.astype(np.float32) * (layer.weight / total_weight)
            composite = scaled if composite is None else composite + scaled
        if composite is None:
            return None
        return np.clip(composite, 0, 255).astype(np.uint8)

    def _decode_frame_ui(self, song: Song, seconds: float) -> np.ndarray | None:
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
            decoder = self._decoder_for(clip)
            if decoder is None:
                return None
            try:
                return decoder.frame_at(clip.source_time_for(seconds))
            except Exception:
                return None
        total_weight = sum(w for _clip, w in weighted)
        composite: np.ndarray | None = None
        for clip, weight in weighted:
            decoder = self._decoder_for(clip)
            if decoder is None:
                continue
            try:
                frame = decoder.frame_at(clip.source_time_for(seconds))
            except Exception:
                frame = None
            if frame is None:
                continue
            scaled = frame.astype(np.float32) * (weight / total_weight)
            composite = scaled if composite is None else composite + scaled
        if composite is None:
            return None
        return np.clip(composite, 0, 255).astype(np.uint8)

    def _emit_frame(self, frame: np.ndarray | None) -> None:
        """Skip emitting (and the Preview/Clean Output QImage copy + repaint
        that follows) when `frame` is literally the same object as last
        time. Normal during playback: VideoDecoder.frame_at() hands back the
        exact same cached ndarray on every tick that lands within the same
        source frame's duration (see video_loader.py), so without this
        check every ~16ms poll tick would still push an unchanged frame
        through to both preview widgets."""
        if frame is self._last_emitted_frame:
            return
        self._last_emitted_frame = frame
        self.frame_changed.emit(frame)

    def _flush_pending(self, *, force_sync: bool = False) -> None:
        clip, seconds = self._pending_clip, self._pending_seconds
        if clip is None or seconds is None or self._song is None:
            return
        if self._song.video_clip_by_id(clip.id) is None:
            self._pending_clip = None
            self._pending_seconds = None
            return
        self._decode_and_emit(self._song, seconds, force_sync=force_sync)

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

    def _close_all_decoders(self) -> None:
        for decoder in self._decoders.values():
            decoder.close()
        self._decoders.clear()
        self._decoder_paths.clear()
        self._play_executor.submit(self._worker_close_all)
