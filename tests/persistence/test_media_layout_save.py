"""Media layout sync runs on Save — Save As must not break the old project."""

from __future__ import annotations

from pathlib import Path

from cueplayer.domain.models import AudioTrack, Project, SetlistCategory
from cueplayer.persistence.media_layout import sync_all_songs_media_to_setlist_folders
from cueplayer.persistence.project_store import load_project, save_project


def test_save_as_other_folder_leaves_old_project_and_media(tmp_path: Path) -> None:
    """
    Save As into a different folder keeps media under the original root.

    Opening the old project file still finds the same relative Media paths.
    """
    original_dir = tmp_path / "show_a"
    original_dir.mkdir()
    project_path = original_dir / "show.cueplayer.json"

    cat = SetlistCategory.create("開場")
    project = Project.create("Show")
    project.setlist_categories.append(cat)
    song = project.songs[0]
    song.name = "曲目一"
    song.category_id = cat.id

    media_file = original_dir / "Media" / "開場" / "曲目一" / "main.wav"
    media_file.parent.mkdir(parents=True)
    media_file.write_bytes(b"RIFF")
    song.audio_tracks.append(
        AudioTrack(id="a1", name="Main", path=media_file, role="main")
    )
    save_project(project, project_path)

    # Reorganise Setlist in memory only (as UI does before Save).
    encore = SetlistCategory.create("安可")
    project.setlist_categories.append(encore)
    song.category_id = encore.id

    other_dir = tmp_path / "show_b"
    other_dir.mkdir()
    save_as_path = other_dir / "copy.cueplayer.json"
    # Same call order as File → Save As: sync for the *new* path, then write.
    moved = sync_all_songs_media_to_setlist_folders(project, project_file=save_as_path)
    assert moved == 0
    save_project(project, save_as_path)

    assert media_file.is_file()
    assert not (other_dir / "Media").exists() or not any(
        (other_dir / "Media").rglob("main.wav")
    )

    old = load_project(project_path)
    assert old.songs[0].audio_tracks[0].path.is_file()
    assert old.songs[0].audio_tracks[0].path.resolve() == media_file.resolve()
    # Old JSON still has the pre-move Setlist folder (file was never overwritten).
    assert old.setlist_categories[0].name == "開場"
    assert old.songs[0].category_id == cat.id

    new = load_project(save_as_path)
    assert new.songs[0].audio_tracks[0].path.is_file()
    assert new.songs[0].audio_tracks[0].path.resolve() == media_file.resolve()
    assert new.songs[0].category_id == encore.id


def test_save_on_original_rearranges_media(tmp_path: Path) -> None:
    """Saving the original project file rearranges Media to match Setlist."""
    root = tmp_path / "show"
    root.mkdir()
    project_path = root / "show.cueplayer.json"
    cat = SetlistCategory.create("開場")
    project = Project.create("Show")
    project.setlist_categories.append(cat)
    song = project.songs[0]
    song.name = "曲目一"
    song.category_id = cat.id
    media_file = root / "Media" / "開場" / "曲目一" / "main.wav"
    media_file.parent.mkdir(parents=True)
    media_file.write_bytes(b"RIFF")
    song.audio_tracks.append(
        AudioTrack(id="a1", name="Main", path=media_file, role="main")
    )
    save_project(project, project_path)

    encore = SetlistCategory.create("安可")
    project.setlist_categories.append(encore)
    song.category_id = encore.id
    n = sync_all_songs_media_to_setlist_folders(project, project_file=project_path)
    assert n >= 1
    save_project(project, project_path)

    new_path = root / "Media" / "安可" / "曲目一" / "main.wav"
    assert new_path.is_file()
    assert not media_file.exists()
    loaded = load_project(project_path)
    assert loaded.songs[0].audio_tracks[0].path.resolve() == new_path.resolve()
