"""When LTC output is off, striped LTC must not leak to speakers as music."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import AudioOutputSettings, Song
from cueplayer.media.audio_loader import load_audio
from cueplayer.playback import audio_engine as eng_mod
from cueplayer.playback.devices import OutputDeviceInfo

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "media" / "中文測試" / "LTC左_音樂右_測試.wav"


def _device() -> OutputDeviceInfo:
    return OutputDeviceInfo(
        index=0,
        name="Test",
        max_output_channels=2,
        default_samplerate=48000.0,
        hostapi_name="Test",
    )


def test_ltc_output_off_still_strips_file_ltc_from_music(monkeypatch) -> None:
    monkeypatch.setattr(eng_mod, "list_output_devices", lambda dedupe=True: [_device()])
    monkeypatch.setattr(eng_mod.sd, "check_output_settings", lambda **kwargs: None)

    assert FIXTURE.is_file()
    buf = load_audio(FIXTURE)

    QApplication.instance() or QApplication([])
    engine = eng_mod.AudioEngine()
    song = Song.create("Striped")
    song.file_ltc_side = "auto"
    engine.set_song(song)
    engine.apply_audio_settings(
        AudioOutputSettings(
            output_device_name="Test",
            ltc_enabled=False,
            ltc_source="auto",
            music_l_route="1",
            music_r_route="2",
        )
    )
    engine.set_buffer(buf)
    engine.flush_deferred_buffer_setup()

    # Wait for async detect (must not be skipped just because LTC output is off).
    for _ in range(200):
        if engine._ltc_detect_ran and not engine._ltc_detect_inflight:
            break
        QApplication.processEvents()
        import time

        time.sleep(0.01)
    assert engine._ltc_detect_ran
    assert engine.detected_ltc_channel == 0

    # LTC bus stays silent when output is disabled.
    ltc = engine._ltc_chunk(0, 2048)
    assert not np.any(ltc != 0.0)
    assert engine._cached_file_ltc_idx is None

    # Music bed must not include the left (LTC) channel — both legs from Right.
    assert engine._cached_music_indices == (1, 1)
    music = engine._music_chunk(0, 2048, engine._sample_rate())
    left_file = buf.samples[:2048, 0]
    right_file = buf.samples[:2048, 1]
    # Speakers follow Right music, not Left LTC stripe.
    assert float(np.max(np.abs(music[:, 0] - right_file[: music.shape[0]]))) < 1e-3
    assert float(np.max(np.abs(music[:, 0] - left_file[: music.shape[0]]))) > 0.05

    engine.shutdown_midi_outputs()
