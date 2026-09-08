from __future__ import annotations

import os
from pathlib import Path

import pytest

from cueplayer.media.cache_management import (
    clear_media_caches,
    media_cache_stats,
    prune_cache_dir,
)


def test_prune_cache_dir_removes_oldest_first(tmp_path: Path) -> None:
    old = tmp_path / "old.npz"
    new = tmp_path / "new.npz"
    old.write_bytes(b"a" * 20)
    new.write_bytes(b"b" * 20)
    os.utime(old, (1, 1))
    os.utime(new, (2, 2))

    removed = prune_cache_dir(tmp_path, max_bytes=20)

    assert removed == 20
    assert not old.exists()
    assert new.exists()


def test_stats_and_clear_cover_both_media_cache_folders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "audio"
    video = tmp_path / "video"
    audio.mkdir()
    video.mkdir()
    (audio / "a.npz").write_bytes(b"a" * 11)
    (video / "v.npz").write_bytes(b"v" * 13)
    monkeypatch.setenv("CUEPLAYER_AUDIO_CACHE", str(audio))
    monkeypatch.setenv("CUEPLAYER_VIDEO_WAVE_CACHE", str(video))

    stats = media_cache_stats()
    assert stats.audio_bytes == 11
    assert stats.video_wave_bytes == 13
    assert stats.file_count == 2
    assert clear_media_caches() == 24
    assert list(audio.iterdir()) == []
    assert list(video.iterdir()) == []
