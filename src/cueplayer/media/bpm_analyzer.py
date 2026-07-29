"""Lightweight BPM estimation from PCM (numpy only, no extra deps)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

# Bump when the estimator changes so the UI can re-run auto BPM once per session.
BPM_DETECT_VERSION = 2


def format_bpm_value(bpm: float) -> str:
    if abs(bpm - round(bpm)) < 1e-9:
        return str(int(round(bpm)))
    text = f"{bpm:.3f}".rstrip("0").rstrip(".")
    return text or "0"


def format_bpm_cell(bpm: float | None, *, auto: bool = False) -> str:
    """Setlist display: auto values render as ``<120>``; user values as ``120``."""
    if bpm is None or float(bpm) <= 0:
        return ""
    text = format_bpm_value(float(bpm))
    return f"<{text}>" if auto else text


def parse_bpm_cell(text: str) -> float | None | bool:
    """
    Parse a BPM cell.

    Returns:
      - float on success
      - None if blank
      - False if invalid
    """
    raw = (text or "").strip()
    if raw.startswith("<") and raw.endswith(">") and len(raw) >= 2:
        raw = raw[1:-1].strip()
    raw = raw.replace(",", ".")
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return False
    if value <= 0:
        return False
    return value


def _to_mono(samples: np.ndarray, exclude_channel: int | None) -> np.ndarray:
    arr = np.asarray(samples, dtype=np.float32)
    if arr.ndim == 1:
        return arr.reshape(-1)
    if arr.shape[1] <= 0:
        return arr.reshape(-1)
    if exclude_channel is not None and 0 <= int(exclude_channel) < arr.shape[1]:
        keep = [i for i in range(arr.shape[1]) if i != int(exclude_channel)]
        if keep:
            return arr[:, keep].mean(axis=1)
    return arr.mean(axis=1)


def _tempo_preference(bpm: float) -> float:
    """Log-normal prior peaked near typical song tempo (~120).

    Down-weights half-tempo guesses (e.g. 80 for a 160 track) when comb
    scores are otherwise close, without forbidding legitimate ballads/DnB.
    """
    bpm = max(40.0, float(bpm))
    mu = math.log(120.0)
    sigma = 0.38
    return float(math.exp(-0.5 * ((math.log(bpm) - mu) / sigma) ** 2))


def _onset_envelope(mono: np.ndarray, sample_rate: int, hop: int) -> np.ndarray | None:
    """Energy flux of a simple high-passed signal (emphasizes attacks)."""
    # First-difference high-pass: reduces sustained pads / LTC bleed vs raw RMS.
    hp = np.diff(mono, prepend=mono[:1]).astype(np.float64)
    n = (hp.size // hop) * hop
    if n < hop * 32:
        return None
    frames = hp[:n].reshape(-1, hop)
    env = np.sqrt(np.mean(frames * frames, axis=1))
    onset = np.maximum(0.0, np.diff(env, prepend=env[:1]))
    onset -= onset.mean()
    if float(np.max(np.abs(onset))) < 1e-9:
        return None
    return onset


def _corr_at(corr: np.ndarray, lag: float) -> float:
    """Linear-interpolated autocorrelation sample at a fractional lag."""
    if lag <= 0 or lag >= len(corr) - 1:
        return 0.0
    i0 = int(math.floor(lag))
    i1 = i0 + 1
    frac = lag - i0
    return float(corr[i0] * (1.0 - frac) + corr[i1] * frac)


def _comb_score(corr: np.ndarray, env_rate: float, bpm: float) -> float:
    """Sum weighted autocorr peaks at tempo harmonics (lag, 2lag, …)."""
    lag = env_rate * 60.0 / max(1e-6, bpm)
    score = 0.0
    for k in (1, 2, 3, 4):
        score += _corr_at(corr, lag * k) / float(k)
    return score


def _pick_tempo_octave(
    corr: np.ndarray,
    env_rate: float,
    scored: list[tuple[float, float]],
    *,
    min_bpm: float,
    max_bpm: float,
) -> float | None:
    """Choose among a tempo and its octave partners.

    Half-tempo bias is common with autocorrelation (every-other-beat lag
    scores high). Prefer a competitive tempo inside the perceptual sweet
    spot (~95–140); otherwise prefer the faster octave when it is close.
    """
    if not scored:
        return None
    scored_sorted = sorted(scored, key=lambda kv: kv[1], reverse=True)
    seeds = [bpm for bpm, _s in scored_sorted[:6]]

    pool: dict[float, float] = {}
    for seed in seeds:
        for cand in (seed, seed * 2.0, seed * 0.5):
            key = round(cand * 2.0) / 2.0
            if not (min_bpm <= key <= max_bpm):
                continue
            score = _comb_score(corr, env_rate, key) * (
                0.55 + 0.45 * _tempo_preference(key)
            )
            pool[key] = max(pool.get(key, 0.0), score)

    if not pool:
        return None
    max_s = max(pool.values())
    if max_s <= 0.0:
        return None
    viable = [(b, s) for b, s in pool.items() if s >= max_s * 0.65]
    if not viable:
        return max(pool.items(), key=lambda kv: kv[1])[0]

    sweet = [(b, s) for b, s in viable if 95.0 <= b <= 140.0]
    if sweet:
        return max(sweet, key=lambda kv: kv[1])[0]

    # Outside the sweet spot (ballad / DnB): prefer the faster competitive octave.
    # Autocorr often scores the half-tempo lag higher; accept the double when
    # its comb score is still in the same ballpark.
    viable.sort(key=lambda kv: kv[0])
    fastest_bpm, fastest_score = viable[-1]
    if fastest_score >= max_s * 0.55:
        return fastest_bpm
    return max(viable, key=lambda kv: kv[1])[0]


def _estimate_bpm_window(
    mono: np.ndarray,
    sample_rate: int,
    *,
    min_bpm: float,
    max_bpm: float,
) -> tuple[float, float] | None:
    """Return (bpm, score) for one mono window, or None if unreliable."""
    hop = max(256, int(round(sample_rate / 86.0)))
    onset = _onset_envelope(mono, sample_rate, hop)
    if onset is None:
        return None

    corr = np.correlate(onset, onset, mode="full")
    mid = len(corr) // 2
    corr = corr[mid:].astype(np.float64)
    env_rate = float(sample_rate) / float(hop)
    min_lag = max(1, int(env_rate * 60.0 / max_bpm))
    max_lag = int(env_rate * 60.0 / min_bpm)
    if max_lag <= min_lag + 1 or max_lag >= len(corr):
        return None

    # Relative prominence gate: reject windows with no clear periodic peak.
    window = corr[min_lag : max_lag + 1]
    peak = float(np.max(window))
    med = float(np.median(window))
    if peak <= 0.0 or peak < med * 1.35:
        return None

    scored: list[tuple[float, float]] = []
    for bpm_i in range(int(round(min_bpm * 2)), int(round(max_bpm * 2)) + 1):
        bpm = bpm_i / 2.0
        score = _comb_score(corr, env_rate, bpm) * (0.55 + 0.45 * _tempo_preference(bpm))
        scored.append((bpm, score))
    best = _pick_tempo_octave(
        corr, env_rate, scored, min_bpm=min_bpm, max_bpm=max_bpm
    )
    if best is None:
        return None
    best_score = _comb_score(corr, env_rate, best) * (
        0.55 + 0.45 * _tempo_preference(best)
    )
    if best_score <= 0.0:
        return None
    return best, float(best_score)


def estimate_bpm(
    samples: np.ndarray,
    sample_rate: int,
    *,
    min_bpm: float = 70.0,
    max_bpm: float = 180.0,
    max_seconds: float = 90.0,
    exclude_channel: int | None = None,
) -> float | None:
    """
    Estimate tempo via onset-energy comb autocorrelation.

    Uses a ~120 BPM perceptual prior and harmonic comb scoring so half/double
    tempo mistakes are less common than a single raw peak pick. Returns a
    value rounded to the nearest 0.5 BPM, or None if unreliable.
    """
    if samples is None or sample_rate <= 0:
        return None
    mono = _to_mono(samples, exclude_channel)
    if mono.size == 0:
        return None
    max_n = int(max(1, sample_rate * max_seconds))
    mono = mono[:max_n]
    if mono.size < sample_rate:  # need ~1s
        return None

    # Several windows so intros without groove don't dominate.
    win = int(sample_rate * 30.0)
    hop = int(sample_rate * 20.0)
    starts = [0]
    if mono.size > win:
        t = hop
        while t + win // 2 < mono.size and len(starts) < 4:
            starts.append(t)
            t += hop

    votes: dict[float, float] = {}
    for start in starts:
        chunk = mono[start : start + win] if mono.size > win else mono
        if chunk.size < sample_rate:
            continue
        result = _estimate_bpm_window(chunk, sample_rate, min_bpm=min_bpm, max_bpm=max_bpm)
        if result is None:
            continue
        bpm, score = result
        key = round(bpm * 2.0) / 2.0
        votes[key] = votes.get(key, 0.0) + score

    if not votes:
        return None
    best = max(votes.items(), key=lambda kv: kv[1])[0]
    return float(best)


def estimate_bpm_from_path(
    path: Path | str,
    *,
    exclude_channel: int | None = None,
) -> float | None:
    """Read an audio file and estimate BPM (first ~90s).

    When ``exclude_channel`` is omitted on stereo files, tries LTC detection
    and strips that channel so striped show files don't poison the onset.
    """
    import soundfile as sf

    file_path = Path(path)
    if not file_path.is_file():
        return None
    try:
        data, sample_rate = sf.read(str(file_path), always_2d=True, dtype="float32")
    except Exception:  # noqa: BLE001
        return None
    sr = int(sample_rate)
    channel = exclude_channel
    if channel is None and data.ndim == 2 and data.shape[1] >= 2:
        try:
            from cueplayer.media.ltc_detect import detect_ltc_channel

            channel = detect_ltc_channel(data, sr)
        except Exception:  # noqa: BLE001
            channel = None
    return estimate_bpm(data, sr, exclude_channel=channel)
