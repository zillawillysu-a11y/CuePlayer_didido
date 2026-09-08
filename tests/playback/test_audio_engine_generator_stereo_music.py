"""Pure stereo music must play when LTC is generated on a separate bus."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import AudioOutputSettings
from cueplayer.media.audio_loader import AudioBuffer, build_peak_pyramid
from cueplayer.playback import audio_engine as eng_mod
from cueplayer.playback.devices import OutputDeviceInfo


def _device() -> OutputDeviceInfo:
    return OutputDeviceInfo(
        index=0,
        name="Test",
        max_output_channels=8,
        default_samplerate=48000.0,
        hostapi_name="Test",
    )


def _stereo_left_only(seconds: float = 0.1, sample_rate: int = 48000) -> AudioBuffer:
    n = int(sample_rate * seconds)
    t = np.linspace(0.0, seconds, n, endpoint=False, dtype=np.float32)
    tone = (0.6 * np.sin(2.0 * np.pi * 440.0 * t)).astype(np.float32)
    stereo = np.zeros((n, 2), dtype=np.float32)
    stereo[:, 0] = tone
    _, levels = build_peak_pyramid(stereo, sample_rate)
    return AudioBuffer(path="left_only.wav", sample_rate=sample_rate, samples=stereo, mono=tone, peak_levels=levels)


def test_generator_ltc_keeps_both_music_channels(monkeypatch) -> None:
    """False LTC detect must not mute music when LTC comes from the generator bus."""
    monkeypatch.setattr(eng_mod, "list_output_devices", lambda dedupe=True: [_device()])
    monkeypatch.setattr(eng_mod.sd, "check_output_settings", lambda **kwargs: None)
    monkeypatch.setattr(eng_mod, "detect_ltc_channel", lambda *args, **kwargs: 0)

    QApplication.instance() or QApplication([])
    engine = eng_mod.AudioEngine()
    engine.apply_audio_settings(
        AudioOutputSettings(
            output_device_name="Test",
            music_l_route="1",
            music_r_route="2",
            ltc_enabled=True,
            ltc_source="generator",
            ltc_generator_enabled=True,
            ltc_channels=[2],
        )
    )
    engine.set_buffer(_stereo_left_only())
    engine.flush_deferred_buffer_setup()

    # Async LTC detect may still flag the left channel — music routing must ignore it.
    engine._detected_ltc_channel = 0
    engine._ltc_detect_ran = True
    engine._refresh_source_routing_cache()

    assert engine._cached_music_indices == (0, 1)
    music = engine._music_chunk(0, 512, 48000)
    assert float(np.max(np.abs(music[:, 0]))) > 0.05
    assert float(np.max(np.abs(music[:, 1]))) == 0.0

    ltc = engine._ltc_chunk(0, 512)
    assert float(np.max(np.abs(ltc))) > 0.0 or engine._uses_generated_ltc()
