"""LTC channel auto-detection tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from cueplayer.media.audio_loader import load_audio, waveform_display_buffer
from cueplayer.media.ltc_detect import detect_ltc_channel
from cueplayer.timecode.ltc import generate_ltc_pcm

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "media" / "中文測試" / "LTC左_音樂右_測試.wav"


def test_detect_ltc_on_left_fixture() -> None:
    assert FIXTURE.is_file()
    buf = load_audio(FIXTURE)
    assert buf.channels >= 2
    assert detect_ltc_channel(buf.samples, buf.sample_rate) == 0


def test_detect_ltc_on_right_when_swapped() -> None:
    assert FIXTURE.is_file()
    buf = load_audio(FIXTURE)
    swapped = np.stack([buf.samples[:, 1], buf.samples[:, 0]], axis=1)
    assert detect_ltc_channel(swapped, buf.sample_rate) == 1


def test_detect_returns_none_for_mono() -> None:
    mono = np.random.default_rng(0).standard_normal(48000).astype(np.float32) * 0.1
    assert detect_ltc_channel(mono, 48000) is None


def test_detect_returns_none_for_pure_stereo_music() -> None:
    sr = 48000
    n = sr * 6
    t = np.linspace(0.0, 6.0, n, endpoint=False)
    rng = np.random.default_rng(2)
    music = (
        0.3 * np.sin(2 * np.pi * 220 * t)
        + 0.2 * np.sin(2 * np.pi * 440 * t)
        + 0.04 * rng.standard_normal(n)
    ).astype(np.float32)
    stereo = np.stack([music, music * 0.9], axis=1)
    assert detect_ltc_channel(stereo, sr) is None


def test_detect_returns_none_for_one_sided_music() -> None:
    sr = 48000
    n = sr * 4
    t = np.linspace(0.0, 4.0, n, endpoint=False)
    tone = (0.4 * np.sin(2 * np.pi * 330 * t)).astype(np.float32)
    left_only = np.zeros((n, 2), dtype=np.float32)
    left_only[:, 0] = tone
    assert detect_ltc_channel(left_only, sr) is None


def test_detect_synth_stripe_left_and_right() -> None:
    sr = 48000
    ltc = generate_ltc_pcm(5.0, sr, "01:00:00:00", 30.0)
    t = np.linspace(0.0, 5.0, ltc.size, endpoint=False)
    music = (0.35 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    left_ltc = np.stack([ltc, music], axis=1)
    right_ltc = np.stack([music, ltc], axis=1)
    assert detect_ltc_channel(left_ltc, sr) == 0
    assert detect_ltc_channel(right_ltc, sr) == 1


def test_waveform_display_excludes_ltc_channel() -> None:
    assert FIXTURE.is_file()
    buf = load_audio(FIXTURE)
    display = waveform_display_buffer(buf, exclude_channel=0)
    assert display.samples is buf.samples  # playback channels untouched
    # Music-only peaks should not match the L+R mix peaks.
    assert not np.allclose(display.mono, buf.mono)
    assert float(np.max(np.abs(display.mono))) > 0.01
