"""Video clip playback synced to the audio sample clock.

CuePlayer has exactly one playback clock: `AudioEngine`'s sample position.
This controller never runs its own timer — the UI feeds it `update_position()`
whenever the engine reports a new position (see MainWindow), and it looks up
which clip (if any) should be showing at that song-timeline time, decodes
the matching source frame, and hands it back for the Preview / Clean Output
widgets to paint. No independent video clock, no second player.
"""

from __future__ import annotations

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
from cueplayer.media.video_loader import MediaDecoder, open_media_decoder

# While scrubbing, decode Preview/Clean at a capped rate so the frame
# follows the playhead without starving timeline paint (PyAV re-seek is
# expensive on the UI thread). set_scrubbing(False) flushes the exact
# release-point frame via _flush_pending().
_MAX_SCRUB_DECODE_HZ = 12.0
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
# clip is playing. Paused/stopped ticks (e.g. programmatic seeks) are left
# unthrottled so they stay frame-accurate.
_MAX_PLAY_DECODE_HZ = 30.0
_MIN_PLAY_DECODE_INTERVAL = 1.0 / _MAX_PLAY_DECODE_HZ

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

    def decode_quality(self) -> VideoDecodeQuality:
        return self._decode_quality

    def video_output_active(self) -> bool:
        return self._video_output_active

    def set_video_output_active(self, active: bool) -> None:
        """Enable/disable frame decode+emit (Preview / Clean Output visibility).

        Audio playback and embedded clip audio are unaffected — only the RGB
        preview path is gated. When re-enabled, the frame at the last
        `update_position()` is decoded immediately."""
        active = bool(active)
        if active == self._video_output_active:
            return
        self._video_output_active = active
        if not active:
            self._cancel_pending()
            self._close_all_decoders()
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

        While dragging, decode is throttled to _MAX_SCRUB_DECODE_HZ so
        Preview/Clean still follow the playhead without starving the
        timeline. On release, flush the exact land frame.
        """
        active = bool(active)
        if active == self._scrubbing:
            return
        self._scrubbing = active
        if not active:
            # Scrub just ended: make sure the exact release-point frame —
            # not a throttled mid-drag stand-in — is what's on screen.
            self._flush_timer.stop()
            self._flush_pending()

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
        # frame request reopens at the new one.
        self._close_all_decoders()

    def set_song(self, song: Song | None) -> None:
        self._song = song
        self._cancel_pending()
        self._close_all_decoders()
        self._warned_overlap_keys.clear()
        self._set_active(None)
        self._last_emitted_frame = _UNSET  # force this emit through even if unchanged
        self._emit_frame(None)

    def refresh(self) -> None:
        """Call after clips are added / removed / re-pathed."""
        if self._song is None:
            self._close_all_decoders()
            return
        valid_ids = {clip.id for clip in self._song.video_clips}
        for clip_id in list(self._decoders):
            if clip_id not in valid_ids:
                self._decoders.pop(clip_id).close()
                self._decoder_paths.pop(clip_id, None)

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

    def _decode_and_emit(self, song: Song, seconds: float) -> None:
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
