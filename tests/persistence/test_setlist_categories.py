"""Setlist folder categories."""

from __future__ import annotations

from cueplayer.domain.models import Project, SetlistCategory, Song
from cueplayer.persistence.project_store import project_from_dict, project_to_dict


def test_setlist_category_round_trip() -> None:
    project = Project.create("Show")
    project.songs = [Song.create("Active"), Song.create("Archive")]
    folder = SetlistCategory.create("Old Songs")
    project.setlist_categories = [folder]
    project.songs[1].category_id = folder.id

    data = project_to_dict(project)
    loaded = project_from_dict(data)

    assert len(loaded.setlist_categories) == 1
    assert loaded.setlist_categories[0].name == "Old Songs"
    assert loaded.songs[1].category_id == folder.id
    assert loaded.songs[0].category_id is None


def test_song_duplicate_clears_category() -> None:
    song = Song.create("Original")
    song.category_id = "cat-1"
    dup = song.duplicate()
    assert dup.category_id is None
