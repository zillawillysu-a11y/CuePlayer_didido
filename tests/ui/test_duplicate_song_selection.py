"""Regression coverage for batch Duplicate selection after list insertion."""

from cueplayer.domain.models import Song


def test_batch_duplicate_indexes_resolve_only_new_song_ids() -> None:
    songs = [Song.create("A"), Song.create("B"), Song.create("C")]
    source_ids = {song.id for song in songs}
    duplicate_ids: list[str] = []

    for row in sorted(range(len(songs)), reverse=True):
        duplicate = songs[row].duplicate(name=f"{songs[row].name} (copy)")
        songs.insert(row + 1, duplicate)
        duplicate_ids.append(duplicate.id)

    duplicate_id_set = set(duplicate_ids)
    selected_indexes = [
        index for index, song in enumerate(songs) if song.id in duplicate_id_set
    ]
    selected_ids = {songs[index].id for index in selected_indexes}

    assert selected_ids == duplicate_id_set
    assert selected_ids.isdisjoint(source_ids)
    assert [songs[index].name for index in selected_indexes] == [
        "A (copy)", "B (copy)", "C (copy)"
    ]
