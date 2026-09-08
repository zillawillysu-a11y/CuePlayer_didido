"""Stale LTC detection must not leak onto the next song's setlist badge."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import AudioTrack, Project
from cueplayer.media.audio_loader import AudioBuffer, build_peak_pyramid
from cueplayer.playback import audio_engine as eng_mod
from cueplayer.playback.devices import OutputDeviceInfo
from cueplayer.ui.main_window import MainWindow, SetlistWidget

ROOT = Path(__file__).resolve().parents[2]
LTC_LEFT_FIXTURE = ROOT / "fixtures" / "media" / "中文測試" / "LTC左_音樂右_測試.wav"


def _device() -> OutputDeviceInfo:
    return OutputDeviceInfo(
        index=0,
        name="Test",
        max_output_channels=8,
        default_samplerate=48000.0,
        hostapi_name="Test",
    )


def _pure_stereo(seconds: float = 0.5, sample_rate: int = 48000) -> AudioBuffer:
    n = int(sample_rate * seconds)
    t = np.linspace(0.0, seconds, n, endpoint=False, dtype=np.float32)
    tone = (0.4 * np.sin(2.0 * np.pi * 440.0 * t)).astype(np.float32)
    stereo = np.stack([tone, tone * 0.9], axis=1)
    mono, levels = build_peak_pyramid(stereo, sample_rate)
    return AudioBuffer(
        path="daughter.wav",
        sample_rate=sample_rate,
        samples=stereo,
        mono=mono,
        peak_levels=levels,
    )


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_set_buffer_clears_previous_ltc_detection(app: QApplication, monkeypatch) -> None:
    monkeypatch.setattr(eng_mod, "list_output_devices", lambda dedupe=True: [_device()])
    monkeypatch.setattr(eng_mod.sd, "check_output_settings", lambda **kwargs: None)

    engine = eng_mod.AudioEngine()
    engine._detected_ltc_channel = 0
    engine._ltc_detect_ran = True
    engine.set_buffer(_pure_stereo())
    assert engine.detected_ltc_channel is None
    assert engine._ltc_detect_ran is False


def test_apply_loaded_audio_does_not_copy_stale_engine_ltc(
    app: QApplication, monkeypatch, tmp_path: Path
) -> None:
    """After a left-LTC song, loading pure music must not inherit LTC L."""
    monkeypatch.setattr(eng_mod, "list_output_devices", lambda dedupe=True: [_device()])
    monkeypatch.setattr(eng_mod.sd, "check_output_settings", lambda **kwargs: None)

    pure_path = tmp_path / "18_Daughter.wav"
    # Minimal writable placeholder path; buffer is supplied directly.
    pure_path.write_bytes(b"RIFF")

    window = MainWindow(Project.create("Stale LTC"))
    song = window.project.songs[0]
    song.name = "18 Daughter"
    song.audio_tracks = [
        AudioTrack(id="main", name="daughter", path=pure_path, role="main")
    ]

    # Simulate leftover detection from the previous striped song.
    window.engine._detected_ltc_channel = 0
    window.engine._ltc_detect_ran = True

    buffer = _pure_stereo()
    window._apply_loaded_audio(
        buffer, pure_path, mark_dirty=False, replace_track=False, refresh_song_widgets=False
    )

    key = window._audio_cache_key(pure_path)
    assert key is not None
    # Must not have been poisoned with the previous song's channel 0.
    assert window._audio_ltc_cache.get(key) != 0

    # Force the per-file detector result into the cache (async may still be running).
    from cueplayer.media.ltc_detect import detect_ltc_channel

    window._audio_ltc_cache[key] = detect_ltc_channel(buffer.samples, buffer.sample_rate)
    window._refresh_setlist_ltc_cells()
    item = window.song_list.item(0, SetlistWidget.COL_LTC)
    assert item is not None
    assert item.data(SetlistWidget.ROLE_LTC_CHANNEL) is None
