"""Lightweight linear-interpolation resampler for device sample-rate mismatches."""

from __future__ import annotations

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
