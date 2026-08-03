"""
Regression test for the WASAPI "Invalid sample rate" (-9997) playback bug.

Selecting a WASAPI shared-mode output (e.g. 喇叭/Realtek Speakers) whose
mixer format is locked to one rate must never open a stream at the loaded
media's native rate if the device rejects it -- see
devices.resolve_output_samplerate() and
AudioEngine._resolve_device_and_route()/_refresh_playback_samples().
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import AudioOutputSettings
from cueplayer.media.audio_loader import AudioBuffer, build_peak_pyramid
from cueplayer.playback import audio_engine as audio_engine_mod
from cueplayer.playback.devices import OutputDeviceInfo


def _wasapi_speakers_locked_to_48k() -> OutputDeviceInfo:
    return OutputDeviceInfo(
        index=22,
        name="喇叭 (Realtek(R) Audio)",
        max_output_channels=2,
        default_samplerate=48000.0,
        hostapi_name="Windows WASAPI",
    )


def _make_buffer(sample_rate: int, seconds: float = 1.0) -> AudioBuffer:
    n = int(sample_rate * seconds)
    tone = np.zeros((n, 2), dtype=np.float32)
    mono, levels = build_peak_pyramid(tone, sample_rate)
    return AudioBuffer(path="x.wav", sample_rate=sample_rate, samples=tone, mono=mono, peak_levels=levels)


def _reject_all_but(rate: float):
    def fake_check(*, device, channels, samplerate, dtype):
        if samplerate != rate:
            raise RuntimeError("Invalid sample rate [PaErrorCode -9997]")

    return fake_check


def test_engine_resolves_device_locked_rate_instead_of_media_rate(monkeypatch) -> None:
    """
    44.1kHz media selected on a 48kHz-locked WASAPI Speakers must resolve
    to 48000 Hz (and resample accordingly) instead of opening the stream
    at the file's native 44100 Hz, which is exactly what raised
    `sounddevice.PortAudioError: Invalid sample rate [PaErrorCode -9997]`.
    """
    device = _wasapi_speakers_locked_to_48k()
    monkeypatch.setattr(audio_engine_mod, "list_output_devices", lambda dedupe=True: [device])
    monkeypatch.setattr(audio_engine_mod.sd, "check_output_settings", _reject_all_but(48000.0))

    QApplication.instance() or QApplication([])
    engine = audio_engine_mod.AudioEngine()
    engine.apply_audio_settings(AudioOutputSettings(output_device_name="Realtek"))
    engine.set_buffer(_make_buffer(44100))
    engine.flush_deferred_buffer_setup()

    assert engine._device_index == 22
    assert engine._playback_rate == 48000
    assert engine._playback_samples is not None
    # Duration must be preserved through the resample (1s @44100 -> 1s @48000).
    assert engine._playback_samples.shape[0] == 48000


def test_engine_keeps_media_rate_when_device_supports_it(monkeypatch) -> None:
    """No unnecessary resampling when the device already accepts the media rate."""
    device = _wasapi_speakers_locked_to_48k()
    monkeypatch.setattr(audio_engine_mod, "list_output_devices", lambda dedupe=True: [device])
    monkeypatch.setattr(audio_engine_mod.sd, "check_output_settings", lambda **kwargs: None)

    QApplication.instance() or QApplication([])
    engine = audio_engine_mod.AudioEngine()
    engine.apply_audio_settings(AudioOutputSettings(output_device_name="Realtek"))
    buf = _make_buffer(44100)
    engine.set_buffer(buf)
    engine.flush_deferred_buffer_setup()

    assert engine._playback_rate == 44100
    # No resampling needed -- same array, not a copy.
    assert engine._playback_samples is buf.samples


def test_emit_position_reaches_full_duration_when_resampled(monkeypatch) -> None:
    """
    Regression for the "nEON" / "Reset 0" early-stop bug: a 44.1kHz song on a
    48kHz-locked device must play/report all the way to its real duration
    instead of stopping ~8.4% early (the 44100/48000 ratio).

    `_position_frame` is bookkept in playback-rate (48000) frames, so the
    EOF check in `_emit_position()` must compare it against the *resampled*
    buffer length, not the native-rate `AudioBuffer.frames` -- otherwise
    playback (and the reported EOF) lands at duration * 44100/48000.
    """
    device = _wasapi_speakers_locked_to_48k()
    monkeypatch.setattr(audio_engine_mod, "list_output_devices", lambda dedupe=True: [device])
    monkeypatch.setattr(audio_engine_mod.sd, "check_output_settings", _reject_all_but(48000.0))

    QApplication.instance() or QApplication([])
    engine = audio_engine_mod.AudioEngine()
    engine.apply_audio_settings(AudioOutputSettings(output_device_name="Realtek"))
    buf = _make_buffer(44100, seconds=3.0)
    engine.set_buffer(buf)
    engine.flush_deferred_buffer_setup()

    assert engine._playback_rate == 48000
    assert engine._playback_samples.shape[0] == 3 * 48000  # resampled length, not 3 * 44100

    # Simulate the stream callback having advanced to just before the true
    # (resampled) end without having reported "done" yet.
    engine._playing = True
    engine._position_frame = engine._playback_samples.shape[0] - 1
    engine._emit_position()
    assert engine.playing is True, "must not stop before the resampled buffer actually ends"

    # Advancing to the buggy (native-rate) frame count must NOT be treated
    # as EOF -- this is exactly the frame at which the old code stopped early.
    assert buf.frames < engine._playback_samples.shape[0]
    engine._position_frame = buf.frames
    engine._emit_position()
    assert engine.playing is True, "must not stop early at the native-rate frame count"

    # Reaching the real (resampled) end must report the full source duration
    # and actually stop.
    engine._position_frame = engine._playback_samples.shape[0]
    engine._emit_position()
    assert engine.playing is False
    assert engine.position == pytest.approx(buf.duration_seconds, abs=1e-6)
    assert buf.duration_seconds == pytest.approx(3.0)


def test_emit_position_stops_at_correct_frame_when_native_matches_device(monkeypatch) -> None:
    """Sanity check: 48kHz-native songs (no resample path) are unaffected."""
    device = _wasapi_speakers_locked_to_48k()
    monkeypatch.setattr(audio_engine_mod, "list_output_devices", lambda dedupe=True: [device])
    monkeypatch.setattr(audio_engine_mod.sd, "check_output_settings", lambda **kwargs: None)

    QApplication.instance() or QApplication([])
    engine = audio_engine_mod.AudioEngine()
    engine.apply_audio_settings(AudioOutputSettings(output_device_name="Realtek"))
    buf = _make_buffer(48000, seconds=2.0)
    engine.set_buffer(buf)
    engine.flush_deferred_buffer_setup()

    assert engine._playback_rate == 48000
    assert engine._playback_samples is buf.samples

    engine._playing = True
    engine._position_frame = buf.frames - 1
    engine._emit_position()
    assert engine.playing is True

    engine._position_frame = buf.frames
    engine._emit_position()
    assert engine.playing is False
    assert engine.position == pytest.approx(buf.duration_seconds, abs=1e-6)


def test_emit_position_syncs_ui_when_callback_stops_first(monkeypatch) -> None:
    """Natural EOF in the audio callback clears `_playing` before the poll tick."""
    device = _wasapi_speakers_locked_to_48k()
    monkeypatch.setattr(audio_engine_mod, "list_output_devices", lambda dedupe=True: [device])
    monkeypatch.setattr(audio_engine_mod.sd, "check_output_settings", lambda **kwargs: None)

    QApplication.instance() or QApplication([])
    engine = audio_engine_mod.AudioEngine()
    engine.apply_audio_settings(AudioOutputSettings(output_device_name="Realtek"))
    buf = _make_buffer(48000, seconds=1.0)
    engine.set_buffer(buf)
    engine.flush_deferred_buffer_setup()

    playing_states: list[bool] = []
    engine.playing_changed.connect(playing_states.append)

    engine._poll.start()
    engine._position_frame = buf.frames
    engine._playing = False

    engine._emit_position()

    assert engine.playing is False
    assert not engine._poll.isActive()
    assert playing_states == [False]
