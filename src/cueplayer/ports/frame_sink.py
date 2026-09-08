"""Decoded video frame consumer boundary.

Preview, Clean Output, NDI, and Web Remote preview all act as sinks on the
single shared decode path (no second video clock).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class FrameSink(Protocol):
    """Accept one RGB frame from the shared video sync path."""

    def push_frame(self, frame: Any | None) -> None:
        """Display or forward ``frame`` (``None`` clears / holds last policy)."""
        ...
