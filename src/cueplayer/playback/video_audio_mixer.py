"""Mixes each video clip's own embedded audio into the master output.

CuePlayer has exactly one playback clock: ``AudioEngine``'s sample position.
This mixer never runs its own playback clock.

Realtime contract (``chunk_at`` — PortAudio callback):
- Read an immutable PCM snapshot (no worker lock wait).
- Mix with canonical integer source-sample indices (no float round gaps).
- Return silence for cache misses; fully overwrite ``outdata`` contribution.
- Reject NaN/Inf / malformed PCM for that contribution only.
- No executor submission, av.open, resampling, file I/O, or Qt.

Off-realtime contract (``schedule_for_song_time`` — poll / seek path):
- Request current/next quantized windows; decode on the background worker.
- Atomically publish completed PCM windows into the RT snapshot.
"""

from __future__ import annotations

from collections import OrderedDict, deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import math
import threading
import time
from typing import Any

import numpy as np

from cueplayer.diagnostics import perf as perf_diag
from cueplayer.domain.models import Song, VideoClip, video_clip_crossfade_weights
from cueplayer.media.video_audio_cache import get_video_audio
from cueplayer.media.video_limits import (
    MAX_VIDEO_AUDIO_DECODE_SECONDS,
    clip_is_heavy,
)
from cueplayer.playback.resample import ascontiguous_yielding, resample_linear_yielding

_HEAVY_WINDOW_SECONDS = 12.0
_HEAVY_WINDOW_STEP = 9.0
_HEAVY_MIN_AHEAD_SECONDS = 36.0
_HEAVY_POST_DECODE_SLEEP = 0.08
_MAX_WINDOWS_PER_CLIP = 8
_EVENT_RING_MAX = 256


@dataclass(frozen=True)
class _CachedPcm:
    samples: np.ndarray  # (frames, 2) float32 at playback rate — immutable view
    origin_seconds: float
    origin_frame: int  # canonical integer sample index of samples[0]
    key: tuple


@dataclass
class _VaEvent:
    kind: str
    t_mono: float
    song_time: float | None = None
    media_time: float | None = None
    detail: dict[str, Any] = field(default_factory=dict)


