"""Source-file LTC pass-through routing tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import AudioOutputSettings
from cueplayer.media.audio_loader import load_audio
from cueplayer.playback import audio_engine as eng_mod

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "media" / "中文測試" / "LTC左_音樂右_測試.wav"


def test_generator_disabled_skips_ltc_pcm(monkeypatch) -> None:
    from cueplayer.playback.devices import OutputDeviceInfo

    device = OutputDeviceInfo(
        index=0,
        name="Test",
        max_output_channels=8,
        default_samplerate=48000.0,
        hostapi_name="Test",
    )
    monkeypatch.setattr(eng_mod, "list_output_devices", lambda dedupe=True: [device])
    monkeypatch.setattr(eng_mod.sd, "check_output_settings", lambda **kwargs: None)

    QApplication.instance() or QApplication([])
    engine = eng_mod.AudioEngine()
    engine.apply_audio_settings(
        AudioOutputSettings(
            output_device_name="Test",
            ltc_enabled=True,
            ltc_source="generator",
            ltc_generator_enabled=False,
            ltc_channels=[2],
        )
    )
    assert not engine._uses_generated_ltc()
    engine._ensure_ltc_cache()
    assert engine._ltc_pcm is None


def test_source_ltc_routes_left_channel_to_ltc_bus(monkeypatch) -> None:
    from cueplayer.playback.devices import OutputDeviceInfo

    device = OutputDeviceInfo(
        index=0,
        name="Test",
        max_output_channels=8,
        default_samplerate=48000.0,
        hostapi_name="Test",
    )
    monkeypatch.setattr(eng_mod, "list_output_devices", lambda dedupe=True: [device])
    monkeypatch.setattr(eng_mod.sd, "check_output_settings", lambda **kwargs: None)

    assert FIXTURE.is_file()
    buf = load_audio(FIXTURE)

    QApplication.instance() or QApplication([])
    engine = eng_mod.AudioEngine()
    engine.apply_audio_settings(
        AudioOutputSettings(
            output_device_name="Test",
            ltc_enabled=True,
            ltc_source="source_left",
            ltc_channels=[2],
        )
    )
    engine.set_buffer(buf)
    engine.flush_deferred_buffer_setup()

    ltc = engine._ltc_chunk(0, 2048)
    music = engine._music_chunk(0, 2048, engine._sample_rate())

    assert np.any(ltc != 0.0)
    assert np.any(music[:, 0] != 0.0)
    assert engine._route.get(2) == [2]
    # Music bus should come from the right channel only (L is LTC).
    assert np.allclose(music[:, 0], music[:, 1])


def test_file_auto_mode_ignores_stale_generator_pcm(monkeypatch) -> None:
    from cueplayer.playback.devices import OutputDeviceInfo
    from cueplayer.timecode.ltc import generate_ltc_pcm

    device = OutputDeviceInfo(
        index=0,
        name="Test",
        max_output_channels=8,
        default_samplerate=48000.0,
        hostapi_name="Test",
    )
    monkeypatch.setattr(eng_mod, "list_output_devices", lambda dedupe=True: [device])
    monkeypatch.setattr(eng_mod.sd, "check_output_settings", lambda **kwargs: None)

    QApplication.instance() or QApplication([])
    engine = eng_mod.AudioEngine()
    engine.apply_audio_settings(
        AudioOutputSettings(
            output_device_name="Test",
            ltc_enabled=True,
            ltc_source="auto",
            ltc_generator_enabled=False,
            ltc_channels=[2],
        )
    )
    engine._ltc_pcm = generate_ltc_pcm(1.0, 48000, "01:00:00:00", 30.0)
    out = engine._ltc_chunk(0, 2048)
    assert not np.any(out != 0.0)
