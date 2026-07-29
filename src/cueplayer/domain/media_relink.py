"""Scan / rematch missing audio + video media referenced by a project."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cueplayer.domain.models import Project
from cueplayer.persistence.media_paths import path_exists


MediaKind = str  # "audio" | "video"


@dataclass(frozen=True)
class MissingMediaRef:
    song_id: str
    song_name: str
    kind: MediaKind
    item_id: str
    item_name: str
    path: Path

    @property
    def basename(self) -> str:
        return self.path.name


def scan_missing_media(project: Project) -> list[MissingMediaRef]:
    """Return every audio track / video clip whose file is not on disk."""
    missing: list[MissingMediaRef] = []
    for song in project.songs:
        for track in song.audio_tracks:
            path = Path(track.path)
            if not path_exists(path):
                missing.append(
                    MissingMediaRef(
                        song_id=song.id,
                        song_name=song.name,
                        kind="audio",
                        item_id=track.id,
                        item_name=track.name,
                        path=path,
                    )
                )
        for clip in song.video_clips:
            path = Path(clip.path)
            if not path_exists(path):
                missing.append(
                    MissingMediaRef(
                        song_id=song.id,
                        song_name=song.name,
                        kind="video",
                        item_id=clip.id,
                        item_name=clip.name,
                        path=path,
                    )
                )
    return missing


def apply_relink(project: Project, ref: MissingMediaRef, new_path: Path) -> bool:
    """Point one missing item at ``new_path``. Returns True if updated."""
    new_path = Path(new_path)
    for song in project.songs:
        if song.id != ref.song_id:
            continue
        if ref.kind == "audio":
            for track in song.audio_tracks:
                if track.id == ref.item_id:
                    track.path = new_path
                    return True
        else:
            for clip in song.video_clips:
                if clip.id == ref.item_id:
                    clip.path = new_path
                    return True
    return False


def index_folder_basenames(
    folder: Path, *, recursive: bool = True
) -> dict[str, list[Path]]:
    """
    Map lowercased basename → candidate files under ``folder``.

    Multiple files with the same name land in the same list (caller decides).
    """
    root = Path(folder)
    if not root.is_dir():
        return {}
    index: dict[str, list[Path]] = {}
    iterator = root.rglob("*") if recursive else root.iterdir()
    for path in iterator:
        try:
            if not path.is_file():
                continue
        except OSError:
            continue
        key = path.name.casefold()
        index.setdefault(key, []).append(path)
    return index


@dataclass
class FolderRelinkResult:
    linked: list[tuple[MissingMediaRef, Path]]
    ambiguous: list[MissingMediaRef]
    unmatched: list[MissingMediaRef]


def relink_from_folder(
    project: Project,
    missing: list[MissingMediaRef],
    folder: Path,
    *,
    recursive: bool = True,
) -> FolderRelinkResult:
    """
    Match missing items to files in ``folder`` by basename (case-insensitive).

    Unique matches are applied immediately. Ambiguous / unmatched are reported.
    """
    index = index_folder_basenames(folder, recursive=recursive)
    linked: list[tuple[MissingMediaRef, Path]] = []
    ambiguous: list[MissingMediaRef] = []
    unmatched: list[MissingMediaRef] = []
    for ref in missing:
        candidates = index.get(ref.basename.casefold(), [])
        if len(candidates) == 1:
            new_path = candidates[0]
            if apply_relink(project, ref, new_path):
                linked.append((ref, new_path))
            else:
                unmatched.append(ref)
        elif len(candidates) > 1:
            ambiguous.append(ref)
        else:
            unmatched.append(ref)
    return FolderRelinkResult(linked=linked, ambiguous=ambiguous, unmatched=unmatched)
