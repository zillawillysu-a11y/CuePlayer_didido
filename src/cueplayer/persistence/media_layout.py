"""Keep Media/ folders aligned with Setlist folders (Save / Bundle)."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from cueplayer.domain.models import Project, Song
from cueplayer.media.audio_disk_cache import adopt_caches_for_path, clone_caches_for_copied_file
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
    # Older CuePlayer projects kept imported media directly under Media/.
    # A later Save may have persisted the intended Setlist/Song subfolder
    # before the physical move completed.  Once a duplicated song introduces
    # a second file with the same basename, the generic rglob fallback below
    # becomes ambiguous and used to leave the original song Unlinked.  The
    # legacy root file is deterministic and belongs to the original project,
    # so prefer it before falling back to a unique recursive match.
    legacy_root_file = media_dir / basename
    if legacy_root_file.is_file():
        try:
            return legacy_root_file.resolve()
        except OSError:
            return legacy_root_file
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


def _path_key(path: Path) -> str:
    try:
        return str(Path(path).expanduser().resolve())
    except OSError:
        return str(Path(path))


def rewrite_media_path_refs(
    project: Project,
    old_path: Path,
    new_path: Path,
) -> int:
    """
    Point every audio/video ref that matched ``old_path`` at ``new_path``.

    Needed when one Save relocate moves a file that several songs still listed
    at the old location — otherwise Bundle reports those songs as missing.
    """
    old_key = _path_key(old_path)
    # Also match the unresolved string form (relative JSON leftovers).
    old_raw = str(Path(old_path))
    try:
        final = Path(new_path).resolve()
    except OSError:
        final = Path(new_path)
    updated = 0
    for song in project.songs:
        for track in song.audio_tracks:
            cur = Path(track.path)
            if _path_key(cur) == old_key or str(cur) == old_raw:
                if Path(track.path) != final:
                    track.path = final
                    updated += 1
        for clip in song.video_clips:
            cur = Path(clip.path)
            if _path_key(cur) == old_key or str(cur) == old_raw:
                if Path(clip.path) != final:
                    clip.path = final
                    updated += 1
    return updated


def heal_stale_media_paths(
    project: Project,
    *,
    project_file: Path | None,
    media_subdir: str = DEFAULT_MEDIA_SUBDIR,
) -> int:
    """
    Repair broken paths when the file still lives uniquely under ``Media/``.

    Typical cause: Setlist folder Save moved ``Media/A/Song/x.wav`` →
    ``Media/B/Song/x.wav`` but another song (or an unsaved undo) still pointed
    at the old path. Returns how many refs were rewritten.
    """
    media_dir = media_root(project_file, media_subdir=media_subdir)
    if media_dir is None or not media_dir.is_dir():
        return 0
    updated = 0
    # Snapshot missing holders first — rewrite may fix several at once.
    missing: list[tuple[str, Path]] = []  # kind placeholder unused; just paths
    seen_missing: set[str] = set()
    for song in project.songs:
        for track in song.audio_tracks:
            former = Path(track.path)
            if path_exists(former):
                continue
            key = str(former)
            if key in seen_missing:
                continue
            seen_missing.add(key)
            missing.append(("audio", former))
        for clip in song.video_clips:
            former = Path(clip.path)
            if path_exists(former):
                continue
            key = str(former)
            if key in seen_missing:
                continue
            seen_missing.add(key)
            missing.append(("video", former))

    for _kind, former in missing:
        # May already have been healed via an earlier rewrite of the same basename.
        if path_exists(former):
            continue
        # Re-check holders still pointing here — path_exists on former is enough
        # only if something else restored the file; scan project for still-broken.
        still_used = False
        for song in project.songs:
            for track in song.audio_tracks:
                if str(Path(track.path)) == str(former) and not path_exists(Path(track.path)):
                    still_used = True
                    break
            if still_used:
                break
            for clip in song.video_clips:
                if str(Path(clip.path)) == str(former) and not path_exists(Path(clip.path)):
                    still_used = True
                    break
            if still_used:
                break
        if not still_used:
            continue
        found = locate_under_media(former, media_dir)
        if found is None:
            continue
        adopt_caches_for_path(found, former_path=former)
        updated += rewrite_media_path_refs(project, former, found)
    return updated


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
    shared_media_keys: set[str] | None = None,
) -> int:
    """
    If song media lives under the project folder, move it into
    ``Media/<SetlistFolder>/<SongName>/``.

    Prefers files already inside ``Media/``. Also relocates files that sit
    elsewhere under the project root (legacy flat layout). External absolute
    paths outside the project folder are left alone. Returns how many files
    were moved or whose stored path was rewritten.

    Files already under ``Media/`` that are shared by multiple songs
    (``shared_media_keys``) stay put so songs can keep pointing at one copy.
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
        try:
            src_key = str(src.resolve())
        except OSError:
            src_key = str(src)
        if (
            shared_media_keys is not None
            and src_key in shared_media_keys
            and path_under_media(src, media_dir)
        ):
            n = _apply_relocated_path(former, src, did_move=False)
            track.path = src
            updated += n
            continue
        new_path, did_move = relocate_path_into_folder(src, dest_folder)
        if new_path is None:
            continue
        n = _apply_relocated_path(former, new_path, did_move=did_move)
        track.path = new_path
        updated += n
        if did_move:
            # Other songs may still list the old path — keep them in sync.
            updated += rewrite_media_path_refs(project, src, new_path)
            updated += rewrite_media_path_refs(project, former, new_path)
    for clip in song.video_clips:
        former = Path(clip.path)
        src = locate_project_media_file(former, media_dir=media_dir, project_root=root)
        if src is None:
            continue
        try:
            src_key = str(src.resolve())
        except OSError:
            src_key = str(src)
        if (
            shared_media_keys is not None
            and src_key in shared_media_keys
            and path_under_media(src, media_dir)
        ):
            n = _apply_relocated_path(former, src, did_move=False)
            clip.path = src
            updated += n
            continue
        new_path, did_move = relocate_path_into_folder(src, dest_folder)
        if new_path is None:
            continue
        n = _apply_relocated_path(former, new_path, did_move=did_move)
        clip.path = new_path
        updated += n
        if did_move:
            updated += rewrite_media_path_refs(project, src, new_path)
            updated += rewrite_media_path_refs(project, former, new_path)
    return updated


