"""Music-lane stand-in waveform from embedded video audio."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from cueplayer.domain.models import VideoClip
from cueplayer.media.video_music_standin import (
    _downsample_to_overview,
    build_music_standin_from_video,
)
from tests.media.test_video_audio_loader import _make_clip_with_tone


def test_build_music_standin_from_short_video(tmp_path: Path) -> None:
    path = tmp_path / "short.mp4"
    _make_clip_with_tone(path, seconds=0.8)
    clip = VideoClip.create(
        name="v",
        path=path,
        start_seconds=0.0,
        duration_seconds=0.8,
        source_duration_seconds=0.8,
    )
    buf = build_music_standin_from_video(clip, timeline_duration=0.8)
    assert buf is not None
    assert buf.duration_seconds == pytest.approx(0.8, abs=0.25)
    assert buf.mono.size > 10
    assert float(np.max(np.abs(buf.mono))) > 0.0


def test_build_music_standin_places_clip_after_timeline_start(tmp_path: Path) -> None:
    path = tmp_path / "offset.mp4"
    _make_clip_with_tone(path, seconds=0.5)
    clip = VideoClip.create(
        name="v",
        path=path,
        start_seconds=1.0,
        duration_seconds=0.5,
        source_duration_seconds=0.5,
    )
    buf = build_music_standin_from_video(clip, timeline_duration=2.0)
    assert buf is not None
    assert buf.duration_seconds == pytest.approx(2.0, abs=0.3)
    # Leading second should be near-silent; clip region has energy.
    sr = buf.sample_rate
    head = buf.mono[: int(0.5 * sr)]
    body = buf.mono[int(1.0 * sr) : int(1.4 * sr)]
    assert float(np.max(np.abs(head))) < 0.05
    assert float(np.max(np.abs(body))) > 0.01


def test_downsample_overview_keeps_signed_peaks() -> None:
    """Abs-only overview used to paint Music lane as bottom-half comb only."""
    sr = 1000
    samples = np.zeros(1000, dtype=np.float32)
    samples[50] = -0.9
    samples[150] = 0.8
    out = _downsample_to_overview(samples, sr, overview_hz=10)
    assert out[0] < 0
    assert out[1] > 0


def test_build_music_standin_honors_cancel_check(tmp_path: Path) -> None:
    path = tmp_path / "short.mp4"
    _make_clip_with_tone(path, seconds=0.5)
    clip = VideoClip.create(
        name="v",
        path=path,
        start_seconds=0.0,
        duration_seconds=0.5,
        source_duration_seconds=0.5,
    )
    assert build_music_standin_from_video(
        clip, timeline_duration=0.5, cancel_check=lambda: True
    ) is None
