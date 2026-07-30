"""Per-file waveform gain in the audio engine."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from cueplayer.media.audio_loader import AudioBuffer, PeakLevel
from cueplayer.playback.audio_engine import AudioEngine


def test_audio_gain_db_applies_to_music_chunk() -> None:
    engine = AudioEngine()
    sr = 48000
    samples = np.ones((480, 2), dtype=np.float32) * 0.5
    mono = samples[:, 0].copy()
    peaks = PeakLevel(
        samples_per_bucket=480,
        mins=mono.copy(),
        maxs=mono.copy(),
    )
    engine.set_buffer(
        AudioBuffer(
            path=Path("fake.wav"),
            sample_rate=sr,
            samples=samples,
            mono=mono,
            peak_levels=[peaks],
        )
    )
    engine.flush_deferred_buffer_setup()
    engine.set_audio_gain_db(6.0)  # ~2x
    chunk = engine._music_chunk(0, 480, sr)  # noqa: SLF001
    assert float(chunk[0, 0]) > 0.9
