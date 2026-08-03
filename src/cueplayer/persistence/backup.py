"""Timestamped project backups beside the project file (Unicode-safe).

Layout::

    演唱會.cueplayer.json
    .cueplayer_backups/
      演唱會_20260727_053012.cueplayer.json
      …

Every successful Save / Auto-Save copies the *previous* on-disk file into
``.cueplayer_backups/`` before overwriting, then prunes older copies so the
folder stays bounded. Chinese project stems are preserved as-is.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

BACKUP_DIR_NAME = ".cueplayer_backups"
DEFAULT_KEEP = 30


def project_stem(project_path: Path) -> str:
    """Strip ``.cueplayer.json`` (or plain ``.json``) from the project filename."""
    name = project_path.name
    lower = name.lower()
    if lower.endswith(".cueplayer.json"):
        return name[: -len(".cueplayer.json")]
    if lower.endswith(".json"):
        return name[: -len(".json")]
    return project_path.stem


def backup_directory(project_path: Path) -> Path:
    return project_path.parent / BACKUP_DIR_NAME


def backup_path_for(project_path: Path, when: datetime | None = None) -> Path:
    when = when or datetime.now(timezone.utc).astimezone()
    stamp = when.strftime("%Y%m%d_%H%M%S")
    return backup_directory(project_path) / f"{project_stem(project_path)}_{stamp}.cueplayer.json"


def create_backup_before_save(
    project_path: Path, *, keep: int = DEFAULT_KEEP
) -> Path | None:
    """
    Copy the existing project file into ``.cueplayer_backups/`` before overwrite.

    Returns the new backup path, or ``None`` when there is nothing to back up
    yet (first Save As). Always Unicode-safe via ``pathlib`` / ``shutil``.
    """
    if not project_path.is_file():
        return None
    dest = backup_path_for(project_path)
    # Avoid colliding with a same-second prior backup.
    if dest.exists():
        stem = dest.name[: -len(".cueplayer.json")]
        n = 1
        while True:
            candidate = dest.with_name(f"{stem}_{n}.cueplayer.json")
            if not candidate.exists():
                dest = candidate
                break
            n += 1
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(project_path, dest)
    prune_backups(project_path, keep=keep)
    return dest


def list_backups(project_path: Path) -> list[Path]:
    """Return backups for this project stem, newest first."""
    directory = backup_directory(project_path)
    if not directory.is_dir():
        return []
    prefix = f"{project_stem(project_path)}_"
    matches = [
        path
        for path in directory.iterdir()
        if path.is_file()
        and path.name.startswith(prefix)
        and path.name.lower().endswith(".cueplayer.json")
    ]
    return sorted(matches, key=lambda path: path.name, reverse=True)


def prune_backups(project_path: Path, *, keep: int = DEFAULT_KEEP) -> int:
    """Delete oldest backups beyond ``keep``. Returns how many were removed."""
    keep_n = max(0, int(keep))
    removed = 0
    for stale in list_backups(project_path)[keep_n:]:
        try:
            stale.unlink()
            removed += 1
        except OSError:
            pass
    return removed
