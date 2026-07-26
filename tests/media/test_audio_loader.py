"""Audio loader / waveform peak tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from cueplayer.media.audio_loader import build_peak_envelope, load_audio

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "media" / "中文測試" / "LTC左_音樂右_測試.wav"


def test_build_peak_envelope_normalizes() -> None:
    samples = np.array([[0.0, 0.0], [0.5, -0.5], [1.0, -1.0], [0.25, 0.0]], dtype=np.float32)
    peaks = build_peak_envelope(samples, target_buckets=2)
    assert peaks.size == 2
    assert float(peaks.max()) <= 1.0 + 1e-6


def test_peak_pyramid_has_multiple_levels() -> None:
    from cueplayer.media.audio_loader import build_peak_pyramid

    rng = np.random.default_rng(0)
    samples = rng.standard_normal((48000, 2)).astype(np.float32) * 0.2
    mono, levels = build_peak_pyramid(samples, sample_rate=48000)
    assert mono.size == 48000
    assert len(levels) >= 2
    assert levels[-1].samples_per_bucket <= levels[0].samples_per_bucket


def test_load_chinese_path_fixture() -> None:
    assert FIXTURE.is_file()
    buffer = load_audio(FIXTURE)
    assert buffer.sample_rate > 0
    assert buffer.frames > 0
    assert buffer.peaks.size > 0
    assert buffer.duration_seconds > 0
