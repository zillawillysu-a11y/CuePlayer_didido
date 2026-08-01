"""Downsampled peak envelopes for video-clip lane waveforms."""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from cueplayer.domain.models import VideoClip
from cueplayer.media.audio_loader import PeakLevel, build_peak_pyramid, choose_peak_level
from cueplayer.media.video_audio_cache import get_video_audio_mono_for_waveform
from cueplayer.media.video_limits import clip_is_heavy


@dataclass(frozen=True)
class ClipWaveformKey:
    path: str
    mtime_ns: int
    source_in: float
    source_out: float | None
    duration: float
    media_kind: str


@dataclass
class ClipWaveformPeaks:
    """Zoom-aware waveform data — same pyramid strategy as the main audio lane."""

    sample_rate: int
    mono_origin_seconds: float
    mono: np.ndarray  # display-normalized mono indexed by source time - origin
    peak_levels: list[PeakLevel]
    # Legacy single-resolution envelope (preview / tests).
    mins: np.ndarray
    maxs: np.ndarray


def build_clip_waveform_data(
    clip: VideoClip,
    *,
    mono: np.ndarray,
    sample_rate: int,
    mono_origin_seconds: float = 0.0,
) -> ClipWaveformPeaks | None:
    """Build pyramid + mono for a clip's embedded audio (source-time indexed)."""
    if mono.size == 0 or sample_rate <= 0:
        return None
    duration = max(0.0, float(clip.duration_seconds))
    if duration <= 1e-9:
        return None

    display, levels = build_peak_pyramid(mono.reshape(-1, 1), sample_rate)

    # Coarse overview buckets across clip timeline for instant preview paint.
    buckets = max(64, min(512, int(duration * 40)))
    span = max(0.0, clip.source_span_seconds)
    src_in = max(0.0, float(clip.source_in_seconds))
    origin = float(mono_origin_seconds)
    spb = duration / buckets
    half_window = max(1, int(round(sample_rate * max(spb / 2.0, 1.0 / buckets))))
    mins = np.zeros(buckets, dtype=np.float32)
    maxs = np.zeros(buckets, dtype=np.float32)
    t_mids = (np.arange(buckets, dtype=np.float64) + 0.5) * spb
    if clip.media_kind == "still":
        src_times = np.full(buckets, src_in, dtype=np.float64)
    elif span <= 1e-9:
        src_times = np.full(buckets, src_in, dtype=np.float64)
    else:
        src_times = src_in + np.mod(t_mids, span)
    centers = np.round((src_times - origin) * sample_rate).astype(np.int64)
    for b in range(buckets):
        center = int(centers[b])
        s0 = max(0, center - half_window)
        s1 = min(display.size, center + half_window)
        if s0 >= s1:
            continue
        segment = display[s0:s1]
        mins[b] = float(segment.min())
        maxs[b] = float(segment.max())

    return ClipWaveformPeaks(
        sample_rate=int(sample_rate),
        mono_origin_seconds=origin,
        mono=display,
        peak_levels=levels,
        mins=mins,
        maxs=maxs,
    )


def timeline_to_clip_local(timeline_t: float, clip: VideoClip) -> float | None:
    """Map absolute timeline seconds to clip-local seconds, or None if outside."""
    if timeline_t < clip.start_seconds or timeline_t > clip.end_seconds:
        return None
    return timeline_t - clip.start_seconds


def clip_local_to_source_time(clip: VideoClip, clip_local_t: float) -> float:
    """Clip-local timeline seconds → source media seconds (trim + loop)."""
    src_in = max(0.0, float(clip.source_in_seconds))
    if clip.media_kind == "still":
        return src_in
    span = max(0.0, clip.source_span_seconds)
    if span <= 1e-9:
        return src_in
    return src_in + (clip_local_t % span)


def sample_clip_peaks_for_times(
    peaks: ClipWaveformPeaks,
    *,
    duration: float,
    clip_t0: float,
    clip_t1: float,
) -> tuple[float, float]:
    """Signed min/max for clip-local time span [clip_t0, clip_t1) — overview envelope."""
    n = int(peaks.mins.size)
    if n == 0 or duration <= 1e-9:
        return 0.0, 0.0
    clip_t0 = max(0.0, min(duration, clip_t0))
    clip_t1 = max(clip_t0, min(duration, clip_t1))
    b0 = int(clip_t0 / duration * n)
    b1 = min(n, max(b0 + 1, int(clip_t1 / duration * n)))
    lo = float(peaks.mins[b0:b1].min())
    hi = float(peaks.maxs[b0:b1].max())
    return lo, hi


