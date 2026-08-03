"""Active-song session / refresh boundary.

Coordinates attaching one ``Song`` to clock, video sync, timeline, and
monitor without missing a refresh (shared mutable Song risk).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from cueplayer.domain.models import Song


@runtime_checkable
class SongSession(Protocol):
    """Activate a song and refresh dependents after domain mutations."""

    def activate_song(self, song: Song | None) -> None:
        """Make ``song`` current on clock / video / UI surfaces."""
        ...

    def refresh_after_mutation(self) -> None:
        """Re-sync engine clips, video sync, and cue lists after Song edits."""
        ...
