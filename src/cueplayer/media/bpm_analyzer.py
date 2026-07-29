"""BPM estimation from PCM.

Uses librosa beat tracking plus an on-beat vs off-beat octave check so
half/double errors common in show files are corrected automatically when
the evidence is clear. ×2 / ÷2 remain available in the UI for edge cases.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

BPM_DETECT_VERSION = 6

_BPM_READ_SECONDS = 90.0
_BPM_ANALYZE_SECONDS = 60.0
_DEFAULT_MIN_BPM = 60.0
_DEFAULT_MAX_BPM = 200.0
_OCTAVE_MARGIN = 1.12


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


def _snap_show_bpm(bpm: float) -> float:
    bpm = float(bpm)
    nearest_int = float(round(bpm))
    if abs(bpm - nearest_int) <= 0.75:
        return nearest_int
    return round(bpm * 2.0) / 2.0


def _as_float(value: object) -> float:
    arr = np.asarray(value, dtype=float).reshape(-1)
    if arr.size == 0:
        return 0.0
    return float(arr[0])


def _activity_starts(mono: np.ndarray, sample_rate: int) -> list[int]:
    """Pick densest windows so talk/gaps before the groove are skipped."""
    win = int(sample_rate * 25.0)
    hop = int(sample_rate * 12.0)
    starts: list[int] = [0]
    if mono.size > win:
        t = hop
        while t + win // 2 < mono.size:
            starts.append(t)
            t += hop

    frame = max(256, int(sample_rate * 0.02))
    ranked: list[tuple[float, int]] = []
    for start in starts:
        chunk = mono[start : start + win] if mono.size > win else mono
        if chunk.size < sample_rate * 2:
            continue
        n = (chunk.size // frame) * frame
        if n < frame * 8:
            continue
        frames = chunk[:n].reshape(-1, frame)
        energy = np.sqrt(np.mean(frames * frames, axis=1))
        onset = np.maximum(0.0, np.diff(energy, prepend=energy[:1]))
        activity = float(np.mean(onset * onset))
        if activity <= 1e-12:
            continue
        ranked.append((activity, start))
    ranked.sort(key=lambda item: item[0], reverse=True)
    chosen = [start for _act, start in ranked[:3]]
    return chosen or starts[:1]


def _on_off_ratio(onset_env: np.ndarray, sr: int, hop: int, bpm: float) -> float:
    """Higher when beat grid lands on onsets and misses the halfway points."""
    period_f = (60.0 / max(1e-6, bpm)) * float(sr) / float(hop)
    if period_f < 2.0:
        return -1.0
    n = len(onset_env)
    best = -1.0
    phase_count = max(8, int(period_f))
    for phase in np.linspace(0.0, period_f, num=phase_count, endpoint=False):
        on_idx = (phase + np.arange(0.0, n, period_f)).astype(int)
        off_idx = (phase + period_f * 0.5 + np.arange(0.0, n, period_f)).astype(int)
        on_idx = on_idx[(on_idx >= 0) & (on_idx < n)]
        off_idx = off_idx[(off_idx >= 0) & (off_idx < n)]
        if len(on_idx) < 4 or len(off_idx) < 4:
            continue
        on_s = float(np.mean(onset_env[on_idx]))
        off_s = float(np.mean(onset_env[off_idx]))
        ratio = on_s / (off_s + 1e-9)
        if ratio > best:
            best = ratio
    return best


def _bring_into_range(bpm: float, min_bpm: float, max_bpm: float) -> float:
    value = float(bpm)
    while value < min_bpm and value * 2.0 <= max_bpm * 1.01:
        value *= 2.0
    while value > max_bpm and value / 2.0 >= min_bpm * 0.99:
        value /= 2.0
    return value


def _resolve_octave(
    mono: np.ndarray,
    sample_rate: int,
    bpm0: float,
    *,
    min_bpm: float,
    max_bpm: float,
) -> float:
    """Pick half/same/double using on-beat vs off-beat onset contrast."""
    import librosa

    hop = 512
    onset = librosa.onset.onset_strength(y=mono, sr=sample_rate, hop_length=hop)
    base = _bring_into_range(bpm0, min_bpm, max_bpm)
    scored: list[tuple[float, float]] = []
    for factor in (0.5, 1.0, 2.0):
        candidate = base * factor
        if candidate < min_bpm * 0.98 or candidate > max_bpm * 1.02:
            continue
        scored.append((_on_off_ratio(onset, sample_rate, hop, candidate), candidate))
    if not scored:
        return base
    scored.sort(key=lambda item: item[0], reverse=True)
    best_ratio, best_bpm = scored[0]
    base_ratio = next((ratio for ratio, bpm in scored if abs(bpm - base) < 1e-6), None)
    # Only flip octave when the alternative is clearly stronger — avoids
    # doubling slow ballads when half/double are both plausible.
    if base_ratio is not None and best_ratio < base_ratio * _OCTAVE_MARGIN:
        return base
    return best_bpm


def _estimate_with_librosa(
    mono: np.ndarray,
    sample_rate: int,
    *,
    min_bpm: float,
    max_bpm: float,
) -> float | None:
    import librosa

    starts = _activity_starts(mono, sample_rate)
    win = int(sample_rate * 30.0)
    votes: dict[float, float] = {}
    for start in starts:
        chunk = mono[start : start + win] if mono.size > win else mono
        if chunk.size < sample_rate * 4:
            continue
        # Soft peak normalize so quiet grooves still track.
        peak = float(np.max(np.abs(chunk)))
        if peak < 1e-6:
            continue
        y = (chunk / peak).astype(np.float32)
        try:
            tempo, _beats = librosa.beat.beat_track(
                y=y,
                sr=sample_rate,
                start_bpm=float(np.clip((min_bpm + max_bpm) * 0.5, 90.0, 140.0)),
                tightness=100,
            )
        except Exception:  # noqa: BLE001
            continue
        raw = _as_float(tempo)
        if raw <= 1.0:
            continue
        resolved = _resolve_octave(
            y,
            sample_rate,
            raw,
            min_bpm=min_bpm,
            max_bpm=max_bpm,
        )
        key = _snap_show_bpm(resolved)
        if key < min_bpm * 0.95 or key > max_bpm * 1.05:
            continue
        votes[key] = votes.get(key, 0.0) + 1.0

    if not votes:
        return None
    return max(votes.items(), key=lambda kv: (kv[1], -abs(kv[0] - 120.0)))[0]


def estimate_bpm(
    samples: np.ndarray,
    sample_rate: int,
    *,
    min_bpm: float = _DEFAULT_MIN_BPM,
    max_bpm: float = _DEFAULT_MAX_BPM,
    max_seconds: float = _BPM_ANALYZE_SECONDS,
    exclude_channel: int | None = None,
) -> float | None:
    """
    Estimate tempo with librosa beat tracking + octave resolve.

    Analyzes the densest windows in the first ``max_seconds`` so rehearsal
    talk/gaps before the groove are less likely to dominate.
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
    try:
        return _estimate_with_librosa(
            mono,
            sample_rate,
            min_bpm=float(min_bpm),
            max_bpm=float(max_bpm),
        )
    except ImportError:
        return None


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
