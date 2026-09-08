from types import SimpleNamespace

import numpy as np
import pytest

from cueplayer.diagnostics.audio_timing import AudioTimingTrace
from cueplayer.playback.audio_engine import AudioEngine


def test_ring_has_fixed_storage_and_keeps_latest_rows():
    trace = AudioTimingTrace(3)
    storage = trace._rows
    for i in range(10):
        trace.record(1, 2, i, i, i + .03, 480, 48000, 48000, 44100,
                     i * 480, (i + 1) * 480, 0, 0, .001)
    rows = trace.snapshot()
    assert trace._rows is storage and len(storage) == 45
    assert [row['sequence'] for row in rows] == [8, 9, 10]
    assert rows[-1]['dac_time'] - rows[-1]['current_time'] == pytest.approx(.03)


@pytest.mark.parametrize('playing', [False, True])
def test_trace_observes_dac_time_without_changing_audio_or_position(monkeypatch, playing):
    outputs = []
    for enabled in ('0', '1'):
        monkeypatch.setenv('CUEPLAYER_AUDIO_TRACE', enabled)
        engine = AudioEngine()
        engine._playing = playing
        engine._playback_rate = 48000
        engine._playback_samples = np.full((96000, 2), .25, dtype=np.float32)
        out = np.empty((480, 2), dtype=np.float32)
        engine._make_stream_callback(48000)(
            out, 480, SimpleNamespace(currentTime=100, outputBufferDacTime=100.03),
            SimpleNamespace(output_underflow=False, _flags=0),
        )
        outputs.append((out.copy(), engine._position_frame))
        rows = engine.audio_timing_diagnostics()['callbacks']
        if enabled == '1':
            assert len(rows) == 1
            assert rows[0]['dac_time'] == 100.03
            assert rows[0]['start_frame'] == 0
            assert rows[0]['end_frame'] == engine._position_frame
            assert rows[0]['reason'] == (0 if playing else 1)
        else:
            assert rows == []
    np.testing.assert_array_equal(outputs[0][0], outputs[1][0])
    assert outputs[0][1] == outputs[1][1]


def test_callback_error_is_observable_without_escaping(monkeypatch):
    monkeypatch.setenv('CUEPLAYER_AUDIO_TRACE', '1')
    engine = AudioEngine()
    engine._playing = True

    def fail(*args):
        raise RuntimeError('synthetic mix failure')

    monkeypatch.setattr(engine, '_music_chunk', fail)
    out = np.ones((64, 2), np.float32)
    engine._make_stream_callback(48000)(out, 64, None, None)
    assert not out.any()
    row = engine.audio_timing_diagnostics()['callbacks'][0]
    assert row['reason'] == 2
    assert np.isnan(row['dac_time'])


def test_stream_attempt_and_seek_generations_are_observed(monkeypatch):
    monkeypatch.setenv('CUEPLAYER_AUDIO_TRACE', '1')
    engine = AudioEngine()
    assert engine._open_output_stream(device=None, channels=2, sample_rate=48000)
    engine.seek(2)
    first = engine.audio_timing_diagnostics()
    assert first['stream_epoch'] == 1
    assert first['transport_generation'] == 1
    assert first['stream_reported']['samplerate'] == 48000
    assert first['source_ready_ranges'].startswith('unknown')
    engine._stop_stream()
    assert engine._open_output_stream(device=None, channels=2, sample_rate=96000)
    assert engine.audio_timing_diagnostics()['stream_epoch'] == 2


def test_variable_blocks_and_status_bits_are_counted_correctly(monkeypatch):
    from cueplayer.playback import audio_engine as module

    engine = AudioEngine()
    callback = engine._make_stream_callback(48000)
    now = [100.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    callback(np.zeros((480, 2), np.float32), 480, None, 2)  # input overflow
    now[0] += .01
    callback(np.zeros((960, 2), np.float32), 960, None, 8)  # output underflow
    now[0] += .02
    callback(np.zeros((240, 2), np.float32), 240, None, 0)
    snap = engine.audio_callback_continuity()
    assert snap['output_underflow_count'] == 1
    assert snap['deadline_miss_count'] == 0
    assert snap['expected_period_s'] == pytest.approx(.005)
    engine._open_output_stream(device=None, channels=2, sample_rate=48000)
    assert engine._cb_last_mono == 0.0  # downtime is not a deadline miss


def test_new_stream_resets_continuity_counters_but_failed_open_does_not(monkeypatch):
    from cueplayer.playback import audio_engine as module

    engine = module.AudioEngine()
    callback = engine._make_stream_callback(48000)
    callback(np.zeros((480, 2), np.float32), 480, None, 8)  # output underflow
    callback(np.zeros((480, 2), np.float32), 480, None, 0)
    before = engine.audio_callback_continuity()
    assert before['callback_count'] == 2
    assert before['output_underflow_count'] == 1

    class Failing:
        def __init__(self, **kwargs):
            self.samplerate = kwargs['samplerate']

        def start(self):
            raise module.sd.PortAudioError('synthetic start failure')

        def stop(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(module.sd, 'OutputStream', Failing)
    assert not engine._open_output_stream(device=None, channels=2, sample_rate=48000)
    after_failure = engine.audio_callback_continuity()
    assert after_failure['callback_count'] == 2
    assert after_failure['output_underflow_count'] == 1

    class Working:
        def __init__(self, **kwargs):
            self.samplerate = kwargs['samplerate']

        def start(self):
            pass

        def stop(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(module.sd, 'OutputStream', Working)
    assert engine._open_output_stream(device=None, channels=2, sample_rate=48000)
    after_success = engine.audio_callback_continuity()
    assert after_success['callback_count'] == 0
    assert after_success['output_underflow_count'] == 0
