"""Collect a portable project bundle: project JSON at root + Media/ copies."""

from __future__ import annotations

import shutil
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

from cueplayer.domain.models import Project
from cueplayer.persistence.media_paths import path_exists
from cueplayer.persistence.project_store import save_project

DEFAULT_MEDIA_SUBDIR = "Media"


@dataclass
class BundleResult:
    project_path: Path
    media_dir: Path
    copied: list[tuple[Path, Path]] = field(default_factory=list)
    reused: list[tuple[Path, Path]] = field(default_factory=list)
    missing: list[Path] = field(default_factory=list)
    renamed: list[tuple[Path, str]] = field(default_factory=list)


def _unique_basename(media_dir: Path, basename: str, used: set[str]) -> str:
    """Pick a free name under media_dir; avoid case-insensitive collisions."""
    key = basename.casefold()
    if key not in used and not (media_dir / basename).exists():
        used.add(key)
        return basename
    stem = Path(basename).stem
    suffix = Path(basename).suffix
    n = 2
    while True:
        candidate = f"{stem}_{n}{suffix}"
        ckey = candidate.casefold()
        if ckey not in used and not (media_dir / candidate).exists():
            used.add(ckey)
            return candidate
        n += 1


def iter_media_paths(project: Project) -> list[Path]:
    """Unique media paths referenced by the project (order preserved)."""
    seen: set[str] = set()
    paths: list[Path] = []
    for song in project.songs:
        for track in song.audio_tracks:
            key = str(Path(track.path))
            if key not in seen:
                seen.add(key)
                paths.append(Path(track.path))
        for clip in song.video_clips:
            key = str(Path(clip.path))
            if key not in seen:
                seen.add(key)
                paths.append(Path(clip.path))
    return paths


def collect_project_bundle(
    project: Project,
    dest_dir: Path,
    *,
    project_filename: str,
    media_subdir: str = DEFAULT_MEDIA_SUBDIR,
) -> BundleResult:
    """
    Copy all reachable media into ``dest_dir / media_subdir`` and write the
    project JSON at ``dest_dir / project_filename`` with relative paths.

    Layout::

        dest_dir/
          show.cueplayer.json
          Media/
            song.wav
            clip.mp4

    Same source file referenced multiple times is only copied once.
    Basename collisions from different sources get ``_2``, ``_3``, … suffixes.
    Missing sources are listed and left pointing at the old path (still absolute).
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    media_dir = dest_dir / (media_subdir.strip() or DEFAULT_MEDIA_SUBDIR)
    media_dir.mkdir(parents=True, exist_ok=True)

    bundled = deepcopy(project)
    result = BundleResult(
        project_path=dest_dir / project_filename,
        media_dir=media_dir,
    )

    # source resolve key → destination path inside Media/
    source_map: dict[str, Path] = {}
    used_names: set[str] = set()

    def _place(source: Path) -> Path | None:
        try:
            resolved = source.expanduser().resolve()
        except OSError:
            resolved = source.expanduser().absolute()
        key = str(resolved)
        if key in source_map:
            result.reused.append((resolved, source_map[key]))
            return source_map[key]
        if not path_exists(resolved):
            result.missing.append(source)
            return None
        basename = _unique_basename(media_dir, resolved.name, used_names)
        if basename != resolved.name:
            result.renamed.append((resolved, basename))
        dest = media_dir / basename
        shutil.copy2(resolved, dest)
        source_map[key] = dest
        result.copied.append((resolved, dest))
        return dest

    for song in bundled.songs:
        for track in song.audio_tracks:
            placed = _place(Path(track.path))
            if placed is not None:
                track.path = placed
        for clip in song.video_clips:
            placed = _place(Path(clip.path))
            if placed is not None:
                clip.path = placed

    save_project(bundled, result.project_path)
    return result
