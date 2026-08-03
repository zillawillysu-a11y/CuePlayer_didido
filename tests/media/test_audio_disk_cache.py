"""Disk cache for decoded song audio."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from cueplayer.media.audio_disk_cache import (
    audio_cache_key,
    load_audio_cached,
    load_cached_audio,
    save_cached_audio,
)
from cueplayer.media.audio_loader import AudioBuffer, build_peak_pyramid


def _tiny_buffer(path: Path) -> AudioBuffer:
    samples = np.zeros((4800, 2), dtype=np.float32)
    samples[100:200, 0] = 0.5
    mono, levels = build_peak_pyramid(samples, 48000)
    return AudioBuffer(
        path=path,
        sample_rate=48000,
        samples=samples,
        mono=mono,
        peak_levels=levels,
    )


def test_disk_cache_roundtrip_and_invalidation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import cueplayer.media.audio_disk_cache as mod

    monkeypatch.setattr(mod, "_CACHE_DIR", tmp_path / "cache")
    audio_path = tmp_path / "song.wav"
    audio_path.write_bytes(b"placeholder")
    buffer = _tiny_buffer(audio_path)

    save_cached_audio(audio_path, buffer)
    loaded = load_cached_audio(audio_path)
    assert loaded is not None
    assert loaded.sample_rate == 48000
    assert loaded.samples.shape == buffer.samples.shape
    assert len(loaded.peak_levels) == len(buffer.peak_levels)

    # Changed file on disk invalidates cache entry.
    audio_path.write_bytes(b"changed")
    assert load_cached_audio(audio_path) is None

    audio_path.write_bytes(b"changed again")
    assert audio_cache_key(audio_path) is not None
    assert load_cached_audio(audio_path) is None


def test_load_audio_cached_writes_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import cueplayer.media.audio_disk_cache as mod

    monkeypatch.setattr(mod, "_CACHE_DIR", tmp_path / "cache")
    audio_path = tmp_path / "song.wav"
    audio_path.write_bytes(b"x")

    calls: list[Path] = []

    def fake_load(path: Path) -> AudioBuffer:
        calls.append(path)
        return _tiny_buffer(path)

    monkeypatch.setattr(mod, "load_audio", fake_load)
    first = load_audio_cached(audio_path)
    second = load_audio_cached(audio_path)
    assert first.sample_rate == 48000
    assert second.sample_rate == 48000
    assert calls == [audio_path]
