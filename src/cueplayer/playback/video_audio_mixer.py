"""Mixes each video clip's own embedded audio into the master output.

CuePlayer has exactly one playback clock: ``AudioEngine``'s sample position.
This mixer never runs its own playback clock.

Realtime contract (``chunk_at`` — PortAudio callback):
- Snapshot the current PCM cache and mix available samples.
- Return silence for cache misses.
- No executor submission, av.open, resampling, file I/O, logging, Qt, or
  waiting for decoder work. Only a brief lock to copy window list references.

Off-realtime contract (``schedule_for_song_time`` — poll / seek path):
- Request current/next quantized windows.
- Decode/resample on the existing background worker.
- Atomically publish completed PCM windows.
"""

from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import math
import threading
import time

import numpy as np

from cueplayer.diagnostics import perf as perf_diag
from cueplayer.domain.models import Song, VideoClip, video_clip_crossfade_weights
from cueplayer.media.video_audio_cache import get_video_audio
from cueplayer.media.video_limits import (
    MAX_VIDEO_AUDIO_DECODE_SECONDS,
    clip_is_heavy,
)
from cueplayer.playback.resample import ascontiguous_yielding, resample_linear_yielding

# Short heavy windows: lock hold stays brief.
_HEAVY_WINDOW_SECONDS = 12.0
# Fixed grid step so backward jumps reuse windows (not playhead-relative keys).
_HEAVY_WINDOW_STEP = 9.0
# Prefetch when coverage ahead of playhead drops below this (schedule path only).
_HEAVY_MIN_AHEAD_SECONDS = 36.0
_HEAVY_POST_DECODE_SLEEP = 0.08
_MAX_WINDOWS_PER_CLIP = 8


@dataclass
class _CachedPcm:
    samples: np.ndarray  # (frames, 2) float32 at playback rate
    origin_seconds: float  # source-media time of samples[0]
    key: tuple


