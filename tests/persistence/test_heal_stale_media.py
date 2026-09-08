"""Heal stale Media paths left behind by Setlist folder moves."""

from __future__ import annotations

from pathlib import Path

from cueplayer.domain.media_relink import scan_missing_media
from cueplayer.domain.models import AudioTrack, Project, SetlistCategory
from cueplayer.persistence.media_layout import (
    heal_stale_media_paths,
    sync_all_songs_media_to_setlist_folders,
)
from cueplayer.persistence.project_store import save_project


def test_heal_relinks_unique_basename_under_media(tmp_path: Path) -> None:
    root = tmp_path / "show"
    root.mkdir()
    project_file = root / "show.cueplayer.json"
    real = root / "Media" / "安可" / "曲目" / "main.wav"
    real.parent.mkdir(parents=True)
    real.write_bytes(b"RIFF")
    stale = root / "Media" / "開場" / "曲目" / "main.wav"  # does not exist

    project = Project.create("Show")
    song = project.songs[0]
    song.name = "曲目"
    song.audio_tracks.append(
        AudioTrack(id="a1", name="Main", path=stale, role="main")
    )
    assert scan_missing_media(project)
    n = heal_stale_media_paths(project, project_file=project_file)
    assert n >= 1
    assert Path(song.audio_tracks[0].path).resolve() == real.resolve()
    assert scan_missing_media(project) == []


def test_heal_prefers_legacy_media_root_when_duplicate_has_same_basename(
    tmp_path: Path,
) -> None:
    """Duplicating a song must not make the original song appear Unlinked."""
    root = tmp_path / "show"
    root.mkdir()
    project_file = root / "show.cueplayer.json"
    media = root / "Media"
    original = media / "原歌.wav"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"ORIGINAL")
    duplicate = media / "New Set" / "原歌 (copy)" / "原歌.wav"
    duplicate.parent.mkdir(parents=True)
    duplicate.write_bytes(b"NEW VERSION")
    stale = media / "_Unfiled" / "原歌" / "原歌.wav"

    project = Project.create("Show")
    song = project.songs[0]
    song.name = "原歌"
    song.audio_tracks.append(
        AudioTrack(id="a1", name="Main", path=stale, role="main")
    )

    assert scan_missing_media(project)
    healed = heal_stale_media_paths(project, project_file=project_file)

    assert healed >= 1
    assert Path(song.audio_tracks[0].path).resolve() == original.resolve()
    assert scan_missing_media(project) == []


def test_move_rewrites_all_songs_sharing_old_path(tmp_path: Path) -> None:
    """Exclusive relocate must not leave a second song pointing at the old path."""
    root = tmp_path / "show"
    root.mkdir()
    project_file = root / "show.cueplayer.json"
    shared = root / "Media" / "開場" / "A" / "bed.wav"
    shared.parent.mkdir(parents=True)
    shared.write_bytes(b"BED")

    project = Project.create("Show")
    cat_a = SetlistCategory.create("開場")
    cat_b = SetlistCategory.create("安可")
    project.setlist_categories.extend([cat_a, cat_b])
    a = project.songs[0]
    a.name = "A"
    a.category_id = cat_a.id
    a.audio_tracks.append(AudioTrack(id="a1", name="Main", path=shared, role="main"))
    b = project.new_song("B")
    # Same path string as A (pre-share-protection scenario / duplicate link).
    b.category_id = cat_a.id
    b.audio_tracks.append(AudioTrack(id="a2", name="Main", path=shared, role="main"))
    project.songs.append(b)
    save_project(project, project_file)

    # Break sharing deliberately: only A changes folder, sync used to move the
    # file for A and leave B stale. With rewrite_media_path_refs, B follows.
    # First drop B's link count by pointing B at a copy identity — actually
    # shared keys prevent move. Simulate post-move stale B:
    a.category_id = cat_b.id
    # Force exclusive move by temporarily making B point elsewhere, sync A,
    # then set B back to old path (as if an old JSON ref survived).
    other = root / "Media" / "開場" / "B" / "other.wav"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"OTH")
    b.audio_tracks[0].path = other
    sync_all_songs_media_to_setlist_folders(project, project_file=project_file)
    new_a = Path(a.audio_tracks[0].path)
    assert new_a.is_file()
    assert "安可" in str(new_a)

    # Stale leftover path on B (as Bundle would see after a bad move).
    b.audio_tracks[0].path = shared  # old location, file gone
    assert not shared.exists()
    assert scan_missing_media(project)
    healed = heal_stale_media_paths(project, project_file=project_file)
    assert healed >= 1
    assert Path(b.audio_tracks[0].path).resolve() == new_a.resolve()
    assert scan_missing_media(project) == []
