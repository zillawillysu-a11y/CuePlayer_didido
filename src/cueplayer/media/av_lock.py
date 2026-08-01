"""Per-path locks for PyAV / FFmpeg native calls.

Concurrent ``av.open`` / seek / decode on the *same* media file from multiple
threads (playback preview, scrub-cache preload, video-clip waveform workers)
can hard-crash on some FFmpeg builds. Serialize native access per resolved path.
"""

from __future__ import annotations

import threading
from pathlib import Path

_guard = threading.Lock()
_locks: dict[str, threading.RLock] = {}


def _path_key(path: Path | str) -> str:
    try:
        return str(Path(path).resolve())
    except OSError:
        return str(Path(path))


def av_path_lock(path: Path | str) -> threading.RLock:
    key = _path_key(path)
    with _guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _locks[key] = lock
        return lock
