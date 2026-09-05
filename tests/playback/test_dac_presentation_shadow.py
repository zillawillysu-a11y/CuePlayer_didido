import pytest

from cueplayer.diagnostics.audio_timing import AudioTimingTrace, estimate_dac_position


def block(trace, *, rate=48000, start=0, dac=100.03, epoch=1, generation=0,
          reason=0, end=None, flags=0):
    frames = int(rate / 100)  # 10ms at all tested rates
    trace.record(epoch, generation, 98765, dac - .03, dac, frames,
                 rate, rate, 44100, start, start + frames if end is None else end,
                 flags, reason, .001)


@pytest.mark.parametrize('rate', [44100, 48000, 96000])
def test_uses_dac_interval_not_write_head_or_host_epoch(rate):
    trace = AudioTimingTrace()
    block(trace, rate=rate, start=rate * 20)
    result = estimate_dac_position(trace.snapshot(), 100.035, 1)
    assert result['position_seconds'] == pytest.approx(20.005)
    assert result['queued_seconds_at_callback'] == pytest.approx(.03)


def test_queued_seek_does_not_replace_audio_still_at_dac():
    trace = AudioTimingTrace()
    block(trace, start=48000 * 10, generation=0)
    block(trace, start=48000 * 2, dac=100.04, generation=1)
    before = estimate_dac_position(trace.snapshot(), 100.035, 1)
    after = estimate_dac_position(trace.snapshot(), 100.045, 1)
    assert before['position_seconds'] == pytest.approx(10.005)
    assert before['transport_generation'] == 0
    assert after['position_seconds'] == pytest.approx(2.005)
    assert after['transport_generation'] == 1


@pytest.mark.parametrize('now,epoch', [(100.02, 1), (100.06, 1), (100.035, 2), (None, 1)])
def test_does_not_guess_before_after_or_across_streams(now, epoch):
    trace = AudioTimingTrace()
    block(trace)
    assert estimate_dac_position(trace.snapshot(), now, epoch)['position_seconds'] is None


@pytest.mark.parametrize('kwargs,reason', [
    ({'end': 50}, 'discontinuous_or_partial_block'),
    ({'reason': 1}, 'paused'),
    ({'reason': 2}, 'exception'),
    ({'reason': 3}, 'music_not_ready'),
    ({'reason': 4}, 'end'),
    ({'flags': 8}, 'output_underflow'),
])
def test_untrusted_or_non_linear_blocks_are_explicitly_unavailable(kwargs, reason):
    trace = AudioTimingTrace()
    block(trace, **kwargs)
    result = estimate_dac_position(trace.snapshot(), 100.035, 1)
    assert result['position_seconds'] is None
    assert result['reason'] == reason


def test_missing_timestamp_is_not_replaced_with_manual_latency():
    trace = AudioTimingTrace()
    block(trace, dac=float('nan'))
    assert estimate_dac_position(trace.snapshot(), 100.035, 1)['position_seconds'] is None