def sample_source_peaks_for_clip_times(
    peaks: ClipWaveformPeaks,
    clip: VideoClip,
    *,
    clip_t0: float,
    clip_t1: float,
    samples_per_pixel: float,
) -> tuple[float, float]:
    """Peak min/max for a clip-local span using the source-time pyramid."""
    src0 = clip_local_to_source_time(clip, clip_t0)
    src1 = clip_local_to_source_time(clip, max(clip_t0, clip_t1 - 1e-9))
    sr = peaks.sample_rate
    origin = peaks.mono_origin_seconds
    s0 = int(round((src0 - origin) * sr))
    s1 = int(round((src1 - origin) * sr))
    s0 = max(0, s0)
    s1 = max(s0 + 1, min(peaks.mono.size, s1))
    level = choose_peak_level(peaks.peak_levels, samples_per_pixel)
    if level is None:
        segment = peaks.mono[s0:s1]
        if segment.size == 0:
            return 0.0, 0.0
        return float(segment.min()), float(segment.max())
    b0 = max(0, s0 // level.samples_per_bucket)
    b1 = min(level.maxs.size, max(b0 + 1, s1 // level.samples_per_bucket))
    return float(level.mins[b0:b1].min()), float(level.maxs[b0:b1].max())


def sample_source_raw_for_clip_times(
    peaks: ClipWaveformPeaks,
    clip: VideoClip,
    *,
    clip_t0: float,
    clip_t1: float,
) -> tuple[float, float]:
    """Raw mono min/max for a clip-local span (high zoom)."""
    src0 = clip_local_to_source_time(clip, clip_t0)
    src1 = clip_local_to_source_time(clip, max(clip_t0, clip_t1 - 1e-9))
    sr = peaks.sample_rate
    origin = peaks.mono_origin_seconds
    s0 = max(0, int(round((src0 - origin) * sr)))
    s1 = max(s0 + 1, min(peaks.mono.size, int(round((src1 - origin) * sr))))
    segment = peaks.mono[s0:s1]
    if segment.size == 0:
        return 0.0, 0.0
    return float(segment.min()), float(segment.max())


def build_clip_waveform_data_from_path(clip: VideoClip) -> ClipWaveformPeaks | None:
    mono, sample_rate, origin = get_video_audio_mono_for_waveform(clip)
    if mono is None:
        return None
    return build_clip_waveform_data(
        clip,
        mono=mono,
        sample_rate=sample_rate,
        mono_origin_seconds=origin,
    )


class VideoClipWaveformCache:
    """Per-clip pyramid cache with background decode/build."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._peaks: dict[ClipWaveformKey, ClipWaveformPeaks | None] = {}
        self._pending: set[ClipWaveformKey] = set()
        self._generation = 0
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="vid-wave")
        self._on_ready: Callable[[], None] | None = None

    def set_on_ready(self, callback: Callable[[], None] | None) -> None:
        self._on_ready = callback

    def clear(self) -> None:
        with self._lock:
            self._generation += 1
            self._peaks.clear()
            self._pending.clear()

    @staticmethod
    def _mtime_ns(path: Path) -> int:
        try:
            return os.stat(path).st_mtime_ns
        except OSError:
            return 0

    def key_for(self, clip: VideoClip) -> ClipWaveformKey:
        return ClipWaveformKey(
            path=str(clip.path),
            mtime_ns=self._mtime_ns(clip.path),
            source_in=round(float(clip.source_in_seconds), 6),
            source_out=(
                round(float(clip.source_out_seconds), 6)
                if clip.source_out_seconds is not None
                else None
            ),
            duration=round(float(clip.duration_seconds), 6),
            media_kind=str(clip.media_kind),
        )

    def get_peaks(self, clip: VideoClip) -> ClipWaveformPeaks | None:
        # Paint path also calls this — must skip heavy clips here, not only
        # in preload(), or the first paint would still decode huge PCM.
        if clip_is_heavy(clip):
            return None
        key = self.key_for(clip)
        with self._lock:
            if key in self._peaks:
                return self._peaks[key]
            if key in self._pending:
                return None
            self._pending.add(key)
            generation = self._generation
        self._executor.submit(self._build_async, generation, key, clip)
        return None

    def peaks_for_paint(self, clip: VideoClip) -> ClipWaveformPeaks | None:
        return self.get_peaks(clip)

    def preload(self, clips: list[VideoClip]) -> None:
        for clip in clips:
            if clip.media_kind == "still":
                continue
            # Skip hour-long sources — decoding capped PCM still holds
            # av_path_lock long enough to freeze Clean Output / Preview.
            if clip_is_heavy(clip):
                continue
            self.get_peaks(clip)

    def _build_async(self, generation: int, key: ClipWaveformKey, clip: VideoClip) -> None:
        try:
            peaks = build_clip_waveform_data_from_path(clip)
        except Exception:
            peaks = None
        with self._lock:
            if generation != self._generation:
                return
            self._peaks[key] = peaks
            self._pending.discard(key)
        # Callback may touch Qt — callers must marshal to the GUI thread.
        cb = self._on_ready
        if cb is not None:
            cb()
