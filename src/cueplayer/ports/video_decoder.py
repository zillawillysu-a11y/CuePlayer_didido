"""Video frame decode boundary (no independent clock).

Implemented by media decoders consumed by ``VideoSyncController``.
Callers pass an explicit timeline time — never a free-running timer.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class VideoDecoderPort(Protocol):
    """Seek/decode a single RGB frame at an explicit song/source time."""

    def frame_at(self, seconds: float) -> Any | None:
        """Return an RGB24 ``(H, W, 3)`` array for ``seconds``, or ``None``."""
        ...

    def close(self) -> None:
        """Release native decoder resources."""
        ...
