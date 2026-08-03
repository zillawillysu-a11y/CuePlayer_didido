"""Project document repository — thin façade over existing persistence.

Not a generic repository framework. Only project JSON load/save/backup.
Schema migrations and UTF-8 rules stay inside ``cueplayer.persistence``.
"""

from __future__ import annotations

from pathlib import Path

from cueplayer.domain.models import Project
from cueplayer.persistence.backup import DEFAULT_KEEP, create_backup_before_save
from cueplayer.persistence.project_store import load_project, save_project

__all__ = ["ProjectRepository", "DEFAULT_KEEP"]


class ProjectRepository:
    """
    File-backed project storage.

    ``MainWindow`` → ``ProjectService`` → **this** → ``persistence.*``
    """

    def load(self, path: Path) -> Project:
        """Load a project JSON document (Unicode paths; migrations applied)."""
        return load_project(Path(path))

    def save(self, project: Project, path: Path) -> None:
        """Write ``project`` to ``path`` as UTF-8 JSON."""
        save_project(project, Path(path))

    def autosave(self, project: Project, path: Path) -> None:
        """
        Overwrite the project file for auto-save.

        Same persistence path as ``save`` — quiet/UI policy lives in the service.
        Callers are expected to run ``backup`` first when replacing an existing file.
        """
        self.save(project, path)

    def backup(self, path: Path, *, keep: int = DEFAULT_KEEP) -> Path | None:
        """
        Copy the on-disk project into ``.cueplayer_backups/`` before overwrite.

        Returns the backup path, or ``None`` when the file does not exist yet.
        May raise ``OSError`` on I/O failure.
        """
        return create_backup_before_save(Path(path), keep=keep)

    def exists(self, path: Path) -> bool:
        """True when ``path`` is an existing file."""
        return Path(path).is_file()
