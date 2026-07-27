"""Heuristic detection of which stereo source channel carries striped LTC."""

from __future__ import annotations

import numpy as np


def detect_ltc_channel(
    samples: np.ndarray,
    sample_rate: int,
    *,
    max_seconds: float = 3.0,
) -> int | None:
    """
    Guess which channel (0=L, 1=R) looks like LTC vs music.

    LTC (bi-phase mark) has a much higher zero-crossing rate and sharper edges
    than typical music beds. Returns ``None`` when both channels score similarly.
    """
    if sample_rate <= 0 or samples.size == 0:
        return None
    if samples.ndim == 1:
        return None
    channels = int(samples.shape[1])
    if channels < 2:
        return None

    n = min(int(samples.shape[0]), int(sample_rate * max_seconds))
    if n < sample_rate // 8:
        return None

    def _score(ch: np.ndarray) -> float:
        x = ch[:n].astype(np.float64, copy=False)
        if x.size < 4:
            return 0.0
        # Zero-crossing rate — LTC is very high vs music.
        signs = np.signbit(x).astype(np.int8)
        zcr = float(np.mean(signs[1:] != signs[:-1]))
        rms = float(np.sqrt(np.mean(x * x))) + 1e-12
        hf = float(np.mean(np.abs(np.diff(x)))) / rms
        # Crest factor: square-ish LTC stays high.
        peak = float(np.max(np.abs(x))) + 1e-12
        crest = peak / rms
        return zcr * 3.0 + hf * 1.5 + min(crest, 8.0) * 0.05

    s0 = _score(samples[:, 0])
    s1 = _score(samples[:, 1])
    lo, hi = (s0, s1) if s0 <= s1 else (s1, s0)
    if hi < 1e-6 or hi / (lo + 1e-9) < 1.2:
        return None
    return 0 if s0 > s1 else 1
