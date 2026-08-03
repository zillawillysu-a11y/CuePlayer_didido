"""Undo/redo for Align Anchors Apply (SetVariantAnchorOffsetCommand)."""

from __future__ import annotations

from pathlib import Path

from cueplayer.domain.models import Song
from cueplayer.domain.song_variant import SongVariant
from cueplayer.domain.undo import SetVariantAnchorOffsetCommand, UndoStack


def test_set_variant_anchor_offset_undo_redo(tmp_path: Path) -> None:
    song = Song.create("曲")
    variant = SongVariant.create("Alt", tmp_path / "a.wav", anchor_offset=0.0)
    song.variants = [variant]
    song.selected_variant_id = variant.id
    mark = song.add_mark(1, 10.0, display_name="Kick")
    mark_time = mark.time_seconds

    command = SetVariantAnchorOffsetCommand(
        variant_id=variant.id,
        old_offset=0.0,
        new_offset=0.5,
    )
    command.redo(song)
    assert variant.anchor_offset == 0.5
    assert mark.time_seconds == mark_time

    stack = UndoStack()
    stack.push(command)
    stack.undo(song)
    assert variant.anchor_offset == 0.0
    assert mark.time_seconds == mark_time

    stack.redo(song)
    assert variant.anchor_offset == 0.5
    assert mark.time_seconds == mark_time


def test_set_variant_anchor_offset_missing_variant_noop(tmp_path: Path) -> None:
    song = Song.create("曲")
    command = SetVariantAnchorOffsetCommand(
        variant_id="missing",
        old_offset=0.0,
        new_offset=1.0,
    )
    command.redo(song)
    command.undo(song)
    assert song.variants == []
