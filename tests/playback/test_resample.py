"""Tests for the dependency-free linear resampler used on device rate mismatches."""

from __future__ import annotations

import numpy as np

from cueplayer.playback.resample import resample_linear, resample_linear_yielding


def test_resample_linear_noop_when_rates_match() -> None:
    samples = np.random.rand(100, 2).astype(np.float32)
    out = resample_linear(samples, 48000, 48000)
    assert out is samples


def test_resample_linear_upsampling_preserves_duration() -> None:
    """1s @44100 must still be ~1s worth of frames after resampling to 48000."""
    sr_src, sr_dst = 44100, 48000
    samples = np.zeros((sr_src, 2), dtype=np.float32)
    out = resample_linear(samples, sr_src, sr_dst)
    assert out.shape[1] == 2
    assert out.shape[0] == sr_dst


def test_resample_linear_downsampling_preserves_duration() -> None:
    sr_src, sr_dst = 48000, 44100
    samples = np.zeros((sr_src, 2), dtype=np.float32)
    out = resample_linear(samples, sr_src, sr_dst)
    assert out.shape[0] == sr_dst


def test_resample_linear_handles_mono() -> None:
    samples = np.linspace(-1.0, 1.0, 44100, dtype=np.float32)
    out = resample_linear(samples, 44100, 48000)
    assert out.ndim == 1
    assert out.shape[0] == 48000


def test_resample_linear_interpolates_a_ramp_accurately() -> None:
    """A linear ramp should resample to (almost) the same start/end values."""
    n = 1000
    ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
    out = resample_linear(ramp, 1000, 500)
    assert out[0] < out[-1]
    assert -0.01 <= float(out[0]) <= 0.01
    assert 0.99 <= float(out[-1]) <= 1.01


def test_resample_linear_empty_input_is_safe() -> None:
    samples = np.zeros((0, 2), dtype=np.float32)
    out = resample_linear(samples, 44100, 48000)
    assert out.shape[0] == 0


def test_resample_linear_yielding_matches_duration() -> None:
    sr_src, sr_dst = 44100, 48000
    samples = np.random.rand(sr_src * 2, 2).astype(np.float32)  # 2s
    out = resample_linear_yielding(samples, sr_src, sr_dst, chunk_seconds=0.25)
    assert out.shape == (sr_dst * 2, 2)
    direct = resample_linear(samples, sr_src, sr_dst)
    assert out.shape == direct.shape
