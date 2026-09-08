"""ScrubFrameCache: sparse RGB posters for hitch-free playhead drags."""

from __future__ import annotations

import time
from pathlib import Path

import av
import numpy as np
import pytest

from cueplayer.domain.models import VideoClip
from cueplayer.media.scrub_frame_cache import ScrubFrameCache

WIDTH, HEIGHT, FPS = 48, 36, 10


def _make_gradient_clip(path: Path, *, seconds: float = 2.0) -> None:
    """Each frame's red channel = frame index * 10 so nearest lookup is testable."""
    container = av.open(str(path), mode="w")
    try:
        stream = container.add_stream("mpeg4", rate=FPS)
        stream.width = WIDTH
        stream.height = HEIGHT
        stream.pix_fmt = "yuv420p"
        for i in range(int(FPS * seconds)):
            arr = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
            arr[:, :, 0] = min(255, i * 10)
            frame = av.VideoFrame.from_ndarray(arr, format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    finally:
        container.close()


@pytest.fixture
def clip_path(tmp_path: Path) -> Path:
    path = tmp_path / "scrub.mp4"
    _make_gradient_clip(path, seconds=2.0)
    return path


def test_preload_and_nearest(clip_path: Path) -> None:
    clip = VideoClip.create(
        name="c",
        path=clip_path,
        start_seconds=0.0,
        duration_seconds=2.0,
        source_duration_seconds=2.0,
    )
    cache = ScrubFrameCache()
    cache.preload([clip])
    # Worker fills asynchronously — wait briefly.
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not cache.ready(clip.id):
        time.sleep(0.05)
    assert cache.ready(clip.id)

    early = cache.nearest(clip.id, 0.05)
    late = cache.nearest(clip.id, 1.5)
    assert early is not None and late is not None
    assert early.shape[2] == 3
    # Later source time should land on a brighter (or equal) red poster.
    assert int(late[0, 0, 0]) >= int(early[0, 0, 0])


def test_clear_drops_frames(clip_path: Path) -> None:
    clip = VideoClip.create(
        name="c",
        path=clip_path,
        start_seconds=0.0,
        duration_seconds=2.0,
        source_duration_seconds=2.0,
    )
    cache = ScrubFrameCache()
    cache.ensure(clip)
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not cache.ready(clip.id):
        time.sleep(0.05)
    assert cache.ready(clip.id)
    cache.clear()
    assert not cache.ready(clip.id)
    assert cache.nearest(clip.id, 0.5) is None
