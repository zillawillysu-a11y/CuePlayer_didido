"""Audio file loading and multi-resolution waveform peaks."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

# Arm Play once this much PCM is in RAM (rest may still be decoding into the
# same buffer). Long files no longer wait for a full 40‑minute read first.
EARLY_PLAY_SECONDS = 30.0


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
    buckets, remainder = divmod(mono.size, spb)
    usable = buckets * spb
    chunk = mono[:usable].reshape(buckets, spb)
    mins = chunk.min(axis=1).astype(np.float32)
    maxs = chunk.max(axis=1).astype(np.float32)
    if remainder:
        # Preserve the real tail envelope; zero padding would invent amplitude.
        tail = mono[usable:]
        mins = np.append(mins, np.float32(tail.min()))
        maxs = np.append(maxs, np.float32(tail.max()))
    return PeakLevel(
        samples_per_bucket=spb,
        mins=mins,
        maxs=maxs,
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
    # Levels are coarse -> fine. Use the coarsest bucket no wider than a pixel.
    for level in levels:
        if level.samples_per_bucket <= max(1.0, samples_per_pixel):
            return level
    return levels[-1]


def probe_audio_duration(path: Path) -> float | None:
    """Return file duration in seconds from metadata (no full decode), or None."""
    path = Path(path)
    try:
        info = sf.info(str(path))
    except Exception:
        return None
    sr = int(getattr(info, "samplerate", 0) or 0)
    frames = int(getattr(info, "frames", 0) or 0)
    if sr > 0 and frames > 0:
        return float(frames) / float(sr)
    duration = float(getattr(info, "duration", 0.0) or 0.0)
    return duration if duration > 0.05 else None


def _quick_display_mono(samples: np.ndarray) -> np.ndarray:
    """Cheap normalized mono for interim paint before the peak pyramid is ready."""
    if samples.ndim == 2:
        mono = samples.mean(axis=1).astype(np.float32)
    else:
        mono = np.asarray(samples, dtype=np.float32)
    peak = float(np.max(np.abs(mono))) if mono.size else 1.0
    return mono / peak if peak > 0 else mono


def _copy_block_into(
    dest: np.ndarray, offset: int, block: np.ndarray
) -> int:
    """Copy ``block`` into ``dest[offset:]``; return frames written."""
    n = min(int(block.shape[0]), int(dest.shape[0]) - offset)
    if n <= 0:
        return 0
    src = block[:n]
    ch = int(dest.shape[1])
    if src.ndim == 1:
        dest[offset : offset + n, 0] = src
        if ch > 1:
            dest[offset : offset + n, 1:] = src[:, np.newaxis]
    elif src.shape[1] == 1 and ch > 1:
        dest[offset : offset + n, :] = src
    elif src.shape[1] >= ch:
        dest[offset : offset + n, :] = src[:, :ch]
    else:
        dest[offset : offset + n, : src.shape[1]] = src
    return n


def load_audio(
    path: Path,
    *,
    on_pcm_ready: Callable[[AudioBuffer], None] | None = None,
    early_play_seconds: float = EARLY_PLAY_SECONDS,
) -> AudioBuffer:
    """
    Decode the file to PCM, then build the display peak pyramid.

    For long files, ``on_pcm_ready`` is called once the first
    ``early_play_seconds`` of PCM are filled (into a full-length buffer that
    continues to load in place) so Play can start before the whole file is
    read. The same AudioBuffer instance is returned after peaks are built.
    """
    path = Path(path)
    info = None
    try:
        info = sf.info(str(path))
    except Exception:
        info = None

    total = int(getattr(info, "frames", 0) or 0) if info is not None else 0
    sample_rate = int(getattr(info, "samplerate", 0) or 0) if info is not None else 0
    channels = int(getattr(info, "channels", 0) or 0) if info is not None else 0

    # Unknown length / exotic containers: fall back to a single full read.
    if total <= 0 or sample_rate <= 0:
        data, sample_rate = sf.read(str(path), always_2d=True, dtype="float32")
        sample_rate = int(sample_rate)
        buffer = AudioBuffer(
            path=path,
            sample_rate=sample_rate,
            samples=data,
            mono=_quick_display_mono(data),
            peak_levels=[],
        )
        if on_pcm_ready is not None:
            on_pcm_ready(buffer)
        mono, levels = build_peak_pyramid(data, sample_rate)
        buffer.mono = mono
        buffer.peak_levels = levels
        return buffer

    channels = max(1, channels)
    samples = np.zeros((total, channels), dtype=np.float32)
    buffer = AudioBuffer(
        path=path,
        sample_rate=sample_rate,
        samples=samples,
        mono=np.zeros(1, dtype=np.float32),
        peak_levels=[],
    )
    early_frames = min(total, max(1, int(float(early_play_seconds) * sample_rate)))
    filled = 0
    early_sent = False
    blocksize = max(1024, sample_rate // 2)

    with sf.SoundFile(str(path)) as handle:
        for block in handle.blocks(
            blocksize=blocksize, dtype="float32", always_2d=True
        ):
            written = _copy_block_into(samples, filled, block)
            if written <= 0:
                break
            filled += written
            if (
                on_pcm_ready is not None
                and not early_sent
                and filled >= early_frames
            ):
                buffer.mono = _quick_display_mono(samples[:filled])
                on_pcm_ready(buffer)
                early_sent = True
            if filled >= total:
                break

    if on_pcm_ready is not None and not early_sent:
        usable = samples if filled >= total else samples[: max(1, filled)]
        if usable is not samples:
            buffer.samples = np.ascontiguousarray(usable, dtype=np.float32)
            samples = buffer.samples
        buffer.mono = _quick_display_mono(samples)
        on_pcm_ready(buffer)

    mono, levels = build_peak_pyramid(samples, sample_rate)
    buffer.mono = mono
    buffer.peak_levels = levels
    return buffer


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


def ltc_waveform_display_buffer(
    buffer: AudioBuffer,
    channel: int,
) -> AudioBuffer | None:
    """
    Display-only buffer for the optional LTC timeline lane (one file channel).

    Returns ``None`` when the channel index is out of range. Playback samples
    stay on the original buffer; this only rebuilds mono/peaks for painting.
    """
    samples = buffer.samples
    if samples.ndim != 2:
        return None
    ch = int(channel)
    if ch < 0 or ch >= samples.shape[1]:
        return None
    mono_src = samples[:, ch]
    mono, levels = build_peak_pyramid(mono_src, int(buffer.sample_rate))
    return AudioBuffer(
        path=buffer.path,
        sample_rate=buffer.sample_rate,
        samples=buffer.samples,
        mono=mono,
        peak_levels=levels,
    )
