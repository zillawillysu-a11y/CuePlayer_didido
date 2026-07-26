"""Pure-Python SMPTE Linear Timecode (LTC) PCM generator.

No libltc dependency — bi-phase mark, 80-bit frames, cacheable float32 mono.
"""

from __future__ import annotations

import numpy as np

from cueplayer.timecode.smpte import Timecode, add_frames, parse_timecode


# Sync word bits 64–79: 0011 1111 1111 1101
_SYNC_WORD = (0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 1)


def encode_ltc_frame_bits(
    hours: int,
    minutes: int,
    seconds: int,
    frames: int,
    *,
    drop_frame: bool = False,
    color_frame: bool = False,
) -> list[int]:
    """
    Build the 80-bit SMPTE LTC word for one timecode frame (non-user-bits zeroed).

    Bit layout follows SMPTE 12M / EBU LTC (BCD time fields + sync word).
    """
    bits = [0] * 80

    fu, ft = frames % 10, frames // 10
    bits[0] = fu & 1
    bits[1] = (fu >> 1) & 1
    bits[2] = (fu >> 2) & 1
    bits[3] = (fu >> 3) & 1
    bits[8] = ft & 1
    bits[9] = (ft >> 1) & 1
    bits[10] = 1 if drop_frame else 0
    bits[11] = 1 if color_frame else 0

    su, st = seconds % 10, seconds // 10
    bits[16] = su & 1
    bits[17] = (su >> 1) & 1
    bits[18] = (su >> 2) & 1
    bits[19] = (su >> 3) & 1
    bits[24] = st & 1
    bits[25] = (st >> 1) & 1
    bits[26] = (st >> 2) & 1

    mu, mt = minutes % 10, minutes // 10
    bits[32] = mu & 1
    bits[33] = (mu >> 1) & 1
    bits[34] = (mu >> 2) & 1
    bits[35] = (mu >> 3) & 1
    bits[40] = mt & 1
    bits[41] = (mt >> 1) & 1
    bits[42] = (mt >> 2) & 1

    hu, ht = hours % 10, hours // 10
    bits[48] = hu & 1
    bits[49] = (hu >> 1) & 1
    bits[50] = (hu >> 2) & 1
    bits[51] = (hu >> 3) & 1
    bits[56] = ht & 1
    bits[57] = (ht >> 1) & 1

    for i, bit in enumerate(_SYNC_WORD):
        bits[64 + i] = bit

    # Bit 27: biphase mark polarity correction — even number of zeros in the word.
    bits[27] = 0
    zero_count = sum(1 for b in bits if b == 0)
    if zero_count % 2 != 0:
        bits[27] = 1

    return bits


def _biphase_encode(bits: list[int], samples_per_bit: int, amplitude: float) -> np.ndarray:
    """Bi-phase mark: edge at every bit boundary; mid-bit edge iff bit == 1."""
    spb = max(2, int(samples_per_bit))
    half = spb // 2
    out = np.empty(len(bits) * spb, dtype=np.float32)
    level = float(amplitude)
    pos = 0
    for bit in bits:
        # Transition at start of bit.
        level = -level
        out[pos : pos + half] = level
        if bit:
            level = -level
        out[pos + half : pos + spb] = level
        pos += spb
    return out


def generate_ltc_pcm(
    duration_seconds: float,
    sample_rate: int,
    start_timecode: str,
    fps: float,
    *,
    amplitude: float = 0.9,
    drop_frame: bool = False,
) -> np.ndarray:
    """
    Cache-friendly mono float32 LTC for ``duration_seconds`` of timeline.

    Timecode advances from ``start_timecode`` at ``fps``. Bit clock is ``fps * 80``.
    Supports 24 / 25 / 30 and 29.97 (encoded as 30-count NDF; bit rate uses real fps).
    """
    sr = max(1, int(sample_rate))
    dur = max(0.0, float(duration_seconds))
    total_samples = max(1, int(round(dur * sr)))
    rate = float(fps) if fps > 0 else 30.0
    bits_per_second = rate * 80.0
    samples_per_bit = sr / bits_per_second
    if samples_per_bit < 2.0:
        raise ValueError(
            f"Sample rate {sr} too low for LTC at {rate:g} fps "
            f"(need ≥ {int(bits_per_second * 2)} Hz)."
        )

    tc = parse_timecode(start_timecode) or Timecode(1, 0, 0, 0)
    # Approximate integer samples/bit; residual drift corrected by absolute bit index.
    spb_i = max(2, int(round(samples_per_bit)))

    out = np.zeros(total_samples, dtype=np.float32)
    # How many complete LTC frames fit.
    frame_samples = samples_per_bit * 80.0
    n_frames = int(np.ceil(total_samples / frame_samples)) + 1

    write_pos = 0.0
    current = tc
    for _ in range(n_frames):
        if int(write_pos) >= total_samples:
            break
        bits = encode_ltc_frame_bits(
            current.hours,
            current.minutes,
            current.seconds,
            current.frames,
            drop_frame=drop_frame,
        )
        # Per-frame sample count from absolute bit clock to limit long-term drift.
        frame_len = int(round((write_pos + frame_samples))) - int(round(write_pos))
        if frame_len < 80 * 2:
            frame_len = spb_i * 80
        # Encode with uniform samples/bit for this frame, then trim/pad to frame_len.
        spb = max(2, frame_len // 80)
        wave = _biphase_encode(bits, spb, amplitude)
        if wave.size < frame_len:
            wave = np.pad(wave, (0, frame_len - wave.size))
        elif wave.size > frame_len:
            wave = wave[:frame_len]

        start_i = int(round(write_pos))
        end_i = min(total_samples, start_i + wave.size)
        if end_i <= start_i:
            break
        out[start_i:end_i] = wave[: end_i - start_i]
        write_pos += frame_samples
        current = add_frames(current, 1, rate)

    return out


def ltc_frame_count(pcm: np.ndarray, sample_rate: int, fps: float) -> int:
    """Approximate number of LTC frames represented in a buffer (for tests)."""
    rate = float(fps) if fps > 0 else 30.0
    frame_samples = (sample_rate / (rate * 80.0)) * 80.0
    if frame_samples <= 0:
        return 0
    return int(pcm.size // frame_samples)
