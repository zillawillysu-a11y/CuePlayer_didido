"""Shared decode cache for embedded video audio (playback mixer + timeline waveforms)."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from cueplayer.media.video_audio_loader import VideoAudioBuffer, load_video_audio

_cache: dict[str, tuple[int, VideoAudioBuffer | None]] = {}


def _mtime_ns(path: Path) -> int:
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return 0


def get_video_audio(path: Path) -> VideoAudioBuffer | None:
    """Return decoded PCM for `path`, reusing cache entries keyed by path + mtime."""
    path = Path(path)
    key = str(path)
    mtime = _mtime_ns(path)
    hit = _cache.get(key)
    if hit is not None and hit[0] == mtime:
        return hit[1]
    try:
        buf = load_video_audio(path)
    except Exception:
        buf = None
    _cache[key] = (mtime, buf)
    return buf


def get_video_audio_mono(path: Path) -> tuple[np.ndarray | None, int]:
    """Mono float32 samples and sample rate; `(None, 48000)` when silent / missing."""
    buf = get_video_audio(path)
    if buf is None or buf.frames == 0:
        return None, 48000
    data = buf.samples
    if data.ndim == 2:
        mono = data.mean(axis=1).astype(np.float32)
    else:
        mono = np.asarray(data, dtype=np.float32)
    return mono, int(buf.sample_rate)


def clear_video_audio_cache() -> None:
    _cache.clear()
