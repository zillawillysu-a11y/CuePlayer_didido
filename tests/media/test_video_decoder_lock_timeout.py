"""VideoDecoder must not freeze the UI when av_path_lock is busy."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import av
import numpy as np

from cueplayer.media.av_lock import av_path_lock
from cueplayer.media.video_loader import VideoDecoder

WIDTH, HEIGHT, FPS = 32, 24, 10


def _make_clip(path: Path, *, seconds: float = 1.0) -> None:
    container = av.open(str(path), mode="w")
    try:
        stream = container.add_stream("mpeg4", rate=FPS)
        stream.width = WIDTH
        stream.height = HEIGHT
        stream.pix_fmt = "yuv420p"
        for _ in range(int(FPS * seconds)):
            arr = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
            arr[:, :] = (0, 200, 0)
            for packet in stream.encode(av.VideoFrame.from_ndarray(arr, format="rgb24")):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    finally:
        container.close()


def test_frame_at_returns_stale_when_path_lock_held(tmp_path: Path) -> None:
    path = tmp_path / "lock.mp4"
    _make_clip(path)
    release = threading.Event()
    decoder = VideoDecoder(path)
    try:
        first = decoder.frame_at(0.1)
        assert first is not None

        held = threading.Event()

        def _hold() -> None:
            with av_path_lock(path):
                held.set()
                assert release.wait(timeout=2.0)

        t = threading.Thread(target=_hold, daemon=True)
        t.start()
        assert held.wait(timeout=1.0)

        t0 = time.monotonic()
        again = decoder.frame_at(0.5)
        elapsed = time.monotonic() - t0
        release.set()
        t.join(timeout=1.0)

        # Must not block for the whole hold — return last frame quickly.
        assert again is not None
        assert elapsed < 0.25
        assert again is first or np.allclose(again, first)
    finally:
        release.set()
        decoder.close()


def test_frame_at_lock_timeout_cold_returns_none_quickly(tmp_path: Path) -> None:
    """Worker/cold path with lock_timeout must not block for seconds."""
    path = tmp_path / "cold.mp4"
    _make_clip(path)
    release = threading.Event()
    decoder = VideoDecoder(path)
    try:
        held = threading.Event()

        def _hold() -> None:
            with av_path_lock(path):
                held.set()
                assert release.wait(timeout=2.0)

        t = threading.Thread(target=_hold, daemon=True)
        t.start()
        assert held.wait(timeout=1.0)

        t0 = time.monotonic()
        frame = decoder.frame_at(0.2, lock_timeout=0.05)
        elapsed = time.monotonic() - t0
        release.set()
        t.join(timeout=1.0)

        assert frame is None  # cold + timeout → no stale
        assert elapsed < 0.2
    finally:
        release.set()
        decoder.close()
