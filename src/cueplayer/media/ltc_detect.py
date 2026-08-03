"""Heuristic detection of which stereo source channel carries striped LTC."""

from __future__ import annotations

import numpy as np


def _score_channel(ch: np.ndarray) -> float:
    x = ch.astype(np.float64, copy=False)
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


def detect_ltc_channel(
    samples: np.ndarray,
    sample_rate: int,
    *,
    max_seconds: float = 30.0,
    window_seconds: float = 3.0,
    hop_seconds: float = 1.0,
) -> int | None:
    """
    Guess which channel (0=L, 1=R) looks like LTC vs music.

    LTC (bi-phase mark) has a much higher zero-crossing rate and sharper edges
    than typical music beds. Returns ``None`` when both channels score similarly.

    Scans multiple windows across the file so intros / late-starting LTC still
    detect (not only the first three seconds).
    """
    if sample_rate <= 0 or samples.size == 0:
        return None
    if samples.ndim == 1:
        return None
    channels = int(samples.shape[1])
    if channels < 2:
        return None

    total = int(samples.shape[0])
    win = min(total, max(int(sample_rate * window_seconds), sample_rate // 4))
    hop = max(sample_rate // 8, int(sample_rate * hop_seconds))
    max_n = min(total, int(sample_rate * max_seconds))

    votes: list[tuple[int, float]] = []
    for start in range(0, max(1, max_n - win + 1), hop):
        end = min(total, start + win)
        if end - start < sample_rate // 8:
            continue
        s0 = _score_channel(samples[start:end, 0])
        s1 = _score_channel(samples[start:end, 1])
        lo, hi = (s0, s1) if s0 <= s1 else (s1, s0)
        if hi < 1e-6 or hi / (lo + 1e-9) < 1.2:
            continue
        margin = hi / (lo + 1e-9)
        votes.append((0 if s0 > s1 else 1, margin))

    if not votes:
        return None

    # Prefer the channel that wins most windows; break ties by confidence.
    left_score = sum(m for ch, m in votes if ch == 0)
    right_score = sum(m for ch, m in votes if ch == 1)
    if abs(left_score - right_score) < 1e-6:
        return None
    return 0 if left_score > right_score else 1
