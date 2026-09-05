from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from cueplayer.media.video_waveform_artifact import (
    SequentialWaveformDecoder, DECODE_EOF, DECODE_PCM, DECODE_SILENCE,
)


@pytest.mark.parametrize('rate', [44100, 48000, 96000])
def test_real_decoder_keeps_every_sample_across_batches(tmp_path: Path, rate):
    path = tmp_path / '批次鼓點.wav'
    pcm = np.random.default_rng(42).uniform(-.5, .5, (rate * 25, 2)).astype(np.float32)
    sf.write(str(path), pcm, rate, subtype='FLOAT')
    decoder = SequentialWaveformDecoder(path)
    chunks = []
    consumed = 0
    try:
        assert decoder.ensure_open() is None
        while True:
            batch = decoder.read_batch(max_seconds=8)
            if batch.kind == DECODE_EOF:
                break
            assert batch.kind in (DECODE_PCM, DECODE_SILENCE)
            assert batch.origin_seconds == pytest.approx(consumed / rate, abs=.5/rate)
            consumed += len(batch.samples)
            chunks.append(batch.samples)
            assert len(chunks) < 10
        assert consumed == len(pcm)
        np.testing.assert_array_equal(np.concatenate(chunks), pcm)
    finally:
        decoder.close()


def test_seek_replaces_pending_tail_and_reopen_resumes_exactly(tmp_path):
    rate = 48000
    pcm = np.random.default_rng(5).uniform(-.3, .3, (rate * 3, 2)).astype(np.float32)
    path = tmp_path / '重定位.wav'
    sf.write(str(path), pcm, rate, subtype='FLOAT')
    decoder = SequentialWaveformDecoder(path)
    try:
        decoder.ensure_open()
        decoder.read_batch(max_seconds=.123)
        decoder.ensure_open(seek_seconds=1.234)
        batch = decoder.read_batch(max_seconds=.123)
        start = round(1.234 * rate)
        assert batch.origin_seconds == pytest.approx(start/rate)
        np.testing.assert_array_equal(batch.samples, pcm[start:start+len(batch.samples)])
        start += len(batch.samples)
        decoder.close()
        decoder.ensure_open()
        resumed = decoder.read_batch(max_seconds=.123)
        assert resumed.origin_seconds == pytest.approx(start/rate)
        np.testing.assert_array_equal(resumed.samples, pcm[start:start+len(resumed.samples)])
    finally:
        decoder.close()


def test_real_pts_gap_is_not_compacted_into_contiguous_pcm(tmp_path):
    decoder = SequentialWaveformDecoder(tmp_path / 'gap.wav')
    decoder._container = object()
    decoder._iterator = iter(())
    decoder._sample_rate = 1000
    decoder._pcm_iterator = iter([
        (0.0, np.ones((100, 2), np.float32)),
        (.2, np.full((100, 2), .5, np.float32)),
    ])
    try:
        first = decoder.read_batch(max_seconds=1)
        second = decoder.read_batch(max_seconds=1)
        assert first.origin_seconds == 0 and first.duration_seconds == .1
        assert second.origin_seconds == .2 and second.duration_seconds == .1
        assert decoder.read_batch().kind == DECODE_EOF
    finally:
        decoder.close()
