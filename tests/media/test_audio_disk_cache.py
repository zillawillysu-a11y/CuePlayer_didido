"""Disk cache for decoded song audio."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from cueplayer.media.audio_disk_cache import (
    audio_cache_key,
    clone_caches_for_copied_file,
    load_all_ltc_channels,
    load_audio_cached,
    load_cached_audio,
    load_cached_video_standin,
    load_cached_waveform_peaks,
    save_cached_audio,
    save_cached_video_standin,
    save_ltc_channel,
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

    def fake_load(path: Path, *, on_pcm_ready=None) -> AudioBuffer:  # noqa: ANN001
        calls.append(path)
        buf = _tiny_buffer(path)
        if on_pcm_ready is not None:
            on_pcm_ready(buf)
        return buf

    monkeypatch.setattr(mod, "load_audio", fake_load)
    first = load_audio_cached(audio_path)
    second = load_audio_cached(audio_path)
    assert first.sample_rate == 48000
    assert second.sample_rate == 48000
    assert calls == [audio_path]


def test_clone_caches_for_copied_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import shutil

    import cueplayer.media.audio_disk_cache as mod

    monkeypatch.setattr(mod, "_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(mod, "_LTC_CACHE_FILE", tmp_path / "cache" / "ltc_channels.json")

    src = tmp_path / "original" / "song.wav"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"WAVDATA")
    save_cached_audio(src, _tiny_buffer(src))
    src_key = audio_cache_key(src)
    assert src_key is not None
    save_ltc_channel(src_key, 0)  # Left

    dest = tmp_path / "Media" / "song.wav"
    dest.parent.mkdir(parents=True)
    shutil.copy2(src, dest)

    assert clone_caches_for_copied_file(src, dest) is True
    assert load_cached_audio(dest) is not None
    dest_key = audio_cache_key(dest)
    assert dest_key is not None
    assert dest_key != src_key
    assert load_all_ltc_channels().get(dest_key) == 0


def test_adopt_caches_when_former_path_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    import cueplayer.media.audio_disk_cache as mod
    from cueplayer.media.audio_disk_cache import adopt_caches_for_path

    monkeypatch.setattr(mod, "_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(mod, "_LTC_CACHE_FILE", tmp_path / "cache" / "ltc_channels.json")

    src = tmp_path / "was" / "song.wav"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"WAVDATA")
    save_cached_audio(src, _tiny_buffer(src))
    src_key = audio_cache_key(src)
    assert src_key is not None
    save_ltc_channel(src_key, 1)

    dest = tmp_path / "now" / "song.wav"
    dest.parent.mkdir(parents=True)
    shutil.copy2(src, dest)
    former = src
    src.unlink()  # simulate move — old path gone

    assert adopt_caches_for_path(dest, former_path=former) is True
    assert load_cached_audio(dest) is not None
    dest_key = audio_cache_key(dest)
    assert dest_key is not None
    assert load_all_ltc_channels().get(dest_key) == 1


def test_adopt_waveform_only_without_ltc_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Media move must reuse waveform even when LTC was never detected."""
    import shutil

    import cueplayer.media.audio_disk_cache as mod
    from cueplayer.media.audio_disk_cache import adopt_caches_for_path

    monkeypatch.setattr(mod, "_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(mod, "_LTC_CACHE_FILE", tmp_path / "cache" / "ltc_channels.json")

    src = tmp_path / "was" / "song.wav"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"WAVDATA")
    save_cached_audio(src, _tiny_buffer(src))
    assert audio_cache_key(src) is not None
    assert load_all_ltc_channels() == {}

    dest = tmp_path / "now" / "song.wav"
    dest.parent.mkdir(parents=True)
    shutil.copy2(src, dest)
    former = src
    src.unlink()

    assert adopt_caches_for_path(dest, former_path=former) is True
    assert load_cached_audio(dest) is not None


def test_peaks_sidecar_survives_without_full_pcm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cueplayer.media.audio_disk_cache as mod

    monkeypatch.setattr(mod, "_CACHE_DIR", tmp_path / "cache")
    audio_path = tmp_path / "long.wav"
    audio_path.write_bytes(b"placeholder")
    buffer = _tiny_buffer(audio_path)
    save_cached_audio(audio_path, buffer)

    # Simulate full PCM write never finishing / being deleted.
    key = audio_cache_key(audio_path)
    assert key is not None
    full = mod._cache_file(key)
    if full.is_file():
        full.unlink()

    peaks = load_cached_waveform_peaks(audio_path)
    assert peaks is not None
    assert peaks.sample_rate == 48000
    assert len(peaks.peak_levels) == len(buffer.peak_levels)
    assert peaks.frames == buffer.frames
    assert load_cached_audio(audio_path) is None


def test_video_standin_disk_peaks_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cueplayer.media.audio_disk_cache as mod

    monkeypatch.setattr(mod, "_CACHE_DIR", tmp_path / "cache")
    buffer = _tiny_buffer(tmp_path / "clip.mp4")
    key = "clip|path|1|2|60.0|0.0|0.0|60.0"
    save_cached_video_standin(key, buffer)
    loaded = load_cached_video_standin(key)
    assert loaded is not None
    assert loaded.sample_rate == 48000
    assert len(loaded.peak_levels) == len(buffer.peak_levels)
    # Peaks-only stand-in — no multi-hundred-MB PCM on disk.
    assert loaded.samples.shape[0] == buffer.frames


def test_clone_copies_peaks_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    import cueplayer.media.audio_disk_cache as mod

    monkeypatch.setattr(mod, "_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(mod, "_LTC_CACHE_FILE", tmp_path / "cache" / "ltc_channels.json")

    src = tmp_path / "a" / "song.wav"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"WAVDATA")
    save_cached_audio(src, _tiny_buffer(src))
    src_key = audio_cache_key(src)
    assert src_key is not None
    # Keep peaks only (long-song case where full .npz never landed).
    mod._cache_file(src_key).unlink(missing_ok=True)
    assert mod._peaks_cache_file(src_key).is_file()

    dest = tmp_path / "b" / "song.wav"
    dest.parent.mkdir(parents=True)
    shutil.copy2(src, dest)
    assert clone_caches_for_copied_file(src, dest) is True
    assert load_cached_waveform_peaks(dest) is not None
