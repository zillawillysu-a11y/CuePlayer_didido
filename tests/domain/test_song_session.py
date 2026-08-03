"""SongSession domain unit tests."""

from __future__ import annotations

from cueplayer.domain.models import Song
from cueplayer.domain.song_session import SongSession


def test_clear_song() -> None:
    session = SongSession()
    session.set_song(Song.create("X"))
    session.clear_song()
    assert session.song is None
    assert session.current_song is None
