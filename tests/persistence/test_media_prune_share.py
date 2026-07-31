"""Empty Media folder prune + shared Media files stay put on Save sync."""

from __future__ import annotations

from pathlib import Path

from cueplayer.domain.models import AudioTrack, Project, SetlistCategory
from cueplayer.persistence.media_layout import (
    prune_empty_dirs_under_media,
    sync_all_songs_media_to_setlist_folders,
)
from cueplayer.persistence.project_store import save_project


def test_prune_removes_empty_nested_dirs(tmp_path: Path) -> None:
    media = tmp_path / "Media"
    leftover = media / "開場" / "舊歌"
    leftover.mkdir(parents=True)
    (media / "安可" / "新歌").mkdir(parents=True)
    keep = media / "安可" / "新歌" / "a.wav"
    keep.write_bytes(b"x")
    n = prune_empty_dirs_under_media(media)
    assert n >= 2
    assert not leftover.exists()
    assert keep.is_file()
    assert (media / "安可" / "新歌").is_dir()


def test_sync_moves_then_prunes_old_song_folder(tmp_path: Path) -> None:
    root = tmp_path / "show"
    root.mkdir()
    project_file = root / "show.cueplayer.json"
    cat_a = SetlistCategory.create("開場")
    cat_b = SetlistCategory.create("安可")
    project = Project.create("Show")
    project.setlist_categories.extend([cat_a, cat_b])
    song = project.songs[0]
    song.name = "曲目"
    song.category_id = cat_a.id
    media_file = root / "Media" / "開場" / "曲目" / "main.wav"
    media_file.parent.mkdir(parents=True)
    media_file.write_bytes(b"RIFF")
    song.audio_tracks.append(
        AudioTrack(id="a1", name="Main", path=media_file, role="main")
    )
    save_project(project, project_file)

    song.category_id = cat_b.id
    sync_all_songs_media_to_setlist_folders(project, project_file=project_file)

    new_path = root / "Media" / "安可" / "曲目" / "main.wav"
    assert new_path.is_file()
    assert not media_file.exists()
    assert not (root / "Media" / "開場" / "曲目").exists()


def test_shared_media_file_not_moved_on_sync(tmp_path: Path) -> None:
    root = tmp_path / "show"
    root.mkdir()
    project_file = root / "show.cueplayer.json"
    shared = root / "Media" / "_Unfiled" / "shared.wav"
    shared.parent.mkdir(parents=True)
    shared.write_bytes(b"SHARE")

    project = Project.create("Show")
    a = project.songs[0]
    a.name = "A"
    a.audio_tracks.append(AudioTrack(id="a1", name="Main", path=shared, role="main"))
    b = project.new_song("B")
    b.audio_tracks.append(AudioTrack(id="a2", name="Main", path=shared, role="main"))
    project.songs.append(b)
    cat = SetlistCategory.create("開場")
    project.setlist_categories.append(cat)
    a.category_id = cat.id
    b.category_id = cat.id

    sync_all_songs_media_to_setlist_folders(project, project_file=project_file)

    assert shared.is_file()
    assert Path(a.audio_tracks[0].path).resolve() == shared.resolve()
    assert Path(b.audio_tracks[0].path).resolve() == shared.resolve()
    # Must not invent A/B duplicates under 開場/
    assert not (root / "Media" / "開場" / "A" / "shared.wav").exists()
    assert not (root / "Media" / "開場" / "B" / "shared.wav").exists()
