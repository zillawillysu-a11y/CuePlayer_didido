"""Renumber Main Cue IDs from 1 in time order."""

from __future__ import annotations

from cueplayer.domain.main_cue_id import (
    capture_main_cue_ids,
    renumber_main_cue_ids_sequential,
)
from cueplayer.domain.models import Project, Song
from cueplayer.domain.undo import RenumberMainCueIdsCommand, UndoContext, UndoStack


def test_renumber_main_cue_ids_sequential() -> None:
    song = Song.create("Test")
    song.add_mark(1, 1.0)
    song.add_mark(1, 2.0)
    inserted = song.add_mark(1, 1.5)
    assert inserted.main_cue_id == "1.1"
    after = renumber_main_cue_ids_sequential(song)
    assert after == {
        m.id: str(i) for i, m in enumerate(song.main_marks_sorted(), start=1)
    }
    assert [m.main_cue_id for m in song.main_marks_sorted()] == ["1", "2", "3"]


def test_renumber_main_cue_ids_undo() -> None:
    project = Project.create("t")
    song = project.songs[0]
    song.add_mark(1, 1.0)
    song.add_mark(1, 2.0)
    before = capture_main_cue_ids(song)
    after = renumber_main_cue_ids_sequential(song)
    stack = UndoStack()
    stack.push(RenumberMainCueIdsCommand(before=before, after=after), song_id=song.id)
    ctx = UndoContext(project, song.id)
    stack.undo(ctx)
    assert capture_main_cue_ids(song) == before
