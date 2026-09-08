"""Portable media path storage (relative to project file when possible)."""

from __future__ import annotations

from pathlib import Path


def project_root_for(project_file: Path | None) -> Path | None:
    """Directory that contains the ``.cueplayer.json`` project file."""
    if project_file is None:
        return None
    return Path(project_file).expanduser().resolve().parent


def to_storage_path(path: Path | str, project_dir: Path | None) -> str:
    """
    Serialize a media path for the project JSON.

    Prefer a portable relative path (POSIX separators) when the file lives
    under the project directory so the whole folder can be moved/copied.
    Otherwise store an absolute path.
    """
    target = Path(path).expanduser()
    try:
        target = target.resolve()
    except OSError:
        target = target.absolute()

    root = Path(project_dir).expanduser().resolve() if project_dir is not None else None
    if root is not None:
        try:
            relative = target.relative_to(root)
            return relative.as_posix()
        except ValueError:
            pass
    return str(target)


def from_storage_path(value: str | Path, project_dir: Path | None) -> Path:
    """
    Resolve a stored media path.

    Relative paths are joined to the project directory. Absolute paths are
    returned as-is (still usable until the host layout changes).
    """
    raw = Path(value)
    if raw.is_absolute():
        return raw
    if project_dir is None:
        return raw
    root = Path(project_dir).expanduser().resolve()
    return (root / raw).resolve()


def path_exists(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False
