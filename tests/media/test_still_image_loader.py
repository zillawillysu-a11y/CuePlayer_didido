"""Still image probing/decoding for the video track."""

from __future__ import annotations

from pathlib import Path

import av
import numpy as np
import pytest

from cueplayer.media.video_loader import (
    StillImageDecoder,
    is_still_image_path,
    probe_media,
    probe_still_image,
)

WIDTH, HEIGHT = 48, 32


def _write_png(path: Path, *, color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    arr[:, :] = color
    frame = av.VideoFrame.from_ndarray(arr, format="rgb24")
    container = av.open(str(path), mode="w")
    try:
        stream = container.add_stream("png")
        stream.width = WIDTH
        stream.height = HEIGHT
        stream.pix_fmt = "rgb24"
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    finally:
        container.close()


@pytest.fixture
def unicode_png(tmp_path: Path) -> Path:
    path = tmp_path / "中文素材" / "標題.png"
    _write_png(path, color=(10, 120, 200))
    return path


def test_is_still_image_path() -> None:
    assert is_still_image_path(Path("x.PNG"))
    assert not is_still_image_path(Path("x.mp4"))


def test_probe_still_image_reads_geometry(unicode_png: Path) -> None:
    info = probe_still_image(unicode_png)
    assert info.media_kind == "still"
    assert info.width == WIDTH
    assert info.height == HEIGHT


def test_probe_media_dispatches_to_still(unicode_png: Path) -> None:
    info = probe_media(unicode_png)
    assert info.media_kind == "still"


def test_still_image_decoder_returns_constant_frame(unicode_png: Path) -> None:
    decoder = StillImageDecoder(unicode_png)
    try:
        early = decoder.frame_at(0.0)
        late = decoder.frame_at(99.0)
        assert early is not None and late is not None
        assert early.shape == (HEIGHT, WIDTH, 3)
        assert np.array_equal(early, late)
        assert early.mean(axis=(0, 1))[2] > early.mean(axis=(0, 1))[0]
    finally:
        decoder.close()
