"""Downsampled peak envelopes for video-clip lane waveforms."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from cueplayer.domain.models import VideoClip
from cueplayer.media.video_audio_cache import get_video_audio_mono_for_waveform

PREVIEW_WAVEFORM_BUCKETS = 256
DEFAULT_WAVEFORM_BUCKETS = 1024
MAX_WAVEFORM_BUCKETS = 2048


@dataclass(frozen=True)
class ClipWaveformKey:
    path: str
    mtime_ns: int
    source_in: float
    source_out: float | None
    duration: float
    media_kind: str
    buckets: int


@dataclass
class ClipWaveformPeaks:
    mins: np.ndarray  # float32, normalized signed min per bucket
    maxs: np.ndarray  # float32, normalized signed max per bucket


def build_clip_waveform_peaks(
    clip: VideoClip,
    *,
    mono: np.ndarray,
    sample_rate: int,
    buckets: int,
    mono_origin_seconds: float = 0.0,
) -> ClipWaveformPeaks | None:
    """
    Peak envelope over the clip's timeline length.

    Respects source trim and loops embedded audio when the clip is longer than
    its trimmed source span (same rule as `VideoAudioMixer.chunk_at`).

    ``mono_origin_seconds`` is the source time of ``mono[0]`` (windowed decode).
    """
    if mono.size == 0 or sample_rate <= 0:
        return None
    buckets = max(8, int(buckets))
    duration = max(0.0, float(clip.duration_seconds))
    if duration <= 1e-9:
        return None

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
        s1 = min(mono.size, center + half_window)
        if s0 >= s1:
            continue
        segment = mono[s0:s1]
        mins[b] = float(segment.min())
        maxs[b] = float(segment.max())

    peak = max(float(np.max(np.abs(mins))), float(np.max(np.abs(maxs))), 1e-9)
    mins /= peak
    maxs /= peak
    return ClipWaveformPeaks(mins=mins, maxs=maxs)


def waveform_buckets_for_clip(clip: VideoClip) -> int:
    """Background hi-res envelope length for one cache entry."""
    duration = max(0.0, float(clip.duration_seconds))
    return max(
        PREVIEW_WAVEFORM_BUCKETS,
        min(MAX_WAVEFORM_BUCKETS, int(duration * 80)),
    )


def waveform_buckets_for_paint(*, pixel_width: int) -> int:
    """Paint-time resolution — one bucket per ~pixel, capped for speed."""
    px = max(1, int(pixel_width))
    return max(64, min(DEFAULT_WAVEFORM_BUCKETS, px))


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
    """Signed min/max for clip-local time span [clip_t0, clip_t1)."""
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


def build_clip_waveform_peaks_from_path(clip: VideoClip, *, buckets: int) -> ClipWaveformPeaks | None:
    mono, sample_rate, origin = get_video_audio_mono_for_waveform(clip)
    if mono is None:
        return None
    return build_clip_waveform_peaks(
        clip,
        mono=mono,
        sample_rate=sample_rate,
        buckets=buckets,
        mono_origin_seconds=origin,
    )


class VideoClipWaveformCache:
    """Per-clip peak cache with background decode/build."""

    def __init__(self) -> None:
        self._peaks: dict[ClipWaveformKey, ClipWaveformPeaks | None] = {}
        self._pending: set[ClipWaveformKey] = set()
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="vid-wave")
        self._on_ready: Callable[[], None] | None = None

    def set_on_ready(self, callback: Callable[[], None] | None) -> None:
        self._on_ready = callback

    def clear(self) -> None:
        self._peaks.clear()
        self._pending.clear()

    @staticmethod
    def _mtime_ns(path: Path) -> int:
        try:
            return os.stat(path).st_mtime_ns
        except OSError:
            return 0

    def key_for(self, clip: VideoClip, *, buckets: int) -> ClipWaveformKey:
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
            buckets=max(8, int(buckets)),
        )

    def get_peaks(self, clip: VideoClip, *, buckets: int) -> ClipWaveformPeaks | None:
        key = self.key_for(clip, buckets=buckets)
        if key in self._peaks:
            return self._peaks[key]
        if key not in self._pending:
            self._pending.add(key)
            self._executor.submit(self._build_async, key, clip)
        return None

    def peaks_for_paint(self, clip: VideoClip, *, buckets: int) -> ClipWaveformPeaks | None:
        """Return cached peaks for paint, falling back to any available resolution."""
        exact = self.get_peaks(clip, buckets=buckets)
        if exact is not None:
            return exact
        return self._best_available_peaks(clip, buckets=buckets)

    def _best_available_peaks(self, clip: VideoClip, *, buckets: int) -> ClipWaveformPeaks | None:
        """Return exact peaks or the closest cached envelope for this clip."""
        prefix = (
            str(clip.path),
            self._mtime_ns(clip.path),
            round(float(clip.source_in_seconds), 6),
            (
                round(float(clip.source_out_seconds), 6)
                if clip.source_out_seconds is not None
                else None
            ),
            round(float(clip.duration_seconds), 6),
            str(clip.media_kind),
        )
        matches: list[tuple[int, ClipWaveformPeaks]] = []
        for key, peaks in self._peaks.items():
            if peaks is None:
                continue
            if (
                key.path,
                key.mtime_ns,
                key.source_in,
                key.source_out,
                key.duration,
                key.media_kind,
            ) != prefix:
                continue
            matches.append((key.buckets, peaks))
        if not matches:
            return None
        adequate = [m for m in matches if m[0] >= buckets]
        if adequate:
            return min(adequate, key=lambda m: m[0])[1]
        return max(matches, key=lambda m: m[0])[1]

    def preload(self, clips: list[VideoClip], *, buckets: int | None = None) -> None:
        for clip in clips:
            if clip.media_kind == "still":
                continue
            self.get_peaks(clip, buckets=PREVIEW_WAVEFORM_BUCKETS)
            hi = buckets if buckets is not None else waveform_buckets_for_clip(clip)
            if hi > PREVIEW_WAVEFORM_BUCKETS:
                self.get_peaks(clip, buckets=hi)

    def _build_async(self, key: ClipWaveformKey, clip: VideoClip) -> None:
        try:
            peaks = build_clip_waveform_peaks_from_path(clip, buckets=key.buckets)
        except Exception:
            peaks = None
        self._peaks[key] = peaks
        self._pending.discard(key)
        cb = self._on_ready
        if cb is not None:
            cb()
