"""Keep Media/ folders aligned with Setlist folders (Bundle + live sync)."""

from __future__ import annotations

import shutil
from pathlib import Path

from cueplayer.domain.models import Project, Song
from cueplayer.media.audio_disk_cache import adopt_caches_for_path
from cueplayer.persistence.media_paths import path_exists, project_root_for

DEFAULT_MEDIA_SUBDIR = "Media"
UNFILED_FOLDER = "_Unfiled"
_INVALID_FOLDER_CHARS = '<>:"/\\|?*'


def safe_folder_name(name: str) -> str:
    """Filesystem-safe folder name (Unicode OK; strip Windows-illegal chars)."""
    text = (name or "").strip() or UNFILED_FOLDER
    for ch in _INVALID_FOLDER_CHARS:
        text = text.replace(ch, "_")
    text = text.rstrip(". ")
    return text or UNFILED_FOLDER


def media_root(project_file: Path | None, *, media_subdir: str = DEFAULT_MEDIA_SUBDIR) -> Path | None:
    root = project_root_for(project_file)
    if root is None:
        return None
    return root / (media_subdir.strip() or DEFAULT_MEDIA_SUBDIR)


def category_folder_name(project: Project, category_id: str | None) -> str:
    if not category_id:
        return UNFILED_FOLDER
    cat = project.setlist_category_by_id(category_id)
    if cat is None:
        return UNFILED_FOLDER
    return safe_folder_name(cat.name)


def safe_song_folder_name(name: str) -> str:
    """Filesystem-safe song subfolder under a Setlist Media folder."""
    return safe_folder_name(name or "Song")


def song_media_rel_folder(project: Project, song: Song) -> str:
    """
    Relative folder under Media/ for a song: ``<SetlistFolder>/<SongName>``.

    Uncategorized songs use ``_Unfiled/<SongName>``.
    """
    folder = category_folder_name(project, song.category_id)
    return f"{folder}/{safe_song_folder_name(song.name)}"


def path_under_media(path: Path, media_dir: Path) -> bool:
    try:
        path.resolve().relative_to(media_dir.resolve())
        return True
    except (ValueError, OSError):
        return False


