"""BPM analyzer unit tests."""

from __future__ import annotations

import numpy as np
import pytest

from cueplayer.media.bpm_analyzer import (
    estimate_bpm,
    format_bpm_cell,
    parse_bpm_cell,
)

librosa = pytest.importorskip("librosa")


def _click_track(bpm: float, *, seconds: float = 12.0, sr: int = 44100) -> np.ndarray:
    period = int(round(sr * 60.0 / bpm))
    n = int(sr * seconds)
    mono = np.zeros(n, dtype=np.float32)
    for i in range(0, n - 200, period):
        mono[i : i + 120] = 1.0
    return mono.reshape(-1, 1)


def _pop_groove(
    bpm: float,
    *,
    seconds: float = 24.0,
    sr: int = 44100,
    eighth_hats: bool = True,
) -> np.ndarray:
    """Kick 1/3 + snare 2/4 (+ optional 8ths) — classic half/double trap."""
    n = int(sr * seconds)
    y = np.zeros(n, dtype=np.float32)
    beat = 60.0 / bpm
    rng = np.random.RandomState(int(bpm) % 97)

    def hit(t: float, amp: float, *, bright: bool = False, length: int = 800) -> None:
        i = int(t * sr)
        if i >= n:
            return
        env = np.exp(-np.linspace(0, 9 if bright else 6, length))
        if bright:
            sig = rng.randn(length).astype(np.float32) * env * amp
        else:
            tl = np.arange(length) / sr
            sig = (np.sin(2 * np.pi * 60.0 * tl) * env * amp).astype(np.float32)
        end = min(n, i + length)
        y[i:end] += sig[: end - i]

    t = 0.0
    beat_i = 0
    while t < seconds:
        if beat_i % 2 == 0:
            hit(t, 1.0, bright=False, length=1100)
        else:
            hit(t, 0.85, bright=True, length=900)
        if eighth_hats:
            hit(t, 0.22, bright=True, length=280)
            hit(t + beat * 0.5, 0.18, bright=True, length=240)
        t += beat
        beat_i += 1
    y += rng.randn(n).astype(np.float32) * 0.01
    return np.tanh(y * 0.8).astype(np.float32).reshape(-1, 1)


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


def test_bpm_progress_placeholders_are_not_user_values() -> None:
    from cueplayer.media.bpm_analyzer import is_bpm_progress_text

    assert is_bpm_progress_text("…")
    assert is_bpm_progress_text("...")
    assert is_bpm_progress_text("67%")
    assert is_bpm_progress_text("100%")
    assert not is_bpm_progress_text("<120>")
    assert not is_bpm_progress_text("120")
    # Progress text must not raise Invalid BPM via the edit path.
    assert parse_bpm_cell("…") is False
    assert parse_bpm_cell("42%") is False


def test_estimate_bpm_on_click_track() -> None:
    bpm = 120.0
    est = estimate_bpm(_click_track(bpm, seconds=16.0), 44100)
    assert est is not None
    assert abs(float(est) - bpm) <= 2.0


def test_estimate_bpm_mid_tempos() -> None:
    for bpm in (96.0, 100.0, 129.0):
        est = estimate_bpm(_click_track(bpm, seconds=18.0), 44100)
        assert est is not None
        assert abs(float(est) - bpm) <= 1.0


@pytest.mark.parametrize(
    "bpm",
    [
        73.0,  # 未曾準備好
        83.0,  # 歸零
        95.0,  # 金黃色的
        96.0,  # 彗尾
        135.0,  # 歹物仔
        136.0,  # 牽我
        167.0,  # 又閣減一工
        170.0,  # Neon
    ],
)
def test_estimate_bpm_ground_truth_show_tempos(bpm: float) -> None:
    """Match tempos the user verified in MixMeister / other BPM software."""
    est = estimate_bpm(_click_track(bpm, seconds=20.0), 44100)
    assert est is not None
    assert abs(float(est) - bpm) <= 1.0, f"expected ~{bpm}, got {est}"


@pytest.mark.parametrize(
    "bpm",
    [
        73.0,
        83.0,
        95.0,
        96.0,
        135.0,
        136.0,
        167.0,
        170.0,
    ],
)
def test_estimate_bpm_pop_groove_tactus(bpm: float) -> None:
    """Half-time / double-time pop grooves must resolve to the tapped pulse."""
    eighth = bpm >= 120.0
    est = estimate_bpm(_pop_groove(bpm, eighth_hats=eighth), 44100)
    assert est is not None
    assert abs(float(est) - bpm) <= 2.0, f"expected ~{bpm}, got {est}"


@pytest.mark.parametrize("bpm", [95.0, 96.0, 100.0, 135.0])
def test_estimate_bpm_busy_hats_keeps_kick_tactus(bpm: float) -> None:
    """Dense 8th/16th hats must not lock onto 2× (金黃色/彗尾 failure mode)."""
    est = estimate_bpm(_busy_hat_groove(bpm), 44100)
    assert est is not None
    assert abs(float(est) - bpm) <= 2.5, f"expected ~{bpm}, got {est}"


def _busy_hat_groove(bpm: float, *, seconds: float = 28.0, sr: int = 44100) -> np.ndarray:
    """Kick + strong 8ths/16ths — previously estimated as 2× for ~95 BPM."""
    n = int(sr * seconds)
    y = np.zeros(n, dtype=np.float32)
    beat = 60.0 / bpm
    rng = np.random.RandomState(3)

    def hit(t: float, amp: float, *, bright: bool = False, length: int = 600, f: float = 55.0) -> None:
        i = int(t * sr)
        if i >= n:
            return
        env = np.exp(-np.linspace(0, 7, length))
        if bright:
            sig = rng.randn(length).astype(np.float32) * env * amp
        else:
            tl = np.arange(length) / sr
            sig = (np.sin(2 * np.pi * f * tl) * env * amp).astype(np.float32)
        end = min(n, i + length)
        y[i:end] += sig[: end - i]

    t = 0.0
    beat_i = 0
    while t < seconds:
        if beat_i % 2 == 0:
            hit(t, 1.0, bright=False, length=1100, f=55.0)
        hit(t + beat * 0.5, 0.55, bright=True, length=500)
        for k in range(2):
            hit(t + beat * 0.5 * k, 0.28, bright=True, length=220)
        for k in range(4):
            hit(t + beat * 0.25 * k, 0.12, bright=True, length=140)
        t += beat
        beat_i += 1
    y += rng.randn(n).astype(np.float32) * 0.012
    return np.tanh(y).astype(np.float32).reshape(-1, 1)


def test_estimate_bpm_excludes_ltc_like_channel() -> None:
    sr = 44100
    music = _click_track(120.0, seconds=16.0, sr=sr)[:, 0]
    t = np.arange(music.size, dtype=np.float32) / sr
    ltc = (np.sign(np.sin(2 * np.pi * 2000.0 * t)) * 0.4).astype(np.float32)
    stereo = np.stack([music, ltc], axis=1)
    cleaned = estimate_bpm(stereo, sr, exclude_channel=1)
    assert cleaned is not None
    assert abs(float(cleaned) - 120.0) <= 3.0


def test_estimate_bpm_skips_quiet_gap_before_groove() -> None:
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
