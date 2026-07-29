"""Lightweight BPM estimation from PCM (numpy only, no extra deps)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

BPM_DETECT_VERSION = 4

# Keep analysis light — rehearsal files can be huge; we only need a groove slice.
_BPM_READ_SECONDS = 90.0
_BPM_ANALYZE_SECONDS = 75.0


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
    """Mild prior — flatter than before so ballads (~73) aren't forced to 2×."""
    bpm = max(40.0, float(bpm))
    mu = math.log(110.0)
    sigma = 0.55
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
    if lag <= 0 or lag >= len(corr) - 1:
        return 0.0
    i0 = int(math.floor(lag))
    i1 = i0 + 1
    frac = lag - i0
    return float(corr[i0] * (1.0 - frac) + corr[i1] * frac)


def _comb_score(corr: np.ndarray, env_rate: float, bpm: float) -> float:
    lag = env_rate * 60.0 / max(1e-6, bpm)
    score = 0.0
    for k in (1, 2, 3, 4):
        score += _corr_at(corr, lag * k) / float(k)
    return score


def _onset_peaks(onset: np.ndarray) -> np.ndarray:
    if onset.size < 8:
        return np.zeros(0, dtype=np.int64)
    thr = float(np.percentile(onset, 80))
    if thr <= 1e-12:
        thr = float(np.max(onset)) * 0.3
    peaks = np.where(
        (onset[1:-1] > thr)
        & (onset[1:-1] >= onset[:-2])
        & (onset[1:-1] >= onset[2:])
    )[0]
    return peaks + 1


def _ioi_bpm_hint(
    onset: np.ndarray,
    env_rate: float,
    *,
    min_bpm: float,
    max_bpm: float,
) -> float | None:
    peaks = _onset_peaks(onset)
    if peaks.size < 10:
        return None
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


def _onset_rate_bpm(onset: np.ndarray, env_rate: float) -> float | None:
    """Peaks-per-minute — distinguishes ballad (~80) from double-time (~160)."""
    peaks = _onset_peaks(onset)
    if peaks.size < 8 or env_rate <= 0:
        return None
    duration_s = onset.size / env_rate
    if duration_s < 2.0:
        return None
    return float(peaks.size) * 60.0 / duration_s


def _snap_show_bpm(bpm: float) -> float:
    bpm = float(bpm)
    nearest_int = float(round(bpm))
    if abs(bpm - nearest_int) <= 0.75:
        return nearest_int
    return round(bpm * 2.0) / 2.0


def _pick_octave_pair(
    slow: float,
    fast: float,
    *,
    slow_raw: float,
    fast_raw: float,
    ioi_hint: float | None,
    onset_rate: float | None,
) -> float:
    """Disambiguate ballad vs double-time using onset rate / IOI, not prior alone."""

    def _near(hint: float | None, bpm: float, tol: float = 8.0) -> bool:
        return hint is not None and abs(hint - bpm) <= tol

    # Onset density is the best cue we have for 73 vs 146 / 83 vs 167.
    if onset_rate is not None:
        if abs(onset_rate - fast) + 5.0 < abs(onset_rate - slow):
            return fast
        if abs(onset_rate - slow) + 5.0 < abs(onset_rate - fast):
            return slow
        # Rate near 2×fast (8th notes) still implies the fast pulse.
        if abs(onset_rate - fast * 2.0) <= 12.0 and fast >= 140.0:
            return fast

    if _near(ioi_hint, slow) and not _near(ioi_hint, fast):
        return slow
    if _near(ioi_hint, fast) and not _near(ioi_hint, slow):
        return fast

    # Raw comb: only flip to double if it clearly wins (not just prior-boosted).
    if fast_raw >= slow_raw * 1.20:
        return fast
    return slow


