"""Video audio extraction (PyAV). Encodes tiny synthetic clips on the fly so
tests stay self-contained (no binary fixtures checked into the repo)."""

from __future__ import annotations

from pathlib import Path

import av
import numpy as np
import pytest

from cueplayer.media.video_audio_loader import load_video_audio

WIDTH, HEIGHT, FPS = 32, 24, 10


def _make_clip_with_tone(
    path: Path,
    *,
    seconds: float = 1.0,
    audio_rate: int = 44100,
    channels: int = 2,
    left_amp: float = 0.6,
    right_amp: float = 0.3,
) -> None:
    container = av.open(str(path), mode="w")
    try:
        vstream = container.add_stream("mpeg4", rate=FPS)
        vstream.width = WIDTH
        vstream.height = HEIGHT
        vstream.pix_fmt = "yuv420p"
        astream = container.add_stream("aac", rate=audio_rate)
        astream.layout = "stereo" if channels == 2 else "mono"

        for _ in range(int(FPS * seconds)):
            arr = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
            for packet in vstream.encode(av.VideoFrame.from_ndarray(arr, format="rgb24")):
                container.mux(packet)
        for packet in vstream.encode():
            container.mux(packet)

        frame_size = astream.frame_size or 1024
        n = int(audio_rate * seconds)
        t = np.arange(n, dtype=np.float32) / audio_rate
        left = (left_amp * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        if channels == 2:
            right = (right_amp * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
            data = np.stack([left, right], axis=0)
            layout = "stereo"
        else:
            data = left[None, :]
            layout = "mono"
        for i in range(0, data.shape[1], frame_size):
            chunk = data[:, i : i + frame_size]
            if chunk.shape[1] == 0:
                continue
            frame = av.AudioFrame.from_ndarray(chunk, format="fltp", layout=layout)
            frame.sample_rate = audio_rate
            for packet in astream.encode(frame):
                container.mux(packet)
        for packet in astream.encode():
            container.mux(packet)
    finally:
        container.close()


def _make_silent_clip(path: Path, *, seconds: float = 0.5) -> None:
    container = av.open(str(path), mode="w")
    try:
        vstream = container.add_stream("mpeg4", rate=FPS)
        vstream.width = WIDTH
        vstream.height = HEIGHT
        vstream.pix_fmt = "yuv420p"
        for _ in range(int(FPS * seconds)):
            arr = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
            for packet in vstream.encode(av.VideoFrame.from_ndarray(arr, format="rgb24")):
                container.mux(packet)
        for packet in vstream.encode():
            container.mux(packet)
    finally:
        container.close()


@pytest.fixture
def stereo_clip(tmp_path: Path) -> Path:
    path = tmp_path / "中文影片" / "有聲音.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    _make_clip_with_tone(path, seconds=1.0)
    return path


def test_load_video_audio_returns_stereo_pcm_with_expected_gain_ratio(stereo_clip: Path) -> None:
    buf = load_video_audio(stereo_clip)
    assert buf is not None
    assert buf.channels == 2
    assert buf.sample_rate == 44100
    assert buf.frames > 0
    # Duration should be close to the encoded 1.0s (container framing adds a
    # little slack, same tolerance as the video-only decoder tests).
    assert buf.frames / buf.sample_rate == pytest.approx(1.0, abs=0.2)

    left_rms = float(np.sqrt(np.mean(buf.samples[:, 0] ** 2)))
    right_rms = float(np.sqrt(np.mean(buf.samples[:, 1] ** 2)))
    assert left_rms > right_rms > 0.0
    assert left_rms / right_rms == pytest.approx(0.6 / 0.3, rel=0.05)


def test_load_video_audio_upmixes_mono_to_stereo(tmp_path: Path) -> None:
    path = tmp_path / "mono.mp4"
    _make_clip_with_tone(path, seconds=0.5, audio_rate=48000, channels=1)
    buf = load_video_audio(path)
    assert buf is not None
    assert buf.sample_rate == 48000
    assert buf.channels == 2


def test_load_video_audio_returns_none_when_no_audio_stream(tmp_path: Path) -> None:
    path = tmp_path / "silent.mp4"
    _make_silent_clip(path)
    assert load_video_audio(path) is None


def test_load_video_audio_respects_max_duration_window(tmp_path: Path) -> None:
    path = tmp_path / "longish.mp4"
    _make_clip_with_tone(path, seconds=2.0)
    buf = load_video_audio(path, start_seconds=0.0, max_duration_seconds=0.4)
    assert buf is not None
    assert buf.frames / buf.sample_rate == pytest.approx(0.4, abs=0.15)


def test_audio_window_for_clip_caps_long_source() -> None:
    from cueplayer.domain.models import VideoClip
    from cueplayer.media.video_audio_cache import audio_window_for_clip
    from cueplayer.media.video_limits import HEAVY_VIDEO_AUDIO_DECODE_SECONDS

    clip = VideoClip.create(
        name="long",
        path=Path("x.mp4"),
        duration_seconds=180.0,
        source_duration_seconds=7200.0,
    )
    clip.source_out_seconds = clip.source_in_seconds + 7200.0
    start, dur = audio_window_for_clip(clip)
    assert start == 0.0
    # Heavy rehearsal sources use the tighter embedded-audio cap.
    assert dur == HEAVY_VIDEO_AUDIO_DECODE_SECONDS

