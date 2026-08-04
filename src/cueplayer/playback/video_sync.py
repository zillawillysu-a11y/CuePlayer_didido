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
from pathlib import Path
from time import monotonic

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal

from cueplayer.diagnostics import perf as perf_diag
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
# Play decode stays on the UI thread (throttled). A background play-decode
# worker was tried and removed: seek/scrub while Clean Output was open raced
# a second PyAV container on the same path (hourglass → hard crash).
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

_UNSET = object()


class VideoSyncController(QObject):
    frame_changed = Signal(object)  # np.ndarray (H, W, 3) RGB24, or None for black
    active_clip_changed = Signal(object)  # VideoClip | None
    overlap_warning = Signal(str)

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
            # Real drag: preload after a short delay. Click-seek releases
            # before this fires, avoiding play-worker / scrub-worker races.
            if self._video_output_active and self._song is not None:
                self._scrub_preload_timer.start()
        else:
            self._scrub_preload_timer.stop()
            # Scrub just ended: make sure the exact release-point frame —
            # not a sparse scrub poster — is what's on screen.
            self._flush_timer.stop()
            self._flush_pending()

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
        self._decode_and_emit(song, seconds)

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
        self._flush_timer.stop()
        self._pending_clip = None
        self._pending_seconds = None
        self._last_decode_time = 0.0
        self._maybe_warn_overlap(song, float(pos))
        primary = song.active_video_clip_at(float(pos))
        self._set_active(primary.id if primary else None)
        self._decode_and_emit(song, float(pos))

    def set_playing(self, active: bool) -> None:
        """Call from AudioEngine.playing_changed.

        While playing, decode work is throttled to _MAX_PLAY_DECODE_HZ (see
        module constants) — this is the fix for the timeline becoming
        unusable while a video clip plays: without it, every ~16ms
        position_changed tick from AudioEngine's poll timer would reach all
        the way into a PyAV decode + colorspace conversion on the same
        thread that has to paint/scroll/zoom the timeline and handle mouse
        input. Paused/stopped ticks stay unthrottled (frame-accurate for
        programmatic seeks, mark navigation, etc).
        """
        active = bool(active)
        if active == self._playing:
            return
        self._playing = active
        if not active:
            # Playback just stopped: land on the exact final position, not
            # a throttled stand-in from the last active window.
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
        self._cancel_pending()
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
        perf_diag.count("video.update_position.calls")
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

        self._decode_and_emit(song, seconds)

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

    def _decode_and_emit(self, song: Song, seconds: float) -> None:
        with perf_diag.span("video.decode"):
            self._last_decode_time = monotonic()
            self._pending_clip = None
            self._pending_seconds = None
            clips = song.active_video_clips_at(seconds)
            if not clips:
                self._emit_frame(None)
                return
            weighted: list[tuple[VideoClip, float]] = []
            for clip in clips:
                weight = video_clip_crossfade_weight(clip, seconds, song.video_clips)
                if weight > 1e-6:
                    weighted.append((clip, weight))
            if not weighted:
                self._emit_frame(None)
                return
            if len(weighted) == 1:
                clip, _weight = weighted[0]
                decoder = self._decoder_for(clip)
                if decoder is None:
                    self._emit_frame(None)
                    return
                try:
                    frame = decoder.frame_at(clip.source_time_for(seconds))
                except Exception:
                    frame = None
                self._emit_frame(frame)
                return
            # Near 0/1 weights: skip float32 composite (common outside crossfade).
            dominant = max(weighted, key=lambda item: item[1])
            if dominant[1] / max(1e-9, sum(w for _c, w in weighted)) >= 0.98:
                clip = dominant[0]
                decoder = self._decoder_for(clip)
                if decoder is None:
                    self._emit_frame(None)
                    return
                try:
                    frame = decoder.frame_at(clip.source_time_for(seconds))
                except Exception:
                    frame = None
                self._emit_frame(frame)
                return
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
                self._emit_frame(None)
                return
            self._emit_frame(np.clip(composite, 0, 255).astype(np.uint8))

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
        perf_diag.count("video.emit.calls")
        self.frame_changed.emit(frame)

    def _flush_pending(self) -> None:
        clip, seconds = self._pending_clip, self._pending_seconds
        if clip is None or seconds is None or self._song is None:
            return
        if self._song.video_clip_by_id(clip.id) is None:
            self._pending_clip = None
            self._pending_seconds = None
            return
        self._decode_and_emit(self._song, seconds)

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
