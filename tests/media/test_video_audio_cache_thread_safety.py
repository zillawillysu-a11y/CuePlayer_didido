"""Thread-safe shared video-audio decode cache."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest

from cueplayer.media.video_audio_cache import (
    clear_video_audio_cache,
    get_video_audio,
    peek_video_audio_mono,
)
from cueplayer.media.video_audio_loader import VideoAudioBuffer


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    clear_video_audio_cache()
    yield
    clear_video_audio_cache()


def test_concurrent_get_video_audio_is_stable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    media = tmp_path / "clip.mov"
    media.write_bytes(b"x")
    calls = {"n": 0}

    def _fake_load(path: Path, *, start_seconds: float = 0.0, max_duration_seconds: float | None = None):
        del start_seconds, max_duration_seconds
        calls["n"] += 1
        samples = np.zeros((4800, 2), dtype=np.float32)
        return VideoAudioBuffer(path=path, sample_rate=48000, samples=samples, origin_seconds=0.0)

    monkeypatch.setattr("cueplayer.media.video_audio_cache.load_video_audio", _fake_load)

    def _one(_: int) -> VideoAudioBuffer | None:
        return get_video_audio(media, start_seconds=0.0, max_duration_seconds=1.0)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_one, range(40)))

    assert all(r is not None and r.frames == 4800 for r in results)
    # One decode wins; everyone else reuses the cache entry.
    assert calls["n"] == 1
    mono, sr = peek_video_audio_mono(media)
    assert mono is not None and sr == 48000
