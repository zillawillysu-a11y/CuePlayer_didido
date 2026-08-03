"""Mixes each video clip's own embedded audio into the master output.

CuePlayer has exactly one playback clock: `AudioEngine`'s sample position (see
`cueplayer.playback.video_sync` module docstring). This mixer never runs its
own timer for *playback* — `AudioEngine`'s realtime callback asks it for a
chunk at an explicit song-timeline *frame* range on every audio buffer.
Per-clip audio is decoded in a background thread for the clip's trim window
only (never a multi-hour whole file), then resampled to the engine rate.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading

import numpy as np

from cueplayer.domain.models import Song, VideoClip, video_clip_crossfade_weights
from cueplayer.media.video_audio_cache import get_video_audio_for_clip
from cueplayer.playback.resample import resample_linear


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
        # clip.id -> (frames, 2) float32 at self._playback_rate, or None for
        # "decoded, but silent". Buffer index 0 == clip.source_in_seconds.
        self._cache: dict[str, np.ndarray | None] = {}
        self._cache_key: dict[str, tuple] = {}
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
                self._cache_key.clear()

    def preload(self, clips: list[VideoClip]) -> None:
        """
        Kick background decode for each clip's trim window. Safe to call from
        the UI thread — returns immediately; ``chunk_at`` yields silence until
        each job finishes.
        """
        valid_ids = {clip.id for clip in clips}
        with self._lock:
            for stale_id in [cid for cid in self._cache if cid not in valid_ids]:
                self._cache.pop(stale_id, None)
                self._cache_key.pop(stale_id, None)
        for clip in clips:
            key = self._key_for(clip)
            with self._lock:
                if self._cache_key.get(clip.id) == key and clip.id in self._cache:
                    continue
                # Reserve the key so duplicate preload calls don't queue twice.
                self._cache_key[clip.id] = key
            self._executor.submit(self._decode_async, clip.id, key, clip)

    def _key_for(self, clip: VideoClip) -> tuple:
        return (
            str(clip.path),
            self._playback_rate,
            round(float(clip.source_in_seconds), 3),
            round(float(clip.source_span_seconds or clip.duration_seconds), 3),
        )

    def _decode_async(self, clip_id: str, key: tuple, clip: VideoClip) -> None:
        samples: np.ndarray | None
        try:
            buf = get_video_audio_for_clip(clip)
        except Exception:
            buf = None
        if buf is None or buf.frames == 0:
            samples = None
        else:
            data = buf.samples
            if data.shape[1] == 1:
                data = np.repeat(data, 2, axis=1)
            elif data.shape[1] > 2:
                data = data[:, :2]
            if int(buf.sample_rate) != int(self._playback_rate):
                data = resample_linear(data, buf.sample_rate, self._playback_rate)
            samples = np.ascontiguousarray(data, dtype=np.float32)
        with self._lock:
            if self._cache_key.get(clip_id) != key:
                return  # stale job
            self._cache[clip_id] = samples

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
            cache_snapshot = {cid: self._cache.get(cid) for cid in self._cache}
        for clip in clips:
            clip_start_frame = int(round(clip.start_seconds * sr))
            clip_end_frame = int(round(clip.end_seconds * sr))
            lo = max(start_frame, clip_start_frame)
            hi = min(end_frame, clip_end_frame)
            if hi <= lo:
                continue
            samples = cache_snapshot.get(clip.id)
            if samples is None or samples.shape[0] <= 0:
                continue
            buf_frames = int(samples.shape[0])
            span_frames = max(1, min(buf_frames, int(round(clip.source_span_seconds * sr))))
            vol = max(0.0, min(1.0, float(clip.volume)))
            active = np.arange(lo, hi, dtype=np.int64)
            offsets = active - clip_start_frame
            if clip.media_kind == "still":
                src_idx = np.zeros(active.size, dtype=np.int64)
            else:
                src_idx = np.mod(offsets, span_frames)
            src_idx = np.clip(src_idx, 0, buf_frames - 1)
            t_seconds = active.astype(np.float64) / sr
            weights = video_clip_crossfade_weights(clip, t_seconds, song.video_clips)
            mask = weights > 1e-6
            if not np.any(mask):
                continue
            out_rows = (active[mask] - start_frame).astype(np.int64)
            scaled = samples[src_idx[mask]] * (vol * weights[mask])[:, np.newaxis]
            out[out_rows] += scaled
        np.clip(out, -1.0, 1.0, out=out)
        return out
