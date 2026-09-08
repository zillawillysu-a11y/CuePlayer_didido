import numpy as np
import pytest

from cueplayer.playback.audio_engine import AudioEngine
from cueplayer.playback.routing_parse import SRC_FILE_LTC


@pytest.mark.parametrize('rate', [44100, 48000, 96000])
@pytest.mark.parametrize('frames', [20, 64, 1024, 4096])
def test_callback_matches_modulo_samples_for_short_loop(rate, frames):
    engine = AudioEngine()
    engine._playback_rate = rate
    engine._playing = True
    engine.loop_enabled = engine._loop_engage = True
    engine.loop_a, engine.loop_b = 0, .01
    length = int(.01 * rate)
    start = length - 20
    engine._position_frame = start
    samples = np.repeat((np.arange(rate, dtype=np.float32) / rate)[:, None], 2, axis=1)
    engine._playback_samples = samples
    out = np.empty((frames, 2), np.float32)
    engine._make_stream_callback(rate)(out, frames, None, None)
    indices = (start + np.arange(frames)) % length
    np.testing.assert_array_equal(out, samples[indices])
    assert engine._position_frame == (start + frames) % length


def test_direct_file_ltc_route_wraps_with_music_bus():
    engine = AudioEngine()
    rate, length, frames = 48000, 480, 1024
    engine._playback_rate = rate
    engine._playing = True
    engine.loop_enabled = engine._loop_engage = True
    engine.loop_a, engine.loop_b = 0, .01
    engine._cached_file_ltc_idx = 0
    engine._route = {SRC_FILE_LTC: [0]}
    engine._output_channel_count = 1
    pcm = np.repeat((np.arange(rate, dtype=np.float32)/rate)[:, None], 2, axis=1)
    engine._playback_samples = pcm
    out = np.empty((frames, 1), np.float32)
    engine._make_stream_callback(rate)(out, frames, None, None)
    np.testing.assert_array_equal(out[:, 0], pcm[np.arange(frames) % length, 0])


@pytest.mark.parametrize('bus', ['_assemble_looped_ltc', '_assemble_looped_video'])
def test_other_loop_buses_use_same_multiple_wrap_intervals(monkeypatch, bus):
    engine = AudioEngine()
    def read(start, count):
        data = np.arange(start, start + count, dtype=np.float32)
        return data if bus.endswith('ltc') else np.repeat(data[:, None], 2, axis=1)
    monkeypatch.setattr(engine, '_ltc_chunk' if bus.endswith('ltc') else '_video_chunk', read)
    out = getattr(engine, bus)(8, 25, 5, 10)
    expected = 5 + (3 + np.arange(25)) % 5
    np.testing.assert_array_equal(out if out.ndim == 1 else out[:, 0], expected)
