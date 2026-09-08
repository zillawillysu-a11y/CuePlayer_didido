"""Find and safely quarantine project media that has no live project reference."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from cueplayer.domain.models import Project
from cueplayer.persistence.media_layout import media_root
from cueplayer.persistence.media_paths import project_root_for

MEDIA_SUFFIXES = frozenset(
    {
        ".wav", ".wave", ".flac", ".ogg", ".mp3", ".aif", ".aiff", ".m4a",
        ".aac", ".wma", ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v",
        ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff",
    }
)


@dataclass(frozen=True)
class UnusedMediaFile:
    path: Path
    relative_path: Path
    size_bytes: int


@dataclass(frozen=True)
class UnusedMediaCleanupResult:
    quarantine_dir: Path
    moved_files: tuple[Path, ...]
    moved_bytes: int


def _path_key(path: Path) -> str:
    try:
        return str(path.resolve()).casefold()
    except OSError:
        return str(path.absolute()).casefold()


def referenced_media_paths(project: Project, *, project_file: Path) -> set[str]:
    """Return normalized paths referenced by every persisted media holder."""
    root = project_root_for(project_file)
    if root is None:
        return set()

    def resolved(path: Path) -> Path:
        candidate = Path(path)
        return candidate if candidate.is_absolute() else root / candidate

    used: set[str] = set()
    for song in project.songs:
        for track in song.audio_tracks:
            used.add(_path_key(resolved(track.path)))
        for variant in song.variants:
            if variant.has_resolvable_path():
                used.add(_path_key(resolved(variant.path)))
        for clip in song.video_clips:
            used.add(_path_key(resolved(clip.path)))
    return used


def find_unused_media(project: Project, *, project_file: Path) -> list[UnusedMediaFile]:
    """List unreferenced media files under this project's Media directory."""
    media_dir = media_root(project_file)
    if media_dir is None or not media_dir.is_dir():
        return []
    used = referenced_media_paths(project, project_file=project_file)
    unused: list[UnusedMediaFile] = []
    for path in media_dir.rglob("*"):
        if not path.is_file() or path.suffix.casefold() not in MEDIA_SUFFIXES:
            continue
        if _path_key(path) in used:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        unused.append(
            UnusedMediaFile(
                path=path,
                relative_path=path.relative_to(media_dir),
                size_bytes=max(0, int(size)),
            )
        )
    return sorted(unused, key=lambda item: str(item.relative_path).casefold())


def quarantine_unused_media(
    files: list[UnusedMediaFile],
    *,
    project_file: Path,
    now: datetime | None = None,
) -> UnusedMediaCleanupResult:
    """Move an already-reviewed unused-media list into a recoverable folder."""
    root = project_root_for(project_file)
    media_dir = media_root(project_file)
    if root is None or media_dir is None:
        raise ValueError("Save the project before cleaning unused media.")
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    quarantine = root / ".cueplayer_trash" / f"Unused Media {stamp}"
    suffix = 2
    while quarantine.exists():
        quarantine = root / ".cueplayer_trash" / f"Unused Media {stamp}_{suffix}"
        suffix += 1

    moved: list[Path] = []
    moved_bytes = 0
    for item in files:
        source = item.path.resolve()
        try:
            relative = source.relative_to(media_dir.resolve())
        except ValueError as exc:
            raise ValueError(f"Refusing to move a file outside Media: {source}") from exc
        if not source.is_file():
            continue
        destination = quarantine / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        moved.append(destination)
        moved_bytes += item.size_bytes

    # Leave unrelated folders alone; only prune now-empty parents below Media.
    parents = sorted(
        {item.path.parent for item in files},
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for folder in parents:
        try:
            if folder.resolve() == media_dir.resolve() or any(folder.iterdir()):
                continue
            folder.rmdir()
        except OSError:
            continue
    return UnusedMediaCleanupResult(quarantine, tuple(moved), moved_bytes)
