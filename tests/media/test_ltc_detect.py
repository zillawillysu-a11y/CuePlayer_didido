"""LTC channel auto-detection tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from cueplayer.media.audio_loader import load_audio
from cueplayer.media.ltc_detect import detect_ltc_channel

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "media" / "中文測試" / "LTC左_音樂右_測試.wav"


def test_detect_ltc_on_left_fixture() -> None:
    assert FIXTURE.is_file()
    buf = load_audio(FIXTURE)
    assert buf.channels >= 2
    assert detect_ltc_channel(buf.samples, buf.sample_rate) == 0


def test_detect_returns_none_for_mono() -> None:
    import numpy as np

    mono = np.random.default_rng(0).standard_normal(48000).astype(np.float32) * 0.1
    assert detect_ltc_channel(mono, 48000) is None
