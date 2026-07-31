"""Mixes each video clip's own embedded audio into the master output.

CuePlayer has exactly one playback clock: `AudioEngine`'s sample position (see
`cueplayer.playback.video_sync` module docstring). This mixer never runs its
own timer for *playback* — `AudioEngine`'s realtime callback asks it for a
chunk at an explicit song-timeline *frame* range on every audio buffer.
Per-clip audio is decoded in a background thread in capped windows (never a
multi-hour whole file), then resampled to the engine rate. Long rehearsal
clips use a sliding window so audio continues past the first minute.
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
        self._cache: dict[str, _CachedPcm] = {}
        self._inflight: dict[str, tuple] = {}
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
        # Small lookback so scrubbing slightly backward still hits the buffer.
        start = max(src_in, float(source_time) - 2.0)
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
            cached = self._cache.get(clip.id)
            if cached is not None and cached.key == key:
                return
            if self._inflight.get(clip.id) == key:
                return
            self._inflight[clip.id] = key
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
        with self._lock:
            if self._inflight.get(clip_id) != key:
                return  # newer request superseded this job
            self._inflight.pop(clip_id, None)
            if samples is None:
                self._cache.pop(clip_id, None)
                return
            self._cache[clip_id] = _CachedPcm(
                samples=samples, origin_seconds=origin, key=key
            )

    def _covers(self, pcm: _CachedPcm, source_time: float) -> bool:
        n = int(pcm.samples.shape[0])
        if n <= 0:
            return False
        end = pcm.origin_seconds + (n / float(self._playback_rate))
        # Require a little headroom so we reload before running off the end.
        return pcm.origin_seconds - 1e-3 <= source_time < end - 0.25

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
        with self._lock:
            cache_snapshot = dict(self._cache)
        for clip in clips:
            clip_start_frame = int(round(clip.start_seconds * sr))
            clip_end_frame = int(round(clip.end_seconds * sr))
            lo = max(start_frame, clip_start_frame)
            hi = min(end_frame, clip_end_frame)
            if hi <= lo:
                continue
            active = np.arange(lo, hi, dtype=np.int64)
            offsets = active - clip_start_frame
            src_in = max(0.0, float(clip.source_in_seconds))
            span = max(0.05, float(clip.source_span_seconds or clip.duration_seconds))
            if clip.media_kind == "still":
                src_times = np.full(active.size, src_in, dtype=np.float64)
            else:
                src_times = src_in + np.mod(offsets.astype(np.float64) / sr, span)

            pcm = cache_snapshot.get(clip.id)
            need_t = float(src_times[0])
            if pcm is None or not self._covers(pcm, need_t):
                # Realtime-safe: schedule a window, stay silent until ready.
                self._request_window(clip, need_t)
                continue

            buf_frames = int(pcm.samples.shape[0])
            origin = float(pcm.origin_seconds)
            src_idx = np.round((src_times - origin) * sr).astype(np.int64)
            valid = (src_idx >= 0) & (src_idx < buf_frames)
            if not np.any(valid):
                self._request_window(clip, need_t)
                continue
            # If the chunk runs past the cached window, ask for the next one.
            if not bool(valid[-1]):
                self._request_window(clip, float(src_times[-1]))

            vol = max(0.0, min(1.0, float(clip.volume)))
            t_seconds = active.astype(np.float64) / sr
            weights = video_clip_crossfade_weights(clip, t_seconds, song.video_clips)
            mask = valid & (weights > 1e-6)
            if not np.any(mask):
                continue
            out_rows = (active[mask] - start_frame).astype(np.int64)
            scaled = pcm.samples[src_idx[mask]] * (vol * weights[mask])[:, np.newaxis]
            out[out_rows] += scaled
        return out
