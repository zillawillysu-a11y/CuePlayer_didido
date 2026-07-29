"""Lightweight BPM estimation from PCM (numpy only, no extra deps)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

# Bump when the estimator changes (manual re-detect still required for old <n>).
BPM_DETECT_VERSION = 3


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
    """Log-normal prior peaked near typical song tempo (~120)."""
    bpm = max(40.0, float(bpm))
    mu = math.log(120.0)
    sigma = 0.36
    return float(math.exp(-0.5 * ((math.log(bpm) - mu) / sigma) ** 2))


def _onset_envelope(mono: np.ndarray, sample_rate: int, hop: int) -> np.ndarray | None:
    """Energy flux of a simple high-passed signal (emphasizes attacks)."""
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


def _ioi_bpm_hint(
    onset: np.ndarray,
    env_rate: float,
    *,
    min_bpm: float,
    max_bpm: float,
) -> float | None:
    """Median inter-onset interval → BPM hint (helps catch half-tempo misses)."""
    if onset.size < 64:
        return None
    thr = float(np.percentile(onset, 90))
    if thr <= 1e-12:
        return None
    peaks = np.where(
        (onset[1:-1] > thr)
        & (onset[1:-1] >= onset[:-2])
        & (onset[1:-1] >= onset[2:])
    )[0]
    if peaks.size < 10:
        return None
    peaks = peaks + 1
    intervals = np.diff(peaks.astype(np.float64))
    lo = env_rate * 60.0 / max_bpm
    hi = env_rate * 60.0 / min_bpm
    valid = intervals[(intervals >= lo) & (intervals <= hi)]
    if valid.size < 6:
        return None
    med = float(np.median(valid))
    if med <= 1e-9:
        return None
    return 60.0 * env_rate / med


def _snap_show_bpm(bpm: float) -> float:
    """Show music is usually whole BPM; collapse near-integers (fixes *.5 drift)."""
    bpm = float(bpm)
    nearest_int = float(round(bpm))
    if abs(bpm - nearest_int) <= 0.7:
        return nearest_int
    return round(bpm * 2.0) / 2.0


def _pick_tempo_octave(
    corr: np.ndarray,
    env_rate: float,
    scored: list[tuple[float, float]],
    *,
    min_bpm: float,
    max_bpm: float,
    ioi_hint: float | None = None,
) -> float | None:
    """Choose among a tempo and its octave partners."""
    if not scored:
        return None
    scored_sorted = sorted(scored, key=lambda kv: kv[1], reverse=True)
    seeds = [bpm for bpm, _s in scored_sorted[:8]]
    if ioi_hint is not None:
        seeds = [ioi_hint, ioi_hint * 2.0, ioi_hint * 0.5, *seeds]

    pool: dict[float, float] = {}
    for seed in seeds:
        for cand in (seed, seed * 2.0, seed * 0.5):
            key = round(cand * 2.0) / 2.0
            if not (min_bpm <= key <= max_bpm):
                continue
            score = _comb_score(corr, env_rate, key) * (
                0.50 + 0.50 * _tempo_preference(key)
            )
            # Soft pull toward the IOI hint / its octave.
            if ioi_hint is not None and ioi_hint > 0:
                for target in (ioi_hint, ioi_hint * 2.0, ioi_hint * 0.5):
                    if min_bpm <= target <= max_bpm and abs(key - target) <= 3.0:
                        score *= 1.12
                        break
            pool[key] = max(pool.get(key, 0.0), score)

    if not pool:
        return None
    max_s = max(pool.values())
    if max_s <= 0.0:
        return None
    viable = [(b, s) for b, s in pool.items() if s >= max_s * 0.60]
    if not viable:
        return max(pool.items(), key=lambda kv: kv[1])[0]

    sweet = [(b, s) for b, s in viable if 92.0 <= b <= 145.0]
    if sweet:
        return max(sweet, key=lambda kv: kv[1])[0]

    viable.sort(key=lambda kv: kv[0])
    slow_bpm, slow_s = viable[0]
    fastest_bpm, fastest_score = viable[-1]

    def _near(hint: float | None, bpm: float, tol: float = 5.0) -> bool:
        return hint is not None and abs(hint - bpm) <= tol

    # Slow winners are often half-tempo — promote double only when IOI agrees
    # or the double's comb score is nearly tied (avoid flipping true ~75 ballads).
    if slow_bpm < 92.0 and fastest_bpm >= slow_bpm * 1.8:
        if _near(ioi_hint, fastest_bpm) and not _near(ioi_hint, slow_bpm):
            return fastest_bpm
        if fastest_score >= max_s * 0.88:
            return fastest_bpm
        if _near(ioi_hint, slow_bpm):
            return slow_bpm

    if fastest_score >= max_s * 0.55 and fastest_bpm >= 100.0:
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
    # Finer hop → less *.5 quantization drift on mid tempos.
    hop = max(192, int(round(sample_rate / 120.0)))
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

    window = corr[min_lag : max_lag + 1]
    peak = float(np.max(window))
    med = float(np.median(window))
    if peak <= 0.0 or peak < med * 1.35:
        return None

    ioi_hint = _ioi_bpm_hint(onset, env_rate, min_bpm=min_bpm, max_bpm=max_bpm)

    scored: list[tuple[float, float]] = []
    for bpm_i in range(int(round(min_bpm * 2)), int(round(max_bpm * 2)) + 1):
        bpm = bpm_i / 2.0
        score = _comb_score(corr, env_rate, bpm) * (0.50 + 0.50 * _tempo_preference(bpm))
        scored.append((bpm, score))
    best = _pick_tempo_octave(
        corr,
        env_rate,
        scored,
        min_bpm=min_bpm,
        max_bpm=max_bpm,
        ioi_hint=ioi_hint,
    )
    if best is None:
        return None
    best_score = _comb_score(corr, env_rate, best) * (
        0.50 + 0.50 * _tempo_preference(best)
    )
    if best_score <= 0.0:
        return None
    return _snap_show_bpm(best), float(best_score)


def _consolidate_octave_votes(
    votes: dict[float, float],
    *,
    min_bpm: float,
    max_bpm: float,
) -> float | None:
    """After multi-window voting, resolve half/double across the whole file."""
    if not votes:
        return None
    ranked = sorted(votes.items(), key=lambda kv: kv[1], reverse=True)
    pool: dict[float, float] = dict(votes)
    for bpm, score in ranked[:5]:
        for cand in (bpm * 2.0, bpm * 0.5):
            key = _snap_show_bpm(cand)
            if not (min_bpm <= key <= max_bpm):
                continue
            pool[key] = pool.get(key, 0.0) + score * 0.45

    max_s = max(pool.values())
    viable = [(b, s) for b, s in pool.items() if s >= max_s * 0.55]
    if not viable:
        return _snap_show_bpm(ranked[0][0])

    sweet = [(b, s) for b, s in viable if 92.0 <= b <= 145.0]
    if sweet:
        return _snap_show_bpm(max(sweet, key=lambda kv: kv[1])[0])

    viable.sort(key=lambda kv: kv[0])
    slow_bpm, slow_s = viable[0]
    fast_bpm, fast_s = viable[-1]
    # Only promote slow→fast when the double is nearly as strong as the half.
    if (
        slow_bpm < 92.0
        and fast_bpm >= slow_bpm * 1.8
        and fast_s >= slow_s * 0.90
        and fast_s >= max_s * 0.70
    ):
        return _snap_show_bpm(fast_bpm)
    return _snap_show_bpm(max(viable, key=lambda kv: kv[1])[0])


def estimate_bpm(
    samples: np.ndarray,
    sample_rate: int,
    *,
    min_bpm: float = 70.0,
    max_bpm: float = 180.0,
    max_seconds: float = 180.0,
    exclude_channel: int | None = None,
) -> float | None:
    """
    Estimate tempo via onset-energy comb autocorrelation.

    Uses a ~120 BPM perceptual prior and harmonic comb scoring so half/double
    tempo mistakes are less common than a single raw peak pick. Returns a
    value rounded toward whole BPM when close (show music), else 0.5 BPM.

    Rehearsal / show files often have talk and silence: we scan up to
    ``max_seconds``, score candidate windows by onset activity, and only vote
    with the densest musical slices (skipping gaps).
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

    win = int(sample_rate * 30.0)
    hop = int(sample_rate * 15.0)
    starts: list[int] = [0]
    if mono.size > win:
        t = hop
        while t + win // 2 < mono.size:
            starts.append(t)
            t += hop

    ranked: list[tuple[float, int]] = []
    hop_n = max(192, int(round(sample_rate / 120.0)))
    for start in starts:
        chunk = mono[start : start + win] if mono.size > win else mono
        if chunk.size < sample_rate * 2:
            continue
        onset = _onset_envelope(chunk, sample_rate, hop_n)
        if onset is None:
            continue
        activity = float(np.mean(onset * onset))
        if activity <= 1e-12:
            continue
        ranked.append((activity, start))
    ranked.sort(key=lambda item: item[0], reverse=True)
    chosen_starts = [start for _act, start in ranked[:5]]
    if not chosen_starts:
        chosen_starts = starts[:3]

    votes: dict[float, float] = {}
    top_act = ranked[0][0] if ranked else 1.0
    for start in chosen_starts:
        chunk = mono[start : start + win] if mono.size > win else mono
        if chunk.size < sample_rate:
            continue
        result = _estimate_bpm_window(chunk, sample_rate, min_bpm=min_bpm, max_bpm=max_bpm)
        if result is None:
            continue
        bpm, score = result
        key = _snap_show_bpm(bpm)
        activity = next((a for a, s in ranked if s == start), 1.0)
        votes[key] = votes.get(key, 0.0) + score * (0.5 + 0.5 * activity / top_act)

    return _consolidate_octave_votes(votes, min_bpm=min_bpm, max_bpm=max_bpm)


def estimate_bpm_from_path(
    path: Path | str,
    *,
    exclude_channel: int | None = None,
) -> float | None:
    """Read an audio file and estimate BPM (first ~3 minutes of audio).

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
