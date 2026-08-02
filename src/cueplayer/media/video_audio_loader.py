"""Extract a video file's embedded audio track for sample-clock-locked mixing.

CuePlayer has exactly one playback clock: `AudioEngine`'s sample position (see
the `cueplayer.playback.video_sync` module docstring). This module decodes a
*window* of clip audio into float32 PCM — never the whole file when the source
is a multi-hour recording. `AudioEngine` / `VideoAudioMixer` then slice frames
out of that buffer. No independent decode timer, no second player.

Keep each decode as one open→seek→read→close under ``av_path_lock``. Yielding
the lock while a demux stays open (so Preview can run) corrupted long reads on
real rehearsal files — buffers stopped around ~30s and the mixer went silent
for a couple of seconds at each seam. The mixer instead uses short windows and
overlaps them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import av
import numpy as np

from cueplayer.media.av_lock import av_path_lock
from cueplayer.media.video_limits import MAX_VIDEO_AUDIO_DECODE_SECONDS

# Re-export for callers / tests that import the cap from this module.
__all__ = [
    "MAX_VIDEO_AUDIO_DECODE_SECONDS",
    "VideoAudioBuffer",
    "load_video_audio",
]


@dataclass
class VideoAudioBuffer:
    path: Path
    sample_rate: int
    samples: np.ndarray  # float32, shape (frames, channels)
    # Absolute source-media time (seconds) corresponding to samples[0].
    origin_seconds: float = 0.0

    @property
    def frames(self) -> int:
        return int(self.samples.shape[0])

    @property
    def channels(self) -> int:
        return int(self.samples.shape[1]) if self.samples.ndim == 2 else 1


def load_video_audio(
    path: Path,
    *,
    start_seconds: float = 0.0,
    max_duration_seconds: float | None = None,
) -> VideoAudioBuffer | None:
    """
    Decode the first audio stream of a video file to float32 stereo PCM.

    Optional ``start_seconds`` / ``max_duration_seconds`` limit the decode to a
    window (seek + early stop). Use this for long sources — decoding a full
    2-hour track into RAM will freeze CuePlayer.

    Returns None when the file has no audio stream at all (e.g. a silent VJ
    loop) — callers should treat that the same as an all-zero buffer.
    """
    path = Path(path)
    start = max(0.0, float(start_seconds))
    if max_duration_seconds is None:
        max_dur = MAX_VIDEO_AUDIO_DECODE_SECONDS
    else:
        max_dur = max(0.05, min(float(max_duration_seconds), MAX_VIDEO_AUDIO_DECODE_SECONDS))
    return _load_video_audio_once(
        path, start_seconds=start, max_duration_seconds=max_dur
    )


def _load_video_audio_once(
    path: Path,
    *,
    start_seconds: float,
    max_duration_seconds: float,
) -> VideoAudioBuffer | None:
    """Decode one contiguous window while holding ``av_path_lock``."""
    start = max(0.0, float(start_seconds))
    max_dur = max(0.05, float(max_duration_seconds))
    end_time = start + max_dur

    with av_path_lock(path):
        container = av.open(str(path))
        try:
            stream = next((s for s in container.streams if s.type == "audio"), None)
            if stream is None:
                return None
            sample_rate = int(stream.codec_context.sample_rate or 48000)
            time_base = float(stream.time_base) if stream.time_base else (1.0 / sample_rate)

            if start > 0.05:
                try:
                    offset = int(start / time_base) if time_base > 0 else 0
                    container.seek(offset, stream=stream, any_frame=False, backward=True)
                except Exception:
                    try:
                        container.seek(int(start * av.time_base))
                    except Exception:
                        pass

            resampler = av.AudioResampler(format="fltp", layout="stereo", rate=sample_rate)
            chunks: list[np.ndarray] = []
            collected_start: float | None = None
            for frame in container.decode(stream):
                frame_t = (
                    float(frame.pts * stream.time_base)
                    if frame.pts is not None and stream.time_base
                    else None
                )
                if frame_t is not None:
                    if frame_t + 0.05 < start:
                        continue
                    if frame_t >= end_time:
                        break
                    if collected_start is None:
                        collected_start = max(start, frame_t)
                for resampled in resampler.resample(frame):
                    arr = resampled.to_ndarray()  # planar fltp: (channels, samples)
                    if arr.size:
                        chunks.append(arr.T.astype(np.float32, copy=False))
                if chunks:
                    got = sum(c.shape[0] for c in chunks) / float(sample_rate)
                    if got >= max_dur:
                        break
            for resampled in resampler.resample(None):
                arr = resampled.to_ndarray()
                if arr.size:
                    chunks.append(arr.T.astype(np.float32, copy=False))
            if not chunks:
                return None
            samples = np.concatenate(chunks, axis=0)
            max_frames = int(round(max_dur * sample_rate))
            if samples.shape[0] > max_frames:
                samples = samples[:max_frames]
            origin = collected_start if collected_start is not None else start
            return VideoAudioBuffer(
                path=path,
                sample_rate=sample_rate,
                samples=samples,
                origin_seconds=float(origin),
            )
        finally:
            container.close()
