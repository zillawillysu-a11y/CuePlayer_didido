"""Project JSON persistence boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from cueplayer.domain.models import Project


@runtime_checkable
class ProjectStore(Protocol):
    """Load/save UTF-8 project documents (schema migrations stay in the adapter)."""

    def load(self, path: Path) -> Project:
        """Load a project from ``path`` (Unicode paths required)."""
        ...

    def save(self, project: Project, path: Path) -> None:
        """Write ``project`` to ``path`` as UTF-8 JSON."""
        ...
