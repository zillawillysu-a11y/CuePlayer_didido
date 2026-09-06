"""Undo / redo commands for LTC generator clips (Phase 3)."""

from __future__ import annotations

from cueplayer.domain.ltc_clips import add_ltc_clip, remove_ltc_clip
from cueplayer.domain.models import Song
from cueplayer.domain.undo import (
    AddLtcClipCommand,
    DeleteLtcClipsCommand,
    EditLtcClipsCommand,
    LtcClipSnapshot,
    SetLtcSourceModeCommand,
    UndoContext,
    UndoStack,
)
from cueplayer.domain.models import Project


def _ctx(project, song):
    return UndoContext(project=project, current_song_id=song.id)


def _stack_with(song_id):
    stack = UndoStack()
    # Push outside the song context; commands carry their own song id.
    return stack


def test_add_ltc_clip_undo_redo_restores_mode() -> None:
    project = Project.create("Undo")
    song = project.songs[0]
    song.duration_seconds = 60.0
    ctx = _ctx(project, song)
    stack = UndoStack()

    clip = add_ltc_clip(
        song, timeline_start_seconds=10.0, duration_seconds=20.0, start_timecode="01:00:05:00"
    )
    assert song.ltc_source_mode == "clip_generator"
    stack.push(
        AddLtcClipCommand(clip=LtcClipSnapshot.from_clip(clip), old_mode="striped_file"),
        song_id=song.id,
    )

    assert len(song.ltc_clips) == 1
    stack.undo(ctx)
    assert song.ltc_clips == []
    assert song.ltc_source_mode == "striped_file"

    stack.redo(ctx)
    assert [c.id for c in song.ltc_clips] == [clip.id]
    assert song.ltc_source_mode == "clip_generator"
    assert song.ltc_clips[0].start_timecode == "01:00:05:00"


def test_delete_ltc_clips_undo_redo_never_restores_mode() -> None:
    project = Project.create("Del")
    song = project.songs[0]
    song.duration_seconds = 60.0
    song.ltc_source_mode = "clip_generator"
    ctx = _ctx(project, song)
    stack = UndoStack()

    c1 = add_ltc_clip(song, timeline_start_seconds=0.0, duration_seconds=10.0, start_timecode="01:00:00:00")
    c2 = add_ltc_clip(song, timeline_start_seconds=30.0, duration_seconds=10.0, start_timecode="01:00:30:00")
    snaps = [LtcClipSnapshot.from_clip(c1), LtcClipSnapshot.from_clip(c2)]
    for snap in snaps:
        remove_ltc_clip(song, snap.id)
    stack.push(DeleteLtcClipsCommand(clips=snaps), song_id=song.id)

    assert song.ltc_clips == []
    assert song.ltc_source_mode == "clip_generator"  # mode is never auto-changed

    stack.undo(ctx)
    assert [c.id for c in song.ltc_clips] == [c1.id, c2.id]
    # Undo restores the clips but keeps the explicit mode unchanged.
    assert song.ltc_source_mode == "clip_generator"

    stack.redo(ctx)
    assert song.ltc_clips == []


def test_edit_ltc_clips_undo_redo() -> None:
    project = Project.create("Edit")
    song = project.songs[0]
    song.duration_seconds = 60.0
    song.ltc_source_mode = "clip_generator"
    ctx = _ctx(project, song)
    stack = UndoStack()

    clip = add_ltc_clip(song, timeline_start_seconds=5.0, duration_seconds=10.0, start_timecode="01:00:02:00")
    old = (5.0, 10.0, "01:00:02:00")
    new = (7.5, 12.0, "01:00:02:00")
    # The UI mutates the domain first, then records the inverse command.
    clip.timeline_start_seconds = new[0]
    clip.duration_seconds = new[1]
    stack.push(EditLtcClipsCommand(changes={clip.id: (old, new)}), song_id=song.id)

    assert (clip.timeline_start_seconds, clip.duration_seconds) == (7.5, 12.0)

    stack.undo(ctx)
    assert (clip.timeline_start_seconds, clip.duration_seconds, clip.start_timecode) == old

    stack.redo(ctx)
    assert (clip.timeline_start_seconds, clip.duration_seconds, clip.start_timecode) == new


def test_set_ltc_source_mode_undo_redo() -> None:
    project = Project.create("Mode")
    song = project.songs[0]
    song.ltc_source_mode = "striped_file"
    ctx = _ctx(project, song)
    stack = UndoStack()

    song.ltc_source_mode = "clip_generator"
    stack.push(
        SetLtcSourceModeCommand(old_mode="striped_file", new_mode="clip_generator"),
        song_id=song.id,
    )
    assert song.ltc_source_mode == "clip_generator"

    stack.undo(ctx)
    assert song.ltc_source_mode == "striped_file"

    stack.redo(ctx)
    assert song.ltc_source_mode == "clip_generator"


def test_last_executed_command_exposes_inner_command() -> None:
    project = Project.create("Last")
    song = project.songs[0]
    song.duration_seconds = 60.0
    ctx = _ctx(project, song)
    stack = UndoStack()

    assert stack.last_executed_command is None
    song.ltc_source_mode = "off"
    stack.push(
        SetLtcSourceModeCommand(old_mode="auto", new_mode="off"),
        song_id=song.id,
    )
    stack.undo(ctx)
    last = stack.last_executed_command
    assert isinstance(last, SetLtcSourceModeCommand)
    assert last.new_mode == "off"