class VideoAudioMixer:
    def __init__(self) -> None:
        self._song: Song | None = None
        self._playback_rate = 48000
        self.muted = False
        self._schedule_suspended = False
        self._cache: dict[str, OrderedDict[tuple, _CachedPcm]] = {}
        # Lock-free RT snapshot: clip_id → tuple[_CachedPcm, ...] (oldest→newest).
        self._rt_snapshot: dict[str, tuple[_CachedPcm, ...]] = {}
        self._pin_source_time: float | None = None
        self._inflight: dict[str, tuple] = {}
        self._pending_need: dict[str, float] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vid-audio")
        self._events: deque[_VaEvent] = deque(maxlen=_EVENT_RING_MAX)
        self._events_lock = threading.Lock()
        # Exceptional callback stats (written from Audio callback — no perf lock).
        self._cb_reject_nonfinite = 0
        self._cb_reject_short = 0
        self._cb_owner_switch = 0
        self._cb_gap_fill = 0
        self._cb_lock_wait_ns = 0  # should stay 0 with snapshot reads
        self._cb_last_window_key: str | None = None

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
        suspended = bool(suspended)
        self._schedule_suspended = suspended
        if suspended:
            with self._lock:
                self._pending_need.clear()
            perf_diag.count("video_audio.schedule_suspended")
        else:
            perf_diag.count("video_audio.schedule_resumed")

    def is_decoding(self) -> bool:
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
                self._publish_snapshot_locked()

    def preload(self, clips: list[VideoClip]) -> None:
        valid_ids = {clip.id for clip in clips}
        with self._lock:
            for stale_id in [cid for cid in self._cache if cid not in valid_ids]:
                self._cache.pop(stale_id, None)
                self._inflight.pop(stale_id, None)
                self._pending_need.pop(stale_id, None)
            self._publish_snapshot_locked()
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
        if self.muted or self._schedule_suspended:
            return
        song = self._song
        if song is None:
            return
        t = float(song_seconds)
        self._pin_source_time = None
        for clip in song.video_clips:
            if clip.hidden or clip.media_kind == "still":
                continue
            if t < float(clip.start_seconds) - 0.05 or t >= float(clip.end_seconds) + 0.05:
                continue
            src = self._song_time_to_source(clip, t)
            self._pin_source_time = float(src)
            self._ensure_coverage(clip, src)
            if clip_is_heavy(clip):
                self._maybe_prefetch(clip, src)

    def drain_events(self) -> list[dict[str, Any]]:
        with self._events_lock:
            items = list(self._events)
            self._events.clear()
        return [
            {
                "kind": e.kind,
                "t_mono": e.t_mono,
                "song_time": e.song_time,
                "media_time": e.media_time,
                **e.detail,
            }
            for e in items
        ]

    def exceptional_callback_stats(self) -> dict[str, Any]:
        return {
            "reject_nonfinite": int(self._cb_reject_nonfinite),
            "reject_short": int(self._cb_reject_short),
            "owner_switch": int(self._cb_owner_switch),
            "gap_fill": int(self._cb_gap_fill),
            "lock_wait_ns": int(self._cb_lock_wait_ns),
            "last_window_key": self._cb_last_window_key,
        }

    def _record_event(
        self,
        kind: str,
        *,
        song_time: float | None = None,
        media_time: float | None = None,
        **detail: Any,
    ) -> None:
        ev = _VaEvent(
            kind=str(kind),
            t_mono=time.monotonic(),
            song_time=song_time,
            media_time=media_time,
            detail=dict(detail),
        )
        with self._events_lock:
            self._events.append(ev)

    def _song_time_to_source(self, clip: VideoClip, song_seconds: float) -> float:
        src_in = max(0.0, float(clip.source_in_seconds))
        span = max(0.05, float(clip.source_span_seconds or clip.duration_seconds))
        local = max(0.0, float(song_seconds) - float(clip.start_seconds))
        if clip.media_kind == "still":
            return src_in
        return src_in + math.fmod(local, span)

    def _window_for(self, clip: VideoClip, source_time: float) -> tuple[float, float]:
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
            rel2 = max(0.0, start - src_in)
            idx2 = int(math.floor(rel2 / step + 1e-9))
            start = src_in + idx2 * step
        dur = min(cap, max(0.05, src_out - start))
        return start, dur

    def _ensure_coverage(self, clip: VideoClip, source_time: float) -> None:
        if self._covers_source(clip.id, source_time):
            perf_diag.count("video_audio.coverage_hit")
            return
        self._request_window(clip, source_time)

    def _covers_source(self, clip_id: str, source_time: float) -> bool:
        snap = self._rt_snapshot.get(clip_id) or ()
        for pcm in snap:
            if self._has_sample(pcm, source_time):
                return True
        with self._lock:
            inflight = self._inflight.get(clip_id)
        if inflight is None:
            return False
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
        with self._lock:
            windows = self._cache.get(clip.id)
            if windows is not None and key in windows:
                windows.move_to_end(key)
                self._pending_need.pop(clip.id, None)
                perf_diag.count("video_audio.duplicate_key_suppressed")
                return
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
        self._record_event(
            "window_decode_start",
            media_time=float(source_time),
            key=str(key),
            start=float(start),
            dur=float(dur),
        )
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
            # Publish only a private contiguous copy — RT never sees a mutable
            # buffer still being written by the worker.
            samples = np.array(samples, dtype=np.float32, copy=True, order="C")

        follow_up: float | None = None
        with self._lock:
            if self._inflight.get(clip_id) != key:
                return
            self._inflight.pop(clip_id, None)
            if samples is not None:
                origin_frame = int(math.floor(origin * float(self._playback_rate) + 1e-9))
                self._install_window(
                    clip_id,
                    _CachedPcm(
                        samples=samples,
                        origin_seconds=origin,
                        origin_frame=origin_frame,
                        key=key,
                    ),
                )
                self._record_event(
                    "window_publish",
                    media_time=origin,
                    key=str(key),
                    origin_frame=origin_frame,
                    frames=int(samples.shape[0]),
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

    def _publish_snapshot_locked(self) -> None:
        """Atomically replace the RT-visible snapshot (call under ``_lock``)."""
        snap: dict[str, tuple[_CachedPcm, ...]] = {}
        for cid, windows in self._cache.items():
            snap[cid] = tuple(windows.values())
        self._rt_snapshot = snap

    def _install_window(self, clip_id: str, pcm: _CachedPcm) -> None:
        windows = self._cache.get(clip_id)
        if windows is None:
            windows = OrderedDict()
            self._cache[clip_id] = windows
        if pcm.key in windows:
            del windows[pcm.key]
        windows[pcm.key] = pcm
        windows.move_to_end(pcm.key)
        pin = self._pin_source_time
        while len(windows) > _MAX_WINDOWS_PER_CLIP:
            # Never evict a window covering the pinned playhead source time.
            victim_key = None
            for key, cand in windows.items():
                if pin is not None and self._has_sample(cand, float(pin)):
                    continue
                if key == pcm.key:
                    continue
                victim_key = key
                break
            if victim_key is None:
                # All remaining cover the pin — drop oldest non-newest.
                for key in list(windows.keys()):
                    if key != pcm.key:
                        victim_key = key
                        break
            if victim_key is None:
                break
            windows.pop(victim_key, None)
            perf_diag.count("video_audio.lru_eviction")
            self._record_event(
                "window_eviction",
                media_time=pin,
                key=str(victim_key),
                pin_source_time=pin,
            )
        self._publish_snapshot_locked()

    def _window_end(self, pcm: _CachedPcm) -> float:
        n = int(pcm.samples.shape[0])
        if n <= 0:
            return float(pcm.origin_seconds)
        return float(pcm.origin_frame + n) / float(self._playback_rate)

    def _has_sample(self, pcm: _CachedPcm, source_time: float) -> bool:
        n = int(pcm.samples.shape[0])
        if n <= 0:
            return False
        src_frame = int(math.floor(float(source_time) * float(self._playback_rate) + 1e-9))
        return int(pcm.origin_frame) <= src_frame < int(pcm.origin_frame) + n

    def _has_sample_locked(self, clip_id: str, source_time: float) -> bool:
        windows = self._cache.get(clip_id)
        if not windows:
            return False
        for pcm in windows.values():
            if self._has_sample(pcm, source_time):
                return True
        return False

    def _find_covering(self, clip_id: str, source_time: float) -> _CachedPcm | None:
        snap = self._rt_snapshot.get(clip_id) or ()
        for pcm in reversed(snap):
            if self._has_sample(pcm, source_time):
                return pcm
        return None

    def _gather_samples(
        self, clip_id: str, src_frames: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, tuple | None]:
        """Composite stereo samples using canonical integer source frames.

        Older windows win on overlap (stable ownership — no oscillation when a
        newer overlapping window publishes).

        Returns ``(samples, valid_mask, first_owner_key)``.
        """
        n = int(src_frames.shape[0])
        out = np.zeros((n, 2), dtype=np.float32)
        valid = np.zeros(n, dtype=bool)
        snap = self._rt_snapshot.get(clip_id) or ()
        if not snap:
            return out, valid, None
        first_owner: tuple | None = None
        last_owner: tuple | None = None
        for pcm in snap:  # oldest → newest; first fill wins
            buf_frames = int(pcm.samples.shape[0])
            if buf_frames <= 0:
                continue
            origin_frame = int(pcm.origin_frame)
            idx = src_frames - origin_frame
            mask = (idx >= 0) & (idx < buf_frames) & (~valid)
            if not np.any(mask):
                continue
            if first_owner is None:
                first_owner = pcm.key
            last_owner = pcm.key
            out[mask] = pcm.samples[idx[mask]]
            valid[mask] = True
        if first_owner is not None and last_owner is not None and first_owner != last_owner:
            # Callback straddled a window seam (vectorized — no per-sample loop).
            self._cb_owner_switch += 1
            self._record_event(
                "owner_switch",
                key=str(last_owner),
                prev_key=str(first_owner),
                first_src=int(src_frames[0]) if n else -1,
                last_src=int(src_frames[-1]) if n else -1,
            )
            # Adjacent-sample delta at the first index owned by the newer window.
            try:
                # Recompute seam: last index still on first_owner vs next.
                older = next(p for p in snap if p.key == first_owner)
                older_end = int(older.origin_frame) + int(older.samples.shape[0])
                seam = np.flatnonzero(src_frames >= older_end)
                if seam.size > 0:
                    i = int(seam[0])
                    if i > 0 and valid[i] and valid[i - 1]:
                        delta = float(np.max(np.abs(out[i] - out[i - 1])))
                        self._record_event(
                            "boundary_delta",
                            media_time=float(src_frames[i]) / float(self._playback_rate),
                            key=str(last_owner),
                            prev_key=str(first_owner),
                            max_adj_delta=delta,
                            peak=float(np.max(np.abs(out[max(0, i - 2) : i + 3]))),
                        )
            except Exception:
                pass
        if np.any(~valid):
            gap_n = int(np.count_nonzero(~valid))
            self._cb_gap_fill += gap_n
            if gap_n > 0:
                self._record_event(
                    "gap_fill",
                    key=str(first_owner),
                    gap_samples=gap_n,
                    first_src=int(src_frames[0]) if n else -1,
                    last_src=int(src_frames[-1]) if n else -1,
                )
        if np.any(valid):
            bad = ~np.isfinite(out).all(axis=1)
            if np.any(bad & valid):
                self._cb_reject_nonfinite += int(np.count_nonzero(bad & valid))
                out[bad & valid] = 0.0
                valid[bad & valid] = False
                self._record_event(
                    "pcm_nonfinite_rejected",
                    key=str(first_owner),
                )
        if last_owner is not None:
            self._cb_last_window_key = str(last_owner)
        return out, valid, first_owner

    def _coverage_end(self, clip_id: str) -> float | None:
        snap = self._rt_snapshot.get(clip_id) or ()
        if not snap:
            return None
        return max(self._window_end(w) for w in snap)

    def _maybe_prefetch(self, clip: VideoClip, source_time: float) -> None:
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
        """Realtime mix — immutable snapshot only; never schedule decode work."""
        out = np.zeros((frames, 2), dtype=np.float32)
        song = self._song
        if song is None or self.muted or frames <= 0:
            return out
        sr = int(self._playback_rate)
        if sr <= 0:
            return out
        end_frame = int(start_frame) + int(frames)
        clips = [c for c in song.video_clips if not c.hidden]
        if not clips:
            return out
        overlapping_ids = song.overlapping_video_clip_ids()
        for clip in clips:
            clip_start_frame = int(round(clip.start_seconds * sr))
            clip_end_frame = int(round(clip.end_seconds * sr))
            lo = max(int(start_frame), clip_start_frame)
            hi = min(end_frame, clip_end_frame)
            if hi <= lo:
                continue
            n = hi - lo
            offsets = np.arange(n, dtype=np.int64) + (lo - clip_start_frame)
            src_in = max(0.0, float(clip.source_in_seconds))
            span = max(0.05, float(clip.source_span_seconds or clip.duration_seconds))
            src_in_frame = int(math.floor(src_in * sr + 1e-9))
            span_frames = max(1, int(math.floor(span * sr + 1e-9)))
            if clip.media_kind == "still":
                src_frames = np.full(n, src_in_frame, dtype=np.int64)
            else:
                src_frames = src_in_frame + np.mod(offsets, span_frames)

            prev_key = self._cb_last_window_key
            gathered, valid, owner = self._gather_samples(clip.id, src_frames)
            if owner is not None and prev_key is not None and prev_key != str(owner):
                self._cb_owner_switch += 1
                self._record_event(
                    "callback_window_switch",
                    key=str(owner),
                    prev_key=str(prev_key),
                    song_time=float(lo) / float(sr),
                    media_time=float(src_frames[0]) / float(sr),
                )
            if not np.any(valid):
                continue
            if int(gathered.shape[0]) != n:
                self._cb_reject_short += 1
                self._record_event(
                    "pcm_short_rejected",
                    requested=n,
                    returned=int(gathered.shape[0]),
                )
                continue

            vol = max(0.0, min(1.0, float(clip.volume)))
            out_rows = np.arange(lo, hi, dtype=np.int64) - int(start_frame)
            if clip.id not in overlapping_ids:
                out[out_rows[valid]] += gathered[valid] * vol
                continue
            t_seconds = (out_rows.astype(np.float64) + start_frame) / float(sr)
            weights = video_clip_crossfade_weights(clip, t_seconds, song.video_clips)
            mask = valid & (weights > 1e-6)
            if not np.any(mask):
                continue
            scaled = gathered[mask] * (vol * weights[mask])[:, np.newaxis]
            out[out_rows[mask]] += scaled
        # Final safety: never emit non-finite into the master mix.
        if not np.isfinite(out).all():
            self._cb_reject_nonfinite += 1
            np.nan_to_num(out, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
        return out
