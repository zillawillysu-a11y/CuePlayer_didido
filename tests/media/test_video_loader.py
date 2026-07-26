"""Video probing / frame decoding (PyAV). Encodes tiny synthetic clips on the fly
so tests stay self-contained (no binary fixtures checked into the repo)."""

from __future__ import annotations

from pathlib import Path

import av
import numpy as np
import pytest

from cueplayer.media.video_loader import VideoDecoder, probe_video

WIDTH, HEIGHT, FPS = 32, 24, 10


def _make_two_color_clip(path: Path, *, seconds: float = 2.0) -> None:
    """Solid red for the first half, solid blue for the second half."""
    container = av.open(str(path), mode="w")
    try:
        stream = container.add_stream("mpeg4", rate=FPS)
        stream.width = WIDTH
        stream.height = HEIGHT
        stream.pix_fmt = "yuv420p"
        total_frames = int(FPS * seconds)
        for i in range(total_frames):
            t = i / FPS
            color = (255, 0, 0) if t < seconds / 2 else (0, 0, 255)
            arr = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
            arr[:, :] = color
            frame = av.VideoFrame.from_ndarray(arr, format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    finally:
        container.close()


@pytest.fixture
def two_color_clip(tmp_path: Path) -> Path:
    path = tmp_path / "中文影片" / "測試.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    _make_two_color_clip(path)
    return path


def test_probe_video_reads_geometry_and_duration(two_color_clip: Path) -> None:
    info = probe_video(two_color_clip)
    assert info.width == WIDTH
    assert info.height == HEIGHT
    assert info.duration_seconds == pytest.approx(2.0, abs=0.2)
    assert info.fps > 0


def test_probe_video_supports_unicode_path(two_color_clip: Path) -> None:
    assert two_color_clip.is_file()
    info = probe_video(two_color_clip)
    assert info.duration_seconds > 0


def test_video_decoder_frame_at_returns_expected_colors(two_color_clip: Path) -> None:
    decoder = VideoDecoder(two_color_clip)
    try:
        early = decoder.frame_at(0.05)
        late = decoder.frame_at(1.8)
        assert early is not None and late is not None
        assert early.shape == (HEIGHT, WIDTH, 3)
        # Dominant channel: red early, blue late.
        assert early.mean(axis=(0, 1))[0] > early.mean(axis=(0, 1))[2]
        assert late.mean(axis=(0, 1))[2] > late.mean(axis=(0, 1))[0]
    finally:
        decoder.close()


def test_video_decoder_handles_backward_seek(two_color_clip: Path) -> None:
    decoder = VideoDecoder(two_color_clip)
    try:
        decoder.frame_at(1.8)
        rewound = decoder.frame_at(0.05)
        assert rewound is not None
        assert rewound.mean(axis=(0, 1))[0] > rewound.mean(axis=(0, 1))[2]
    finally:
        decoder.close()


def test_video_decoder_close_is_idempotent_and_stops_decoding(two_color_clip: Path) -> None:
    decoder = VideoDecoder(two_color_clip)
    decoder.close()
    decoder.close()  # must not raise
    assert decoder.frame_at(0.5) is None


def test_probe_video_raises_for_missing_file(tmp_path: Path) -> None:
    with pytest.raises(Exception):
        probe_video(tmp_path / "does-not-exist.mp4")


def test_video_decoder_max_decode_height_downscales_frame(two_color_clip: Path) -> None:
    """Preview/Clean Output decode-quality cap: smaller frames, same aspect ratio."""
    full = VideoDecoder(two_color_clip)
    capped = VideoDecoder(two_color_clip, max_decode_height=HEIGHT // 2)
    try:
        full_frame = full.frame_at(0.05)
        capped_frame = capped.frame_at(0.05)
        assert full_frame is not None and capped_frame is not None
        assert full_frame.shape == (HEIGHT, WIDTH, 3)
        assert capped_frame.shape[0] <= HEIGHT // 2
        assert capped_frame.shape[0] < full_frame.shape[0]
        # Still recognizably red (downscale must not corrupt color).
        assert capped_frame.mean(axis=(0, 1))[0] > capped_frame.mean(axis=(0, 1))[2]
    finally:
        full.close()
        capped.close()


def test_video_decoder_frame_at_reuses_cached_ndarray_within_same_source_frame(
    two_color_clip: Path,
) -> None:
    """Root-cause regression test for the "timeline lags during video playback"
    bug: AudioEngine's position ticks land far more often (~60Hz) than the
    clip's own frame rate (10fps here), so most calls land within the same
    already-decoded source frame's duration. Those must be a cache hit — no
    repeated colorspace conversion — or the UI thread pays for a full
    reformat/to_ndarray on every tick even though nothing changed on screen."""
    decoder = VideoDecoder(two_color_clip)
    try:
        conversions = {"n": 0}
        original_to_ndarray = decoder._to_ndarray

        def counting_to_ndarray(frame):  # noqa: ANN001
            conversions["n"] += 1
            return original_to_ndarray(frame)

        decoder._to_ndarray = counting_to_ndarray

        # FPS=10 -> each source frame spans ~0.1s; 0.05 and 0.06 fall inside
        # the very same frame's window as 0.0.
        first = decoder.frame_at(0.05)
        second = decoder.frame_at(0.06)

        assert conversions["n"] == 1  # only the *first* call actually converted
        assert first is second  # second call returned the identical cached array
    finally:
        decoder.close()


def test_video_decoder_max_decode_height_never_upscales(two_color_clip: Path) -> None:
    decoder = VideoDecoder(two_color_clip, max_decode_height=HEIGHT * 10)
    try:
        frame = decoder.frame_at(0.05)
        assert frame is not None
        assert frame.shape == (HEIGHT, WIDTH, 3)
    finally:
        decoder.close()
