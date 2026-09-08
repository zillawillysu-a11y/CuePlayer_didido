"""Rate fallback must be consistent even if start invokes a callback immediately."""
from types import SimpleNamespace

import numpy as np
import pytest

from cueplayer.media.audio_loader import AudioBuffer, build_peak_pyramid
from cueplayer.playback import audio_engine as module


def engine_at_two_seconds(source_rate=44100):
    engine = module.AudioEngine()
    samples = np.full((source_rate * 3, 2), .2, np.float32)
    mono, peaks = build_peak_pyramid(samples, source_rate)
    engine._buffer = AudioBuffer('音源.wav', source_rate, samples, mono, peaks)
    engine._playback_rate = 48000
    engine._position_frame = 96000
    engine._refresh_playback_samples()
    engine._wait_for_playback_samples()
    engine._ltc_pcm = np.ones(32, np.float32)  # invalid at a new stream rate
    return engine


@pytest.mark.parametrize('source_rate,target_rate', [(44100, 48000), (44100, 96000), (48000, 96000), (96000, 44100)])
def test_all_consumers_are_ready_before_start(monkeypatch, source_rate, target_rate):
    engine = engine_at_two_seconds(source_rate)
    engine._playing = True
    observed = []

    class Stream:
        def __init__(self, **kwargs):
            self.samplerate = kwargs['samplerate']
            self.callback = kwargs['callback']

        def start(self):
            observed.append((engine._playback_rate, engine._video_mixer._playback_rate,
                             engine._position_frame, engine._playback_samples.shape[0]))
            if target_rate != 48000:
                assert engine._ltc_pcm is None
            out = np.empty((64, 2), np.float32)
            self.callback(out, 64, None, SimpleNamespace(output_underflow=False))

        def stop(self): pass
        def close(self): pass

    monkeypatch.setattr(module.sd, 'OutputStream', Stream)
    assert engine._open_output_stream(device=None, channels=2, sample_rate=target_rate)
    assert observed == [(target_rate, target_rate, target_rate * 2, target_rate * 3)]
    assert engine._active_stream_token == engine._stream_token()


def test_start_failure_closes_stream_and_restores_rate_position(monkeypatch):
    engine = engine_at_two_seconds()
    streams = []

    class Failing:
        def __init__(self, **kwargs):
            self.samplerate = kwargs['samplerate']
            self.closed = False
            streams.append(self)
        def start(self):
            raise module.sd.PortAudioError('synthetic start failure')
        def stop(self): pass
        def close(self): self.closed = True

    monkeypatch.setattr(module.sd, 'OutputStream', Failing)
    assert not engine._open_output_stream(device=None, channels=2, sample_rate=96000)
    assert streams[0].closed
    assert engine._stream is None
    assert engine._playback_rate == engine._video_mixer._playback_rate == 48000
    assert engine._position_frame == 96000
    assert engine._playback_samples.shape[0] == 144000


def test_reported_rate_mismatch_never_starts_wrong_rate_callback(monkeypatch):
    engine = engine_at_two_seconds()
    started = []
    closed = []

    class WrongRate:
        samplerate = 96000
        def __init__(self, **kwargs): pass
        def start(self): started.append(True)
        def close(self): closed.append(True)

    monkeypatch.setattr(module.sd, 'OutputStream', WrongRate)
    assert not engine._open_output_stream(device=None, channels=2, sample_rate=48000)
    assert started == [] and closed == [True]
    assert engine._position_frame == 96000


def test_fallback_token_matches_final_rate(monkeypatch):
    engine = engine_at_two_seconds()
    monkeypatch.setattr(module, 'iter_output_samplerate_candidates', lambda **kw: [48000, 96000])

    class Stream:
        def __init__(self, **kwargs):
            self.samplerate = kwargs['samplerate']
            if self.samplerate == 48000:
                raise module.sd.PortAudioError('48k rejected')
        def start(self): pass
        def stop(self): pass
        def close(self): pass

    monkeypatch.setattr(module.sd, 'OutputStream', Stream)
    assert engine._start_stream()
    assert engine._playback_rate == engine._video_mixer._playback_rate == 96000
    assert engine._position_frame == 192000
    assert engine._active_stream_token == engine._stream_token()
    assert engine._ltc_pcm is None


def test_conversion_failure_restores_existing_pcm_without_second_conversion(monkeypatch):
    engine = engine_at_two_seconds()
    previous_pcm = engine._playback_samples
    calls = []

    def failed_conversion():
        calls.append(engine._playback_rate)
        engine._playback_samples = None
        raise RuntimeError('conversion failed')

    monkeypatch.setattr(engine, '_refresh_playback_samples', failed_conversion)
    assert not engine._open_output_stream(device=None, channels=2, sample_rate=96000)
    assert calls == [96000]
    assert engine._playback_samples is previous_pcm
    assert engine._playback_rate == engine._video_mixer._playback_rate == 48000
    assert engine._position_frame == 96000


def test_failed_close_retains_stream_and_stops_fallback(monkeypatch):
    engine = engine_at_two_seconds()
    attempts = []
    can_close = [False]

    class Broken:
        def __init__(self, **kwargs):
            self.samplerate = kwargs['samplerate']
            attempts.append(self)
        def start(self):
            raise module.sd.PortAudioError('start failed')
        def stop(self): pass
        def close(self):
            if not can_close[0]:
                raise module.sd.PortAudioError('close failed')

    monkeypatch.setattr(module.sd, 'OutputStream', Broken)
    assert not engine._start_stream()
    assert len(attempts) == 1
    assert engine._stream is attempts[0]
    assert not engine.playing
    assert 'close' in engine.routing_warning.lower()
    can_close[0] = True  # permit deliberate retry/fixture teardown
    assert engine._stop_stream()
    assert engine._stream is None
