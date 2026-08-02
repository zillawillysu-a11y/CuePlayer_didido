"""LTC PCM → timecode decode (for MTC mirror)."""

from __future__ import annotations

import numpy as np
import pytest

from cueplayer.timecode.ltc import encode_ltc_frame_bits, generate_ltc_pcm
from cueplayer.timecode.ltc_decode import decode_ltc_frame_bits, decode_ltc_timecode
from cueplayer.timecode.smpte import Timecode, add_frames


def test_decode_ltc_frame_bits_roundtrip() -> None:
    bits = encode_ltc_frame_bits(1, 2, 3, 4)
    assert decode_ltc_frame_bits(bits) == Timecode(1, 2, 3, 4)


@pytest.mark.parametrize("fps", [24.0, 25.0, 30.0, 29.97])
@pytest.mark.parametrize("sample_rate", [44100, 48000])
def test_decode_generated_ltc_pcm(fps: float, sample_rate: int) -> None:
    start = "01:00:00:00"
    pcm = generate_ltc_pcm(1.5, sample_rate, start, fps)
    tc = decode_ltc_timecode(pcm[: int(sample_rate / fps) * 4], sample_rate, fps)
    assert tc == Timecode(1, 0, 0, 0)


@pytest.mark.parametrize("sample_rate", [44100, 48000])
def test_decode_ltc_at_later_position(sample_rate: int) -> None:
    fps = 30.0
    pcm = generate_ltc_pcm(2.0, sample_rate, "10:00:00:00", fps)
    frame_len = int(round(sample_rate / fps))
    # Around 0.5s → about frame 15.
    start = frame_len * 15
    win = pcm[start : start + frame_len * 4]
    tc = decode_ltc_timecode(win, sample_rate, fps)
    assert tc is not None
    expected = add_frames(Timecode(10, 0, 0, 0), 15, fps)
    assert abs(tc.total_frames(fps) - expected.total_frames(fps)) <= 1


def test_decode_rejects_silence() -> None:
    silence = np.zeros(48000, dtype=np.float32)
    assert decode_ltc_timecode(silence, 48000, 30.0) is None


def test_decode_known_stripe_for_mtc_mirror() -> None:
    """File LTC starting at 02:00:00:00 must report that TC at t=0 (not song start)."""
    pcm = generate_ltc_pcm(1.0, 48000, "02:00:00:00", 30.0)
    tc = decode_ltc_timecode(pcm, 48000, 30.0)
    assert tc == Timecode(2, 0, 0, 0)