def _pick_tempo_octave(
    corr: np.ndarray,
    env_rate: float,
    scored: list[tuple[float, float]],
    *,
    min_bpm: float,
    max_bpm: float,
    ioi_hint: float | None = None,
    onset_rate: float | None = None,
) -> float | None:
    if not scored:
        return None
    scored_sorted = sorted(scored, key=lambda kv: kv[1], reverse=True)
    seeds = [bpm for bpm, _s in scored_sorted[:10]]
    if ioi_hint is not None:
        seeds = [ioi_hint, ioi_hint * 2.0, ioi_hint * 0.5, *seeds]
    if onset_rate is not None:
        seeds = [onset_rate, onset_rate * 0.5, onset_rate * 2.0, *seeds]

    # Raw comb pool (no prior) for fair octave compare.
    raw_pool: dict[float, float] = {}
    for seed in seeds:
        for cand in (seed, seed * 2.0, seed * 0.5):
            key = round(cand * 2.0) / 2.0
            if not (min_bpm <= key <= max_bpm):
                continue
            raw_pool[key] = max(raw_pool.get(key, 0.0), _comb_score(corr, env_rate, key))

    if not raw_pool:
        return None
    max_raw = max(raw_pool.values())
    if max_raw <= 0.0:
        return None
    viable = [(b, s) for b, s in raw_pool.items() if s >= max_raw * 0.55]
    if not viable:
        return max(raw_pool.items(), key=lambda kv: kv[1])[0]

    # Mild prior only for ranking within a band — not for forcing octaves.
    def _rank_key(item: tuple[float, float]) -> float:
        bpm, raw = item
        return raw * (0.75 + 0.25 * _tempo_preference(bpm))

    sweet = [(b, s) for b, s in viable if 95.0 <= b <= 145.0]
    if sweet:
        return max(sweet, key=_rank_key)[0]

    viable.sort(key=lambda kv: kv[0])
    slow_bpm, slow_raw = viable[0]
    fast_bpm, fast_raw = viable[-1]
    if slow_bpm < 95.0 and fast_bpm >= slow_bpm * 1.85:
        return _pick_octave_pair(
            slow_bpm,
            fast_bpm,
            slow_raw=slow_raw,
            fast_raw=fast_raw,
            ioi_hint=ioi_hint,
            onset_rate=onset_rate,
        )
    return max(viable, key=_rank_key)[0]


def _estimate_bpm_window(
    mono: np.ndarray,
    sample_rate: int,
    *,
    min_bpm: float,
    max_bpm: float,
) -> tuple[float, float] | None:
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
    if peak <= 0.0 or peak < med * 1.30:
        return None

    ioi_hint = _ioi_bpm_hint(onset, env_rate, min_bpm=min_bpm, max_bpm=max_bpm)
    onset_rate = _onset_rate_bpm(onset, env_rate)

    scored: list[tuple[float, float]] = []
    for bpm_i in range(int(round(min_bpm * 2)), int(round(max_bpm * 2)) + 1):
        bpm = bpm_i / 2.0
        raw = _comb_score(corr, env_rate, bpm)
        scored.append((bpm, raw * (0.75 + 0.25 * _tempo_preference(bpm))))
    best = _pick_tempo_octave(
        corr,
        env_rate,
        scored,
        min_bpm=min_bpm,
        max_bpm=max_bpm,
        ioi_hint=ioi_hint,
        onset_rate=onset_rate,
    )
    if best is None:
        return None
    best_raw = _comb_score(corr, env_rate, best)
    if best_raw <= 0.0:
        return None
    return _snap_show_bpm(best), float(best_raw)


