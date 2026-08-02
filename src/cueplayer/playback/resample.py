"""Lightweight linear-interpolation resampler for device sample-rate mismatches."""

from __future__ import annotations

import time

import numpy as np


def resample_linear(samples: np.ndarray, src_rate: float, dst_rate: float) -> np.ndarray:
    """
    Resample (frames,) or (frames, channels) float32 audio from src_rate to dst_rate.

    Linear interpolation is not studio-quality, but it is dependency-free and
    good enough to feed a stream opened at a rate the output device actually
    accepts (e.g. 44.1kHz media on a WASAPI endpoint locked to a 48kHz mix
    format) without pitch/speed drift.
    """
    src = np.asarray(samples, dtype=np.float32)
    n_src = src.shape[0]
    if n_src == 0 or src_rate <= 0 or dst_rate <= 0 or src_rate == dst_rate:
        return src
    n_dst = max(1, int(round(n_src * (float(dst_rate) / float(src_rate)))))
    if n_src == 1:
        return np.repeat(src[:1], n_dst, axis=0)
    src_t = np.arange(n_src, dtype=np.float64)
    dst_t = np.linspace(0.0, n_src - 1, num=n_dst, dtype=np.float64)
    if src.ndim == 1:
        return np.interp(dst_t, src_t, src).astype(np.float32)
    out = np.empty((n_dst, src.shape[1]), dtype=np.float32)
    for ch in range(src.shape[1]):
        out[:, ch] = np.interp(dst_t, src_t, src[:, ch])
    return out


def resample_linear_yielding(
    samples: np.ndarray,
    src_rate: float,
    dst_rate: float,
    *,
    chunk_seconds: float = 0.25,
) -> np.ndarray:
    """Like ``resample_linear``, but yields the GIL between chunks.

    Background video-audio window installs used to run one giant ``np.interp``
    over 30–60s of stereo PCM, starving the PortAudio callback and Preview
    for ~0.5s every window prefetch. Chunk + ``sleep(0)`` keeps playback alive.
    """
    src = np.asarray(samples, dtype=np.float32)
    n_src = int(src.shape[0])
    if n_src == 0 or src_rate <= 0 or dst_rate <= 0 or int(src_rate) == int(dst_rate):
        return src
    chunk = max(1, int(round(float(chunk_seconds) * float(src_rate))))
    if n_src <= chunk:
        return resample_linear(src, src_rate, dst_rate)
    pieces: list[np.ndarray] = []
    i = 0
    while i < n_src:
        j = min(n_src, i + chunk)
        pieces.append(resample_linear(src[i:j], src_rate, dst_rate))
        i = j
        time.sleep(0)
    return np.concatenate(pieces, axis=0)


def ascontiguous_yielding(
    samples: np.ndarray,
    *,
    chunk_seconds: float = 0.5,
    sample_rate: float = 48000.0,
) -> np.ndarray:
    """``ascontiguousarray`` in slices so a huge copy cannot freeze the audio callback."""
    src = np.asarray(samples, dtype=np.float32)
    if src.size == 0 or src.flags.c_contiguous:
        return np.ascontiguousarray(src, dtype=np.float32)
    n = int(src.shape[0])
    chunk = max(1, int(round(float(chunk_seconds) * float(sample_rate))))
    if n <= chunk:
        return np.ascontiguousarray(src, dtype=np.float32)
    if src.ndim == 1:
        out = np.empty(n, dtype=np.float32)
    else:
        out = np.empty((n, src.shape[1]), dtype=np.float32)
    i = 0
    while i < n:
        j = min(n, i + chunk)
        out[i:j] = src[i:j]
        i = j
        time.sleep(0)
    return out


