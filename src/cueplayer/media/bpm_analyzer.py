"""Lightweight BPM estimation from PCM (numpy only, no extra deps)."""

from __future__ import annotations

from pathlib import Path

import numpy as np


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


def estimate_bpm(
    samples: np.ndarray,
    sample_rate: int,
    *,
    min_bpm: float = 70.0,
    max_bpm: float = 180.0,
    max_seconds: float = 90.0,
) -> float | None:
    """
    Estimate tempo via onset-energy autocorrelation.

    Returns a value rounded to the nearest 0.5 BPM, or None if unreliable.
    """
    if samples is None or sample_rate <= 0:
        return None
    arr = np.asarray(samples, dtype=np.float32)
    if arr.size == 0:
        return None
    mono = arr.mean(axis=1) if arr.ndim == 2 else arr.reshape(-1)
    max_n = int(max(1, sample_rate * max_seconds))
    mono = mono[:max_n]
    if mono.size < sample_rate:  # need ~1s
        return None

    hop = max(256, int(round(sample_rate / 86.0)))  # ~11.6 ms
    n = (mono.size // hop) * hop
    if n < hop * 32:
        return None
    frames = mono[:n].reshape(-1, hop)
    env = np.sqrt(np.mean(frames * frames, axis=1)).astype(np.float64)
    onset = np.maximum(0.0, np.diff(env, prepend=env[:1]))
    onset -= onset.mean()
    if float(np.max(np.abs(onset))) < 1e-9:
        return None

    corr = np.correlate(onset, onset, mode="full")
    mid = len(corr) // 2
    corr = corr[mid:]
    env_rate = float(sample_rate) / float(hop)
    min_lag = max(1, int(env_rate * 60.0 / max_bpm))
    max_lag = int(env_rate * 60.0 / min_bpm)
    if max_lag <= min_lag + 1 or max_lag >= len(corr):
        return None
    window = corr[min_lag : max_lag + 1]
    peak_lag = int(np.argmax(window)) + min_lag
    if peak_lag <= 0:
        return None
    bpm = 60.0 * env_rate / float(peak_lag)

    candidates: list[float] = [bpm, bpm * 2.0, bpm * 0.5]
    best: float | None = None
    best_score = -1.0
    for cand in candidates:
        if not (min_bpm <= cand <= max_bpm):
            continue
        lag = int(round(env_rate * 60.0 / cand))
        if lag <= 0 or lag >= len(corr):
            continue
        score = float(corr[lag])
        if score > best_score:
            best_score = score
            best = cand
    if best is None:
        return None
    return round(best * 2.0) / 2.0


def estimate_bpm_from_path(path: Path | str) -> float | None:
    """Read an audio file and estimate BPM (first ~90s)."""
    import soundfile as sf

    file_path = Path(path)
    if not file_path.is_file():
        return None
    try:
        data, sample_rate = sf.read(str(file_path), always_2d=True, dtype="float32")
    except Exception:  # noqa: BLE001
        return None
    return estimate_bpm(data, int(sample_rate))
