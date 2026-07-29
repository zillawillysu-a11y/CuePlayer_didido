"""Collect a portable project bundle: project JSON at root + Media/<Folder>/<Song>/."""

from __future__ import annotations

import shutil
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

from cueplayer.domain.models import Project
from cueplayer.media.audio_disk_cache import (
    adopt_caches_for_path,
    clone_caches_for_copied_file,
)
from cueplayer.persistence.media_layout import (
    DEFAULT_MEDIA_SUBDIR,
    UNFILED_FOLDER,
    path_under_media,
    prune_empty_dirs_under_media,
    safe_folder_name,
    song_media_rel_folder,
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
    moved: list[tuple[Path, Path]] = field(default_factory=list)
    missing: list[Path] = field(default_factory=list)
    renamed: list[tuple[Path, str]] = field(default_factory=list)
    # Top-level Setlist folder names that received at least one file.
    folders_used: list[str] = field(default_factory=list)


def _same_file_fingerprint(a: Path, b: Path) -> bool:
    """True when ``b`` can stand in for ``a`` (skip re-copy)."""
    import filecmp

    try:
        if int(a.stat().st_size) != int(b.stat().st_size):
            return False
    except OSError:
        return False
    try:
        return bool(filecmp.cmp(a, b, shallow=False))
    except OSError:
        return False


def collect_project_bundle(
    project: Project,
    dest_dir: Path,
    *,
    project_filename: str,
    media_subdir: str = DEFAULT_MEDIA_SUBDIR,
) -> BundleResult:
    """
    Copy / reuse media into Setlist-mirrored folders and write the project JSON
    at ``dest_dir / project_filename`` with relative paths.

    Incremental-friendly: files already under ``dest_dir/Media/`` are reused or
    moved into the correct ``<Folder>/<Song>/`` slot — not copied again. New
    external media is copied in. Safe to re-run on the same Bundle folder.

    Layout::

        dest_dir/
          show.cueplayer.json
          Media/
            Act1/
              SongA/
                song.wav
            _Unfiled/
              Loose/
                loose.wav
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

    # Ensure every Setlist category has a folder on disk (even if empty).
    for category in bundled.setlist_categories:
        (media_dir / safe_folder_name(category.name)).mkdir(parents=True, exist_ok=True)
    (media_dir / UNFILED_FOLDER).mkdir(parents=True, exist_ok=True)

    # source resolve key → destination path inside Media/
    source_map: dict[str, Path] = {}
    folders_used: set[str] = set()

    def _note_folder(rel_folder: str) -> None:
        top = rel_folder.split("/", 1)[0]
        if top:
            folders_used.add(top)

    def _place(source: Path, *, rel_folder: str) -> Path | None:
        try:
            resolved = source.expanduser().resolve()
        except OSError:
            resolved = source.expanduser().absolute()
        key = str(resolved)
        if key in source_map:
            result.reused.append((resolved, source_map[key]))
            return source_map[key]

        dest_folder = media_dir / rel_folder
        dest_folder.mkdir(parents=True, exist_ok=True)

        # Already inside this Bundle's Media/ — reuse or relocate, never re-copy.
        if path_exists(resolved) and path_under_media(resolved, media_dir):
            try:
                if resolved.parent.resolve() == dest_folder.resolve():
                    source_map[key] = resolved
                    result.reused.append((resolved, resolved))
                    _note_folder(rel_folder)
                    return resolved
            except OSError:
                if resolved.parent == dest_folder:
                    source_map[key] = resolved
                    result.reused.append((resolved, resolved))
                    _note_folder(rel_folder)
                    return resolved
            dest = unique_dest(dest_folder, resolved.name)
            try:
                if dest.resolve() == resolved.resolve():
                    source_map[key] = resolved
                    result.reused.append((resolved, resolved))
                    _note_folder(rel_folder)
                    return resolved
            except OSError:
                pass
            former = resolved
            try:
                shutil.move(str(resolved), str(dest))
            except OSError:
                result.missing.append(source)
                return None
            adopt_caches_for_path(dest, former_path=former)
            source_map[key] = dest
            # Remap under the new path so later refs to the old location reuse.
            try:
                source_map[str(dest.resolve())] = dest
            except OSError:
                source_map[str(dest)] = dest
            result.moved.append((former, dest))
            _note_folder(rel_folder)
            return dest

        if not path_exists(resolved):
            result.missing.append(source)
            return None

        # Incremental: identical file already sitting at the destination.
        candidate = dest_folder / resolved.name
        if candidate.is_file() and _same_file_fingerprint(resolved, candidate):
            try:
                dest = candidate.resolve()
            except OSError:
                dest = candidate
            # Dest may already exist from a prior Bundle — still clone caches so
            # opening the Bundle does not re-decode waveform / re-detect LTC.
            if dest != resolved:
                clone_caches_for_copied_file(resolved, dest)
            source_map[key] = dest
            result.reused.append((resolved, dest))
            _note_folder(rel_folder)
            return dest

        dest = unique_dest(dest_folder, resolved.name)
        if dest.name != resolved.name:
            result.renamed.append((resolved, dest.name))
        shutil.copy2(resolved, dest)
        clone_caches_for_copied_file(resolved, dest)
        source_map[key] = dest
        result.copied.append((resolved, dest))
        _note_folder(rel_folder)
        return dest

    for song in bundled.songs:
        rel_folder = song_media_rel_folder(bundled, song)
        for track in song.audio_tracks:
            placed = _place(Path(track.path), rel_folder=rel_folder)
            if placed is not None:
                track.path = placed
        for clip in song.video_clips:
            placed = _place(Path(clip.path), rel_folder=rel_folder)
            if placed is not None:
                clip.path = placed

    # Stable order: declared categories first, then _Unfiled, then any extras.
    ordered: list[str] = []
    for category in bundled.setlist_categories:
        name = safe_folder_name(category.name)
        if name in folders_used and name not in ordered:
            ordered.append(name)
    if UNFILED_FOLDER in folders_used:
        ordered.append(UNFILED_FOLDER)
    for name in sorted(folders_used):
        if name not in ordered:
            ordered.append(name)
    result.folders_used = ordered

    # Drop empty leftovers from Media-internal moves; keep declared Setlist stubs.
    preserve = {safe_folder_name(c.name) for c in bundled.setlist_categories}
    preserve.add(UNFILED_FOLDER)
    prune_empty_dirs_under_media(media_dir, preserve_names=preserve)

    save_project(bundled, result.project_path)
    return result
