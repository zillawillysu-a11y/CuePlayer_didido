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


def test_setlist_category_row_color_round_trip() -> None:
    project = Project.create("Show")
    folder = SetlistCategory.create("VIP")
    folder.row_color = "#FF5A5F"
    project.setlist_categories = [folder]

    loaded = project_from_dict(project_to_dict(project))
    assert loaded.setlist_categories[0].row_color == "#FF5A5F"


def test_setlist_category_missing_row_color_migrates_empty() -> None:
    project = Project.create("Show")
    folder = SetlistCategory.create("Archive")
    project.setlist_categories = [folder]
    data = project_to_dict(project)
    del data["setlist_categories"][0]["row_color"]
    loaded = project_from_dict(data)
    assert loaded.setlist_categories[0].row_color == ""


def test_song_duplicate_clears_category() -> None:
    song = Song.create("Original")
    song.category_id = "cat-1"
    dup = song.duplicate()
    assert dup.category_id is None


def test_next_setlist_number_is_scoped_per_category() -> None:
    project = Project.create("Show")
    project.songs = [Song.create("A"), Song.create("B"), Song.create("C")]
    folder = SetlistCategory.create("Archive")
    project.setlist_categories = [folder]
    project.songs[0].setlist_number = 3.0
    project.songs[1].setlist_number = 1.0
    project.songs[1].category_id = folder.id
    project.songs[2].setlist_number = 5.0
    project.songs[2].category_id = folder.id

    assert project.next_setlist_number(None) == 4.0
    assert project.next_setlist_number(folder.id) == 6.0
    assert len(project.songs_in_category(None)) == 1
    assert len(project.songs_in_category(folder.id)) == 2
