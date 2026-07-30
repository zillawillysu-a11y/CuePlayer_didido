"""Bundle path remap should keep in-memory LTC badge cache lit."""

from __future__ import annotations

from pathlib import Path

from cueplayer.media.audio_disk_cache import audio_cache_key, save_ltc_channel
from cueplayer.persistence.project_bundle import BundleResult
from cueplayer.ui.main_window import MainWindow


def test_remount_caches_after_bundle_keeps_ltc(
    tmp_path: Path, monkeypatch
) -> None:
    import cueplayer.media.audio_disk_cache as mod

    monkeypatch.setattr(mod, "_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(mod, "_LTC_CACHE_FILE", tmp_path / "cache" / "ltc_channels.json")

    src = tmp_path / "old" / "曲.wav"
    dest = tmp_path / "bundle" / "Media" / "_Unfiled" / "曲.wav"
    src.parent.mkdir(parents=True)
    dest.parent.mkdir(parents=True)
    payload = b"RIFF" + b"\x00" * 64
    src.write_bytes(payload)
    dest.write_bytes(payload)

    old_key = audio_cache_key(src)
    assert old_key is not None
    save_ltc_channel(old_key, 0)

    class _Host:
        def __init__(self) -> None:
            self._audio_ltc_cache = {old_key: 0}
            self._audio_buffer_cache: dict = {}

        def _audio_cache_key(self, path: Path):
            return audio_cache_key(path)

    host = _Host()
    result = BundleResult(
        project_path=tmp_path / "bundle" / "show.cueplayer.json",
        media_dir=tmp_path / "bundle" / "Media",
        copied=[(src, dest)],
    )
    MainWindow._remount_caches_after_bundle(host, result)  # type: ignore[arg-type]

    new_key = audio_cache_key(dest)
    assert new_key is not None
    assert host._audio_ltc_cache.get(new_key) == 0
