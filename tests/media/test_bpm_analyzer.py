"""BPM analyzer unit tests."""

from __future__ import annotations

import numpy as np

from cueplayer.media.bpm_analyzer import (
    estimate_bpm,
    format_bpm_cell,
    parse_bpm_cell,
)


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
    sr = 44100
    bpm = 120.0
    period = int(round(sr * 60.0 / bpm))
    n = sr * 10
    mono = np.zeros(n, dtype=np.float32)
    for i in range(0, n - 200, period):
        mono[i : i + 120] = 1.0
    samples = mono.reshape(-1, 1)
    est = estimate_bpm(samples, sr)
    assert est is not None
    assert abs(float(est) - bpm) <= 2.0