def _shared_media_keys(
    project: Project, *, media_dir: Path
) -> set[str]:
    """Resolved Media/ paths referenced by more than one audio/video item."""
    counts: dict[str, int] = {}
    for song in project.songs:
        for track in song.audio_tracks:
            path = Path(track.path)
            if not path_exists(path) or not path_under_media(path, media_dir):
                continue
            try:
                key = str(path.resolve())
            except OSError:
                key = str(path)
            counts[key] = counts.get(key, 0) + 1
        for clip in song.video_clips:
            path = Path(clip.path)
            if not path_exists(path) or not path_under_media(path, media_dir):
                continue
            try:
                key = str(path.resolve())
            except OSError:
                key = str(path)
            counts[key] = counts.get(key, 0) + 1
    return {key for key, n in counts.items() if n > 1}


def prune_empty_dirs_under_media(
    media_dir: Path,
    *,
    preserve_names: set[str] | None = None,
) -> int:
    """
    Remove empty directories under ``Media/`` (bottom-up).

    Never deletes ``media_dir`` itself. Optional ``preserve_names`` keeps empty
    top-level Setlist stubs (e.g. category folders Bundle created on purpose).
    """
    media_dir = Path(media_dir)
    if not media_dir.is_dir():
        return 0
    preserve = {safe_folder_name(n) for n in (preserve_names or set())}
    removed = 0
    # Deepest paths first so parents become empty after children go.
    try:
        candidates = sorted(
            (p for p in media_dir.rglob("*") if p.is_dir()),
            key=lambda p: len(p.parts),
            reverse=True,
        )
    except OSError:
        return 0
    for folder in candidates:
        try:
            rel = folder.relative_to(media_dir)
        except ValueError:
            continue
        if len(rel.parts) == 1 and rel.parts[0] in preserve:
            continue
        try:
            if any(folder.iterdir()):
                continue
            folder.rmdir()
            removed += 1
        except OSError:
            continue
    return removed


def sync_all_songs_media_to_setlist_folders(
    project: Project,
    *,
    project_file: Path | None,
    media_subdir: str = DEFAULT_MEDIA_SUBDIR,
) -> int:
    """Reconcile every song's Media/ files with its current Setlist folder."""
    # Fix stale absolute paths left behind by earlier moves before rearranging.
    healed = heal_stale_media_paths(
        project, project_file=project_file, media_subdir=media_subdir
    )
    root = project_root_for(project_file)
    media_dir = (
        root / (media_subdir.strip() or DEFAULT_MEDIA_SUBDIR) if root is not None else None
    )
    shared: set[str] = set()
    if media_dir is not None:
        shared = _shared_media_keys(project, media_dir=media_dir)
    total = healed
    for song in project.songs:
        total += sync_song_media_to_setlist_folder(
            project,
            song,
            project_file=project_file,
            media_subdir=media_subdir,
            shared_media_keys=shared,
        )
    if media_dir is not None:
        prune_empty_dirs_under_media(media_dir)
    return total


