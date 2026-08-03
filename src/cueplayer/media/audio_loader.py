"""Audio file loading and multi-resolution waveform peaks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf


@dataclass
class PeakLevel:
    """One pyramid level: min/max per bucket over `samples_per_bucket` source samples."""

    samples_per_bucket: int
    mins: np.ndarray  # float32
    maxs: np.ndarray  # float32


@dataclass
class AudioBuffer:
    path: Path
    sample_rate: int
    samples: np.ndarray  # float32, shape (frames, channels)
    mono: np.ndarray  # float32 mono for high-zoom drawing
    peak_levels: list[PeakLevel]

    @property
    def frames(self) -> int:
        return int(self.samples.shape[0])

    @property
    def channels(self) -> int:
        return int(self.samples.shape[1]) if self.samples.ndim == 2 else 1

    @property
    def duration_seconds(self) -> float:
        return self.frames / float(self.sample_rate)

    @property
    def peaks(self) -> np.ndarray:
        """Compatibility: abs peak envelope from finest coarse-enough level."""
        level = self.peak_levels[-1] if self.peak_levels else None
        if level is None:
            return np.zeros(1, dtype=np.float32)
        return np.maximum(np.abs(level.mins), np.abs(level.maxs))


def _minmax_buckets(mono: np.ndarray, samples_per_bucket: int) -> PeakLevel:
    spb = max(1, int(samples_per_bucket))
    buckets = max(1, mono.size // spb)
    usable = buckets * spb
    chunk = mono[:usable].reshape(buckets, spb)
    return PeakLevel(
        samples_per_bucket=spb,
        mins=chunk.min(axis=1).astype(np.float32),
        maxs=chunk.max(axis=1).astype(np.float32),
    )


def build_peak_pyramid(samples: np.ndarray, sample_rate: int) -> tuple[np.ndarray, list[PeakLevel]]:
    """
    Build signed min/max peak pyramid for detailed zoom.

    Levels go from coarse overview to ~1ms, then callers may use raw mono
    when zoomed past one sample per pixel.
    """
    if samples.ndim == 2:
        mono = samples.mean(axis=1).astype(np.float32)
    else:
        mono = np.asarray(samples, dtype=np.float32)

    # Normalize for display stability (keep raw samples for playback).
    peak = float(np.max(np.abs(mono))) if mono.size else 1.0
    display = mono / peak if peak > 0 else mono

    # ~1ms finest pyramid level, then coarser powers of two.
    ms = max(1, int(round(sample_rate / 1000)))
    spb_list = [ms * 64, ms * 16, ms * 4, ms]
    # Drop levels that are wider than the whole file.
    spb_list = [spb for spb in spb_list if spb < max(2, display.size)]
    if not spb_list:
        spb_list = [max(1, display.size // 1000)]

    levels = [_minmax_buckets(display, spb) for spb in sorted(set(spb_list), reverse=True)]
    return display, levels


def build_peak_envelope(samples: np.ndarray, target_buckets: int = 4000) -> np.ndarray:
    """Legacy helper used by tests: absolute peak envelope."""
    if samples.ndim == 2:
        mono = samples.mean(axis=1)
    else:
        mono = samples
    mono = np.asarray(mono, dtype=np.float32)
    if mono.size == 0:
        return np.zeros(1, dtype=np.float32)

    buckets = max(1, min(target_buckets, mono.size))
    usable = (mono.size // buckets) * buckets
    if usable <= 0:
        return np.abs(mono[:1])
    chunk = mono[:usable].reshape(buckets, -1)
    peaks = np.max(np.abs(chunk), axis=1)
    peak_max = float(peaks.max()) if peaks.size else 1.0
    if peak_max > 0:
        peaks /= peak_max
    return peaks.astype(np.float32)


def choose_peak_level(levels: list[PeakLevel], samples_per_pixel: float) -> PeakLevel | None:
    if not levels:
        return None
    # Prefer the finest level that still has >= ~1 bucket per pixel.
    for level in reversed(levels):
        if level.samples_per_bucket <= max(1.0, samples_per_pixel):
            return level
    return levels[0]


def load_audio(path: Path) -> AudioBuffer:
    path = Path(path)
    data, sample_rate = sf.read(str(path), always_2d=True, dtype="float32")
    mono, levels = build_peak_pyramid(data, int(sample_rate))
    return AudioBuffer(
        path=path,
        sample_rate=int(sample_rate),
        samples=data,
        mono=mono,
        peak_levels=levels,
    )


def waveform_display_buffer(
    buffer: AudioBuffer,
    *,
    exclude_channel: int | None = None,
) -> AudioBuffer:
    """
    Buffer used only for timeline waveform drawing.

    When ``exclude_channel`` is set (striped LTC on L or R), rebuild mono/peaks
    from the remaining music channel(s) so LTC square-wave energy does not
    dominate the green waveform. Playback still uses ``buffer.samples``.
    """
    if exclude_channel is None:
        return buffer
    samples = buffer.samples
    if samples.ndim != 2 or samples.shape[1] < 2:
        return buffer
    ch = int(exclude_channel)
    if ch < 0 or ch >= samples.shape[1]:
        return buffer
    keep = [i for i in range(samples.shape[1]) if i != ch]
    if not keep:
        return buffer
    music = samples[:, keep]
    if music.shape[1] == 1:
        music = music[:, 0]
    mono, levels = build_peak_pyramid(music, int(buffer.sample_rate))
    return AudioBuffer(
        path=buffer.path,
        sample_rate=buffer.sample_rate,
        samples=buffer.samples,
        mono=mono,
        peak_levels=levels,
    )