def _consolidate_octave_votes(
    votes: dict[float, float],
    *,
    min_bpm: float,
    max_bpm: float,
    onset_rate_hints: list[float],
) -> float | None:
    if not votes:
        return None
    ranked = sorted(votes.items(), key=lambda kv: kv[1], reverse=True)
    pool: dict[float, float] = dict(votes)
    for bpm, score in ranked[:5]:
        for cand in (bpm * 2.0, bpm * 0.5):
            key = _snap_show_bpm(cand)
            if min_bpm <= key <= max_bpm:
                pool[key] = pool.get(key, 0.0) + score * 0.35

    max_s = max(pool.values())
    viable = [(b, s) for b, s in pool.items() if s >= max_s * 0.50]
    if not viable:
        return _snap_show_bpm(ranked[0][0])

    sweet = [(b, s) for b, s in viable if 95.0 <= b <= 145.0]
    if sweet:
        return _snap_show_bpm(max(sweet, key=lambda kv: kv[1])[0])

    viable.sort(key=lambda kv: kv[0])
    slow_bpm, slow_s = viable[0]
    fast_bpm, fast_s = viable[-1]
    rate = float(np.median(onset_rate_hints)) if onset_rate_hints else None
    if slow_bpm < 95.0 and fast_bpm >= slow_bpm * 1.85:
        return _snap_show_bpm(
            _pick_octave_pair(
                slow_bpm,
                fast_bpm,
                slow_raw=slow_s,
                fast_raw=fast_s,
                ioi_hint=None,
                onset_rate=rate,
            )
        )
    return _snap_show_bpm(max(viable, key=lambda kv: kv[1])[0])


def estimate_bpm(
    samples: np.ndarray,
    sample_rate: int,
    *,
    min_bpm: float = 65.0,
    max_bpm: float = 180.0,
    max_seconds: float = _BPM_ANALYZE_SECONDS,
    exclude_channel: int | None = None,
) -> float | None:
    """
    Estimate tempo via onset-energy comb autocorrelation.

    Octave (half/double) is resolved with onset-peak rate so ballads (~73/83)
    are not forced up to ~150/165 by a mid-tempo prior. Returns whole BPM when
    close, else 0.5 BPM.
    """
    if samples is None or sample_rate <= 0:
        return None
    mono = _to_mono(samples, exclude_channel)
    if mono.size == 0:
        return None
    max_n = int(max(1, sample_rate * max_seconds))
    mono = mono[:max_n]
    if mono.size < sample_rate:
        return None

    win = int(sample_rate * 25.0)
    hop = int(sample_rate * 12.0)
    starts: list[int] = [0]
    if mono.size > win:
        t = hop
        while t + win // 2 < mono.size:
            starts.append(t)
            t += hop

    hop_n = max(192, int(round(sample_rate / 120.0)))
    ranked: list[tuple[float, int]] = []
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
    chosen_starts = [start for _act, start in ranked[:4]]
    if not chosen_starts:
        chosen_starts = starts[:2]

    votes: dict[float, float] = {}
    rate_hints: list[float] = []
    top_act = ranked[0][0] if ranked else 1.0
    for start in chosen_starts:
        chunk = mono[start : start + win] if mono.size > win else mono
        if chunk.size < sample_rate:
            continue
        onset = _onset_envelope(chunk, sample_rate, hop_n)
        if onset is not None:
            env_rate = float(sample_rate) / float(hop_n)
            rate = _onset_rate_bpm(onset, env_rate)
            if rate is not None:
                rate_hints.append(rate)
        result = _estimate_bpm_window(chunk, sample_rate, min_bpm=min_bpm, max_bpm=max_bpm)
        if result is None:
            continue
        bpm, score = result
        key = _snap_show_bpm(bpm)
        activity = next((a for a, s in ranked if s == start), 1.0)
        votes[key] = votes.get(key, 0.0) + score * (0.5 + 0.5 * activity / top_act)

    return _consolidate_octave_votes(
        votes,
        min_bpm=min_bpm,
        max_bpm=max_bpm,
        onset_rate_hints=rate_hints,
    )


def estimate_bpm_from_path(
    path: Path | str,
    *,
    exclude_channel: int | None = None,
) -> float | None:
    """Read only the start of an audio file and estimate BPM (memory-light)."""
    import soundfile as sf

    file_path = Path(path)
    if not file_path.is_file():
        return None
    try:
        info = sf.info(str(file_path))
        sr = int(info.samplerate)
        frames = int(min(info.frames, max(1, sr * _BPM_READ_SECONDS)))
        data, sample_rate = sf.read(
            str(file_path),
            always_2d=True,
            dtype="float32",
            frames=frames,
            start=0,
        )
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
