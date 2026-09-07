"""LTC encoder unit tests."""

from __future__ import annotations

import numpy as np
import pytest

from cueplayer.timecode.ltc import encode_ltc_frame_bits, generate_ltc_pcm, generate_ltc_pcm_segment


def _scalar_reference(
    duration_seconds: float,
    sample_rate: int,
    start_timecode: str,
    fps: float,
    *,
    amplitude: float = 0.9,
    drop_frame: bool = False,
) -> np.ndarray:
    """Pre-vectorization algorithm kept only as an exact equivalence oracle."""
    from cueplayer.timecode.ltc import _biphase_encode, _ltc_frame_len
    from cueplayer.timecode.smpte import Timecode, add_frames, parse_timecode

    sr = max(1, int(sample_rate))
    total_samples = max(1, int(round(max(0.0, duration_seconds) * sr)))
    rate = float(fps) if fps > 0 else 30.0
    tc = parse_timecode(start_timecode) or Timecode(1, 0, 0, 0)
    out = np.zeros(total_samples, dtype=np.float32)
    level = float(amplitude)
    pos = 0
    frame_idx = 0
    while pos < total_samples:
        frame_len = min(_ltc_frame_len(frame_idx, sr, rate), total_samples - pos)
        if frame_len < 160:
            if total_samples - pos < 160:
                break
            frame_len = min(total_samples - pos, max(160, int(round(sr / rate))))
        bits = encode_ltc_frame_bits(
            tc.hours,
            tc.minutes,
            tc.seconds,
            tc.frames,
            drop_frame=drop_frame,
        )
        wave, level = _biphase_encode(
            bits, frame_len, amplitude, initial_level=level
        )
        out[pos : pos + frame_len] = wave
        pos += frame_len
        frame_idx += 1
        tc = add_frames(tc, 1, rate)
    return out


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


@pytest.mark.parametrize(
    ("fps", "start", "duration", "drop_frame"),
    [
        (24.0, "00:00:00:00", 0.01, False),
        (24.0, "01:02:03:04", 0.237, False),
        (25.0, "10:59:58:23", 1.017, False),
        (30.0, "23:59:59:29", 0.503, False),
        (29.97, "03:14:15:09", 0.731, False),
        (29.97, "03:14:15:09", 0.731, True),
        (29.97, "23:59:58:17", 69.123, True),
    ],
)
def test_vectorized_pcm_is_byte_exact_to_scalar_encoder(
    fps: float, start: str, duration: float, drop_frame: bool
) -> None:
    expected = _scalar_reference(
        duration, 48000, start, fps, amplitude=0.73, drop_frame=drop_frame
    )
    actual = generate_ltc_pcm(
        duration, 48000, start, fps, amplitude=0.73, drop_frame=drop_frame
    )
    np.testing.assert_array_equal(actual, expected)


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


@pytest.mark.parametrize("sample_rate", [44100, 48000])
def test_generate_ltc_frame_lengths_match(sample_rate: int) -> None:
    fps = 30.0
    pcm = generate_ltc_pcm(1.0, sample_rate, "01:00:00:00", fps)
    assert pcm.shape[0] == sample_rate
    max_gap = 0
    gap = 0
    for x in pcm:
        if abs(float(x)) < 1e-6:
            gap += 1
            max_gap = max(max_gap, gap)
        else:
            gap = 0
    assert max_gap < 8


def test_generate_ltc_pcm_segment_matches_full_cache() -> None:
    sr = 48000
    full = generate_ltc_pcm(2.0, sr, "01:00:00:00", 30.0)
    start = 12345
    frames = 4096
    seg = generate_ltc_pcm_segment(start, frames, sr, "01:00:00:00", 30.0)
    assert np.allclose(seg, full[start : start + frames])


def test_ltc_cursor_sequential_matches_cache() -> None:
    from cueplayer.timecode.ltc import LtcPlaybackCursor

    sr = 48000
    full = generate_ltc_pcm(1.5, sr, "05:00:00:00", 30.0)
    cursor = LtcPlaybackCursor(sr, 30.0, "05:00:00:00")
    parts = [cursor.render(i, 1024) for i in range(0, sr, 1024)]
    joined = np.concatenate(parts)[:sr]
    assert np.allclose(joined, full[:sr])


def test_ltc_cursor_seek_is_fast() -> None:
    from cueplayer.timecode.ltc import LtcPlaybackCursor
    import time

    cursor = LtcPlaybackCursor(48000, 30.0, "03:00:00:00")
    t0 = time.perf_counter()
    seg = cursor.render(48000 * 200, 2048)
    elapsed = time.perf_counter() - t0
    assert seg.size == 2048
    assert float(np.max(np.abs(seg))) > 0.1
    assert elapsed < 0.05


def test_ltc_advances_from_start_tc() -> None:
    # Two short buffers starting at different TCs should not be identical.
    a = generate_ltc_pcm(0.1, 48000, "01:00:00:00", 30.0)
    b = generate_ltc_pcm(0.1, 48000, "01:00:01:00", 30.0)
    assert not np.allclose(a, b)
