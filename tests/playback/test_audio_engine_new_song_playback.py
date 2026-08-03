"""New song playback must not stay silent while LTC still outputs."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import AudioOutputSettings
from cueplayer.media.audio_loader import AudioBuffer, build_peak_pyramid
from cueplayer.playback import audio_engine as eng_mod
from cueplayer.playback.devices import OutputDeviceInfo


def _wasapi_48k() -> OutputDeviceInfo:
    return OutputDeviceInfo(
        index=22,
        name="Speakers",
        max_output_channels=8,
        default_samplerate=48000.0,
        hostapi_name="Windows WASAPI",
    )


def _reject_all_but(rate: float):
    def fake_check(*, device, channels, samplerate, dtype):
        if samplerate != rate:
            raise RuntimeError("Invalid sample rate")

    return fake_check


def _make_buffer(sample_rate: int, seconds: float = 0.25) -> AudioBuffer:
    n = int(sample_rate * seconds)
    t = np.linspace(0.0, seconds, n, endpoint=False, dtype=np.float32)
    mono = (0.5 * np.sin(2.0 * np.pi * 440.0 * t)).astype(np.float32)
    stereo = np.stack([mono, mono * 0.8], axis=1)
    _, levels = build_peak_pyramid(stereo, sample_rate)
    return AudioBuffer(path="tone.wav", sample_rate=sample_rate, samples=stereo, mono=mono, peak_levels=levels)


def test_play_has_music_after_44100_load_on_48k_device(monkeypatch) -> None:
    device = _wasapi_48k()
    monkeypatch.setattr(eng_mod, "list_output_devices", lambda dedupe=True: [device])
    monkeypatch.setattr(eng_mod.sd, "check_output_settings", _reject_all_but(48000.0))

    QApplication.instance() or QApplication([])
    engine = eng_mod.AudioEngine()
    engine.apply_audio_settings(AudioOutputSettings(output_device_name="Speakers"))
    engine.set_buffer(_make_buffer(44100))
    engine.ensure_playback_ready()

    assert engine._playback_samples is not None
    assert engine._playback_samples.shape[0] == pytest.approx(int(48000 * 0.25), rel=0.02)

    engine.play()
    chunk = engine._music_chunk(0, 256, 48000)
    assert float(np.max(np.abs(chunk))) > 0.01
