import numpy as np
import pytest

from cueplayer.media.audio_loader import build_peak_pyramid, choose_peak_level, _minmax_buckets


@pytest.mark.parametrize('rate', [44100, 48000, 96000])
def test_zoom_selects_coarsest_bucket_no_wider_than_pixel(rate):
    _, levels = build_peak_pyramid(np.zeros(rate, np.float32), rate)
    for level in levels:
        assert choose_peak_level(levels, level.samples_per_bucket) is level
    assert choose_peak_level(levels, .1) is levels[-1]
    assert choose_peak_level(levels, rate * 100) is levels[0]


@pytest.mark.parametrize('rate', [44100, 48000, 96000])
def test_last_sample_is_covered_at_every_level_without_changing_pcm(rate):
    pcm = np.zeros((rate + 1, 2), np.float32)
    pcm[-1] = 1
    before = pcm.copy()
    _, levels = build_peak_pyramid(pcm, rate)
    np.testing.assert_array_equal(pcm, before)
    for level in levels:
        assert len(level.maxs) == (len(pcm) + level.samples_per_bucket - 1) // level.samples_per_bucket
        assert level.maxs[-1] == 1


def test_partial_bucket_preserves_min_without_zero_padding():
    level = _minmax_buckets(np.array([.2, .5, .8], np.float32), 2)
    np.testing.assert_allclose(level.mins, [.2, .8])
    np.testing.assert_allclose(level.maxs, [.5, .8])


def test_sub_bucket_and_empty_input_are_defined():
    level = _minmax_buckets(np.array([.7], np.float32), 64)
    assert level.mins[0] == pytest.approx(.7)
    assert _minmax_buckets(np.zeros(0, np.float32), 64).maxs.size == 0


def test_legacy_disk_peaks_recover_tail_from_saved_mono(tmp_path):
    from cueplayer.media.audio_disk_cache import _levels_from_npz

    path = tmp_path / '舊快取.npz'
    mono = np.array([.2, .5, .8], np.float32)
    np.savez(path, n_peaks=1, peak_0_spb=2,
             peak_0_mins=np.array([.2], np.float32),
             peak_0_maxs=np.array([.5], np.float32))
    with np.load(path, allow_pickle=False) as saved:
        level = _levels_from_npz(saved, mono)[0]
    np.testing.assert_allclose(level.mins, [.2, .8])
    np.testing.assert_allclose(level.maxs, [.5, .8])
