"""BPM estimation from PCM.

Tempo errors on show files are usually *tactus* (which pulse you tap), not a
wrong period math — e.g. 4/4 half-time (68 vs 136), ballad double (83 vs 166),
or 6/8 dotted-quarter vs eighth feel. We estimate candidates with librosa, then
pick the pulse that best matches onset density + beat-grid contrast.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np

BPM_DETECT_VERSION = 7

_BPM_READ_SECONDS = 90.0
_BPM_ANALYZE_SECONDS = 60.0
_DEFAULT_MIN_BPM = 60.0
_DEFAULT_MAX_BPM = 200.0

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
        # Progress UI text must never be treated as a typed BPM value.
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


def _onset_rate_per_sec(mono: np.ndarray, sample_rate: int) -> float:
    import librosa

    times = librosa.onset.onset_detect(y=mono, sr=sample_rate, units="time")
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


def _grid_contrast(onset_env: np.ndarray, sr: int, hop: int, bpm: float) -> float:
    """On-beat vs halfway-beat onset contrast for a candidate pulse."""
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


def _density_fit(onset_rate: float, bpm: float) -> float:
    """
    Prefer pulses where onset density ≈ 1× or 2× the beat rate.

    4/4 with 8th hats → dens≈2; sparse ballad → dens≈1.
    Half-time wrong guess (68 for a 136 song) → dens≈2.5–3 → poor fit at 68,
    good fit after doubling. Double-time wrong guess on a ballad → dens≈0.5.
    """
    beat_rate = float(bpm) / 60.0
    if beat_rate <= 1e-6 or onset_rate <= 1e-6:
        return 0.05
    dens = onset_rate / beat_rate
    return float(
        max(
            np.exp(-((dens - 1.0) ** 2) / (2 * 0.35**2)),
            0.90 * np.exp(-((dens - 2.0) ** 2) / (2 * 0.45**2)),
            0.35 * np.exp(-((dens - 0.5) ** 2) / (2 * 0.25**2)),
            # Compound / 6/8: three subdivisions per tapped pulse.
            0.55 * np.exp(-((dens - 3.0) ** 2) / (2 * 0.55**2)),
        )
    )


def _tempo_prior(bpm: float) -> float:
    """Mild preference for show-music tapping range (~70–160)."""
    return float(np.exp(-((np.log(max(1.0, bpm)) - np.log(110.0)) ** 2) / (2 * 0.48**2)))


def _candidate_pool(
    mono: np.ndarray,
    sample_rate: int,
    *,
    min_bpm: float,
    max_bpm: float,
) -> list[float]:
    import librosa

    pool: set[float] = set()
    onset_env = librosa.onset.onset_strength(y=mono, sr=sample_rate)

    for start_bpm in (80.0, 100.0, 120.0, 140.0, 160.0):
        try:
            tempo, _beats = librosa.beat.beat_track(
                y=mono,
                sr=sample_rate,
                onset_envelope=onset_env,
                start_bpm=start_bpm,
                tightness=100,
            )
            raw = _as_float(tempo)
        except Exception:  # noqa: BLE001
            raw = 0.0
        if raw > 1.0:
            pool.add(raw)
        try:
            t2 = _as_float(
                librosa.feature.tempo(
                    onset_envelope=onset_env,
                    sr=sample_rate,
                    start_bpm=start_bpm,
                )
            )
        except Exception:  # noqa: BLE001
            t2 = 0.0
        if t2 > 1.0:
            pool.add(t2)

    # Meter / tactus relatives. Most show-file mistakes are 4/4 half-time or
    # double-time (×1/2, ×2). Compound 6/8 (×2/3, ×3/2, ×3) is real but was
    # stealing votes from straight 4/4 grooves (e.g. 136 → 91), so keep those
    # out of the auto pool for now.
    expanded: set[float] = set()
    for bpm in list(pool):
        for factor in (0.5, 1.0, 2.0):
            expanded.add(bpm * factor)

    return [
        bpm
        for bpm in expanded
        if min_bpm * 0.98 <= bpm <= max_bpm * 1.02
    ]


def _pick_tactus(
    mono: np.ndarray,
    sample_rate: int,
    candidates: list[float],
    *,
    onset_rate: float,
) -> float | None:
    if not candidates:
        return None
    import librosa

    hop = 512
    onset_env = librosa.onset.onset_strength(y=mono, sr=sample_rate, hop_length=hop)
    scored: list[tuple[float, float]] = []
    for bpm in candidates:
        contrast = _grid_contrast(onset_env, sample_rate, hop, bpm)
        if contrast <= 0.0:
            continue
        dens = _density_fit(onset_rate, bpm)
        prior = _tempo_prior(bpm)
        score = float(contrast) * dens * (0.50 + 0.50 * prior)
        scored.append((score, bpm))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def _report_progress(progress: ProgressFn | None, percent: int) -> None:
    if progress is None:
        return
    try:
        progress(max(0, min(100, int(percent))))
    except Exception:  # noqa: BLE001
        pass


def _estimate_with_librosa(
    mono: np.ndarray,
    sample_rate: int,
    *,
    min_bpm: float,
    max_bpm: float,
    progress: ProgressFn | None = None,
) -> float | None:
    starts = _activity_starts(mono, sample_rate)
    win = int(sample_rate * 30.0)
    votes: dict[float, float] = {}
    total = max(1, len(starts))
    for index, start in enumerate(starts):
        # Analyze windows occupy roughly 30%→90% of the overall job.
        _report_progress(progress, 30 + int(60 * index / total))
        chunk = mono[start : start + win] if mono.size > win else mono
        if chunk.size < sample_rate * 4:
            continue
        peak = float(np.max(np.abs(chunk)))
        if peak < 1e-6:
            continue
        y = (chunk / peak).astype(np.float32)
        onset_rate = _onset_rate_per_sec(y, sample_rate)
        candidates = _candidate_pool(y, sample_rate, min_bpm=min_bpm, max_bpm=max_bpm)
        picked = _pick_tactus(y, sample_rate, candidates, onset_rate=onset_rate)
        if picked is None:
            continue
        key = _snap_show_bpm(picked)
        if key < min_bpm * 0.95 or key > max_bpm * 1.05:
            continue
        # Weight by how well density fits the chosen pulse.
        weight = max(0.15, _density_fit(onset_rate, key))
        votes[key] = votes.get(key, 0.0) + weight

    _report_progress(progress, 92)
    if not votes:
        return None
    return max(votes.items(), key=lambda kv: (kv[1], -abs(kv[0] - 110.0)))[0]


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
    """
    Estimate tempo by choosing the musical pulse (tactus), not only a period.

    Half/double (4/4 half-time) and compound-related (≈2/3, 3/2, 3) candidates
    are scored with onset density + beat-grid contrast.
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
    _report_progress(progress, 20)
    try:
        return _estimate_with_librosa(
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
    _report_progress(progress, 5)
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
    _report_progress(progress, 18)
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
