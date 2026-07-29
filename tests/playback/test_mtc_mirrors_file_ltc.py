"""MTC mirrors decoded file LTC numbers."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from cueplayer.domain.models import AudioOutputSettings
from cueplayer.media.audio_loader import AudioBuffer
from cueplayer.playback.audio_engine import AudioEngine
from cueplayer.playback.mtc_output import MtcOutput
from cueplayer.timecode.ltc import generate_ltc_pcm
from cueplayer.timecode.mtc import absolute_timecode
from cueplayer.timecode.smpte import Timecode, add_frames


def test_set_mirror_origin_aligns_absolute() -> None:
    mtc = MtcOutput()
    mtc.set_timebase("00:00:00:00", 30.0)
    # At 1.0s the file LTC reads 01:00:01:00 → origin should be 01:00:00:00.
    mtc.set_mirror_origin(Timecode(1, 0, 1, 0), 1.0)
    assert absolute_timecode(mtc._start_tc, 1.0, 30.0) == Timecode(1, 0, 1, 0)  # noqa: SLF001
    assert absolute_timecode(mtc._start_tc, 0.0, 30.0) == Timecode(1, 0, 0, 0)  # noqa: SLF001


def _stereo_buffer(ltc_start: str, *, sr: int = 48000, fps: float = 30.0) -> AudioBuffer:
    ltc = generate_ltc_pcm(2.0, sr, ltc_start, fps)
    music = np.zeros_like(ltc)
    stereo = np.stack([music, ltc], axis=1)
    mono = music
    return AudioBuffer(
        path=Path("stripe_test.wav"),
        sample_rate=sr,
        samples=stereo,
        mono=mono,
        peak_levels=[],
    )


def test_engine_mirrors_file_ltc_into_mtc_origin() -> None:
    sr = 48000
    fps = 30.0
    buf = _stereo_buffer("03:00:00:00", sr=sr, fps=fps)

    engine = AudioEngine()
    engine.set_song_timebase("01:00:00:00", fps)  # deliberately different song start
    engine.apply_audio_settings(
        AudioOutputSettings(
            ltc_enabled=True,
            ltc_source="source_right",
            mtc_enabled=True,
            midi_port_name="",
        )
    )
    engine.set_buffer(buf)
    engine.flush_deferred_buffer_setup()

    engine._sync_mtc_to_file_ltc(0.0, force=True)  # noqa: SLF001
    start = engine._mtc._start_tc  # noqa: SLF001
    assert absolute_timecode(start, 0.0, fps) == Timecode(3, 0, 0, 0)

    engine._sync_mtc_to_file_ltc(1.0, force=True)  # noqa: SLF001
    start = engine._mtc._start_tc  # noqa: SLF001
    at_1s = absolute_timecode(start, 1.0, fps)
    expected = add_frames(Timecode(3, 0, 0, 0), 30, fps)
    assert abs(at_1s.total_frames(fps) - expected.total_frames(fps)) <= 1
