"""In-process Event Bus — infrastructure only (Sprint 3 Task 3).

Why this exists
---------------
CuePlayer currently fans out chrome / session notifications through a mix of
MainWindow private helpers, Qt signals, and direct cross-widget calls. An
explicit bus gives a typed, testable seam for **future** publish/subscribe
without growing MainWindow further.

Problems it is intended to solve (eventually, after adoption tasks)
-------------------------------------------------------------------
- Decouple publishers (services) from concrete UI refresh call sites.
- Allow multiple remote / UI clients to observe the same domain-ish events.
- Make notification contracts unit-testable without constructing MainWindow.

Problems it intentionally does NOT solve yet
--------------------------------------------
- Playback clock / playhead (``AudioEngine`` remains sole sample clock).
- Async / queued / cross-thread delivery (callers stay on the UI thread).
- Sticky / replay / history of events.
- Priorities or ordered topic graphs.
- Networking / Web Remote protocol.
- Replacing Qt widget signals for local widget wiring.
- Migrating PlaybackService / ShowSessionService / ProjectService /
  SettingsService (adoption is a later sprint task).

API (minimal)
-------------
- ``subscribe(event_type, handler)``
- ``unsubscribe(event_type, handler)``
- ``publish(event)``
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable, TypeVar

EventT = TypeVar("EventT")


class EventBus:
    """Synchronous, in-process pub/sub keyed by event **type**.

    Handlers run immediately on ``publish``, in subscription order, on the
    calling thread. Exceptions from a handler propagate and stop later
    handlers for that publish.
    """

    def __init__(self) -> None:
        self._handlers: dict[type, list[Callable[..., None]]] = defaultdict(list)

    def subscribe(
        self, event_type: type[EventT], handler: Callable[[EventT], None]
    ) -> None:
        """Register ``handler`` for instances of ``event_type``.

        Duplicate subscription of the same handler object is ignored.
        """
        bucket = self._handlers[event_type]
        if handler not in bucket:
            bucket.append(handler)

    def unsubscribe(
        self, event_type: type[EventT], handler: Callable[[EventT], None]
    ) -> None:
        """Remove ``handler`` for ``event_type`` if present (no-op otherwise)."""
        bucket = self._handlers.get(event_type)
        if not bucket:
            return
        try:
            bucket.remove(handler)
        except ValueError:
            return
        if not bucket:
            del self._handlers[event_type]

    def publish(self, event: object) -> None:
        """Deliver ``event`` to handlers registered for ``type(event)``.

        Exact type match only (no inheritance walk) — keeps dispatch simple
        and predictable until an adoption task needs otherwise.
        """
        handlers = list(self._handlers.get(type(event), ()))
        for handler in handlers:
            handler(event)
