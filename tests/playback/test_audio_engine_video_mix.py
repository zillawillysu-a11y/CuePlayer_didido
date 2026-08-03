"""
AudioEngine mixes each video clip's own audio into the same output stream as
music, at the exact write-head frame (no independent clock) — see
AudioEngine._video_chunk / VideoAudioMixer.

The real `sounddevice.OutputStream` is replaced with a fake that just
captures the realtime `callback`, so these tests exercise the actual
production code path (device resolution, routing, `_start_stream`) without
touching real audio hardware.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import AudioOutputSettings, Song, VideoClip
from cueplayer.media.audio_loader import AudioBuffer, build_peak_pyramid
from cueplayer.playback import audio_engine as audio_engine_mod
from cueplayer.playback.audio_engine import AudioEngine
from cueplayer.playback.devices import OutputDeviceInfo


def _stereo_device() -> OutputDeviceInfo:
    return OutputDeviceInfo(
        index=0, name="Test Output", max_output_channels=2, default_samplerate=48000.0, hostapi_name="Test"
    )


def _silent_buffer(sample_rate: int = 48000, seconds: float = 2.0) -> AudioBuffer:
    n = int(sample_rate * seconds)
    tone = np.zeros((n, 2), dtype=np.float32)
    mono, levels = build_peak_pyramid(tone, sample_rate)
    return AudioBuffer(path=Path("x.wav"), sample_rate=sample_rate, samples=tone, mono=mono, peak_levels=levels)


class _FakeStream:
    """Stands in for sd.OutputStream; just remembers the realtime callback."""

    last_callback = None

    def __init__(self, **kwargs) -> None:
        self._callback = kwargs["callback"]
        type(self).last_callback = self._callback

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def close(self) -> None:
        pass


@pytest.fixture
def engine(monkeypatch) -> AudioEngine:
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(audio_engine_mod, "list_output_devices", lambda: [_stereo_device()])
    monkeypatch.setattr(audio_engine_mod.sd, "check_output_settings", lambda **kwargs: None)
    monkeypatch.setattr(audio_engine_mod.sd, "OutputStream", _FakeStream)
    eng = AudioEngine()
    eng.apply_audio_settings(AudioOutputSettings(output_device_name="Test"))
    eng.set_buffer(_silent_buffer())
    eng.flush_deferred_buffer_setup()
    return eng


def _song_with_clip(volume: float = 1.0, muted: bool = False) -> tuple[Song, VideoClip]:
    song = Song.create("Song")
    song.video_track_muted = muted
    clip = VideoClip.create(
        name="clip", path=Path("clip.mp4"), start_seconds=0.0, duration_seconds=2.0, volume=volume
    )
    song.add_video_clip(clip)
    return song, clip


def _inject_fake_clip_audio(engine: AudioEngine, clip: VideoClip, value: float) -> None:
    n = int(2.0 * engine._playback_rate)
    samples = np.full((n, 2), value, dtype=np.float32)
    engine._video_mixer._cache[clip.id] = samples
    engine._video_mixer._cache_key[clip.id] = (str(clip.path), engine._playback_rate)


def test_engine_mixes_video_clip_audio_into_output(engine: AudioEngine) -> None:
    song, clip = _song_with_clip(volume=1.0)
    engine.set_song(song)
    _inject_fake_clip_audio(engine, clip, 0.4)

    engine.play()
    callback = _FakeStream.last_callback
    assert callback is not None

    outdata = np.zeros((500, 2), dtype=np.float32)
    callback(outdata, 500, None, None)

    # Silent music + 0.4 clip audio, routed 1:1 to a stereo device.
    assert np.allclose(outdata, 0.4, atol=1e-4)


def test_engine_applies_per_clip_volume_to_mixed_audio(engine: AudioEngine) -> None:
    song, clip = _song_with_clip(volume=0.25)
    engine.set_song(song)
    _inject_fake_clip_audio(engine, clip, 0.8)

    engine.play()
    outdata = np.zeros((500, 2), dtype=np.float32)
    _FakeStream.last_callback(outdata, 500, None, None)

    assert np.allclose(outdata, 0.2, atol=1e-4)  # 0.8 * 0.25


def test_engine_video_track_muted_silences_clip_audio_but_keeps_stream(engine: AudioEngine) -> None:
    song, clip = _song_with_clip(volume=1.0, muted=True)
    engine.set_song(song)
    _inject_fake_clip_audio(engine, clip, 0.9)

    engine.play()
    outdata = np.zeros((500, 2), dtype=np.float32)
    _FakeStream.last_callback(outdata, 500, None, None)

    assert np.allclose(outdata, 0.0, atol=1e-6)


def test_engine_set_video_track_muted_toggles_live() -> None:
    """set_video_track_muted() must not require reloading the song/clips."""
    mixer_muted_states: list[bool] = []

    class _Mixer:
        def set_muted(self, muted: bool) -> None:
            mixer_muted_states.append(bool(muted))

    from cueplayer.playback.video_audio_mixer import VideoAudioMixer

    real_mixer = VideoAudioMixer()
    engine = AudioEngine.__new__(AudioEngine)  # avoid full Qt/audio init for this narrow check
    engine._video_mixer = real_mixer
    engine.set_video_track_muted(True)
    assert real_mixer.muted is True
    engine.set_video_track_muted(False)
    assert real_mixer.muted is False


def test_engine_master_volume_scales_video_audio_like_music(engine: AudioEngine) -> None:
    song, clip = _song_with_clip(volume=1.0)
    engine.set_song(song)
    _inject_fake_clip_audio(engine, clip, 1.0)
    engine.set_volume(0.5)

    engine.play()
    outdata = np.zeros((500, 2), dtype=np.float32)
    _FakeStream.last_callback(outdata, 500, None, None)

    assert np.allclose(outdata, 0.5, atol=1e-4)


def test_refresh_video_clips_prunes_deleted_clip_from_mixer_cache(engine: AudioEngine) -> None:
    song, clip = _song_with_clip()
    engine.set_song(song)
    _inject_fake_clip_audio(engine, clip, 0.5)
    assert clip.id in engine._video_mixer._cache

    song.remove_video_clips_by_ids({clip.id})
    engine.refresh_video_clips()
    assert clip.id not in engine._video_mixer._cache


def test_play_opens_a_stream_for_video_clips_with_no_music_loaded(monkeypatch) -> None:
    """Root cause of the "no video audio" bug: with no music track loaded and
    LTC disabled, play() used to fall back to the silent bookkeeping timer,
    so a video clip's own audio was never actually rendered — no realtime
    callback ever ran. A video clip alone must still open a real stream."""
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(audio_engine_mod, "list_output_devices", lambda: [_stereo_device()])
    monkeypatch.setattr(audio_engine_mod.sd, "check_output_settings", lambda **kwargs: None)
    monkeypatch.setattr(audio_engine_mod.sd, "OutputStream", _FakeStream)
    eng = AudioEngine()
    eng.apply_audio_settings(AudioOutputSettings(output_device_name="Test"))
    # No eng.set_buffer(...) — this song has video-only audio, no music track.
    eng.set_duration(2.0)

    song, clip = _song_with_clip(volume=1.0)
    eng.set_song(song)
    _inject_fake_clip_audio(eng, clip, 0.6)

    _FakeStream.last_callback = None
    eng.play()
    assert _FakeStream.last_callback is not None, "no output stream opened for video-only audio"

    outdata = np.zeros((500, 2), dtype=np.float32)
    _FakeStream.last_callback(outdata, 500, None, None)
    assert np.allclose(outdata, 0.6, atol=1e-4)


def test_music_volume_scales_music_but_not_video_clip_audio(engine: AudioEngine) -> None:
    """Dedicated Music-vs-Video balance fader (AGENTS.md: independent of
    per-clip Video volume, and must never touch LTC gain)."""
    song, clip = _song_with_clip(volume=1.0)
    engine.set_song(song)
    _inject_fake_clip_audio(engine, clip, 0.6)
    # Give the "music" bed a real, non-silent signal to scale.
    n = engine._playback_samples.shape[0]
    engine._playback_samples[: min(n, 500)] = 0.8

    engine.set_music_volume(0.25)
    engine.play()
    outdata = np.zeros((500, 2), dtype=np.float32)
    _FakeStream.last_callback(outdata, 500, None, None)

    # 0.8 * 0.25 (music, ducked) + 0.6 (video clip audio, untouched).
    assert np.allclose(outdata, 0.2 + 0.6, atol=1e-4)


def test_music_volume_does_not_affect_ltc(monkeypatch) -> None:
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(audio_engine_mod, "list_output_devices", lambda: [_stereo_device()])
    monkeypatch.setattr(audio_engine_mod.sd, "check_output_settings", lambda **kwargs: None)
    monkeypatch.setattr(audio_engine_mod.sd, "OutputStream", _FakeStream)
    eng = AudioEngine()
    eng.apply_audio_settings(
        AudioOutputSettings(output_device_name="Test", ltc_enabled=True, ltc_channels=[1])
    )
    eng.set_buffer(_silent_buffer())
    eng.flush_deferred_buffer_setup()
    eng.set_music_volume(0.0)

    ltc_before = eng._ltc_chunk(0, 500).copy()
    assert np.any(ltc_before != 0.0)
    ltc_after = eng._ltc_chunk(0, 500)
    assert np.array_equal(ltc_before, ltc_after)


def test_music_source_route_applies_music_volume_and_video_audio(
    engine: AudioEngine, monkeypatch
) -> None:
    """Regression: Music Source bus used a raw file channel, so Video audio
    vanished and the Music fader did nothing whenever L/R were Music Source
    (or File-LTC remapped speakers onto that bus)."""
    engine.apply_audio_settings(
        AudioOutputSettings(
            output_device_name="Test",
            music_l_route="Music Source",
            music_r_route="Music Source",
            ltc_enabled=False,
        )
    )
    # Non-silent stereo music bed.
    n = engine._playback_samples.shape[0]
    engine._playback_samples[: min(n, 800)] = 0.8
    engine.flush_deferred_buffer_setup()

    song, clip = _song_with_clip(volume=1.0)
    engine.set_song(song)
    _inject_fake_clip_audio(engine, clip, 0.6)
    engine.set_music_volume(0.25)

    engine.play()
    outdata = np.zeros((500, 2), dtype=np.float32)
    _FakeStream.last_callback(outdata, 500, None, None)

    # Processed Music Source = mid(music*0.25 + video) on both outs.
    # music 0.8*0.25=0.2, video 0.6 → 0.8 per channel after sum.
    assert np.allclose(outdata, 0.8, atol=1e-4)
