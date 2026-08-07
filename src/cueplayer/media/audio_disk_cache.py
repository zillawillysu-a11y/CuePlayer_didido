"""Persistent on-disk cache for decoded song audio and LTC detection results."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from cueplayer.media.audio_loader import AudioBuffer, PeakLevel, load_audio

_CACHE_DIR = Path(os.environ.get("CUEPLAYER_AUDIO_CACHE", Path.home() / ".cache" / "cueplayer" / "audio"))
_LTC_CACHE_FILE = _CACHE_DIR / "ltc_channels.json"


def audio_cache_key(path: Path) -> tuple[str, int, int] | None:
    try:
        resolved = path.resolve()
        stat = resolved.stat()
        return (str(resolved), int(stat.st_mtime_ns), int(stat.st_size))
    except OSError:
        return None


def _digest_for_key(key: tuple[str, int, int]) -> str:
    path_str, mtime_ns, size = key
    return hashlib.sha256(f"{path_str}\0{mtime_ns}\0{size}".encode("utf-8")).hexdigest()[:32]


def _cache_file(key: tuple[str, int, int]) -> Path:
    return _CACHE_DIR / f"{_digest_for_key(key)}.npz"


def _peaks_cache_file(key: tuple[str, int, int]) -> Path:
    return _CACHE_DIR / f"{_digest_for_key(key)}.peaks.npz"


def _standin_cache_file(cache_key: str) -> Path:
    digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:32]
    return _CACHE_DIR / f"standin_{digest}.npz"


# Compressing multi-hundred-MB float32 PCM is extremely slow and often never
# finishes before quit — long songs then re-decode every launch. Uncompressed
# npz writes much faster for large buffers.
_COMPRESS_PCM_MAX_BYTES = 32 * 1024 * 1024


def _peak_arrays(buffer: AudioBuffer) -> dict[str, np.ndarray]:
    arrays: dict[str, np.ndarray] = {
        "sample_rate": np.int32(buffer.sample_rate),
        "frames": np.int64(buffer.frames),
        "channels": np.int32(buffer.channels),
        "mono": buffer.mono.astype(np.float32, copy=False),
        "n_peaks": np.int32(len(buffer.peak_levels)),
    }
    for i, level in enumerate(buffer.peak_levels):
        arrays[f"peak_{i}_spb"] = np.int32(level.samples_per_bucket)
        arrays[f"peak_{i}_mins"] = level.mins.astype(np.float32, copy=False)
        arrays[f"peak_{i}_maxs"] = level.maxs.astype(np.float32, copy=False)
    return arrays


def _levels_from_npz(data: np.lib.npyio.NpzFile) -> list[PeakLevel]:
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
    return levels


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
            levels = _levels_from_npz(data)
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


def load_cached_waveform_peaks(path: Path) -> AudioBuffer | None:
    """Small peaks-only cache for instant Music-lane paint after restart.

    ``samples`` are zeros of the correct length so duration/UI work; the
    engine still needs a full PCM load (or full ``.npz`` hit) for sound.
    """
    key = audio_cache_key(path)
    if key is None:
        return None
    cache_path = _peaks_cache_file(key)
    if not cache_path.is_file():
        return None
    try:
        with np.load(cache_path, allow_pickle=False) as data:
            sample_rate = int(data["sample_rate"])
            frames = int(data["frames"])
            channels = max(1, int(data["channels"]))
            mono = np.asarray(data["mono"], dtype=np.float32)
            levels = _levels_from_npz(data)
        samples = np.zeros((max(1, frames), channels), dtype=np.float32)
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
    """Persist peaks (always) + full PCM (when possible) for next launch."""
    key = audio_cache_key(path)
    if key is None:
        return
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        return

    # Peaks sidecar first — tiny, so waveform survives even if PCM write fails.
    try:
        peaks_path = _peaks_cache_file(key)
        tmp_peaks = peaks_path.with_name(peaks_path.stem + ".tmp")
        np.savez(str(tmp_peaks), **_peak_arrays(buffer))
        Path(str(tmp_peaks) + ".npz").replace(peaks_path)
    except Exception:
        pass

    try:
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
        nbytes = int(buffer.samples.nbytes)
        if nbytes > _COMPRESS_PCM_MAX_BYTES:
            np.savez(str(tmp_base), **arrays)
        else:
            np.savez_compressed(str(tmp_base), **arrays)
        tmp_file = Path(str(tmp_base) + ".npz")
        tmp_file.replace(_cache_file(key))
    except Exception:
        pass
    finally:
        from cueplayer.media.cache_management import prune_media_caches

        prune_media_caches()


def load_audio_cached(
    path: Path,
    *,
    on_pcm_ready: Callable[[AudioBuffer], None] | None = None,
) -> AudioBuffer:
    """Disk cache hit when possible; otherwise decode from the media file.

    ``on_pcm_ready`` is forwarded on cold decode so playback can start before
    the peak pyramid finishes. Cache hits call it with the full buffer.
    """
    cached = load_cached_audio(path)
    if cached is not None:
        if on_pcm_ready is not None:
            on_pcm_ready(cached)
        return cached
    buffer = load_audio(path, on_pcm_ready=on_pcm_ready)
    save_cached_audio(path, buffer)
    return buffer


def load_cached_video_standin(cache_key: str) -> AudioBuffer | None:
    """Display-only Music-lane stand-in from video audio (peaks persisted).

    Full PCM is not stored — playback uses VideoAudioMixer; the Music lane
    only needs the peak pyramid. Zeroed ``samples`` keep duration/UI correct.
    """
    cache_path = _standin_cache_file(cache_key)
    if not cache_path.is_file():
        return None
    try:
        with np.load(cache_path, allow_pickle=False) as data:
            sample_rate = int(data["sample_rate"])
            frames = int(data["frames"]) if "frames" in data else int(
                np.asarray(data["mono"]).shape[0]
            )
            channels = max(1, int(data["channels"])) if "channels" in data else 1
            mono = np.asarray(data["mono"], dtype=np.float32)
            levels = _levels_from_npz(data)
            path_str = str(data["path"]) if "path" in data else ""
            # Legacy full-PCM standin files still load (samples present).
            if "samples" in data:
                samples = np.asarray(data["samples"], dtype=np.float32)
            else:
                samples = np.zeros((max(1, frames), channels), dtype=np.float32)
        return AudioBuffer(
            path=Path(path_str) if path_str else Path("standin"),
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


def save_cached_video_standin(cache_key: str, buffer: AudioBuffer) -> None:
    """Persist peaks-only stand-in (tiny) so long videos reopen without re-decode."""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path = _standin_cache_file(cache_key)
        arrays = _peak_arrays(buffer)
        arrays["path"] = np.asarray(str(buffer.path))
        tmp_base = cache_path.with_name(cache_path.stem + ".tmp")
        np.savez(str(tmp_base), **arrays)
        Path(str(tmp_base) + ".npz").replace(cache_path)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Persistent LTC detection results
# ---------------------------------------------------------------------------
# Stored as a single JSON file mapping cache-key → channel (0, 1, or -1=none).
# Key format: "<hex-digest>" (same SHA-256 used for the waveform .npz).

def _ltc_json_key(key: tuple[str, int, int]) -> str:
    path_str, mtime_ns, size = key
    return hashlib.sha256(f"{path_str}\0{mtime_ns}\0{size}".encode("utf-8")).hexdigest()[:32]


def _load_ltc_json() -> dict[str, Any]:
    if not _LTC_CACHE_FILE.is_file():
        return {}
    try:
        with _LTC_CACHE_FILE.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except Exception:  # noqa: BLE001
        pass
    return {}


def load_all_ltc_channels() -> dict[tuple[str, int, int], int | None]:
    """Return every persisted LTC result keyed by audio cache key.

    The caller is responsible for mapping these back to audio paths via
    ``audio_cache_key``.  Values: ``0`` = Left, ``1`` = Right, ``None`` = none.
    Values are keyed by their hex digest so songs on other drives still restore.
    """
    raw = _load_ltc_json()
    result: dict[tuple[str, int, int], int | None] = {}
    for jk, v in raw.items():
        # Stored as {"hex32": {"path": ..., "mtime": ..., "size": ..., "channel": ...}}
        if not isinstance(v, dict):
            continue
        try:
            key: tuple[str, int, int] = (str(v["path"]), int(v["mtime"]), int(v["size"]))
            raw_ch = v.get("channel")
            channel: int | None = None if raw_ch is None else int(raw_ch)
        except (KeyError, TypeError, ValueError):
            continue
        result[key] = channel
    return result


def save_ltc_channel(
    key: tuple[str, int, int], channel: int | None
) -> None:
    """Persist one LTC detection result to the JSON store."""
    from cueplayer.util.thread_priority import lower_background_thread_priority
    lower_background_thread_priority()
    jk = _ltc_json_key(key)
    path_str, mtime_ns, size = key
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        data = _load_ltc_json()
        data[jk] = {
            "path": path_str,
            "mtime": mtime_ns,
            "size": size,
            "channel": channel,
        }
        tmp = _LTC_CACHE_FILE.with_suffix(".tmp.json")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        tmp.replace(_LTC_CACHE_FILE)
    except OSError:
        pass


def clone_caches_for_copied_file(source: Path, dest: Path) -> bool:
    """
    After copying ``source`` → ``dest``, reuse waveform + LTC disk caches.

    Keys include the absolute path, so Bundle/Relink copies would otherwise
    force a full re-decode and LTC re-detect. ``shutil.copy2`` preserves
    mtime/size; only the path portion of the key changes.
    """
    import shutil

    source = Path(source)
    dest = Path(dest)
    old_key = audio_cache_key(source)
    new_key = audio_cache_key(dest)
    if old_key is None or new_key is None:
        return False
    if old_key == new_key:
        return True

    cloned_wave = False
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    old_npz = _cache_file(old_key)
    new_npz = _cache_file(new_key)
    if old_npz.is_file():
        try:
            if (
                not new_npz.is_file()
                or new_npz.stat().st_size != old_npz.stat().st_size
            ):
                shutil.copy2(old_npz, new_npz)
            cloned_wave = True
        except OSError:
            pass

    # Peaks sidecar — waveform paint after restart without waiting on full PCM.
    old_peaks = _peaks_cache_file(old_key)
    new_peaks = _peaks_cache_file(new_key)
    if old_peaks.is_file():
        try:
            if (
                not new_peaks.is_file()
                or new_peaks.stat().st_size != old_peaks.stat().st_size
            ):
                shutil.copy2(old_peaks, new_peaks)
            cloned_wave = True
        except OSError:
            pass

    rows = load_all_ltc_channels()
    if old_key in rows:
        try:
            save_ltc_channel(new_key, rows[old_key])
        except Exception:  # noqa: BLE001
            pass

    return cloned_wave


def adopt_caches_for_path(
    dest: Path, *, former_path: Path | None = None
) -> bool:
    """
    Reuse waveform/LTC caches for ``dest`` when the old file is gone.

    Looks up a donor cache entry by matching mtime+size (and optionally the
    former absolute path stored in the LTC JSON). Used by Relink after a
    move/copy where ``former_path`` no longer exists on disk.

    Also probes the waveform ``.npz`` keyed by ``(former_path, mtime, size)``
    even when no LTC row exists — otherwise Media moves re-decode waveforms.
    """
    import shutil

    dest = Path(dest)
    if former_path is not None and Path(former_path).is_file() and dest.is_file():
        return clone_caches_for_copied_file(Path(former_path), dest)

    new_key = audio_cache_key(dest)
    if new_key is None:
        return False

    _path, mtime_ns, size = new_key
    rows = load_all_ltc_channels()
    donor: tuple[str, int, int] | None = None
    channel: int | None | object = object()

    former_norm: str | None = None
    if former_path is not None:
        try:
            former_norm = str(Path(former_path).expanduser().resolve())
        except OSError:
            former_norm = str(Path(former_path))

    # Prefer exact former-path row, then mtime+size match.
    if former_norm is not None:
        for key, ch in rows.items():
            if key[0] == former_norm:
                donor = key
                channel = ch
                break
    if donor is None:
        for key, ch in rows.items():
            if key[1] == mtime_ns and key[2] == size:
                donor = key
                channel = ch
                break

    # Waveform-only: synthesize the old key from the known former path + new
    # file's mtime/size (move preserves those). Peaks sidecar alone is enough
    # for Music-lane paint after restart.
    if donor is None and former_norm is not None:
        synthetic = (former_norm, mtime_ns, size)
        if _cache_file(synthetic).is_file() or _peaks_cache_file(synthetic).is_file():
            donor = synthetic

    if donor is None:
        return False
    if donor == new_key:
        return True

    cloned_wave = False
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    old_npz = _cache_file(donor)
    new_npz = _cache_file(new_key)
    if old_npz.is_file():
        try:
            if (
                not new_npz.is_file()
                or new_npz.stat().st_size != old_npz.stat().st_size
            ):
                shutil.copy2(old_npz, new_npz)
            cloned_wave = True
        except OSError:
            pass

    old_peaks = _peaks_cache_file(donor)
    new_peaks = _peaks_cache_file(new_key)
    if old_peaks.is_file():
        try:
            if (
                not new_peaks.is_file()
                or new_peaks.stat().st_size != old_peaks.stat().st_size
            ):
                shutil.copy2(old_peaks, new_peaks)
            cloned_wave = True
        except OSError:
            pass

    if channel is not object:
        try:
            save_ltc_channel(new_key, channel)  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001
            pass

    return cloned_wave
