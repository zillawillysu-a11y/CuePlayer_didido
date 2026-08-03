"""A–B loop engage behaviour."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.playback import audio_engine as eng_mod


def test_engage_ab_loop_seeks_when_past_b(monkeypatch) -> None:
    from cueplayer.playback.devices import OutputDeviceInfo

    device = OutputDeviceInfo(
        index=0,
        name="Test",
        max_output_channels=2,
        default_samplerate=48000.0,
        hostapi_name="Test",
    )
    monkeypatch.setattr(eng_mod, "list_output_devices", lambda dedupe=True: [device])
    monkeypatch.setattr(eng_mod.sd, "check_output_settings", lambda **kwargs: None)

    QApplication.instance() or QApplication([])
    engine = eng_mod.AudioEngine()
    engine.set_duration(120.0)
    engine.loop_a = 10.0
    engine.loop_b = 20.0
    engine.loop_enabled = True
    engine.seek(25.0)
    assert engine.raw_position == pytest.approx(25.0)

    engine.engage_ab_loop()

    assert engine.raw_position == pytest.approx(10.0)
    assert engine._loop_engage is True


def test_engage_ab_loop_keeps_position_inside_region(monkeypatch) -> None:
    from cueplayer.playback.devices import OutputDeviceInfo

    device = OutputDeviceInfo(
        index=0,
        name="Test",
        max_output_channels=2,
        default_samplerate=48000.0,
        hostapi_name="Test",
    )
    monkeypatch.setattr(eng_mod, "list_output_devices", lambda dedupe=True: [device])
    monkeypatch.setattr(eng_mod.sd, "check_output_settings", lambda **kwargs: None)

    QApplication.instance() or QApplication([])
    engine = eng_mod.AudioEngine()
    engine.set_duration(120.0)
    engine.loop_a = 10.0
    engine.loop_b = 20.0
    engine.loop_enabled = True
    engine.seek(15.0)

    engine.engage_ab_loop()

    assert engine.raw_position == pytest.approx(15.0)
    assert engine._loop_engage is True
