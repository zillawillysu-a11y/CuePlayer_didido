"""Video clip crossfade weight tests."""

from __future__ import annotations

import numpy as np

from cueplayer.domain.models import VideoClip, video_clip_crossfade_weight, video_clip_crossfade_weights


def test_crossfade_batch_matches_scalar() -> None:
    clips = [
        VideoClip.create(name="a", path="/a.mp4", start_seconds=0.0, duration_seconds=10.0),
        VideoClip.create(name="b", path="/b.mp4", start_seconds=5.0, duration_seconds=10.0),
    ]
    times = np.linspace(0.0, 14.0, 256, dtype=np.float64)
    batch = video_clip_crossfade_weights(clips[0], times, clips)
    scalar = np.array(
        [video_clip_crossfade_weight(clips[0], float(t), clips) for t in times],
        dtype=np.float32,
    )
    assert np.allclose(batch, scalar, atol=1e-6)
