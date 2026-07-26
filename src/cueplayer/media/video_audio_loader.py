"""Extract a video file's embedded audio track for sample-clock-locked mixing.

CuePlayer has exactly one playback clock: `AudioEngine`'s sample position (see
the `cueplayer.playback.video_sync` module docstring). This module only ever
decodes a whole clip's audio once, up front, into a plain float32 PCM buffer —
`AudioEngine` / `VideoAudioMixer` then slice frames out of it exactly the way
they already slice the loaded music buffer. No independent decode timer, no
second player, no realtime decoding inside the audio callback.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import av
import numpy as np


@dataclass
class VideoAudioBuffer:
    path: Path
    sample_rate: int
    samples: np.ndarray  # float32, shape (frames, channels)

    @property
    def frames(self) -> int:
        return int(self.samples.shape[0])

    @property
    def channels(self) -> int:
        return int(self.samples.shape[1]) if self.samples.ndim == 2 else 1


def load_video_audio(path: Path) -> VideoAudioBuffer | None:
    """
    Decode the first audio stream of a video file to float32 stereo PCM.

    Returns None when the file has no audio stream at all (e.g. a silent VJ
    loop) — callers should treat that the same as an all-zero buffer.
    """
    path = Path(path)
    container = av.open(str(path))
    try:
        stream = next((s for s in container.streams if s.type == "audio"), None)
        if stream is None:
            return None
        sample_rate = int(stream.codec_context.sample_rate or 48000)
        resampler = av.AudioResampler(format="fltp", layout="stereo", rate=sample_rate)
        chunks: list[np.ndarray] = []
        for frame in container.decode(stream):
            for resampled in resampler.resample(frame):
                arr = resampled.to_ndarray()  # planar fltp: (channels, samples)
                if arr.size:
                    chunks.append(arr.T.astype(np.float32, copy=False))
        for resampled in resampler.resample(None):  # flush trailing buffered samples
            arr = resampled.to_ndarray()
            if arr.size:
                chunks.append(arr.T.astype(np.float32, copy=False))
        if not chunks:
            return None
        samples = np.concatenate(chunks, axis=0)
        return VideoAudioBuffer(path=path, sample_rate=sample_rate, samples=samples)
    finally:
        container.close()