def unique_dest(folder: Path, basename: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    candidate = folder / basename
    if not candidate.exists():
        return candidate
    stem = Path(basename).stem
    suffix = Path(basename).suffix
    n = 2
    while True:
        candidate = folder / f"{stem}_{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def locate_under_media(path: Path, media_dir: Path) -> Path | None:
    """
    Resolve a media path that should live under ``media_dir``.

    Prefer the given path when it exists and is under Media/. If the path is
    stale (e.g. after undo of a folder move), uniquely match by basename.
    """
    path = Path(path)
    if path_exists(path) and path_under_media(path, media_dir):
        try:
            return path.resolve()
        except OSError:
            return path
    if not media_dir.is_dir():
        return None
    basename = path.name
    if not basename:
        return None
    matches = [p for p in media_dir.rglob(basename) if p.is_file()]
    if len(matches) == 1:
        try:
            return matches[0].resolve()
        except OSError:
            return matches[0]
    return None


def relocate_path_into_folder(path: Path, dest_folder: Path) -> tuple[Path | None, bool]:
    """
    Move ``path`` into ``dest_folder`` when needed.

    Returns ``(final_path, did_move)``. Adopts waveform/LTC caches after a move.
    """
    path = Path(path)
    if not path_exists(path):
        return None, False
    dest_folder = Path(dest_folder)
    dest_folder.mkdir(parents=True, exist_ok=True)
    try:
        if path.resolve().parent == dest_folder.resolve():
            return path.resolve(), False
    except OSError:
        if path.parent == dest_folder:
            return path, False

    dest = unique_dest(dest_folder, path.name)
    former = path
    try:
        shutil.move(str(path), str(dest))
    except OSError:
        return None, False
    adopt_caches_for_path(dest, former_path=former)
    try:
        return dest.resolve(), True
    except OSError:
        return dest, True


def _apply_relocated_path(holder_path: Path, new_path: Path, *, did_move: bool) -> int:
    """Update a Path field; return 1 if the file moved or the stored path changed."""
    changed = did_move
    try:
        if Path(holder_path).resolve() != Path(new_path).resolve():
            changed = True
    except OSError:
        if Path(holder_path) != Path(new_path):
            changed = True
    return 1 if changed else 0


def path_under_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def locate_project_media_file(
    path: Path, *, media_dir: Path, project_root: Path
) -> Path | None:
    """Find a file under Media/ or elsewhere under the project root."""
    found = locate_under_media(path, media_dir)
    if found is not None:
        return found
    path = Path(path)
    if path_exists(path) and path_under_root(path, project_root):
        try:
            return path.resolve()
        except OSError:
            return path
    return None


def sync_song_media_to_setlist_folder(
    project: Project,
    song: Song,
    *,
    project_file: Path | None,
    media_subdir: str = DEFAULT_MEDIA_SUBDIR,
) -> int:
    """
    If song media lives under the project folder, move it into
    ``Media/<SetlistFolder>/<SongName>/``.

    Prefers files already inside ``Media/``. Also relocates files that sit
    elsewhere under the project root (legacy flat layout). External absolute
    paths outside the project folder are left alone. Returns how many files
    were moved or whose stored path was rewritten.
    """
    root = project_root_for(project_file)
    if root is None:
        return 0
    media_dir = root / (media_subdir.strip() or DEFAULT_MEDIA_SUBDIR)
    media_dir.mkdir(parents=True, exist_ok=True)
    dest_folder = media_dir / song_media_rel_folder(project, song)
    updated = 0
    for track in song.audio_tracks:
        former = Path(track.path)
        src = locate_project_media_file(former, media_dir=media_dir, project_root=root)
        if src is None:
            continue
        new_path, did_move = relocate_path_into_folder(src, dest_folder)
        if new_path is None:
            continue
        n = _apply_relocated_path(former, new_path, did_move=did_move)
        track.path = new_path
        updated += n
    for clip in song.video_clips:
        former = Path(clip.path)
        src = locate_project_media_file(former, media_dir=media_dir, project_root=root)
        if src is None:
            continue
        new_path, did_move = relocate_path_into_folder(src, dest_folder)
        if new_path is None:
            continue
        n = _apply_relocated_path(former, new_path, did_move=did_move)
        clip.path = new_path
        updated += n
    return updated


def sync_all_songs_media_to_setlist_folders(
    project: Project,
    *,
    project_file: Path | None,
    media_subdir: str = DEFAULT_MEDIA_SUBDIR,
) -> int:
    """Reconcile every song's Media/ files with its current Setlist folder."""
    total = 0
    for song in project.songs:
        total += sync_song_media_to_setlist_folder(
            project,
            song,
            project_file=project_file,
            media_subdir=media_subdir,
        )
    return total


def sync_rename_setlist_media_folder(
    project: Project,
    *,
    project_file: Path | None,
    old_name: str,
    new_name: str,
    media_subdir: str = DEFAULT_MEDIA_SUBDIR,
) -> int:
    """
    Rename ``Media/<old>`` → ``Media/<new>`` then rewrite project paths.

    Returns number of media paths updated. No-op if the old folder is missing
    or the new name already exists as a different directory. Path rewrite uses
    basename locate so undo/redo of the rename stays recoverable.
    """
    media_dir = media_root(project_file, media_subdir=media_subdir)
    if media_dir is None:
        return 0
    old_folder = media_dir / safe_folder_name(old_name)
    new_folder = media_dir / safe_folder_name(new_name)
    if old_folder == new_folder:
        return 0
    if not old_folder.is_dir():
        return 0
    if new_folder.exists():
        return 0
    try:
        old_folder.rename(new_folder)
    except OSError:
        return 0
    return sync_all_songs_media_to_setlist_folders(
        project,
        project_file=project_file,
        media_subdir=media_subdir,
    )
