"""Mixes each video clip's own embedded audio into the master output.

CuePlayer has exactly one playback clock: `AudioEngine`'s sample position (see
`cueplayer.playback.video_sync` module docstring). This mixer never runs its
own timer for *playback* — `AudioEngine`'s realtime callback asks it for a
chunk at an explicit song-timeline *frame* range on every audio buffer.
Per-clip audio is decoded in a background thread in capped windows (never a
multi-hour whole file), then resampled to the engine rate. Long rehearsal
clips use a sliding window so audio continues past the first minute.

Rapid seek/scrub only keeps *one* decode job per clip; later requests while a
job is running stash the latest source time and run after the current job —
stale mid-queue 30–120s decodes must not pile up under ``av_path_lock``.

Heavy-clip seams used to click every ~30–45s because:
1. Coverage treated the last 0.25s of a window as "missing" → forced silence.
2. Each callback used only one window past its end.
3. The next window held ``av_path_lock`` for the whole decode while Preview
   also needed it — prefetch finished after the playhead ran dry.

Now we composite cached windows, prefetch ~two-thirds of a window early (plus
a far horizon), keep more overlaps, and decode long windows in short lock
segments so Preview can interleave.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import threading

import numpy as np

from cueplayer.domain.models import Song, VideoClip, video_clip_crossfade_weights
from cueplayer.media.video_audio_cache import get_video_audio
from cueplayer.media.video_limits import audio_decode_cap_for_clip
from cueplayer.playback.resample import resample_linear

# Start decoding the next window when this much audio remains. Contended
# Preview decode used to finish the next 75s window too late (~45s seams).
_PREFETCH_LEAD_SECONDS = 55.0
# Keep recent windows so the playhead can cross a seam without silence.
_MAX_WINDOWS_PER_CLIP = 5


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
        # clip_id -> newest-last list of windows (double-buffer while sliding).
        self._cache: dict[str, list[_CachedPcm]] = {}
        # clip_id -> key of the job currently running (at most one per clip).
        self._inflight: dict[str, tuple] = {}
        # Latest source_time requested while a job was already busy.
        self._pending_need: dict[str, float] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vid-audio")

    def set_song(self, song: Song | None) -> None:
        self._song = song

    def set_muted(self, muted: bool) -> None:
        self.muted = bool(muted)

    def set_playback_rate(self, rate: int) -> None:
        rate = max(1, int(rate))
        if rate != self._playback_rate:
            self._playback_rate = rate
            with self._lock:
                self._cache.clear()
                self._inflight.clear()
                self._pending_need.clear()

    def preload(self, clips: list[VideoClip]) -> None:
        """
        Kick background decode for each clip near its source_in. Safe to call
        from the UI thread — returns immediately; ``chunk_at`` yields silence
        until each job finishes. Long clips only decode a capped window; the
        playhead later slides that window forward.
        """
        valid_ids = {clip.id for clip in clips}
        with self._lock:
            for stale_id in [cid for cid in self._cache if cid not in valid_ids]:
                self._cache.pop(stale_id, None)
                self._inflight.pop(stale_id, None)
                self._pending_need.pop(stale_id, None)
        for clip in clips:
            if clip.media_kind == "still":
                continue
            self._request_window(clip, float(clip.source_in_seconds))

    def _window_for(self, clip: VideoClip, source_time: float) -> tuple[float, float]:
        """Return (start_seconds, duration_seconds) covering ``source_time``."""
        cap = audio_decode_cap_for_clip(clip)
        src_in = max(0.0, float(clip.source_in_seconds))
        span = max(0.05, float(clip.source_span_seconds or clip.duration_seconds))
        src_out = src_in + span
        # Lookback so the new window overlaps the previous one while sliding.
        lookback = min(8.0, max(2.0, cap * 0.12))
        start = max(src_in, float(source_time) - lookback)
        if start + cap > src_out and span > cap:
            start = max(src_in, src_out - cap)
        dur = min(cap, max(0.05, src_out - start))
        return start, dur

    def _request_window(self, clip: VideoClip, source_time: float) -> None:
        start, dur = self._window_for(clip, source_time)
        key = (
            str(clip.path),
            self._playback_rate,
            round(start, 2),
            round(dur, 2),
        )
        with self._lock:
            windows = self._cache.get(clip.id) or []
            if any(cached.key == key for cached in windows):
                self._pending_need.pop(clip.id, None)
                return
            if self._inflight.get(clip.id) == key:
                self._pending_need.pop(clip.id, None)
                return
            if clip.id in self._inflight:
                # One job already running — keep only the latest need; do not
                # queue another decode that would hold av_path_lock for minutes.
                self._pending_need[clip.id] = float(source_time)
                return
            self._inflight[clip.id] = key
            self._pending_need.pop(clip.id, None)
        self._executor.submit(self._decode_window, clip.id, key, clip, start, dur)

    def _decode_window(
        self,
        clip_id: str,
        key: tuple,
        clip: VideoClip,
        start: float,
        dur: float,
    ) -> None:
        samples: np.ndarray | None
        origin = float(start)
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
                data = resample_linear(data, buf.sample_rate, self._playback_rate)
            samples = np.ascontiguousarray(data, dtype=np.float32)

        follow_up: float | None = None
        with self._lock:
            if self._inflight.get(clip_id) != key:
                # Should not happen with coalesce; drop safely.
                return
            self._inflight.pop(clip_id, None)
            if samples is not None:
                self._install_window(
                    clip_id,
                    _CachedPcm(samples=samples, origin_seconds=origin, key=key),
                )
            follow_up = self._pending_need.pop(clip_id, None)
            # If any cached window already covers the pending need, skip.
            if follow_up is not None and samples is not None:
                if self._has_sample_locked(clip_id, follow_up):
                    follow_up = None

        if follow_up is not None:
            self._request_window(clip, follow_up)

    def _install_window(self, clip_id: str, pcm: _CachedPcm) -> None:
        """Append a decoded window; keep a few prior ones for seam coverage."""
        windows = [w for w in (self._cache.get(clip_id) or []) if w.key != pcm.key]
        windows.append(pcm)
        self._cache[clip_id] = windows[-_MAX_WINDOWS_PER_CLIP:]

    def _window_end(self, pcm: _CachedPcm) -> float:
        n = int(pcm.samples.shape[0])
        if n <= 0:
            return float(pcm.origin_seconds)
        return float(pcm.origin_seconds) + (n / float(self._playback_rate))

    def _has_sample(self, pcm: _CachedPcm, source_time: float) -> bool:
        """True if ``source_time`` falls inside the PCM (no artificial headroom)."""
        n = int(pcm.samples.shape[0])
        if n <= 0:
            return False
        end = self._window_end(pcm)
        return pcm.origin_seconds - 1e-4 <= source_time < end - 1e-6

    def _has_sample_locked(self, clip_id: str, source_time: float) -> bool:
        for pcm in self._cache.get(clip_id) or []:
            if self._has_sample(pcm, source_time):
                return True
        return False

    def _find_covering(self, clip_id: str, source_time: float) -> _CachedPcm | None:
        with self._lock:
            windows = list(self._cache.get(clip_id) or [])
        for pcm in reversed(windows):
            if self._has_sample(pcm, source_time):
                return pcm
        return None

    def _gather_samples(
        self, clip_id: str, src_times: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """Composite stereo samples for ``src_times`` from every cached window.

        Older windows fill first; newer windows only cover holes. A freshly
        decoded window must not punch silence (seek pads / cold start) into
        audio that the previous window already had.
        """
        n = int(src_times.shape[0])
        out = np.zeros((n, 2), dtype=np.float32)
        valid = np.zeros(n, dtype=bool)
        sr = float(self._playback_rate)
        with self._lock:
            windows = list(self._cache.get(clip_id) or [])
        for pcm in windows:
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
        return out, valid

    def _coverage_end(self, clip_id: str) -> float | None:
        """Latest source time covered by any cached window, or None."""
        with self._lock:
            windows = list(self._cache.get(clip_id) or [])
        if not windows:
            return None
        return max(self._window_end(w) for w in windows)

    def _maybe_prefetch(self, clip: VideoClip, source_time: float) -> None:
        """Keep decoded audio well ahead of the playhead (often two windows)."""
        pcm = self._find_covering(clip.id, source_time)
        if pcm is None:
            self._request_window(clip, source_time)
            return
        remaining = self._window_end(pcm) - float(source_time)
        cap = audio_decode_cap_for_clip(clip)
        # Prefetch when ~2/3 of the current window is still ahead — not only
        # in the last 30s (that matched the ~45s dropout the user heard).
        lead = min(_PREFETCH_LEAD_SECONDS, max(28.0, cap * 0.72))
        if remaining < lead:
            ahead = float(source_time) + max(12.0, lead * 0.55)
            self._request_window(clip, ahead)
        # Second horizon: ensure coverage past playhead + ~one full window.
        cov_end = self._coverage_end(clip.id)
        horizon = float(source_time) + max(lead, cap * 0.85)
        if cov_end is None or cov_end < horizon - 0.5:
            self._request_window(clip, horizon)

    def chunk_at(self, start_frame: int, frames: int) -> np.ndarray:
        """
        Stereo (frames, 2) chunk of video-clip audio for playback-rate frames
        [start_frame, start_frame + frames) of the *song timeline*.
        """
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
        # Overlap check once per buffer — crossfade weights are expensive and
        # unused for the common single-clip / non-overlapping case.
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

            need_t = float(src_times[0])
            end_t = float(src_times[-1])
            gathered, valid = self._gather_samples(clip.id, src_times)
            if not np.any(valid):
                # Realtime-safe: schedule a window, stay silent until ready.
                self._request_window(clip, need_t)
                continue

            # Sliding window: decode the next slice before this one ends.
            self._maybe_prefetch(clip, end_t)
            if not bool(valid[-1]):
                self._request_window(clip, end_t)

            vol = max(0.0, min(1.0, float(clip.volume)))
            out_rows = np.arange(lo, hi, dtype=np.int64) - start_frame
            if clip.id not in overlapping_ids:
                if not np.any(valid):
                    continue
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
