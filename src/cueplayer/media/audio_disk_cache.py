"""Persistent on-disk cache for decoded song audio (waveform + playback)."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import numpy as np

from cueplayer.media.audio_loader import AudioBuffer, PeakLevel, load_audio

_CACHE_DIR = Path(os.environ.get("CUEPLAYER_AUDIO_CACHE", Path.home() / ".cache" / "cueplayer" / "audio"))


def audio_cache_key(path: Path) -> tuple[str, int, int] | None:
    try:
        resolved = path.resolve()
        stat = resolved.stat()
        return (str(resolved), int(stat.st_mtime_ns), int(stat.st_size))
    except OSError:
        return None


def _cache_file(key: tuple[str, int, int]) -> Path:
    path_str, mtime_ns, size = key
    digest = hashlib.sha256(f"{path_str}\0{mtime_ns}\0{size}".encode("utf-8")).hexdigest()[:32]
    return _CACHE_DIR / f"{digest}.npz"


def load_cached_audio(path: Path) -> AudioBuffer | None:
    """Return a cached buffer when the source file is unchanged, else None."""
    key = audio_cache_key(path)
    if key is None:
        return None
    cache_path = _cache_file(key)
    if not cache_path.is_file():
        return None
    try:
        with np.load(cache_path, allow_pickle=False) as data:
            sample_rate = int(data["sample_rate"])
            samples = np.asarray(data["samples"], dtype=np.float32)
            mono = np.asarray(data["mono"], dtype=np.float32)
            n_peaks = int(data["n_peaks"])
            levels: list[PeakLevel] = []
            for i in range(n_peaks):
                levels.append(
                    PeakLevel(
                        samples_per_bucket=int(data[f"peak_{i}_spb"]),
                        mins=np.asarray(data[f"peak_{i}_mins"], dtype=np.float32),
                        maxs=np.asarray(data[f"peak_{i}_maxs"], dtype=np.float32),
                    )
                )
        return AudioBuffer(
            path=path,
            sample_rate=sample_rate,
            samples=samples,
            mono=mono,
            peak_levels=levels,
        )
    except Exception:
        try:
            cache_path.unlink(missing_ok=True)
        except OSError:
            pass
        return None


def save_cached_audio(path: Path, buffer: AudioBuffer) -> None:
    key = audio_cache_key(path)
    if key is None:
        return
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        arrays: dict[str, np.ndarray] = {
            "sample_rate": np.int32(buffer.sample_rate),
            "samples": buffer.samples.astype(np.float32, copy=False),
            "mono": buffer.mono.astype(np.float32, copy=False),
            "n_peaks": np.int32(len(buffer.peak_levels)),
        }
        for i, level in enumerate(buffer.peak_levels):
            arrays[f"peak_{i}_spb"] = np.int32(level.samples_per_bucket)
            arrays[f"peak_{i}_mins"] = level.mins.astype(np.float32, copy=False)
            arrays[f"peak_{i}_maxs"] = level.maxs.astype(np.float32, copy=False)
        tmp_base = _cache_file(key).with_name(_cache_file(key).stem + ".tmp")
        np.savez_compressed(str(tmp_base), **arrays)
        tmp_file = Path(str(tmp_base) + ".npz")
        tmp_file.replace(_cache_file(key))
    except OSError:
        pass


def load_audio_cached(path: Path) -> AudioBuffer:
    """Disk cache hit when possible; otherwise decode from the media file."""
    cached = load_cached_audio(path)
    if cached is not None:
        return cached
    buffer = load_audio(path)
    save_cached_audio(path, buffer)
    return buffer
