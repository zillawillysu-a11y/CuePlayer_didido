"""BPM analyzer unit tests."""

from __future__ import annotations

import numpy as np

from cueplayer.media.bpm_analyzer import (
    estimate_bpm,
    format_bpm_cell,
    parse_bpm_cell,
)


def _click_track(bpm: float, *, seconds: float = 12.0, sr: int = 44100) -> np.ndarray:
    period = int(round(sr * 60.0 / bpm))
    n = int(sr * seconds)
    mono = np.zeros(n, dtype=np.float32)
    for i in range(0, n - 200, period):
        mono[i : i + 120] = 1.0
    return mono.reshape(-1, 1)


def test_format_bpm_cell_auto_uses_brackets() -> None:
    assert format_bpm_cell(120, auto=True) == "<120>"
    assert format_bpm_cell(120.0, auto=False) == "120"
    assert format_bpm_cell(128.5, auto=True) == "<128.5>"
    assert format_bpm_cell(None, auto=True) == ""


def test_parse_bpm_cell_strips_brackets() -> None:
    assert parse_bpm_cell("<120>") == 120.0
    assert parse_bpm_cell("128.5") == 128.5
    assert parse_bpm_cell("") is None
    assert parse_bpm_cell("abc") is False


def test_estimate_bpm_on_click_track() -> None:
    bpm = 120.0
    est = estimate_bpm(_click_track(bpm), 44100)
    assert est is not None
    assert abs(float(est) - bpm) <= 2.0


def test_estimate_bpm_prefers_true_tempo_over_half() -> None:
    """High-tempo click trains must not collapse to half-tempo."""
    bpm = 160.0
    est = estimate_bpm(_click_track(bpm, seconds=16.0), 44100)
    assert est is not None
    assert abs(float(est) - bpm) <= 3.5
    assert float(est) > 120.0  # not ~80


def test_estimate_bpm_double_time_clicks() -> None:
    bpm = 175.0
    est = estimate_bpm(_click_track(bpm, seconds=16.0), 44100)
    assert est is not None
    assert abs(float(est) - bpm) <= 3.5


def test_estimate_bpm_mid_tempo_click_track() -> None:
    bpm = 100.0
    est = estimate_bpm(_click_track(bpm), 44100)
    assert est is not None
    assert abs(float(est) - bpm) <= 2.0


def test_estimate_bpm_excludes_ltc_like_channel() -> None:
    sr = 44100
    music = _click_track(120.0, seconds=10.0, sr=sr)[:, 0]
    # Dense square-ish carrier on R (LTC-like) — would poison mean-mono.
    t = np.arange(music.size, dtype=np.float32) / sr
    ltc = (np.sign(np.sin(2 * np.pi * 2000.0 * t)) * 0.4).astype(np.float32)
    stereo = np.stack([music, ltc], axis=1)
    poisoned = estimate_bpm(stereo, sr, exclude_channel=None)
    cleaned = estimate_bpm(stereo, sr, exclude_channel=1)
    assert cleaned is not None
    assert abs(float(cleaned) - 120.0) <= 3.0
    # Without exclude the result may be wrong; cleaned must stay near 120.
    del poisoned


def test_estimate_bpm_skips_quiet_gap_before_groove() -> None:
    """Rehearsal-like: talk/silence first, then a clear click groove."""
    sr = 44100
    bpm = 120.0
    talk = np.random.RandomState(0).randn(sr * 20).astype(np.float32) * 0.02
    groove = _click_track(bpm, seconds=40.0, sr=sr)[:, 0]
    mono = np.concatenate([talk, groove]).reshape(-1, 1)
    est = estimate_bpm(mono, sr, max_seconds=90.0)
    assert est is not None
    assert abs(float(est) - bpm) <= 3.0


def test_estimate_bpm_silence_returns_none() -> None:
    sr = 44100
    silence = np.zeros((sr * 5, 1), dtype=np.float32)
    assert estimate_bpm(silence, sr) is None
