"""grandMA show export boundary (MA2 / MA3 adapters).

Concrete exporters live under ``cueplayer.exporters``; this port is the
stable method application code should call later via ``ExportService``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, Sequence, runtime_checkable


@runtime_checkable
class ShowExporter(Protocol):
    """Export one or more song plans into a console import directory."""

    def export_show_to_directory(
        self,
        plans: Sequence[Any],
        directory: Path,
    ) -> dict[str, Path]:
        """
        Write Sequence/Timecode (and install Plugin/Macro when full export).

        ``plans`` are ``SongExportPlan`` instances from exporters.common;
        typed as ``Any`` here so ports do not import the exporters package.
        """
        ...