@dataclass(frozen=True)
class ExternalMediaRef:
    """A media file that lives outside the project folder (not yet Bundled)."""

    song_id: str
    song_name: str
    kind: str  # "audio" | "video"
    item_id: str
    item_name: str
    path: Path

    @property
    def basename(self) -> str:
        return self.path.name


@dataclass
class IngestExternalResult:
    copied: list[tuple[Path, Path]] = field(default_factory=list)
    failed: list[Path] = field(default_factory=list)


def scan_external_media(
    project: Project,
    *,
    project_file: Path | None,
    media_subdir: str = DEFAULT_MEDIA_SUBDIR,
) -> list[ExternalMediaRef]:
    """
    List audio/video files that exist on disk but sit **outside** the project
    folder (typical Explorer drops from Downloads / another drive).

    Files already under the project root (including outside ``Media/``) are
    excluded — Save relocates those via ``sync_all_songs_media_to_setlist_folders``.
    """
    root = project_root_for(project_file)
    if root is None:
        return []
    media_dir = root / (media_subdir.strip() or DEFAULT_MEDIA_SUBDIR)
    found: list[ExternalMediaRef] = []
    seen: set[str] = set()

    def _consider(song: Song, *, kind: str, item_id: str, item_name: str, path: Path) -> None:
        if not path_exists(path):
            return
        try:
            key = str(path.resolve())
        except OSError:
            key = str(path)
        if key in seen:
            return
        if path_under_media(path, media_dir) or path_under_root(path, root):
            return
        seen.add(key)
        found.append(
            ExternalMediaRef(
                song_id=song.id,
                song_name=song.name,
                kind=kind,
                item_id=item_id,
                item_name=item_name,
                path=Path(path),
            )
        )

    for song in project.songs:
        for track in song.audio_tracks:
            _consider(
                song,
                kind="audio",
                item_id=track.id,
                item_name=track.name,
                path=Path(track.path),
            )
        for clip in song.video_clips:
            _consider(
                song,
                kind="video",
                item_id=clip.id,
                item_name=clip.name,
                path=Path(clip.path),
            )
    return found


def ingest_external_media_into_project(
    project: Project,
    *,
    project_file: Path | None,
    media_subdir: str = DEFAULT_MEDIA_SUBDIR,
    only: list[ExternalMediaRef] | None = None,
) -> IngestExternalResult:
    """
    Copy external media into ``Media/<Setlist>/<Song>/`` and rewrite project paths.

    Leaves the original files in place (copy, not move) — same as Collect Bundle.
    """
    result = IngestExternalResult()
    root = project_root_for(project_file)
    if root is None:
        return result
    media_dir = root / (media_subdir.strip() or DEFAULT_MEDIA_SUBDIR)
    media_dir.mkdir(parents=True, exist_ok=True)

    targets: set[str] | None = None
    if only is not None:
        targets = set()
        for ref in only:
            try:
                targets.add(str(Path(ref.path).resolve()))
            except OSError:
                targets.add(str(Path(ref.path)))

    # source resolve → dest (dedupe shared files across songs)
    placed: dict[str, Path] = {}

    def _copy_into(song: Song, source: Path) -> Path | None:
        try:
            resolved = source.expanduser().resolve()
        except OSError:
            resolved = source.expanduser().absolute()
        key = str(resolved)
        if targets is not None and key not in targets:
            return None
        if key in placed:
            return placed[key]
        if not path_exists(resolved):
            result.failed.append(source)
            return None
        if path_under_media(resolved, media_dir) or path_under_root(resolved, root):
            return None
        dest_folder = media_dir / song_media_rel_folder(project, song)
        dest = unique_dest(dest_folder, resolved.name)
        try:
            shutil.copy2(resolved, dest)
        except OSError:
            result.failed.append(source)
            return None
        clone_caches_for_copied_file(resolved, dest)
        try:
            final = dest.resolve()
        except OSError:
            final = dest
        placed[key] = final
        result.copied.append((resolved, final))
        return final

    for song in project.songs:
        for track in song.audio_tracks:
            new_path = _copy_into(song, Path(track.path))
            if new_path is not None:
                track.path = new_path
        for clip in song.video_clips:
            new_path = _copy_into(song, Path(clip.path))
            if new_path is not None:
                clip.path = new_path
    return result


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
