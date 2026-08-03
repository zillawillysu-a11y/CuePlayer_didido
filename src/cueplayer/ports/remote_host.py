"""Web Remote host boundary.

Web Remote must eventually talk only to this surface — never MainWindow
private ``_`` attributes (see ``docs/ARCHITECTURE_REVIEW.md``).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from cueplayer.domain.models import Project, Song

from cueplayer.ports.clock import PlaybackClock


@runtime_checkable
class RemoteHost(Protocol):
    """Public host API exposed to the LAN Web Remote bridge."""

    def get_playback_clock(self) -> PlaybackClock:
        """Return the master sample clock (AudioEngine today)."""
        ...

    def get_project(self) -> Project | None:
        """Active project, if any."""
        ...

    def get_current_song(self) -> Song | None:
        """Song currently on the timeline / engine."""
        ...
