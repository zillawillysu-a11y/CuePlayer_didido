"""Bounded, user-visible management for recoverable media caches."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


AUDIO_CACHE_MAX_BYTES = 8 * 1024**3
VIDEO_WAVE_CACHE_MAX_BYTES = 2 * 1024**3


def audio_cache_dir() -> Path:
    return Path(
        os.environ.get(
            "CUEPLAYER_AUDIO_CACHE",
            Path.home() / ".cache" / "cueplayer" / "audio",
        )
    )


def video_wave_cache_dir() -> Path:
    return Path(
        os.environ.get(
            "CUEPLAYER_VIDEO_WAVE_CACHE",
            Path.home() / ".cache" / "cueplayer" / "video_waveforms",
        )
    )


@dataclass(frozen=True)
class MediaCacheStats:
    audio_bytes: int
    video_wave_bytes: int
    file_count: int

    @property
    def total_bytes(self) -> int:
        return int(self.audio_bytes + self.video_wave_bytes)


def _cache_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return [path for path in root.iterdir() if path.is_file()]


def media_cache_stats() -> MediaCacheStats:
    audio = _cache_files(audio_cache_dir())
    video = _cache_files(video_wave_cache_dir())

    def _size(paths: list[Path]) -> int:
        total = 0
        for path in paths:
            try:
                total += int(path.stat().st_size)
            except OSError:
                pass
        return total

    return MediaCacheStats(_size(audio), _size(video), len(audio) + len(video))


def prune_cache_dir(root: Path, *, max_bytes: int) -> int:
    """Remove oldest recoverable files until `root` is within its byte budget."""
    rows: list[tuple[float, int, Path]] = []
    for path in _cache_files(root):
        try:
            stat = path.stat()
            rows.append((float(stat.st_mtime), int(stat.st_size), path))
        except OSError:
            pass
    total = sum(size for _mtime, size, _path in rows)
    removed = 0
    for _mtime, size, path in sorted(rows):
        if total <= max(0, int(max_bytes)):
            break
        try:
            path.unlink(missing_ok=True)
        except OSError:
            continue
        total -= size
        removed += size
    return removed


def prune_media_caches() -> int:
    return prune_cache_dir(
        audio_cache_dir(), max_bytes=AUDIO_CACHE_MAX_BYTES
    ) + prune_cache_dir(
        video_wave_cache_dir(), max_bytes=VIDEO_WAVE_CACHE_MAX_BYTES
    )


def clear_media_caches() -> int:
    removed = 0
    for root in (audio_cache_dir(), video_wave_cache_dir()):
        for path in _cache_files(root):
            try:
                size = int(path.stat().st_size)
                path.unlink(missing_ok=True)
                removed += size
            except OSError:
                pass
    return removed
