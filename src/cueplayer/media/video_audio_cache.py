"""Shared decode cache for embedded video audio (playback mixer + timeline waveforms)."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import numpy as np

from cueplayer.domain.models import VideoClip
from cueplayer.media.video_audio_loader import (
    MAX_VIDEO_AUDIO_DECODE_SECONDS,
    VideoAudioBuffer,
    load_video_audio,
)

_cache: dict[tuple, VideoAudioBuffer | None] = {}
_mtime: dict[str, int] = {}
# Cache dict + iterators must be guarded: waveform workers and the playback
# mixer both call in (and PyAV releases the GIL during decode).
_cache_lock = threading.RLock()
# Serialize native demux — concurrent av.open on some builds hard-crashes.
_decode_lock = threading.Lock()


def _mtime_ns(path: Path) -> int:
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return 0


def audio_window_for_clip(clip: VideoClip) -> tuple[float, float]:
    """
    (start_seconds, duration_seconds) of source audio needed for this clip.

    Caps at ``MAX_VIDEO_AUDIO_DECODE_SECONDS`` so multi-hour files never fully
    decode into RAM.
    """
    start = max(0.0, float(clip.source_in_seconds))
    span = max(0.05, float(clip.source_span_seconds) or float(clip.duration_seconds))
    span = min(span, MAX_VIDEO_AUDIO_DECODE_SECONDS)
    return start, span


def get_video_audio(
    path: Path,
    *,
    start_seconds: float = 0.0,
    max_duration_seconds: float | None = None,
) -> VideoAudioBuffer | None:
    """Return decoded PCM for a path window, reusing cache entries."""
    path = Path(path)
    start = max(0.0, float(start_seconds))
    if max_duration_seconds is None:
        dur = MAX_VIDEO_AUDIO_DECODE_SECONDS
    else:
        dur = max(0.05, min(float(max_duration_seconds), MAX_VIDEO_AUDIO_DECODE_SECONDS))
    # Quantize window so tiny trim edits don't thrash the cache.
    start_q = round(start, 3)
    dur_q = round(dur, 3)
    mtime = _mtime_ns(path)
    key = (str(path), mtime, start_q, dur_q)
    with _cache_lock:
        if key in _cache:
            return _cache[key]
    with _decode_lock:
        with _cache_lock:
            if key in _cache:
                return _cache[key]
        try:
            buf = load_video_audio(path, start_seconds=start_q, max_duration_seconds=dur_q)
        except Exception:
            buf = None
        with _cache_lock:
            _cache[key] = buf
            return buf


def get_video_audio_for_clip(clip: VideoClip) -> VideoAudioBuffer | None:
    """Decode only the trim window this clip needs (never the whole source file)."""
    start, dur = audio_window_for_clip(clip)
    return get_video_audio(clip.path, start_seconds=start, max_duration_seconds=dur)


def get_video_audio_mono(path: Path) -> tuple[np.ndarray | None, int]:
    """Mono float32 for a path — prefer ``get_video_audio_mono_for_clip`` for clips."""
    buf = get_video_audio(path)
    if buf is None or buf.frames == 0:
        return None, 48000
    data = buf.samples
    if data.ndim == 2:
        mono = data.mean(axis=1).astype(np.float32)
    else:
        mono = np.asarray(data, dtype=np.float32)
    return mono, int(buf.sample_rate)


def get_video_audio_mono_for_clip(clip: VideoClip) -> tuple[np.ndarray | None, int, float]:
    """
    Mono float32 + sample rate + origin_seconds for a clip's trim window.

    ``origin_seconds`` is the source time of mono[0] (for peak indexing).
    """
    buf = get_video_audio_for_clip(clip)
    if buf is None or buf.frames == 0:
        return None, 48000, 0.0
    data = buf.samples
    if data.ndim == 2:
        mono = data.mean(axis=1).astype(np.float32)
    else:
        mono = np.asarray(data, dtype=np.float32)
    return mono, int(buf.sample_rate), float(buf.origin_seconds)


def get_video_audio_mono_for_waveform(clip: VideoClip) -> tuple[np.ndarray | None, int, float]:
    """
    Mono for timeline waveform drawing.

    Decodes from source 0 through the clip's current trim/out point (capped) so
    small left-trim edits reuse the same PCM window instead of re-decoding.
    """
    start, dur = audio_window_for_waveform(clip)
    buf = get_video_audio(clip.path, start_seconds=start, max_duration_seconds=dur)
    if buf is None or buf.frames == 0:
        return None, 48000, 0.0
    data = buf.samples
    if data.ndim == 2:
        mono = data.mean(axis=1).astype(np.float32)
    else:
        mono = np.asarray(data, dtype=np.float32)
    return mono, int(buf.sample_rate), float(buf.origin_seconds)


def audio_window_for_waveform(clip: VideoClip) -> tuple[float, float]:
    """Wide source window for waveform peaks (trim-friendly, still capped)."""
    end = max(
        0.05,
        float(clip.source_in_seconds)
        + float(clip.source_span_seconds or clip.duration_seconds),
    )
    span = min(end, MAX_VIDEO_AUDIO_DECODE_SECONDS)
    return 0.0, span


def peek_video_audio_mono(path: Path) -> tuple[np.ndarray | None, int]:
    """Return mono only if already cached — never triggers a decode (UI paint-safe)."""
    path = Path(path)
    mtime = _mtime_ns(path)
    prefix = str(path)
    with _cache_lock:
        items = list(_cache.items())
    for key, buf in items:
        if key[0] == prefix and key[1] == mtime and buf is not None and buf.frames > 0:
            data = buf.samples
            if data.ndim == 2:
                mono = data.mean(axis=1).astype(np.float32)
            else:
                mono = np.asarray(data, dtype=np.float32)
            return mono, int(buf.sample_rate)
    return None, 48000


def clear_video_audio_cache() -> None:
    with _cache_lock:
        _cache.clear()
        _mtime.clear()
