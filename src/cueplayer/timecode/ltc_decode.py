"""Decode SMPTE Linear Timecode from mono PCM (inverse of ``generate_ltc_pcm``).

Pure Python — no libltc. Round-trips CuePlayer's bi-phase encoder and reads
typical striped music+LTC files when the song FPS matches the stripe.
"""

from __future__ import annotations

import numpy as np

from cueplayer.timecode.ltc import _SYNC_WORD
from cueplayer.timecode.smpte import Timecode

_SYNC = tuple(_SYNC_WORD)


def decode_ltc_frame_bits(bits: list[int] | tuple[int, ...]) -> Timecode | None:
    """Parse an 80-bit LTC word into HH:MM:SS:FF. Returns None if sync missing."""
    if len(bits) < 80:
        return None
    word = [int(b) & 1 for b in bits[:80]]
    if tuple(word[64:80]) != _SYNC:
        return None
    frames = (word[0] | (word[1] << 1) | (word[2] << 2) | (word[3] << 3)) + 10 * (
        word[8] | (word[9] << 1)
    )
    seconds = (word[16] | (word[17] << 1) | (word[18] << 2) | (word[19] << 3)) + 10 * (
        word[24] | (word[25] << 1) | (word[26] << 2)
    )
    minutes = (word[32] | (word[33] << 1) | (word[34] << 2) | (word[35] << 3)) + 10 * (
        word[40] | (word[41] << 1) | (word[42] << 2)
    )
    hours = (word[48] | (word[49] << 1) | (word[50] << 2) | (word[51] << 3)) + 10 * (
        word[56] | (word[57] << 1)
    )
    if frames >= 30 or seconds >= 60 or minutes >= 60 or hours >= 24:
        return None
    return Timecode(hours, minutes, seconds, frames)


def _sliced_sign(pcm: np.ndarray, *, threshold: float) -> np.ndarray:
    """Bipolar ±1 with hold through a small dead zone (rejects DC / bleed)."""
    x = np.asarray(pcm, dtype=np.float64)
    sign = np.zeros(x.size, dtype=np.int8)
    sign[x > threshold] = 1
    sign[x < -threshold] = -1
    last = 1
    for i in range(sign.size):
        if sign[i] == 0:
            sign[i] = last
        else:
            last = int(sign[i])
    return sign


def _demod_bits_at_phase(
    sign: np.ndarray,
    *,
    phase: float,
    samples_per_bit: float,
    max_bits: int,
) -> list[int]:
    """
    Demodulate bi-phase mark assuming bit cell *i* starts at
    ``phase + i * samples_per_bit``.

    Bit = 1 iff the polarity flips near the cell midpoint (extra transition).
    """
    bits: list[int] = []
    n = int(sign.size)
    for i in range(max_bits):
        start = phase + i * samples_per_bit
        end = phase + (i + 1) * samples_per_bit
        if end >= n - 1:
            break
        mid = start + 0.5 * samples_per_bit
        # Sample just after start, around mid, and just before end.
        a = int(start + samples_per_bit * 0.15)
        b = int(mid)
        c = int(end - samples_per_bit * 0.15)
        a = min(max(0, a), n - 1)
        b = min(max(0, b), n - 1)
        c = min(max(0, c), n - 1)
        # Mid-cell transition ⇒ bit 1 (start-half polarity differs from end-half).
        bits.append(1 if sign[a] != sign[c] or sign[a] != sign[b] and sign[b] != sign[c] else 0)
        # Prefer the classic test: compare early vs late half.
        bits[-1] = 1 if int(sign[a]) != int(sign[c]) else 0
    return bits


def _find_sync(bits: list[int]) -> int:
    n = len(bits)
    if n < 80:
        return -1
    for i in range(0, n - 79):
        if tuple(bits[i + 64 : i + 80]) == _SYNC:
            return i
    return -1


def decode_ltc_timecode(
    pcm: np.ndarray,
    sample_rate: int,
    fps: float,
    *,
    threshold: float = 0.02,
) -> Timecode | None:
    """
    Decode the first valid LTC frame found in ``pcm``.

    ``fps`` sets the bit clock (fps × 80). Returns None when silent / not LTC.
    Prefers a lock where the following frame also decodes as TC+1 when present.
    """
    if pcm is None or sample_rate <= 0:
        return None
    mono = np.asarray(pcm, dtype=np.float32).reshape(-1)
    if mono.size < 160:
        return None
    rate = float(fps) if fps > 0 else 30.0
    samples_per_bit = float(sample_rate) / (rate * 80.0)
    if samples_per_bit < 2.0:
        return None
    peak = float(np.max(np.abs(mono)))
    if peak < threshold:
        return None
    thr = max(threshold, peak * 0.15)
    sign = _sliced_sign(mono, threshold=thr)

    step = max(0.25, samples_per_bit / 8.0)
    max_bits = min(240, int(mono.size / samples_per_bit) - 1)
    if max_bits < 80:
        return None

    from cueplayer.timecode.smpte import add_frames

    best: Timecode | None = None
    best_score = -1
    phase = 0.0
    while phase < samples_per_bit:
        bits = _demod_bits_at_phase(
            sign, phase=phase, samples_per_bit=samples_per_bit, max_bits=max_bits
        )
        sync_at = _find_sync(bits)
        while sync_at >= 0:
            tc = decode_ltc_frame_bits(bits[sync_at : sync_at + 80])
            if tc is not None:
                score = 1
                if sync_at + 160 <= len(bits):
                    nxt = decode_ltc_frame_bits(bits[sync_at + 80 : sync_at + 160])
                    if nxt is not None and nxt == add_frames(tc, 1, rate):
                        score = 3
                    elif nxt is not None:
                        score = 0  # reject contradictory next frame
                if score > best_score:
                    best_score = score
                    best = tc
                    if score >= 3:
                        return best
            # Continue searching for another sync in this phase.
            rest = bits[sync_at + 1 :]
            rel = _find_sync(rest)
            sync_at = sync_at + 1 + rel if rel >= 0 else -1
        phase += step
    return best if best_score > 0 else None


def decode_ltc_timecode_near(
    pcm: np.ndarray,
    sample_rate: int,
    fps: float,
    *,
    center_sample: int = 0,
) -> Timecode | None:
    """Prefer a decode window around ``center_sample`` inside ``pcm``."""
    mono = np.asarray(pcm, dtype=np.float32).reshape(-1)
    rate = float(fps) if fps > 0 else 30.0
    frame_len = max(160, int(round(float(sample_rate) / rate)))
    need = frame_len * 3
    if mono.size <= need:
        return decode_ltc_timecode(mono, sample_rate, fps)
    center = max(0, int(center_sample))
    start = min(max(0, center - frame_len // 2), max(0, mono.size - need))
    return decode_ltc_timecode(mono[start : start + need], sample_rate, fps)
