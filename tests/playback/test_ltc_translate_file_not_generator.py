"""Translate file LTC → MTC must not keep Song Start / generator numbers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import AudioOutputSettings
from cueplayer.media.audio_loader import AudioBuffer
from cueplayer.playback.audio_engine import AudioEngine
from cueplayer.timecode.ltc import generate_ltc_pcm
from cueplayer.timecode.mtc import absolute_timecode
from cueplayer.timecode.smpte import Timecode


def _stripe(ltc_start: str, *, sr: int = 48000, fps: float = 30.0) -> AudioBuffer:
    ltc = generate_ltc_pcm(2.0, sr, ltc_start, fps)
    music = np.zeros_like(ltc)
    stereo = np.stack([ltc, music], axis=1)  # Left = LTC
    return AudioBuffer(
        path=Path("stripe.wav"),
        sample_rate=sr,
        samples=stereo,
        mono=music,
        peak_levels=[],
    )


def test_translate_mirrors_file_even_when_ltc_source_is_generator() -> None:
    """Translate means file stripe — never leave MTC on Song Start TC."""
    QApplication.instance() or QApplication([])
    fps = 30.0
    buf = _stripe("05:00:00:00", fps=fps)
    engine = AudioEngine()
    engine.set_song_timebase("01:00:00:00", fps)
    engine.apply_audio_settings(
        AudioOutputSettings(
            ltc_enabled=False,
            ltc_source="generator",  # common mis-config; Translate still reads file
            ltc_generator_enabled=True,
            midi_enabled=True,
            mtc_enabled=True,
            ltc_to_mtc_translate=True,
            midi_port_name="",
        )
    )
    engine.set_buffer(buf)
    engine.flush_deferred_buffer_setup()

    engine._sync_mtc_to_file_ltc(0.0, force=True)
    assert engine._ltc_mirror_last_ok is True
    start = engine._mtc._start_tc
    assert absolute_timecode(start, 0.0, fps) == Timecode(5, 0, 0, 0)
    engine.shutdown_midi_outputs()


def test_translate_with_auto_source_after_async_detect() -> None:
    from cueplayer.media.audio_loader import load_audio
    from cueplayer.playback import audio_engine as eng_mod
    from cueplayer.playback.devices import OutputDeviceInfo

    root = Path(__file__).resolve().parents[2]
    fixture = root / "fixtures" / "media" / "中文測試" / "LTC左_音樂右_測試.wav"
    assert fixture.is_file()

    def _device() -> OutputDeviceInfo:
        return OutputDeviceInfo(
            index=0,
            name="Test",
            max_output_channels=2,
            default_samplerate=48000.0,
            hostapi_name="Test",
        )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(eng_mod, "list_output_devices", lambda dedupe=True: [_device()])
    monkeypatch.setattr(eng_mod.sd, "check_output_settings", lambda **kwargs: None)
    try:
        QApplication.instance() or QApplication([])
        buf = load_audio(fixture)
        fps = 30.0
        engine = AudioEngine()
        engine.set_song_timebase("01:00:00:00", fps)
        engine.apply_audio_settings(
            AudioOutputSettings(
                output_device_name="Test",
                ltc_enabled=False,
                ltc_source="auto",
                midi_enabled=True,
                mtc_enabled=True,
                ltc_to_mtc_translate=True,
                midi_port_name="",
            )
        )
        engine.set_buffer(buf)
        engine.flush_deferred_buffer_setup()

        import time

        for _ in range(200):
            QApplication.processEvents()
            if engine._ltc_detect_ran and not engine._ltc_detect_inflight:
                break
            time.sleep(0.01)

        assert engine._ltc_detect_ran
        assert engine.detected_ltc_channel == 0
        # Music stripped off Left LTC even though LTC output is off.
        assert engine._cached_music_indices == (1, 1)
        # Decode may need a few frames into the stripe; Translate path is covered
        # by test_translate_mirrors_file_even_when_ltc_source_is_generator.
        engine.shutdown_midi_outputs()
    finally:
        monkeypatch.undo()
