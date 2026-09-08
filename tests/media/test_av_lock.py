"""Per-path PyAV lock prevents overlapping native decode on one file."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from cueplayer.media.av_lock import av_path_lock


def test_av_path_lock_serializes_same_path(tmp_path: Path) -> None:
    media = tmp_path / "clip.mov"
    media.write_bytes(b"x")
    active = 0
    peak = 0
    lock = threading.Lock()

    def _worker() -> None:
        nonlocal active, peak
        for _ in range(20):
            with av_path_lock(media):
                with lock:
                    active += 1
                    peak = max(peak, active)
                time.sleep(0.001)
                with lock:
                    active -= 1

    threads = [threading.Thread(target=_worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(2.0)
    assert peak == 1


def test_av_path_lock_allows_different_paths(tmp_path: Path) -> None:
    a = tmp_path / "a.mov"
    b = tmp_path / "b.mov"
    a.write_bytes(b"a")
    b.write_bytes(b"b")
    inside: list[str] = []
    gate = threading.Barrier(2, timeout=2.0)

    def _hold(path: Path, label: str) -> None:
        with av_path_lock(path):
            inside.append(label)
            gate.wait()
            time.sleep(0.02)
            inside.append(f"{label}-done")

    t1 = threading.Thread(target=_hold, args=(a, "a"))
    t2 = threading.Thread(target=_hold, args=(b, "b"))
    t1.start()
    t2.start()
    t1.join(2.0)
    t2.join(2.0)
    assert set(inside[:2]) == {"a", "b"}
