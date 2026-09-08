"""Pure-Python SMPTE Linear Timecode (LTC) PCM generator.

No libltc dependency — bi-phase mark, 80-bit frames, cacheable float32 mono.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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


def _ltc_frame_start(frame_idx: int, sample_rate: int, fps: float) -> int:
    rate = float(fps) if fps > 0 else 30.0
    return int(round(frame_idx * sample_rate / rate))


def _ltc_frame_len(frame_idx: int, sample_rate: int, fps: float) -> int:
    return max(
        160,
        _ltc_frame_start(frame_idx + 1, sample_rate, fps)
        - _ltc_frame_start(frame_idx, sample_rate, fps),
    )


def _biphase_encode(
    bits: list[int],
    frame_len: int,
    amplitude: float,
    *,
    initial_level: float | None = None,
) -> tuple[np.ndarray, float]:
    """Bi-phase mark with exactly ``frame_len`` samples (80 bit cells).

    Bit boundaries use cumulative rounding so non-integer samples/bit at
    rates like 44.1 kHz do not need pad/truncate (which breaks decoders).
    ``initial_level`` carries polarity from the previous LTC frame.
    """
    frame_len = max(160, int(frame_len))
    boundaries = [int(round(i * frame_len / 80)) for i in range(81)]
    out = np.zeros(frame_len, dtype=np.float32)
    level = float(amplitude) if initial_level is None else float(initial_level)
    for i, bit in enumerate(bits):
        start, end = boundaries[i], boundaries[i + 1]
        if end <= start:
            continue
        mid = start + (end - start) // 2
        level = -level
        out[start:mid] = level
        if bit:
            level = -level
        out[mid:end] = level
    return out, level


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
    out = np.zeros(total_samples, dtype=np.float32)
    level = float(amplitude)
    pos = 0
    frame_idx = 0
    min_frame_samples = 80 * 2

    while pos < total_samples:
        frame_len = min(
            _ltc_frame_len(frame_idx, sr, rate),
            total_samples - pos,
        )
        if frame_len < min_frame_samples:
            if total_samples - pos < min_frame_samples:
                break
            frame_len = min(total_samples - pos, max(min_frame_samples, int(round(sr / rate))))

        bits = encode_ltc_frame_bits(
            tc.hours,
            tc.minutes,
            tc.seconds,
            tc.frames,
            drop_frame=drop_frame,
        )
        wave, level = _biphase_encode(bits, frame_len, amplitude, initial_level=level)
        out[pos : pos + frame_len] = wave
        pos += frame_len
        frame_idx += 1
        tc = add_frames(tc, 1, rate)

    return out


def _frame_index_covering(sample_pos: int, sample_rate: int, fps: float) -> int:
    """LTC frame index whose sample range contains ``sample_pos``."""
    rate = float(fps) if fps > 0 else 30.0
    sr = max(1, int(sample_rate))
    pos = max(0, int(sample_pos))
    # Inverse of _ltc_frame_start ≈ round(i * sr / rate)
    approx = int(pos * rate / sr)
    for cand in range(max(0, approx - 2), approx + 4):
        start = _ltc_frame_start(cand, sr, rate)
        end = start + _ltc_frame_len(cand, sr, rate)
        if start <= pos < end:
            return cand
    return max(0, approx)


@dataclass
class LtcPlaybackCursor:
    """Incremental LTC renderer for realtime playback (O(chunk) when sequential)."""

    sample_rate: int
    fps: float
    start_timecode: str
    amplitude: float = 0.9
    drop_frame: bool = False
    stream_pos: int = 0
    frame_idx: int = 0
    level: float = field(init=False)
    tc: Timecode = field(init=False)
    _wave: np.ndarray | None = field(default=None, init=False, repr=False)
    _wave_start: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.stream_pos = 0
        self.frame_idx = 0
        self.level = float(self.amplitude)
        self.tc = parse_timecode(self.start_timecode) or Timecode(1, 0, 0, 0)
        self._wave = None
        self._wave_start = 0

    def configure(
        self,
        *,
        sample_rate: int,
        fps: float,
        start_timecode: str,
        amplitude: float = 0.9,
        drop_frame: bool = False,
    ) -> None:
        changed = (
            int(sample_rate) != int(self.sample_rate)
            or abs(float(fps) - float(self.fps)) > 1e-9
            or str(start_timecode) != str(self.start_timecode)
            or abs(float(amplitude) - float(self.amplitude)) > 1e-9
            or bool(drop_frame) != bool(self.drop_frame)
        )
        self.sample_rate = max(1, int(sample_rate))
        self.fps = float(fps) if fps > 0 else 30.0
        self.start_timecode = start_timecode
        self.amplitude = float(amplitude)
        self.drop_frame = bool(drop_frame)
        if changed:
            self.reset()

    def _skip_to_frame(self, target_frame_idx: int) -> None:
        """Jump to the start of ``target_frame_idx`` without building PCM."""
        target_frame_idx = max(0, int(target_frame_idx))
        if target_frame_idx < self.frame_idx:
            self.reset()
        if target_frame_idx == self.frame_idx and self.stream_pos == _ltc_frame_start(
            self.frame_idx, self.sample_rate, self.fps
        ):
            return
        delta = target_frame_idx - self.frame_idx
        if delta > 0:
            # Approximate polarity: each LTC frame has an even transition count
            # often enough that keeping amplitude is fine; decoders resync in 1–2 frames.
            self.tc = add_frames(self.tc, delta, self.fps)
            self.frame_idx = target_frame_idx
            self.level = float(self.amplitude)
        self.stream_pos = _ltc_frame_start(self.frame_idx, self.sample_rate, self.fps)
        self._wave = None

    def _seek_to(self, target_pos: int) -> None:
        target_pos = max(0, int(target_pos))
        if target_pos == self.stream_pos:
            return
        if target_pos < self.stream_pos:
            self.reset()
        frame_idx = _frame_index_covering(target_pos, self.sample_rate, self.fps)
        self._skip_to_frame(frame_idx)
        self.stream_pos = target_pos
        self._wave = None

    def _ensure_wave(self) -> np.ndarray:
        if self._wave is not None:
            return self._wave
        frame_len = _ltc_frame_len(self.frame_idx, self.sample_rate, self.fps)
        bits = encode_ltc_frame_bits(
            self.tc.hours,
            self.tc.minutes,
            self.tc.seconds,
            self.tc.frames,
            drop_frame=self.drop_frame,
        )
        wave, self.level = _biphase_encode(
            bits, frame_len, self.amplitude, initial_level=self.level
        )
        self._wave = wave
        self._wave_start = _ltc_frame_start(self.frame_idx, self.sample_rate, self.fps)
        return wave

    def _advance_after_frame(self) -> None:
        self.frame_idx += 1
        self.tc = add_frames(self.tc, 1, self.fps)
        self._wave = None
        self.stream_pos = _ltc_frame_start(self.frame_idx, self.sample_rate, self.fps)

    def render(self, start_frame: int, num_frames: int) -> np.ndarray:
        if num_frames <= 0:
            return np.zeros(0, dtype=np.float32)
        start_frame = max(0, int(start_frame))
        if start_frame != self.stream_pos:
            self._seek_to(start_frame)
        out = np.zeros(num_frames, dtype=np.float32)
        written = 0
        while written < num_frames:
            wave = self._ensure_wave()
            local = self.stream_pos - self._wave_start
            if local < 0 or local >= wave.size:
                # Landed past current wave — advance frame bookkeeping.
                self._advance_after_frame()
                continue
            take = min(num_frames - written, wave.size - local)
            out[written : written + take] = wave[local : local + take]
            written += take
            self.stream_pos += take
            if self.stream_pos >= self._wave_start + wave.size:
                self._advance_after_frame()
        return out


def generate_ltc_pcm_segment(
    start_frame: int,
    num_frames: int,
    sample_rate: int,
    start_timecode: str,
    fps: float,
    *,
    amplitude: float = 0.9,
    drop_frame: bool = False,
) -> np.ndarray:
    """Generate ``num_frames`` of LTC PCM starting at playback frame ``start_frame``."""
    cursor = LtcPlaybackCursor(
        sample_rate=sample_rate,
        fps=fps,
        start_timecode=start_timecode,
        amplitude=amplitude,
        drop_frame=drop_frame,
    )
    return cursor.render(start_frame, num_frames)


def ltc_frame_count(pcm: np.ndarray, sample_rate: int, fps: float) -> int:
    """Approximate number of LTC frames represented in a buffer (for tests)."""
    rate = float(fps) if fps > 0 else 30.0
    frame_samples = (sample_rate / (rate * 80.0)) * 80.0
    if frame_samples <= 0:
        return 0
    return int(pcm.size // frame_samples)