class VideoAudioMixer:
    """
    Looks up which video clip(s) are active for a given playback-rate frame
    range and returns their pre-decoded, resampled PCM — silence outside any
    clip, for hidden clips, while muted, or while a background decode is still
    pending.
    """

    def __init__(self) -> None:
        self._song: Song | None = None
        self._playback_rate = 48000
        self.muted = False
        self._schedule_suspended = False
        # clip_id → OrderedDict[key, _CachedPcm] (true LRU, move-to-end on use)
        self._cache: dict[str, OrderedDict[tuple, _CachedPcm]] = {}
        self._inflight: dict[str, tuple] = {}
        self._pending_need: dict[str, float] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vid-audio")

    def set_song(self, song: Song | None) -> None:
        self._song = song

    def set_muted(self, muted: bool) -> None:
        muted = bool(muted)
        self.muted = muted
        if muted:
            with self._lock:
                self._pending_need.clear()
            perf_diag.count("video_audio.mute_cleared_pending")

    def set_schedule_suspended(self, suspended: bool) -> None:
        """Suspend window scheduling/chaining (SCRUB / FINAL_LAND / RESUME)."""
        suspended = bool(suspended)
        self._schedule_suspended = suspended
        if suspended:
            with self._lock:
                self._pending_need.clear()
            perf_diag.count("video_audio.schedule_suspended")
        else:
            perf_diag.count("video_audio.schedule_resumed")

    def is_decoding(self) -> bool:
        """True while a background window decode holds / will hold ``av_path_lock``."""
        with self._lock:
            return bool(self._inflight)

    def set_playback_rate(self, rate: int) -> None:
        rate = max(1, int(rate))
        if rate != self._playback_rate:
            self._playback_rate = rate
            with self._lock:
                self._cache.clear()
                self._inflight.clear()
                self._pending_need.clear()

    def preload(self, clips: list[VideoClip]) -> None:
        """Kick background decode near source_in; warm a second heavy slice."""
        valid_ids = {clip.id for clip in clips}
        with self._lock:
            for stale_id in [cid for cid in self._cache if cid not in valid_ids]:
                self._cache.pop(stale_id, None)
                self._inflight.pop(stale_id, None)
                self._pending_need.pop(stale_id, None)
        if self.muted or self._schedule_suspended:
            return
        for clip in clips:
            if clip.media_kind == "still":
                continue
            self._request_window(clip, float(clip.source_in_seconds))
            if clip_is_heavy(clip):
                self._request_window(
                    clip,
                    float(clip.source_in_seconds) + _HEAVY_WINDOW_STEP,
                )

    def schedule_for_song_time(self, song_seconds: float) -> None:
        """Off-RT: ensure current/next windows for the Audio sample-clock position.

        Must never be called from the PortAudio callback.
        """
        if self.muted or self._schedule_suspended:
            return
        song = self._song
        if song is None:
            return
        t = float(song_seconds)
        for clip in song.video_clips:
            if clip.hidden or clip.media_kind == "still":
                continue
            if t < float(clip.start_seconds) - 0.05 or t >= float(clip.end_seconds) + 0.05:
                continue
            src = self._song_time_to_source(clip, t)
            self._ensure_coverage(clip, src)
            if clip_is_heavy(clip):
                self._maybe_prefetch(clip, src)

    def _song_time_to_source(self, clip: VideoClip, song_seconds: float) -> float:
        src_in = max(0.0, float(clip.source_in_seconds))
        span = max(0.05, float(clip.source_span_seconds or clip.duration_seconds))
        local = max(0.0, float(song_seconds) - float(clip.start_seconds))
        if clip.media_kind == "still":
            return src_in
        return src_in + math.fmod(local, span)

    def _window_for(self, clip: VideoClip, source_time: float) -> tuple[float, float]:
        """Return quantized (start_seconds, duration_seconds) covering ``source_time``."""
        src_in = max(0.0, float(clip.source_in_seconds))
        span = max(0.05, float(clip.source_span_seconds or clip.duration_seconds))
        src_out = src_in + span

        if not clip_is_heavy(clip):
            start = src_in
            dur = min(MAX_VIDEO_AUDIO_DECODE_SECONDS, max(0.05, src_out - start))
            return start, dur

        cap = _HEAVY_WINDOW_SECONDS
        step = _HEAVY_WINDOW_STEP
        rel = max(0.0, float(source_time) - src_in)
        idx = int(math.floor(rel / step))
        start = src_in + idx * step
        if start + cap > src_out and span > cap:
            start = max(src_in, src_out - cap)
            # Re-quantize onto the grid so keys stay stable.
            rel2 = max(0.0, start - src_in)
            idx2 = int(math.floor(rel2 / step + 1e-9))
            start = src_in + idx2 * step
        dur = min(cap, max(0.05, src_out - start))
        return start, dur

    def _ensure_coverage(self, clip: VideoClip, source_time: float) -> None:
        """Schedule only when no cached/inflight window covers ``source_time``."""
        if self._covers_source(clip.id, source_time):
            perf_diag.count("video_audio.coverage_hit")
            return
        self._request_window(clip, source_time)

    def _covers_source(self, clip_id: str, source_time: float) -> bool:
        with self._lock:
            windows = self._cache.get(clip_id)
            if windows:
                for pcm in windows.values():
                    if self._has_sample(pcm, source_time):
                        return True
            inflight = self._inflight.get(clip_id)
        if inflight is None:
            return False
        # Inflight key encodes quantized start/dur — treat as coverage-in-progress
        # when the requested time falls inside that window.
        try:
            _path, _rate, start, dur = inflight
            start_f = float(start)
            dur_f = float(dur)
            return start_f - 1e-4 <= float(source_time) < start_f + dur_f - 1e-6
        except Exception:
            return False

    def _request_window(self, clip: VideoClip, source_time: float) -> None:
        if self.muted or self._schedule_suspended:
            return
        start, dur = self._window_for(clip, source_time)
        key = (
            str(clip.path),
            self._playback_rate,
            round(start, 2),
            round(dur, 2),
        )
        perf_diag.count("video_audio.window_decode_requests")
        perf_diag.note("video_audio.last_window_key", str(key))
        with self._lock:
            windows = self._cache.get(clip.id)
            if windows is not None and key in windows:
                # Touch LRU on coverage/key hit.
                windows.move_to_end(key)
                self._pending_need.pop(clip.id, None)
                perf_diag.count("video_audio.duplicate_key_suppressed")
                return
            # Coverage hit under a different overlapping key.
            if windows is not None:
                for pcm in windows.values():
                    if self._has_sample(pcm, source_time):
                        windows.move_to_end(pcm.key)
                        self._pending_need.pop(clip.id, None)
                        perf_diag.count("video_audio.coverage_hit_suppressed")
                        return
            if self._inflight.get(clip.id) == key:
                self._pending_need.pop(clip.id, None)
                perf_diag.count("video_audio.duplicate_inflight_suppressed")
                return
            if clip.id in self._inflight:
                self._pending_need[clip.id] = float(source_time)
                return
            self._inflight[clip.id] = key
            self._pending_need.pop(clip.id, None)
        perf_diag.count("video_audio.unique_window_keys")
        self._executor.submit(self._decode_window, clip.id, key, clip, start, dur)

    def _decode_window(
        self,
        clip_id: str,
        key: tuple,
        clip: VideoClip,
        start: float,
        dur: float,
    ) -> None:
        try:
            from cueplayer.playback import media_load_probe as _mlp

            _mlp.note_va_decode_window()
        except Exception:
            pass
        perf_diag.count("video_audio.decode_windows")
        samples: np.ndarray | None
        origin = float(start)
        heavy = clip_is_heavy(clip)
        try:
            buf = get_video_audio(
                clip.path, start_seconds=start, max_duration_seconds=dur
            )
        except Exception:
            buf = None
        if buf is None or buf.frames == 0:
            samples = None
        else:
            origin = float(buf.origin_seconds)
            data = buf.samples
            if data.ndim == 1:
                data = np.stack([data, data], axis=1)
            elif data.shape[1] == 1:
                data = np.repeat(data, 2, axis=1)
            elif data.shape[1] > 2:
                data = data[:, :2]
            if int(buf.sample_rate) != int(self._playback_rate):
                data = resample_linear_yielding(
                    data, buf.sample_rate, self._playback_rate
                )
            samples = ascontiguous_yielding(
                data, sample_rate=float(self._playback_rate)
            )

        follow_up: float | None = None
        with self._lock:
            if self._inflight.get(clip_id) != key:
                return
            self._inflight.pop(clip_id, None)
            if samples is not None:
                self._install_window(
                    clip_id,
                    _CachedPcm(samples=samples, origin_seconds=origin, key=key),
                )
            if not self.muted and not self._schedule_suspended:
                follow_up = self._pending_need.pop(clip_id, None)
                if follow_up is not None and samples is not None:
                    if self._has_sample_locked(clip_id, follow_up):
                        cov = [
                            self._window_end(w)
                            for w in (self._cache.get(clip_id) or {}).values()
                        ]
                        follow_up = (
                            max(cov) - _HEAVY_WINDOW_STEP * 0.5 if cov else None
                        )
            else:
                self._pending_need.pop(clip_id, None)
                follow_up = None

        if heavy:
            time.sleep(_HEAVY_POST_DECODE_SLEEP)

        if follow_up is not None and not self.muted and not self._schedule_suspended:
            self._request_window(clip, follow_up)

    def _install_window(self, clip_id: str, pcm: _CachedPcm) -> None:
        """Publish window and evict true LRU beyond the 8-window cap."""
        windows = self._cache.get(clip_id)
        if windows is None:
            windows = OrderedDict()
            self._cache[clip_id] = windows
        if pcm.key in windows:
            del windows[pcm.key]
        windows[pcm.key] = pcm
        windows.move_to_end(pcm.key)
        while len(windows) > _MAX_WINDOWS_PER_CLIP:
            windows.popitem(last=False)
            perf_diag.count("video_audio.lru_eviction")

    def _window_end(self, pcm: _CachedPcm) -> float:
        n = int(pcm.samples.shape[0])
        if n <= 0:
            return float(pcm.origin_seconds)
        return float(pcm.origin_seconds) + (n / float(self._playback_rate))

    def _has_sample(self, pcm: _CachedPcm, source_time: float) -> bool:
        n = int(pcm.samples.shape[0])
        if n <= 0:
            return False
        end = self._window_end(pcm)
        return pcm.origin_seconds - 1e-4 <= source_time < end - 1e-6

    def _has_sample_locked(self, clip_id: str, source_time: float) -> bool:
        windows = self._cache.get(clip_id)
        if not windows:
            return False
        for pcm in windows.values():
            if self._has_sample(pcm, source_time):
                return True
        return False

    def _find_covering(self, clip_id: str, source_time: float) -> _CachedPcm | None:
        with self._lock:
            windows = self._cache.get(clip_id)
            if not windows:
                return None
            # Prefer newest covering window (OrderedDict end = most recently used).
            for key in reversed(windows):
                pcm = windows[key]
                if self._has_sample(pcm, source_time):
                    return pcm
        return None

    def _gather_samples(
        self, clip_id: str, src_times: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """Composite stereo samples; older windows win on overlap.

        Touch LRU for windows that actually contribute samples.
        """
        n = int(src_times.shape[0])
        out = np.zeros((n, 2), dtype=np.float32)
        valid = np.zeros(n, dtype=bool)
        sr = float(self._playback_rate)
        touched: list[tuple] = []
        with self._lock:
            windows = self._cache.get(clip_id)
            snapshot = list(windows.values()) if windows else []
        for pcm in snapshot:
            buf_frames = int(pcm.samples.shape[0])
            if buf_frames <= 0:
                continue
            origin = float(pcm.origin_seconds)
            idx = np.round((src_times - origin) * sr).astype(np.int64)
            mask = (idx >= 0) & (idx < buf_frames) & (~valid)
            if not np.any(mask):
                continue
            out[mask] = pcm.samples[idx[mask]]
            valid[mask] = True
            touched.append(pcm.key)
        if touched:
            with self._lock:
                windows = self._cache.get(clip_id)
                if windows is not None:
                    for key in touched:
                        if key in windows:
                            windows.move_to_end(key)
        return out, valid

    def _coverage_end(self, clip_id: str) -> float | None:
        with self._lock:
            windows = self._cache.get(clip_id)
            if not windows:
                return None
            return max(self._window_end(w) for w in windows.values())

    def _maybe_prefetch(self, clip: VideoClip, source_time: float) -> None:
        """Keep ~``_HEAVY_MIN_AHEAD_SECONDS`` buffered; idle when ahead is healthy."""
        if self.muted or self._schedule_suspended:
            return
        if not clip_is_heavy(clip):
            return
        if self.is_decoding():
            return
        cov = self._coverage_end(clip.id)
        if cov is None or not self._covers_source(clip.id, source_time):
            self._request_window(clip, source_time)
            return
        ahead = float(cov) - float(source_time)
        if ahead >= _HEAVY_MIN_AHEAD_SECONDS:
            return
        self._request_window(clip, float(cov) + 0.01)

    def chunk_at(self, start_frame: int, frames: int) -> np.ndarray:
        """Realtime mix — cache read only; never schedule decode work."""
        out = np.zeros((frames, 2), dtype=np.float32)
        song = self._song
        if song is None or self.muted or frames <= 0:
            return out
        sr = self._playback_rate
        if sr <= 0:
            return out
        end_frame = start_frame + frames
        clips = [c for c in song.video_clips if not c.hidden]
        if not clips:
            return out
        overlapping_ids = song.overlapping_video_clip_ids()
        for clip in clips:
            clip_start_frame = int(round(clip.start_seconds * sr))
            clip_end_frame = int(round(clip.end_seconds * sr))
            lo = max(start_frame, clip_start_frame)
            hi = min(end_frame, clip_end_frame)
            if hi <= lo:
                continue
            n = hi - lo
            offsets = np.arange(n, dtype=np.int64) + (lo - clip_start_frame)
            src_in = max(0.0, float(clip.source_in_seconds))
            span = max(0.05, float(clip.source_span_seconds or clip.duration_seconds))
            if clip.media_kind == "still":
                src_times = np.full(n, src_in, dtype=np.float64)
            else:
                src_times = src_in + np.mod(offsets.astype(np.float64) / sr, span)

            gathered, valid = self._gather_samples(clip.id, src_times)
            if not np.any(valid):
                continue

            vol = max(0.0, min(1.0, float(clip.volume)))
            out_rows = np.arange(lo, hi, dtype=np.int64) - start_frame
            if clip.id not in overlapping_ids:
                out[out_rows[valid]] += gathered[valid] * vol
                continue
            t_seconds = (out_rows.astype(np.float64) + start_frame) / sr
            weights = video_clip_crossfade_weights(clip, t_seconds, song.video_clips)
            mask = valid & (weights > 1e-6)
            if not np.any(mask):
                continue
            scaled = gathered[mask] * (vol * weights[mask])[:, np.newaxis]
            out[out_rows[mask]] += scaled
        return out
