"""Heuristic detection of which stereo source channel carries striped LTC."""

from __future__ import annotations

import numpy as np

# Bi-phase LTC bit clock is fps*80 (≈1920–2400 Hz). At 44.1–96 kHz that lands
# in a narrow zero-crossing band; music/noise usually sits outside it.
_LTC_ZCR_MIN = 0.025
_LTC_ZCR_MAX = 0.110
# Square-ish constant-amplitude carrier (crest ≈ 1); reject spiky music/noise.
_LTC_CREST_MAX = 2.2
# Both legs of a stripe must carry energy — silent "R" is not striped LTC.
_MIN_RMS = 0.01
# Envelope of true LTC is nearly flat; music pumps.
_MAX_ENV_CV = 0.35


def _channel_features(ch: np.ndarray, sample_rate: int) -> dict[str, float]:
    x = ch.astype(np.float64, copy=False)
    if x.size < 4 or sample_rate <= 0:
        return {"rms": 0.0, "zcr": 0.0, "crest": 0.0, "env_cv": 1.0, "ltc_score": 0.0}

    signs = np.signbit(x).astype(np.int8)
    zcr = float(np.mean(signs[1:] != signs[:-1]))
    rms = float(np.sqrt(np.mean(x * x))) + 1e-12
    peak = float(np.max(np.abs(x))) + 1e-12
    crest = peak / rms

    frame = max(sample_rate // 20, 64)
    n = (x.size // frame) * frame
    if n >= frame * 2:
        frames = x[:n].reshape(-1, frame)
        frame_rms = np.sqrt(np.mean(frames * frames, axis=1))
        env_cv = float(np.std(frame_rms) / (float(np.mean(frame_rms)) + 1e-12))
    else:
        env_cv = 1.0

    in_band = _LTC_ZCR_MIN <= zcr <= _LTC_ZCR_MAX
    crest_ok = crest <= _LTC_CREST_MAX
    stable = env_cv <= _MAX_ENV_CV
    # Soft score: peak near mid-band ZCR with square crest + flat envelope.
    if rms < _MIN_RMS or not in_band:
        ltc_score = 0.0
    else:
        # Distance from ideal ~0.06 ZCR (30 fps mid-bit rate at 48 kHz).
        zcr_fit = 1.0 - min(1.0, abs(zcr - 0.06) / 0.06)
        crest_fit = 1.0 - min(1.0, max(0.0, crest - 1.0) / 1.2)
        stab_fit = 1.0 - min(1.0, env_cv / _MAX_ENV_CV)
        ltc_score = float(
            (0.45 * zcr_fit + 0.30 * crest_fit + 0.25 * stab_fit)
            * (1.0 if crest_ok and stable else 0.35)
        )

    return {
        "rms": rms,
        "zcr": zcr,
        "crest": crest,
        "env_cv": env_cv,
        "ltc_score": ltc_score,
    }


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

    Returns ``None`` when the file does not look like a music+LTC stripe
    (pure stereo music, mono, silence on one leg, or ambiguous scores).
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
        feats = [_channel_features(samples[start:end, ch], sample_rate) for ch in range(channels)]
        # Striped LTC always has energy on both the LTC and music legs.
        if any(f["rms"] < _MIN_RMS for f in feats[:2]):
            continue
        scores = [f["ltc_score"] for f in feats]
        ranked = sorted(enumerate(scores), key=lambda item: item[1], reverse=True)
        best_ch, hi = ranked[0]
        lo = ranked[1][1] if len(ranked) > 1 else 0.0
        # Need a clearly LTC-like winner, not just "slightly more square than music".
        if hi < 0.45 or hi < lo + 0.12:
            continue
        votes.append((best_ch, hi - lo))

    if not votes:
        return None

    by_ch: dict[int, float] = {}
    counts: dict[int, int] = {}
    for ch, margin in votes:
        by_ch[ch] = by_ch.get(ch, 0.0) + margin
        counts[ch] = counts.get(ch, 0) + 1
    ranked = sorted(by_ch.items(), key=lambda item: item[1], reverse=True)
    best_ch, best_score = ranked[0]
    if len(ranked) > 1 and abs(best_score - ranked[1][1]) < 1e-6:
        return None
    # Require the winner to show up in a majority of scored windows.
    if counts.get(best_ch, 0) < max(1, (len(votes) + 1) // 2):
        return None
    return int(best_ch)
