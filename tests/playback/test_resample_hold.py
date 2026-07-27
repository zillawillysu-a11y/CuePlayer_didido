"""Hold resampler tests (LTC-friendly)."""

from __future__ import annotations

import numpy as np

from cueplayer.playback.resample import resample_hold, resample_hold_segment, resample_linear


def test_resample_hold_preserves_square_edges_better_than_linear() -> None:
    sr_src = 44100
    sr_dst = 48000
    n = sr_src
    mono = np.zeros(n, dtype=np.float32)
    mono[::18] = 0.9
    mono[9::18] = -0.9
    hold = resample_hold(mono, sr_src, sr_dst)
    linear = resample_linear(mono, sr_src, sr_dst)
    hold_edges = float(np.mean(np.abs(np.diff(np.sign(hold)))))
    linear_edges = float(np.mean(np.abs(np.diff(np.sign(linear)))))
    assert hold_edges >= linear_edges


def test_resample_hold_segment_matches_full() -> None:
    mono = np.array([0.5, -0.5, 0.5, -0.5] * 1000, dtype=np.float32)
    full = resample_hold(mono, 44100, 48000)
    dst_start = 100
    frames = 256
    seg = resample_hold_segment(mono, 44100, 48000, dst_start, frames)
    assert np.allclose(seg, full[dst_start : dst_start + frames])
