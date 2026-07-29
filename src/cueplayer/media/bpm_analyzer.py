"""Lightweight BPM estimation from PCM (numpy only, no extra deps).

Auto BPM is a best-effort starting point for show files (talk, gaps, LTC).
Half/double ambiguity is common — the UI exposes ×2 / ÷2 for one-click fix.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

BPM_DETECT_VERSION = 5

_BPM_READ_SECONDS = 90.0
_BPM_ANALYZE_SECONDS = 60.0


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


def _onset_envelope(mono: np.ndarray, sample_rate: int, hop: int) -> np.ndarray | None:
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


def _snap_show_bpm(bpm: float) -> float:
    bpm = float(bpm)
    nearest_int = float(round(bpm))
    if abs(bpm - nearest_int) <= 0.75:
        return nearest_int
    return round(bpm * 2.0) / 2.0


def _estimate_bpm_window(
    mono: np.ndarray,
    sample_rate: int,
    *,
    min_bpm: float,
    max_bpm: float,
) -> tuple[float, float] | None:
    """Return (bpm, raw_comb_score) for one mono window — no octave flipping."""
    hop = max(192, int(round(sample_rate / 110.0)))
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

    # Strongest comb on a 0.5 BPM grid. Deliberately do NOT auto-pick ×2/÷2 —
    # that guess was wrong more often than right on real show files. Users fix
    # octave with setlist ×2 / ÷2.
    best_bpm = None
    best_score = -1.0
    for bpm_i in range(int(round(min_bpm * 2)), int(round(max_bpm * 2)) + 1):
        bpm = bpm_i / 2.0
        score = _comb_score(corr, env_rate, bpm)
        if score > best_score:
            best_score = score
            best_bpm = bpm
    if best_bpm is None or best_score <= 0.0:
        return None
    # Sub-grid refine: parabolic peak around the winning lag (cuts ±1 BPM drift).
    lag = env_rate * 60.0 / best_bpm
    y0 = _corr_at(corr, lag - 1.0)
    y1 = _corr_at(corr, lag)
    y2 = _corr_at(corr, lag + 1.0)
    denom = (y0 - 2.0 * y1 + y2)
    if abs(denom) > 1e-12 and y1 >= y0 and y1 >= y2:
        delta = 0.5 * (y0 - y2) / denom
        if abs(delta) <= 1.0:
            refined_lag = lag + delta
            if refined_lag > 1e-6:
                best_bpm = 60.0 * env_rate / refined_lag
    return _snap_show_bpm(best_bpm), float(best_score)


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

    Picks the strongest period in ``min_bpm``–``max_bpm`` across the densest
    audio windows. Does not invent half/double — those need human ×2/÷2 on
    show material with talk/gaps.
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

    hop_n = max(192, int(round(sample_rate / 110.0)))
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

    if not votes:
        return None
    return _snap_show_bpm(max(votes.items(), key=lambda kv: kv[1])[0])


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
