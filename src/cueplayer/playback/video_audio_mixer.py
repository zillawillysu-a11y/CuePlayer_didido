"""Mixes each video clip's own embedded audio into the master output.

CuePlayer has exactly one playback clock: `AudioEngine`'s sample position (see
`cueplayer.playback.video_sync` module docstring). This mixer never runs its
own timer or decode thread — `AudioEngine`'s realtime callback asks it for a
chunk at an explicit song-timeline *frame* range on every audio buffer, the
same way it already asks `_music_chunk()` / `_ltc_chunk()` for music and LTC
(see `AudioEngine._video_chunk`). Per-clip audio is decoded once and cached,
resampled to the engine's playback rate, from the Qt/main thread via
`preload()` — never inside the realtime audio callback.
"""

from __future__ import annotations

import numpy as np

from cueplayer.domain.models import Song, VideoClip, video_clip_crossfade_weight
from cueplayer.media.video_audio_cache import get_video_audio
from cueplayer.playback.resample import resample_linear


class VideoAudioMixer:
    """
    Looks up which video clip(s) are active for a given playback-rate frame
    range and returns their pre-decoded, resampled PCM — silence outside any
    clip, for hidden clips, or while muted.

    Overlap resolution: accumulate all active clips with auto crossfade weights
    (see `video_clip_crossfade_weight`). Source audio loops modulo the clip's
    trimmed source span when the timeline clip is stretched longer.
    """

    def __init__(self) -> None:
        self._song: Song | None = None
        self._playback_rate = 48000
        self.muted = False
        # clip.id -> (frames, 2) float32 at self._playback_rate, or None for
        # "decoded, but silent" (no audio stream / decode failure).
        self._cache: dict[str, np.ndarray | None] = {}
        self._cache_key: dict[str, tuple] = {}

    def set_song(self, song: Song | None) -> None:
        self._song = song

    def set_muted(self, muted: bool) -> None:
        self.muted = bool(muted)

    def set_playback_rate(self, rate: int) -> None:
        rate = max(1, int(rate))
        if rate != self._playback_rate:
            self._playback_rate = rate
            self._cache.clear()
            self._cache_key.clear()

    def preload(self, clips: list[VideoClip]) -> None:
        """
        Decode (and cache) audio for the given clips, dropping cache entries
        for clips no longer present. Call from the UI thread whenever the
        song's video clips change (added / edited / removed / re-pathed) or
        the playback rate changes — never from the realtime audio callback.
        """
        valid_ids = {clip.id for clip in clips}
        for stale_id in [cid for cid in self._cache if cid not in valid_ids]:
            self._cache.pop(stale_id, None)
            self._cache_key.pop(stale_id, None)
        for clip in clips:
            self._ensure_cached(clip)

    def _ensure_cached(self, clip: VideoClip) -> np.ndarray | None:
        key = (str(clip.path), self._playback_rate)
        if self._cache_key.get(clip.id) == key:
            return self._cache.get(clip.id)
        samples: np.ndarray | None
        try:
            buf = get_video_audio(clip.path)
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
        self._cache[clip.id] = samples
        self._cache_key[clip.id] = key
        return samples

    def chunk_at(self, start_frame: int, frames: int) -> np.ndarray:
        """
        Stereo (frames, 2) chunk of video-clip audio for playback-rate frames
        [start_frame, start_frame + frames) of the *song timeline* — i.e. the
        same frame space as `AudioEngine._position_frame`.
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
        for clip in clips:
            clip_start_frame = int(round(clip.start_seconds * sr))
            clip_end_frame = int(round(clip.end_seconds * sr))
            lo = max(start_frame, clip_start_frame)
            hi = min(end_frame, clip_end_frame)
            if hi <= lo:
                continue
            samples = self._cache.get(clip.id)
            if samples is None or samples.shape[0] <= 0:
                continue
            span_frames = max(1, int(round(clip.source_span_seconds * sr)))
            source_in_frame = int(round(clip.source_in_seconds * sr))
            vol = max(0.0, min(1.0, float(clip.volume)))
            for dst_idx in range(lo, hi):
                timeline_offset = dst_idx - clip_start_frame
                if clip.media_kind == "still":
                    src_idx = min(source_in_frame, samples.shape[0] - 1)
                else:
                    src_idx = source_in_frame + (timeline_offset % span_frames)
                if src_idx < 0 or src_idx >= samples.shape[0]:
                    continue
                t_seconds = dst_idx / sr
                weight = video_clip_crossfade_weight(clip, t_seconds, song.video_clips)
                if weight <= 1e-6:
                    continue
                out_row = dst_idx - start_frame
                out[out_row] += samples[src_idx] * vol * weight
        np.clip(out, -1.0, 1.0, out=out)
        return out
