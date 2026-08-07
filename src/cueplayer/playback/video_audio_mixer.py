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
# Contiguous published coverage ahead of the playhead (not global max end).
# ~4×9s steps keeps the next seam decoding inside the 3s overlap budget.
_HEAVY_MIN_AHEAD_SECONDS = 36.0
_HEAVY_POST_DECODE_SLEEP = 0.08
_MAX_WINDOWS_PER_CLIP = 8
_EVENT_RING_MAX = 256
# Treat windows as contiguous when they overlap or touch within one sample.
_CONTIGUOUS_ADJACENCY_FRAMES = 1
_COLD_SEEK_GAP_WINDOW_S = 2.0
_COLD_START_WINDOW_SECONDS = 2.0
# A several-minute clip took ~9.3 s to decode as one PCM block on the measured
# Windows machine, so pressing Play immediately after a song switch began with
# silence. Use the already-proven sliding-window path well below the separate
# 10-minute "heavy UI media" threshold; this changes background scheduling,
# not the callback/sample-clock contract.
_WINDOWED_AUDIO_SECONDS = 90.0


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
        # Off-RT coverage / publish diagnostics (never take these locks in chunk_at).
        self._cold_seek_until_mono = 0.0
        self._gap_fill_seen = 0
        self._steady_gap_fill_delta = 0
        self._cold_gap_fill_delta = 0
        self._req_meta: dict[tuple, dict[str, Any]] = {}
        self._last_coverage_diag: dict[str, Any] = {}

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
            if self._uses_windowed_decode(clip):
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
            if self._uses_windowed_decode(clip):
                self._ensure_contiguous_prefetch(clip, src)
        self._harvest_gap_fill_deltas()

    def note_discontinuous_seek(self, song_seconds: float) -> None:
        """Off-RT: after a jump, rebuild contiguous coverage from the new playhead.

        Far-future cache entries must not satisfy local ahead checks.
        """
        self._cold_seek_until_mono = time.monotonic() + _COLD_SEEK_GAP_WINDOW_S
        perf_diag.count("video_audio.discontinuous_seek")
        self._record_event(
            "discontinuous_seek",
            song_time=float(song_seconds),
            media_time=None,
        )
        # Clear pending needs so stale far-ahead requests do not win.
        with self._lock:
            self._pending_need.clear()
        self.schedule_for_song_time(float(song_seconds))

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
            "steady_gap_fill_delta": int(self._steady_gap_fill_delta),
            "cold_seek_gap_fill_delta": int(self._cold_gap_fill_delta),
            **dict(self._last_coverage_diag),
        }

    def publish_coverage_to_perf(self) -> None:
        """Copy off-RT coverage diagnostics into PERF (report path only)."""
        stats = self.exceptional_callback_stats()
        for key, value in stats.items():
            perf_diag.note(f"video_audio.{key}", value)
        perf_diag.note(
            "video_audio.steady_gap_fill_delta", int(self._steady_gap_fill_delta)
        )
        perf_diag.note(
            "video_audio.cold_seek_gap_fill_delta", int(self._cold_gap_fill_delta)
        )

    def _harvest_gap_fill_deltas(self) -> None:
        """Attribute new callback gap_fill samples to steady vs cold-seek (off RT)."""
        now_gap = int(self._cb_gap_fill)
        delta = max(0, now_gap - int(self._gap_fill_seen))
        self._gap_fill_seen = now_gap
        if delta <= 0:
            return
        if time.monotonic() < float(self._cold_seek_until_mono):
            self._cold_gap_fill_delta += delta
            perf_diag.count("video_audio.cold_seek_gap_fill_samples", delta)
        else:
            self._steady_gap_fill_delta += delta
            perf_diag.count("video_audio.steady_gap_fill_samples", delta)

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
        if not self._uses_windowed_decode(clip):
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

    @staticmethod
    def _uses_windowed_decode(clip: VideoClip) -> bool:
        return bool(
            clip_is_heavy(clip)
            or float(clip.source_span_seconds or clip.duration_seconds or 0.0)
            >= _WINDOWED_AUDIO_SECONDS
            or float(clip.source_duration_seconds or 0.0)
            >= _WINDOWED_AUDIO_SECONDS
        )

    def _ensure_coverage(self, clip: VideoClip, source_time: float) -> None:
        # Published coverage only — in-flight must not suppress the request that
        # creates the first callback-visible PCM for this playhead.
        if self._covers_source_published(clip.id, source_time):
            perf_diag.count("video_audio.coverage_hit")
            return
        self._request_window(clip, source_time)

    def _source_frame(self, source_time: float) -> int:
        return int(
            math.floor(float(source_time) * float(self._playback_rate) + 1e-9)
        )

    def _pcm_end_frame(self, pcm: _CachedPcm) -> int:
        n = int(pcm.samples.shape[0])
        if n <= 0:
            return int(pcm.origin_frame)
        return int(pcm.origin_frame) + n

    def _covers_source_published(self, clip_id: str, source_time: float) -> bool:
        snap = self._rt_snapshot.get(clip_id) or ()
        for pcm in snap:
            if self._has_sample(pcm, source_time):
                return True
        return False

    def _covers_source(self, clip_id: str, source_time: float) -> bool:
        """Published or in-flight coverage (duplicate-suppression helper)."""
        if self._covers_source_published(clip_id, source_time):
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

    def _contiguous_component(
        self,
        clip_id: str,
        source_frame: int,
        *,
        windows: tuple[_CachedPcm, ...] | None = None,
    ) -> tuple[int | None, set[tuple]]:
        """Return ``(frontier_end_frame, keys)`` for the contiguous component
        containing ``source_frame``.

        A window joins the component only when it overlaps or touches the
        growing union within ``_CONTIGUOUS_ADJACENCY_FRAMES``. Windows that
        merely satisfy ``start <= frontier`` (i.e. any past window) must NOT
        join — that bug marked disjoint holes as "contiguous", so eviction
        dropped true forward grid cells and caused publish_late / gap_fill.
        """
        snap = windows if windows is not None else (self._rt_snapshot.get(clip_id) or ())
        if not snap:
            return None, set()
        intervals: list[tuple[int, int, _CachedPcm]] = []
        for pcm in snap:
            n = int(pcm.samples.shape[0])
            if n <= 0:
                continue
            start = int(pcm.origin_frame)
            intervals.append((start, start + n, pcm))
        if not intervals:
            return None, set()
        covering = [iv for iv in intervals if iv[0] <= int(source_frame) < iv[1]]
        if not covering:
            return None, set()
        adj = _CONTIGUOUS_ADJACENCY_FRAMES
        u_start = min(iv[0] for iv in covering)
        u_end = max(iv[1] for iv in covering)
        keys = {iv[2].key for iv in covering}
        changed = True
        while changed:
            changed = False
            for start, end, pcm in intervals:
                if pcm.key in keys:
                    continue
                # True interval merge: must overlap/touch the current UNION,
                # not merely start before the frontier tip.
                if start <= u_end + adj and end + adj >= u_start:
                    keys.add(pcm.key)
                    if start < u_start:
                        u_start = start
                    if end > u_end:
                        u_end = end
                    changed = True
        return int(u_end), keys

    def _contiguous_frontier_frame(
        self,
        clip_id: str,
        source_frame: int,
        *,
        windows: tuple[_CachedPcm, ...] | None = None,
    ) -> int | None:
        """Exclusive end frame of *published* PCM contiguous from ``source_frame``."""
        frontier, _keys = self._contiguous_component(
            clip_id, source_frame, windows=windows
        )
        return frontier

    def _contiguous_keys(
        self, clip_id: str, source_frame: int
    ) -> set[tuple]:
        """Keys of published windows on the contiguous chain from ``source_frame``."""
        _frontier, keys = self._contiguous_component(clip_id, source_frame)
        return keys

    def _note_coverage_diag(
        self,
        clip: VideoClip,
        source_time: float,
        *,
        frontier: int | None,
        next_key: tuple | None,
    ) -> None:
        sr = float(self._playback_rate)
        src_frame = self._source_frame(source_time)
        ahead_frames = (
            None if frontier is None else max(0, int(frontier) - int(src_frame))
        )
        diag = {
            "current_source_frame": int(src_frame),
            "contiguous_frontier_frame": (
                None if frontier is None else int(frontier)
            ),
            "contiguous_ahead_samples": ahead_frames,
            "contiguous_ahead_seconds": (
                None if ahead_frames is None else round(float(ahead_frames) / sr, 6)
            ),
            "next_required_window_key": (
                None if next_key is None else str(next_key)
            ),
            "pin_source_time": self._pin_source_time,
            "clip_id": clip.id,
        }
        self._last_coverage_diag = diag
        if perf_diag.is_enabled():
            for k, v in diag.items():
                perf_diag.note(f"video_audio.{k}", v)

    def _ensure_contiguous_prefetch(
        self, clip: VideoClip, source_time: float
    ) -> None:
        """Request the next contiguous quantized window(s) before the seam.

        Uses contiguous published frontier only — a disjoint far-future cache
        entry must not suppress local prefetch. In-flight adjacent keys suppress
        duplicates but do not count as callback coverage.
        """
        if self.muted or self._schedule_suspended:
            return
        if not self._uses_windowed_decode(clip):
            return
        sr = float(self._playback_rate)
        src_frame = self._source_frame(source_time)
        frontier = self._contiguous_frontier_frame(clip.id, src_frame)

        start, dur = self._window_for(clip, source_time)
        del dur
        next_start = float(start) + _HEAVY_WINDOW_STEP
        n_start, n_dur = self._window_for(clip, next_start + 0.01)
        next_key = (
            str(clip.path),
            self._playback_rate,
            round(n_start, 2),
            round(n_dur, 2),
        )

        if frontier is None:
            # Current window missing/inflight — also queue the following cell.
            self._request_window(clip, source_time)
            self._request_window(clip, next_start + 0.01)
            self._note_coverage_diag(
                clip, source_time, frontier=None, next_key=next_key
            )
            return

        ahead_s = (float(frontier) - float(src_frame)) / sr
        # Next required sample is the first frame past the contiguous frontier.
        target_time = float(frontier) / sr + 1e-6
        tgt_start, tgt_dur = self._window_for(clip, target_time)
        req_key = (
            str(clip.path),
            self._playback_rate,
            round(tgt_start, 2),
            round(tgt_dur, 2),
        )
        self._note_coverage_diag(
            clip, source_time, frontier=frontier, next_key=req_key
        )

        if ahead_s >= _HEAVY_MIN_AHEAD_SECONDS:
            return

        # Do not early-return on is_decoding: _request_window coalesces into
        # pending_need so the worker chains the next contiguous cell.
        self._request_window(
            clip,
            target_time,
            first_required_frame=int(frontier),
        )

    def _request_window(
        self,
        clip: VideoClip,
        source_time: float,
        *,
        first_required_frame: int | None = None,
    ) -> None:
        if self.muted or self._schedule_suspended:
            return
        start, dur = self._window_for(clip, source_time)
        cold_start = bool(
            self._uses_windowed_decode(clip)
            and time.monotonic() < float(self._cold_seek_until_mono)
            and not self._covers_source_published(clip.id, source_time)
            and self._pin_source_time is not None
            and abs(float(source_time) - float(self._pin_source_time)) < 0.25
        )
        if cold_start:
            src_in = max(0.0, float(clip.source_in_seconds))
            src_out = src_in + max(
                0.05, float(clip.source_span_seconds or clip.duration_seconds)
            )
            start = min(max(src_in, float(source_time)), src_out)
            dur = min(
                _COLD_START_WINDOW_SECONDS,
                max(0.05, src_out - start),
            )
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
            # Only suppress when *this* quantized key's samples are already
            # published — do not treat an unrelated covering window as the
            # requested next cell (that hid contiguous holes behind far cache).
            if self._inflight.get(clip.id) == key:
                self._pending_need.pop(clip.id, None)
                perf_diag.count("video_audio.duplicate_inflight_suppressed")
                return
            if clip.id in self._inflight:
                self._pending_need[clip.id] = float(source_time)
                return
            self._inflight[clip.id] = key
            self._pending_need.pop(clip.id, None)
            req_mono = time.monotonic()
            self._req_meta[key] = {
                "request_mono": req_mono,
                "first_required_frame": (
                    int(first_required_frame)
                    if first_required_frame is not None
                    else self._source_frame(start)
                ),
                "source_time": float(source_time),
                "start": float(start),
                "cold_start": cold_start,
            }
        perf_diag.count("video_audio.unique_window_keys")
        perf_diag.note("video_audio.last_window_request_mono", time.monotonic())
        perf_diag.note("video_audio.last_window_request_key", str(key))
        self._record_event(
            "window_decode_start",
            media_time=float(source_time),
            key=str(key),
            start=float(start),
            dur=float(dur),
            first_required_frame=(
                None
                if first_required_frame is None
                else int(first_required_frame)
            ),
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
        heavy = self._uses_windowed_decode(clip)
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
        cold_start = False
        pin_snapshot = self._pin_source_time
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
                pub_mono = time.monotonic()
                meta = self._req_meta.pop(key, None)
                lead_s = None
                cold_start = bool(meta and meta.get("cold_start"))
                if meta is not None:
                    first_req = int(meta.get("first_required_frame", origin_frame))
                    pin_f = (
                        self._source_frame(float(pin_snapshot))
                        if pin_snapshot is not None
                        else None
                    )
                    if pin_f is not None:
                        lead_s = (float(first_req) - float(pin_f)) / float(
                            self._playback_rate
                        )
                    perf_diag.note("video_audio.last_window_publish_mono", pub_mono)
                    perf_diag.note(
                        "video_audio.last_window_request_mono",
                        meta.get("request_mono"),
                    )
                    if lead_s is not None:
                        perf_diag.note(
                            "video_audio.publish_lead_seconds", round(lead_s, 6)
                        )
                        perf_diag.record_ms(
                            "video_audio.publish_lead_ms", float(lead_s) * 1000.0
                        )
                        if lead_s < 0.0:
                            perf_diag.count("video_audio.publish_late")
                self._record_event(
                    "window_publish",
                    media_time=origin,
                    key=str(key),
                    origin_frame=origin_frame,
                    frames=int(samples.shape[0]),
                    publish_lead_seconds=lead_s,
                )
            if not self.muted and not self._schedule_suspended:
                follow_up = self._pending_need.pop(clip_id, None)
                if heavy:
                    pin = pin_snapshot
                    if pin is not None:
                        pin_frame = self._source_frame(float(pin))
                        # Contiguous frontier from the live playhead — never
                        # global max (far-future windows must not suppress).
                        fr = self._contiguous_frontier_frame(
                            clip_id,
                            pin_frame,
                            windows=tuple(
                                (self._cache.get(clip_id) or OrderedDict()).values()
                            ),
                        )
                        if cold_start and fr is not None:
                            # The short jump-priority window intentionally
                            # releases av_path_lock quickly for RGB decode.
                            # Continue exactly at its frontier before honoring
                            # any far quantized prefetch request.
                            follow_up = float(fr) / float(self._playback_rate) + 1e-6
                        elif follow_up is not None and self._has_sample_locked(
                            clip_id, follow_up
                        ):
                            follow_up = None
                        if follow_up is None and fr is not None:
                            ahead = (float(fr) - float(pin_frame)) / float(
                                self._playback_rate
                            )
                            if ahead < _HEAVY_MIN_AHEAD_SECONDS:
                                follow_up = float(fr) / float(self._playback_rate) + 1e-6
                        elif follow_up is None and fr is None:
                            follow_up = float(pin)
            else:
                self._pending_need.pop(clip_id, None)
                follow_up = None

        if heavy:
            time.sleep(_HEAVY_POST_DECODE_SLEEP)

        if follow_up is not None and not self.muted and not self._schedule_suspended:
            fr_arg = None
            if pin_snapshot is not None:
                pin_frame = self._source_frame(float(pin_snapshot))
                fr = self._contiguous_frontier_frame(clip_id, pin_frame)
                if fr is not None:
                    fr_arg = int(fr)
            self._request_window(clip, follow_up, first_required_frame=fr_arg)

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
        pin_frame = self._source_frame(float(pin)) if pin is not None else None
        while len(windows) > _MAX_WINDOWS_PER_CLIP:
            # Prefer evicting disjoint stale/far windows before the current
            # playhead window or its contiguous forward chain.
            cont_keys: set[tuple] = set()
            if pin_frame is not None:
                # Temporarily publish so contiguous scan sees the new window.
                self._publish_snapshot_locked()
                cont_keys = self._contiguous_keys(clip_id, int(pin_frame))
            victim_key = None

            def _mid(c: _CachedPcm) -> int:
                return int(c.origin_frame) + int(c.samples.shape[0]) // 2

            def _end(c: _CachedPcm) -> int:
                return int(c.origin_frame) + int(c.samples.shape[0])

            # 1) Disjoint from contiguous chain, farthest from pin first.
            disjoint: list[tuple[tuple, _CachedPcm]] = [
                (k, c)
                for k, c in windows.items()
                if k not in cont_keys and k != pcm.key
            ]
            if disjoint and pin_frame is not None:
                disjoint.sort(
                    key=lambda kc: abs(_mid(kc[1]) - int(pin_frame)),
                    reverse=True,
                )
                victim_key = disjoint[0][0]
            elif disjoint:
                victim_key = disjoint[0][0]

            # 2) Fully behind the playhead (even if wrongly kept): never drop
            #    the covering window or anything still ahead of pin.
            if victim_key is None and pin_frame is not None:
                behind: list[tuple[tuple, _CachedPcm]] = []
                for key, cand in windows.items():
                    if key == pcm.key or key in cont_keys:
                        # Contiguous-behind cells are still droppable once the
                        # playhead has left them — free room for forward fill.
                        if key in cont_keys and _end(cand) <= int(pin_frame):
                            behind.append((key, cand))
                        continue
                    if _end(cand) <= int(pin_frame):
                        behind.append((key, cand))
                if behind:
                    behind.sort(key=lambda kc: _end(kc[1]))  # oldest end first
                    victim_key = behind[0][0]

            if victim_key is None:
                # 3) Last resort: oldest non-covering, non-newest.
                for key, cand in windows.items():
                    if key == pcm.key:
                        continue
                    if pin is not None and self._has_sample(cand, float(pin)):
                        continue
                    victim_key = key
                    break
            if victim_key is None:
                for key in list(windows.keys()):
                    if key != pcm.key:
                        victim_key = key
                        break
            if victim_key is None:
                break
            # Never evict a window that still covers the pin if another victim exists.
            if (
                pin is not None
                and victim_key in windows
                and self._has_sample(windows[victim_key], float(pin))
            ):
                alt = None
                for key, cand in windows.items():
                    if key in (pcm.key, victim_key):
                        continue
                    if self._has_sample(cand, float(pin)):
                        continue
                    alt = key
                    break
                if alt is not None:
                    victim_key = alt
                else:
                    break
            windows.pop(victim_key, None)
            perf_diag.count("video_audio.lru_eviction")
            self._record_event(
                "window_eviction",
                media_time=pin,
                key=str(victim_key),
                pin_source_time=pin,
                preserved_contiguous=sorted(str(k) for k in cont_keys),
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
