"""Shared in-process infrastructure (non-domain, non-UI).

``core`` holds cross-cutting primitives that application / adapters / ui may
depend on without importing each other. Keep this package tiny and free of
Qt, networking, and playback-clock semantics.
"""

from __future__ import annotations

from cueplayer.core.event_bus import EventBus

__all__ = ["EventBus"]
