"""Background media job queue boundary.

Today MainWindow owns several ThreadPoolExecutors (load / prefetch /
LTC detect / BPM). This port is the future single submission surface.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class MediaJobQueue(Protocol):
    """Enqueue non-realtime media work off the UI / audio threads."""

    def submit_load_audio(self, path: Path) -> None:
        """Decode / cache primary song audio for playback."""
        ...

    def submit_prefetch_audio(self, path: Path) -> None:
        """Warm caches for a nearby / next song without blocking play."""
        ...

    def submit_detect_ltc(self, path: Path) -> None:
        """Detect which source channel carries striped LTC."""
        ...

    def submit_detect_bpm(self, path: Path) -> None:
        """Run BPM analysis for setlist / song metadata."""
        ...
