"""Collect a portable project bundle: project JSON at root + Media/<Folder>/."""

from __future__ import annotations

import shutil
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

from cueplayer.domain.models import Project
from cueplayer.media.audio_disk_cache import clone_caches_for_copied_file
from cueplayer.persistence.media_layout import (
    DEFAULT_MEDIA_SUBDIR,
    UNFILED_FOLDER,
    category_folder_name,
    safe_folder_name,
    unique_dest,
)
from cueplayer.persistence.media_paths import path_exists
from cueplayer.persistence.project_store import save_project


@dataclass
class BundleResult:
    project_path: Path
    media_dir: Path
    copied: list[tuple[Path, Path]] = field(default_factory=list)
    reused: list[tuple[Path, Path]] = field(default_factory=list)
    missing: list[Path] = field(default_factory=list)
    renamed: list[tuple[Path, str]] = field(default_factory=list)


def collect_project_bundle(
    project: Project,
    dest_dir: Path,
    *,
    project_filename: str,
    media_subdir: str = DEFAULT_MEDIA_SUBDIR,
) -> BundleResult:
    """
    Copy all reachable media into Setlist-mirrored folders and write the
    project JSON at ``dest_dir / project_filename`` with relative paths.

    Layout::

        dest_dir/
          show.cueplayer.json
          Media/
            Act1/
              song.wav
            _Unfiled/
              loose.wav

    Same source file referenced multiple times is only copied once (first
    song's folder wins). Basename collisions get ``_2``, ``_3``, … suffixes.
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

    # Ensure every category has a folder on disk (even if empty).
    for category in bundled.setlist_categories:
        (media_dir / safe_folder_name(category.name)).mkdir(parents=True, exist_ok=True)
    (media_dir / UNFILED_FOLDER).mkdir(parents=True, exist_ok=True)

    # source resolve key → destination path inside Media/
    source_map: dict[str, Path] = {}

    def _place(source: Path, *, folder_name: str) -> Path | None:
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
        dest_folder = media_dir / folder_name
        dest = unique_dest(dest_folder, resolved.name)
        if dest.name != resolved.name:
            result.renamed.append((resolved, dest.name))
        shutil.copy2(resolved, dest)
        clone_caches_for_copied_file(resolved, dest)
        source_map[key] = dest
        result.copied.append((resolved, dest))
        return dest

    for song in bundled.songs:
        folder_name = category_folder_name(bundled, song.category_id)
        for track in song.audio_tracks:
            placed = _place(Path(track.path), folder_name=folder_name)
            if placed is not None:
                track.path = placed
        for clip in song.video_clips:
            placed = _place(Path(clip.path), folder_name=folder_name)
            if placed is not None:
                clip.path = placed

    save_project(bundled, result.project_path)
    return result
