"""BPM estimation from PCM (MixMeister-style onset autocorrelation).

MixMeister BPM Analyzer is the user's ground-truth tool: onset strength →
period search via autocorrelation / comb filtering, then pick the tapped
pulse. We follow that shape, but:

- analyze at 22.05 kHz across several ~25 s windows (not only the densest)
- full-spectrum onset for busy grooves; kick-band (<180 Hz) onset to
  stop soft ballads locking onto 2× (73→146, 83→164)
- resolve half/double with density + kick/full agreement, then
  activity-weighted octave-fold consensus across windows (fixes ±1 drift
  like 135→136 / 136→137 on real show stems)
- fold absurd double-time locks above ~190 (204→102)
- refine ±2 BPM on a 0.25 comb grid, then snap to show integers

``librosa`` is used for onset strength / STFT (+ optional resample). Numba
JIT is warmed once in the background so the first real detect is not a hitch.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from pathlib import Path

import numpy as np

BPM_DETECT_VERSION = 12

_BPM_READ_SECONDS = 75.0
_BPM_ANALYZE_SECONDS = 75.0
_ANALYZE_SR = 22050
_HOP = 256
_WINDOW_SECONDS = 25.0
_WINDOW_HOP_SECONDS = 5.0
_MAX_WINDOWS = 10
_DEFAULT_MIN_BPM = 60.0
_DEFAULT_MAX_BPM = 200.0
# Show tapping almost never sits above this as the pulse; prefer half (204→102).
_SHOW_TACTUS_CEILING = 190.0
_KICK_MAX_HZ = 180.0

ProgressFn = Callable[[int], None]


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


def is_bpm_progress_text(text: str) -> bool:
    """True for detect-progress placeholders (``…`` / ``67%``), not user BPM."""
    raw = (text or "").strip()
    if not raw:
        return False
    if raw in {"…", "...", "⋯", "．．．"}:
        return True
    if raw.endswith("%"):
        num = raw[:-1].strip().replace(",", ".")
        try:
            pct = float(num)
        except ValueError:
            return False
        return 0.0 <= pct <= 100.0
    return False


def parse_bpm_cell(text: str) -> float | None | bool:
    """
    Parse a BPM cell.

    Returns:
      - float on success
      - None if blank
      - False if invalid
    """
    raw = (text or "").strip()
    if is_bpm_progress_text(raw):
        return False
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


def warmup_bpm_analyzer() -> None:
    """JIT-compile librosa onset path once (call from a background worker)."""
    try:
        import librosa

        y = np.zeros(_ANALYZE_SR, dtype=np.float32)
        librosa.onset.onset_strength(y=y, sr=_ANALYZE_SR, hop_length=_HOP)
    except Exception:  # noqa: BLE001
        pass


def _report_progress(progress: ProgressFn | None, percent: int) -> None:
    if progress is None:
        return
    try:
        progress(max(0, min(100, int(percent))))
    except Exception:  # noqa: BLE001
        pass


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


def _snap_show_bpm(bpm: float) -> float:
    bpm = float(bpm)
    nearest_int = float(round(bpm))
    # Slightly wider than before so 135.6 / 136.4 land on MixMeister integers.
    if abs(bpm - nearest_int) <= 0.70:
        return nearest_int
    half = round(bpm * 2.0) / 2.0
    if abs(bpm - half) <= 0.30:
        return half
    return nearest_int if abs(bpm - nearest_int) <= abs(bpm - half) else half


def _resample_mono(mono: np.ndarray, sample_rate: int, target_sr: int) -> np.ndarray:
    if sample_rate == target_sr:
        return mono.astype(np.float32, copy=False)
    try:
        import librosa

        return librosa.resample(
            mono.astype(np.float32, copy=False),
            orig_sr=sample_rate,
            target_sr=target_sr,
            res_type="kaiser_fast",
        ).astype(np.float32)
    except Exception:  # noqa: BLE001
        # Cheap fallback: linear interpolate.
        duration = mono.size / float(sample_rate)
        n = max(1, int(round(duration * target_sr)))
        x_old = np.linspace(0.0, 1.0, num=mono.size, endpoint=False)
        x_new = np.linspace(0.0, 1.0, num=n, endpoint=False)
        return np.interp(x_new, x_old, mono).astype(np.float32)


def _densest_window(mono: np.ndarray, sample_rate: int, seconds: float) -> np.ndarray:
    win = int(sample_rate * seconds)
    if mono.size <= win:
        return mono
    hop = max(sample_rate // 2, win // 4)
    frame = max(256, int(sample_rate * 0.02))
    best_start = 0
    best_act = -1.0
    t = 0
    while t + win // 2 < mono.size:
        chunk = mono[t : t + win]
        n = (chunk.size // frame) * frame
        if n >= frame * 8:
            frames = chunk[:n].reshape(-1, frame)
            energy = np.sqrt(np.mean(frames * frames, axis=1))
            onset = np.maximum(0.0, np.diff(energy, prepend=energy[:1]))
            # Prefer punchy grooves over continuous talk/noise floors.
            peaky = float(np.percentile(onset, 92))
            act = peaky * peaky * float(np.mean(onset * onset) + 1e-12)
            if act > best_act:
                best_act = act
                best_start = t
        t += hop
    return mono[best_start : best_start + win]


def _onset_envelope(mono: np.ndarray, sample_rate: int) -> np.ndarray | None:
    import librosa

    peak = float(np.max(np.abs(mono)))
    if peak < 1e-6:
        return None
    y = (mono / peak).astype(np.float32)
    onset = librosa.onset.onset_strength(y=y, sr=sample_rate, hop_length=_HOP)
    onset = np.asarray(onset, dtype=np.float64)
    if onset.size < 32:
        return None
    onset = onset - float(onset.mean())
    if float(np.max(np.abs(onset))) < 1e-9:
        return None
    return onset


def _onset_rate_per_sec(mono: np.ndarray, sample_rate: int) -> float:
    import librosa

    times = librosa.onset.onset_detect(
        y=mono, sr=sample_rate, hop_length=_HOP, units="time"
    )
    if times is None or len(times) < 4:
        return 0.0
    times = np.asarray(times, dtype=float)
    dur = float(mono.size) / float(sample_rate)
    t0, t1 = dur * 0.1, dur * 0.9
    times = times[(times >= t0) & (times <= t1)]
    if len(times) < 4:
        return 0.0
    span = float(times[-1] - times[0])
    if span < 1.0:
        return 0.0
    return float(len(times) / span)


def _corr_at(corr: np.ndarray, lag: float) -> float:
    if lag <= 1.0 or lag >= len(corr) - 1:
        return 0.0
    i0 = int(np.floor(lag))
    frac = lag - i0
    return float(corr[i0] * (1.0 - frac) + corr[i0 + 1] * frac)


def _comb_score(corr: np.ndarray, env_rate: float, bpm: float) -> float:
    lag = env_rate * 60.0 / max(1e-6, bpm)
    score = _corr_at(corr, lag)
    for k in (2, 3, 4):
        score += _corr_at(corr, lag * k) / float(k)
    return score


def _density_fit(onset_rate: float, bpm: float) -> float:
    beat_rate = float(bpm) / 60.0
    if beat_rate <= 1e-6 or onset_rate <= 1e-6:
        return 0.05
    dens = onset_rate / beat_rate
    return float(
        max(
            np.exp(-((dens - 1.0) ** 2) / (2 * 0.32**2)),
            0.92 * np.exp(-((dens - 2.0) ** 2) / (2 * 0.42**2)),
            0.25 * np.exp(-((dens - 0.5) ** 2) / (2 * 0.22**2)),
            0.45 * np.exp(-((dens - 3.0) ** 2) / (2 * 0.55**2)),
        )
    )


def _tempo_prior(bpm: float) -> float:
    """Mild MixMeister-like preference for common show tapping range."""
    return float(np.exp(-((np.log(max(1.0, bpm)) - np.log(105.0)) ** 2) / (2 * 0.55**2)))


def _grid_contrast(onset_env: np.ndarray, env_rate: float, bpm: float) -> float:
    period_f = env_rate * 60.0 / max(1e-6, bpm)
    if period_f < 2.0:
        return -1.0
    n = len(onset_env)
    best = -1.0
    for phase in np.linspace(0.0, period_f, num=max(8, int(period_f)), endpoint=False):
        on_idx = (phase + np.arange(0.0, n, period_f)).astype(int)
        off_idx = (phase + period_f * 0.5 + np.arange(0.0, n, period_f)).astype(int)
        on_idx = on_idx[(on_idx >= 0) & (on_idx < n)]
        off_idx = off_idx[(off_idx >= 0) & (off_idx < n)]
        if len(on_idx) < 4 or len(off_idx) < 4:
            continue
        ratio = float(np.mean(onset_env[on_idx])) / (float(np.mean(onset_env[off_idx])) + 1e-9)
        if ratio > best:
            best = ratio
    return best


def _candidate_tempos(
    corr: np.ndarray,
    env_rate: float,
    *,
    min_bpm: float,
    max_bpm: float,
) -> list[tuple[float, float]]:
    """Return [(comb_score, bpm), ...] for top autocorrelation peaks + halves/doubles."""
    scored: list[tuple[float, float]] = []
    for bpm_i in range(int(round(min_bpm * 4)), int(round(max_bpm * 4)) + 1):
        bpm = bpm_i / 4.0
        scored.append((_comb_score(corr, env_rate, bpm), bpm))
    scored.sort(reverse=True)
    # Keep a small peak set, then expand octaves around each.
    seeds = [bpm for _score, bpm in scored[:8]]
    pool: set[float] = set()
    for bpm in seeds:
        for factor in (0.5, 1.0, 2.0):
            cand = bpm * factor
            if min_bpm * 0.98 <= cand <= max_bpm * 1.02:
                pool.add(cand)
    out = [(_comb_score(corr, env_rate, bpm), bpm) for bpm in pool]
    out.sort(reverse=True)
    return out


def _pick_tactus(
    onset_env: np.ndarray,
    env_rate: float,
    candidates: list[tuple[float, float]],
    *,
    onset_rate: float,
    corr: np.ndarray | None = None,
) -> float | None:
    """Pick tempo: strongest comb period, then octave via density + grid."""
    if not candidates:
        return None
    seed_comb, seed = max(candidates, key=lambda item: item[0])
    octave_pool: list[float] = []
    for factor in (0.5, 1.0, 2.0):
        octave_pool.append(seed * factor)
    for _comb, bpm in candidates[:16]:
        for factor in (0.5, 1.0, 2.0):
            rel = seed * factor
            if abs(bpm - rel) / max(rel, 1e-6) < 0.08:
                octave_pool.append(bpm)

    ranked: list[tuple[float, float]] = []
    seen: set[float] = set()
    for bpm in octave_pool:
        key = round(float(bpm) * 4.0) / 4.0
        if key in seen:
            continue
        seen.add(key)
        if key < 60.0 * 0.98 or key > 200.0 * 1.02:
            continue
        comb = next((c for c, b in candidates if abs(b - key) < 0.13), 0.0)
        if comb <= 0.0 and corr is not None:
            comb = _comb_score(corr, env_rate, key)
        if comb <= 0.0:
            comb = float(seed_comb) * 0.25
        dens = _density_fit(onset_rate, key)
        prior = _tempo_prior(key)
        grid = _grid_contrast(onset_env, env_rate, key)
        grid_term = 0.65 + 0.35 * (
            max(0.2, min(float(grid) if grid > 0 else 0.2, 8.0)) / 4.0
        )
        score = float(comb) * (0.48 + 0.52 * dens) * (0.48 + 0.52 * prior) * grid_term
        if abs(key - seed) / max(seed, 1e-6) < 0.06:
            score *= 1.08
        ranked.append((score, key))
    if not ranked:
        return float(seed)
    ranked.sort(reverse=True)
    return ranked[0][1]


def _kick_band_seed(
    mono: np.ndarray,
    sample_rate: int,
    *,
    min_bpm: float,
    max_bpm: float,
) -> float | None:
    """Dominant tempo from low-band energy flux (kick / bass pulse)."""
    import librosa

    peak = float(np.max(np.abs(mono)))
    if peak < 1e-6:
        return None
    y = (mono / peak).astype(np.float32)
    stft = np.abs(librosa.stft(y, n_fft=2048, hop_length=_HOP))
    freqs = librosa.fft_frequencies(sr=sample_rate, n_fft=2048)
    low_bins = freqs <= _KICK_MAX_HZ
    if not np.any(low_bins):
        return None
    low = stft[low_bins].mean(axis=0)
    onset = np.maximum(0.0, np.diff(low, prepend=low[:1])).astype(np.float64)
    onset = onset - float(onset.mean())
    if float(np.max(np.abs(onset))) < 1e-9 or onset.size < 32:
        return None
    env_rate = float(sample_rate) / float(_HOP)
    corr = np.correlate(onset, onset, mode="full")
    corr = corr[len(corr) // 2 :].astype(np.float64)
    candidates = _candidate_tempos(corr, env_rate, min_bpm=min_bpm, max_bpm=max_bpm)
    if not candidates:
        return None
    return float(candidates[0][1])


def _merge_full_and_kick(
    full_bpm: float,
    kick_bpm: float | None,
    *,
    onset_rate: float,
) -> float:
    """Prefer kick when full-spectrum locked onto a soft-ballad double."""
    if kick_bpm is None or kick_bpm <= 0:
        return float(full_bpm)
    full = float(full_bpm)
    kick = float(kick_bpm)
    dens_full = onset_rate / max(1e-6, full / 60.0)
    ratio = full / max(kick, 1e-6)
    # Classic failure: full≈2×kick (73→146, 83→164). Keep kick unless the
    # full-band density clearly shows a busy groove at the fast pulse.
    if 1.85 <= ratio <= 2.15 and 66.0 <= kick <= 115.0:
        if dens_full < 1.75:
            return kick
        return full
    # Near agreement — stay with full (already refined).
    if abs(full - kick) / max(full, 1e-6) <= 0.06:
        return full
    # Unrelated mid-tempo kick (金黃色-style): trust kick in show ballad range
    # when full looks like an odd non-octave lock.
    if 70.0 <= kick <= 110.0 and not (1.85 <= ratio <= 2.15) and dens_full < 1.35:
        if abs(full - kick) >= 12.0:
            return kick
    return full


def _refine_nearby(
    onset_env: np.ndarray,
    corr: np.ndarray,
    env_rate: float,
    bpm: float,
    *,
    onset_rate: float,
    min_bpm: float,
    max_bpm: float,
) -> float:
    """Local ±2 BPM comb search, then prefer a nearby integer when close."""
    del onset_env, onset_rate
    best_bpm = bpm
    best_score = -1.0
    for bpm_i in range(int(round((bpm - 2.0) * 4)), int(round((bpm + 2.0) * 4)) + 1):
        cand = bpm_i / 4.0
        if cand < min_bpm * 0.98 or cand > max_bpm * 1.02:
            continue
        score = _comb_score(corr, env_rate, cand)
        if score > best_score:
            best_score = score
            best_bpm = cand
    nearest = float(round(best_bpm))
    if abs(best_bpm - nearest) <= 0.85 and min_bpm <= nearest <= max_bpm:
        int_score = _comb_score(corr, env_rate, nearest)
        if int_score >= 0.96 * best_score:
            return nearest
    return best_bpm


def _window_activity(mono: np.ndarray, sample_rate: int) -> float:
    frame = max(256, int(sample_rate * 0.02))
    n = (mono.size // frame) * frame
    if n < frame * 8:
        return 0.0
    frames = mono[:n].reshape(-1, frame)
    energy = np.sqrt(np.mean(frames * frames, axis=1))
    onset = np.maximum(0.0, np.diff(energy, prepend=energy[:1]))
    peaky = float(np.percentile(onset, 92))
    return float(peaky * peaky * (float(np.mean(onset * onset)) + 1e-12))


def _analysis_windows(mono: np.ndarray, sample_rate: int) -> list[np.ndarray]:
    """Densest groove window plus evenly spaced companions across the buffer."""
    win_n = int(sample_rate * _WINDOW_SECONDS)
    if mono.size < sample_rate * 4:
        return []
    if mono.size <= win_n:
        return [mono]

    hop = max(sample_rate // 2, int(sample_rate * _WINDOW_HOP_SECONDS))
    max_start = mono.size - win_n
    starts = list(range(0, max_start + 1, hop))
    if starts[-1] != max_start:
        starts.append(max_start)
    if len(starts) > _MAX_WINDOWS:
        idx = np.linspace(0, len(starts) - 1, num=_MAX_WINDOWS, dtype=int)
        starts = [starts[int(i)] for i in idx]

    windows = [mono[s : s + win_n] for s in starts]
    # Always include densest groove slice (may overlap a companion window).
    windows.append(_densest_window(mono, sample_rate, _WINDOW_SECONDS))
    return windows


def _estimate_one_window(
    mono: np.ndarray,
    sample_rate: int,
    *,
    min_bpm: float,
    max_bpm: float,
) -> tuple[float, float, float] | None:
    """Return (snapped_bpm, onset_rate, activity) for one analysis window."""
    onset = _onset_envelope(mono, sample_rate)
    if onset is None:
        return None
    onset_rate = _onset_rate_per_sec(mono, sample_rate)
    env_rate = float(sample_rate) / float(_HOP)
    corr = np.correlate(onset, onset, mode="full")
    corr = corr[len(corr) // 2 :].astype(np.float64)
    candidates = _candidate_tempos(corr, env_rate, min_bpm=min_bpm, max_bpm=max_bpm)
    picked = _pick_tactus(
        onset, env_rate, candidates, onset_rate=onset_rate, corr=corr
    )
    if picked is None:
        return None
    kick = _kick_band_seed(mono, sample_rate, min_bpm=min_bpm, max_bpm=max_bpm)
    picked = _merge_full_and_kick(picked, kick, onset_rate=onset_rate)
    refined = _refine_nearby(
        onset,
        corr,
        env_rate,
        picked,
        onset_rate=onset_rate,
        min_bpm=min_bpm,
        max_bpm=max_bpm,
    )
    snapped = _snap_show_bpm(refined)
    return float(snapped), float(onset_rate), _window_activity(mono, sample_rate)


def _consensus_bpm(
    estimates: list[float],
    onset_rates: list[float],
    activities: list[float],
) -> float | None:
    """Pick a reference tempo, map windows onto that octave, then majority vote.

    Soft octave votes find the tapped pulse (68 vs 136). Mapping then keeps
    legitimate fast clicks (167) from being pulled to half by the midrange prior.
    """
    if not estimates:
        return None
    if len(estimates) == 1:
        return float(estimates[0])
    med_or = float(np.median(np.asarray(onset_rates, dtype=np.float64)))
    acts = np.asarray(activities, dtype=np.float64)
    if acts.size == 0:
        return float(estimates[0])
    if float(np.max(acts)) < 1e-18:
        # Synthetic clicks / flat envelopes: fall back to equal votes.
        acts = np.ones(acts.shape[0], dtype=np.float64)
    else:
        acts = np.sqrt(np.maximum(acts, 0.0))
        acts = acts / (float(np.max(acts)) + 1e-18)

    pool: set[float] = set()
    for bpm in estimates:
        for factor in (0.5, 1.0, 2.0):
            cand = _snap_show_bpm(float(bpm) * factor)
            if _DEFAULT_MIN_BPM <= cand <= _DEFAULT_MAX_BPM:
                pool.add(float(cand))

    ref_ranked: list[tuple[float, float]] = []
    for cand in pool:
        score = 0.0
        for bpm, _onset_rate, act in zip(estimates, onset_rates, acts, strict=True):
            for factor, weight in ((1.0, 1.0), (0.5, 0.7), (2.0, 0.7)):
                alt = float(bpm) * factor
                if abs(alt - cand) / max(cand, 1e-6) <= 0.05:
                    score += float(act) * weight
                    break
        # Mild prior only — must not overturn clear majorities at 160+.
        score *= 0.75 + 0.25 * _tempo_prior(cand)
        score *= 0.7 + 0.3 * _density_fit(med_or, cand)
        ref_ranked.append((score, cand))
    ref_ranked.sort(reverse=True)
    reference = float(ref_ranked[0][1])

    mapped: list[float] = []
    for bpm in estimates:
        opts = [float(bpm)]
        for factor in (0.5, 2.0):
            alt = _snap_show_bpm(float(bpm) * factor)
            if _DEFAULT_MIN_BPM <= alt <= _DEFAULT_MAX_BPM:
                opts.append(float(alt))
        mapped.append(
            float(min(opts, key=lambda x: abs(np.log(max(x, 1e-6) / max(reference, 1e-6)))))
        )

    weighted: Counter[float] = Counter()
    raw_counts: Counter[float] = Counter()
    for bpm, act in zip(mapped, acts, strict=True):
        weighted[float(bpm)] += float(act)
        raw_counts[float(bpm)] += 1

    ranked = sorted(
        raw_counts.items(),
        key=lambda item: (item[1], weighted[item[0]]),
        reverse=True,
    )
    if len(ranked) >= 2:
        (bpm0, count0), (bpm1, count1) = ranked[0], ranked[1]
        if count0 == count1 and abs(bpm0 - bpm1) <= 1.5:
            med = float(np.median(np.asarray(mapped, dtype=np.float64)))
            return float(bpm1 if abs(bpm1 - med) < abs(bpm0 - med) else bpm0)
    return float(ranked[0][0])


def _prefer_show_tactus(bpm: float) -> float:
    """Halve absurd double-time locks above the show ceiling (204→102).

    Legitimate fast taps like Neon (~170) stay put; only values above
    ``_SHOW_TACTUS_CEILING`` fold down while half remains a valid tempo.
    """
    value = float(bpm)
    while value > _SHOW_TACTUS_CEILING and (value * 0.5) >= _DEFAULT_MIN_BPM:
        value = _snap_show_bpm(value * 0.5)
    return float(value)


def _estimate_core(
    mono: np.ndarray,
    sample_rate: int,
    *,
    min_bpm: float,
    max_bpm: float,
    progress: ProgressFn | None = None,
) -> float | None:
    _report_progress(progress, 15)
    mono = _resample_mono(mono, sample_rate, _ANALYZE_SR)
    sample_rate = _ANALYZE_SR
    _report_progress(progress, 28)
    windows = _analysis_windows(mono, sample_rate)
    if not windows:
        return None

    estimates: list[float] = []
    onset_rates: list[float] = []
    activities: list[float] = []
    n = len(windows)
    for i, win in enumerate(windows):
        _report_progress(progress, 30 + int(55 * (i / max(1, n))))
        one = _estimate_one_window(
            win, sample_rate, min_bpm=min_bpm, max_bpm=max_bpm
        )
        if one is None:
            continue
        bpm, onset_rate, activity = one
        estimates.append(bpm)
        onset_rates.append(onset_rate)
        activities.append(activity)

    _report_progress(progress, 90)
    consensus = _consensus_bpm(estimates, onset_rates, activities)
    if consensus is None:
        return None
    _report_progress(progress, 95)
    return _prefer_show_tactus(consensus)


def estimate_bpm(
    samples: np.ndarray,
    sample_rate: int,
    *,
    min_bpm: float = _DEFAULT_MIN_BPM,
    max_bpm: float = _DEFAULT_MAX_BPM,
    max_seconds: float = _BPM_ANALYZE_SECONDS,
    exclude_channel: int | None = None,
    progress: ProgressFn | None = None,
) -> float | None:
    """Estimate tempo via MixMeister-style onset autocorrelation + tactus pick."""
    if samples is None or sample_rate <= 0:
        return None
    mono = _to_mono(samples, exclude_channel)
    if mono.size == 0:
        return None
    max_n = int(max(1, sample_rate * max_seconds))
    mono = mono[:max_n]
    if mono.size < sample_rate:
        return None
    _report_progress(progress, 8)
    try:
        return _estimate_core(
            mono,
            sample_rate,
            min_bpm=float(min_bpm),
            max_bpm=float(max_bpm),
            progress=progress,
        )
    except ImportError:
        return None


def estimate_bpm_from_path(
    path: Path | str,
    *,
    exclude_channel: int | None = None,
    progress: ProgressFn | None = None,
) -> float | None:
    """Read only the start of an audio file and estimate BPM (memory-light)."""
    import soundfile as sf

    file_path = Path(path)
    if not file_path.is_file():
        return None
    _report_progress(progress, 3)
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
    _report_progress(progress, 12)
    sr = int(sample_rate)
    channel = exclude_channel
    if channel is None and data.ndim == 2 and data.shape[1] >= 2:
        try:
            from cueplayer.media.ltc_detect import detect_ltc_channel

            channel = detect_ltc_channel(data, sr)
        except Exception:  # noqa: BLE001
            channel = None
    result = estimate_bpm(data, sr, exclude_channel=channel, progress=progress)
    if result is not None:
        _report_progress(progress, 100)
    return result