def resample_hold(samples: np.ndarray, src_rate: float, dst_rate: float) -> np.ndarray:
    """
    Nearest-neighbour (zero-order hold) resample for square-wave signals.

    Linear interpolation smears bi-phase LTC; hold resampling preserves edges
    well enough for striped file LTC when device rate differs from file rate.
    """
    src = np.asarray(samples, dtype=np.float32)
    n_src = src.shape[0]
    if n_src == 0 or src_rate <= 0 or dst_rate <= 0 or src_rate == dst_rate:
        return src
    n_dst = max(1, int(round(n_src * (float(dst_rate) / float(src_rate)))))
    if n_src == 1:
        return np.repeat(src[:1], n_dst, axis=0)
    dst_i = np.arange(n_dst, dtype=np.float64)
    src_i = np.floor(dst_i * float(src_rate) / float(dst_rate)).astype(np.int64)
    src_i = np.clip(src_i, 0, n_src - 1)
    if src.ndim == 1:
        return src[src_i].astype(np.float32)
    return src[src_i].astype(np.float32)


def resample_hold_segment(
    mono: np.ndarray,
    src_rate: float,
    dst_rate: float,
    dst_start: int,
    dst_frames: int,
) -> np.ndarray:
    """Hold-resample a mono channel for playback-rate frames [dst_start, dst_start+dst_frames)."""
    if dst_frames <= 0:
        return np.zeros(0, dtype=np.float32)
    src = np.asarray(mono, dtype=np.float32).reshape(-1)
    if src.size == 0 or src_rate <= 0 or dst_rate <= 0:
        return np.zeros(dst_frames, dtype=np.float32)
    if int(src_rate) == int(dst_rate):
        end = min(dst_start + dst_frames, src.size)
        out = np.zeros(dst_frames, dtype=np.float32)
        if end > dst_start:
            n = end - dst_start
            out[:n] = src[dst_start:end]
        return out
    dst_i = np.arange(dst_start, dst_start + dst_frames, dtype=np.float64)
    src_i = np.floor(dst_i * float(src_rate) / float(dst_rate)).astype(np.int64)
    src_i = np.clip(src_i, 0, src.size - 1)
    return src[src_i].astype(np.float32)


def resample_linear_segment(
    samples: np.ndarray,
    src_rate: float,
    dst_rate: float,
    dst_start: int,
    dst_frames: int,
) -> np.ndarray:
    """Linear-resample a slice for playback-rate frames [dst_start, dst_start+dst_frames)."""
    if dst_frames <= 0:
        ch = 1 if samples.ndim == 1 else max(1, int(samples.shape[1]))
        return np.zeros((0, ch), dtype=np.float32) if samples.ndim != 1 else np.zeros(0, dtype=np.float32)
    src = np.asarray(samples, dtype=np.float32)
    if src.size == 0 or src_rate <= 0 or dst_rate <= 0:
        ch = 1 if src.ndim == 1 else max(1, src.shape[1])
        return np.zeros((dst_frames, ch), dtype=np.float32) if src.ndim != 1 else np.zeros(dst_frames, dtype=np.float32)
    if int(src_rate) == int(dst_rate):
        end = min(dst_start + dst_frames, src.shape[0])
        if src.ndim == 1:
            out = np.zeros(dst_frames, dtype=np.float32)
            if end > dst_start:
                out[: end - dst_start] = src[dst_start:end]
            return out
        out = np.zeros((dst_frames, src.shape[1]), dtype=np.float32)
        if end > dst_start:
            out[: end - dst_start] = src[dst_start:end]
        return out
    dst_t = np.arange(dst_start, dst_start + dst_frames, dtype=np.float64)
    src_t = np.clip(
        dst_t * float(src_rate) / float(dst_rate),
        0.0,
        max(0.0, float(src.shape[0] - 1)),
    )
    src_x = np.arange(src.shape[0], dtype=np.float64)
    if src.ndim == 1:
        return np.interp(src_t, src_x, src).astype(np.float32)
    out = np.empty((dst_frames, src.shape[1]), dtype=np.float32)
    for ch in range(src.shape[1]):
        out[:, ch] = np.interp(src_t, src_x, src[:, ch])
    return out
