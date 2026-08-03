"""LTC encoder unit tests."""

from __future__ import annotations

import numpy as np
import pytest

from cueplayer.timecode.ltc import encode_ltc_frame_bits, generate_ltc_pcm


def test_encode_ltc_sync_word() -> None:
    bits = encode_ltc_frame_bits(1, 0, 0, 0)
    assert len(bits) == 80
    assert bits[64:80] == [0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 1]
    # Even number of zeros (polarity bit 27).
    assert sum(1 for b in bits if b == 0) % 2 == 0


def test_encode_ltc_known_timecode() -> None:
    # 01:02:03:04 → BCD fields
    bits = encode_ltc_frame_bits(1, 2, 3, 4)
    # Frame units = 4 → bits 0-3 = 0010 (LSB first)
    assert bits[0:4] == [0, 0, 1, 0]
    # Seconds units = 3 → 1100 LSB first? 3 = 0011 → bits 16-19 = 1,1,0,0
    assert bits[16:20] == [1, 1, 0, 0]
    # Minutes units = 2 → 0100
    assert bits[32:36] == [0, 1, 0, 0]
    # Hours units = 1 → 1000
    assert bits[48:52] == [1, 0, 0, 0]


def test_generate_ltc_pcm_shape_and_energy() -> None:
    sr = 48000
    fps = 30.0
    seconds = 0.5
    pcm = generate_ltc_pcm(seconds, sr, "01:00:00:00", fps, amplitude=0.8)
    assert pcm.ndim == 1
    assert pcm.dtype == np.float32
    assert pcm.shape[0] == int(round(seconds * sr))
    assert float(np.max(np.abs(pcm))) > 0.1
    # Should contain both polarities (bi-phase).
    assert float(np.min(pcm)) < -0.1
    assert float(np.max(pcm)) > 0.1


@pytest.mark.parametrize("fps", [24.0, 25.0, 30.0, 29.97])
def test_generate_ltc_various_fps(fps: float) -> None:
    pcm = generate_ltc_pcm(0.2, 48000, "10:00:00:00", fps)
    assert pcm.size == int(round(0.2 * 48000))
    assert np.any(pcm != 0)


def test_generate_ltc_continuous_no_gaps() -> None:
    pcm = generate_ltc_pcm(2.0, 48000, "01:00:00:00", 30.0)
    max_gap = 0
    gap = 0
    for x in pcm:
        if abs(float(x)) < 1e-6:
            gap += 1
            max_gap = max(max_gap, gap)
        else:
            gap = 0
  # Bi-phase should stay active; old encoder left multi-sample silence between frames.
    assert max_gap < 8
    assert float(np.max(np.abs(pcm))) > 0.1


def test_ltc_advances_from_start_tc() -> None:
    # Two short buffers starting at different TCs should not be identical.
    a = generate_ltc_pcm(0.1, 48000, "01:00:00:00", 30.0)
    b = generate_ltc_pcm(0.1, 48000, "01:00:01:00", 30.0)
    assert not np.allclose(a, b)
