"""Video clip waveform peak envelope tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from cueplayer.domain.models import VideoClip
from cueplayer.media.video_clip_waveform import (
    peaks_from_artifact,
    sample_clip_peaks_for_times,
    sample_source_raw_for_clip_times,
    timeline_to_clip_local,
)
from cueplayer.media.video_waveform_artifact import empty_artifact, _fill_chunk_peaks


@pytest.fixture
def source_peaks(tmp_path):
    """Exercise current shared-source artifact API, not removed PCM clip copies."""
    path = tmp_path / "來源.wav"
    path.touch()

    def build(clip, *, mono, sample_rate, mono_origin_seconds=0.0):
        art = empty_artifact(path, duration_seconds=max(0.05, mono.size / sample_rate))
        _fill_chunk_peaks(art, pcm=mono, pcm_rate=sample_rate, pcm_origin=mono_origin_seconds)
        art.complete = bool(mono.size)
        return peaks_from_artifact(clip, art)

    return build


def _clip(**kwargs) -> VideoClip:
    source_out = kwargs.pop("source_out_seconds", None)
    defaults = dict(
        name="test",
        path=Path("clip.mp4"),
        start_seconds=0.0,
        source_in_seconds=0.0,
        duration_seconds=4.0,
        media_kind="video",
    )
    defaults.update(kwargs)
    clip = VideoClip.create(**defaults)
    if source_out is not None:
        clip.source_out_seconds = float(source_out)
    return clip


def test_source_artifact_has_pyramid(source_peaks) -> None:
    sr = 1000
    t = np.linspace(0, 2 * np.pi, sr * 2, dtype=np.float32)
    mono = (0.5 * np.sin(t)).astype(np.float32)
    clip = _clip(duration_seconds=2.0, source_out_seconds=2.0)
    peaks = source_peaks(clip, mono=mono, sample_rate=sr)
    assert peaks is not None
    assert peaks.mono.size / peaks.sample_rate == pytest.approx(2.0)
    assert len(peaks.peak_levels) >= 1
    assert peaks.mins.size >= 64


def test_source_sampling_loops_without_copying_pcm(source_peaks) -> None:
    sr = 100
    mono = np.zeros(sr * 2, dtype=np.float32)
    mono[10:20] = 1.0
    mono[110:120] = -1.0
    clip = _clip(
        duration_seconds=4.0,
        source_in_seconds=0.0,
        source_out_seconds=2.0,
    )
    data = source_peaks(clip, mono=mono, sample_rate=sr)
    assert data is not None
    first = sample_source_raw_for_clip_times(data, clip, clip_t0=0.1, clip_t1=0.2)
    repeat = sample_source_raw_for_clip_times(data, clip, clip_t0=2.1, clip_t1=2.2)
    assert first[1] > 0.5
    assert repeat == pytest.approx(first)


def test_still_clip_returns_peaks_from_source_in(source_peaks) -> None:
    sr = 100
    mono = np.linspace(-1.0, 1.0, sr, dtype=np.float32)
    clip = _clip(duration_seconds=3.0, media_kind="still", source_in_seconds=0.5)
    peaks = source_peaks(clip, mono=mono, sample_rate=sr)
    assert peaks is not None
    assert peaks.mins.size >= 64


def test_pending_artifact_is_not_reported_as_silence(source_peaks) -> None:
    clip = _clip()
    peaks = source_peaks(clip, mono=np.zeros(0, dtype=np.float32), sample_rate=48000)
    assert np.isnan(peaks.mins).all()
    assert not np.any(peaks.coverage)


def test_timeline_to_clip_local() -> None:
    clip = _clip(start_seconds=5.0, duration_seconds=10.0)
    assert timeline_to_clip_local(7.0, clip) == pytest.approx(2.0)
    assert timeline_to_clip_local(4.9, clip) is None
    assert timeline_to_clip_local(15.1, clip) is None


def test_sample_source_raw_resolves_trimmed_audio(source_peaks) -> None:
    sr = 1000
    mono = np.zeros(sr * 4, dtype=np.float32)
    mono[1500:1600] = 1.0
    clip = _clip(duration_seconds=2.0, source_in_seconds=1.5, source_out_seconds=3.5)
    peaks = source_peaks(clip, mono=mono, sample_rate=sr, mono_origin_seconds=0.0)
    assert peaks is not None
    lo, hi = sample_source_raw_for_clip_times(peaks, clip, clip_t0=0.0, clip_t1=0.2)
    assert hi > 0.5


def test_sample_clip_peaks_tracks_time_offset(source_peaks) -> None:
    sr = 1000
    mono = np.zeros(sr * 10, dtype=np.float32)
    mono[0:100] = 1.0
    mono[5000:5100] = -1.0
    clip = _clip(duration_seconds=10.0, source_out_seconds=10.0)
    peaks = source_peaks(clip, mono=mono, sample_rate=sr)
    assert peaks is not None

    start_lo, start_hi = sample_clip_peaks_for_times(
        peaks, duration=10.0, clip_t0=0.0, clip_t1=0.5
    )
    mid_lo, mid_hi = sample_clip_peaks_for_times(
        peaks, duration=10.0, clip_t0=4.8, clip_t1=5.2
    )
    assert start_hi > 0.5
    assert mid_lo < -0.5
    assert not np.isclose(start_hi, mid_hi)
