"""Undo/redo for video clip add / delete / edit (move, trim, split, duplicate)."""

from __future__ import annotations

from pathlib import Path

from cueplayer.domain.models import Song, VideoClip
from cueplayer.domain.undo import (
    AddVideoClipsCommand,
    DeleteVideoClipsCommand,
    EditVideoClipsCommand,
    UndoStack,
    VideoClipSnapshot,
)


def test_add_video_clip_undo_redo() -> None:
    song = Song.create("Song")
    clip = VideoClip.create(name="開場", path=Path("開場.mp4"), start_seconds=0.0, duration_seconds=2.0)
    song.add_video_clip(clip)

    stack = UndoStack()
    stack.push(AddVideoClipsCommand(clips=[VideoClipSnapshot.from_clip(clip)]))

    stack.undo(song)
    assert song.video_clips == []

    stack.redo(song)
    assert [c.id for c in song.video_clips] == [clip.id]
    assert song.video_clips[0].name == "開場"


def test_delete_video_clip_undo_redo() -> None:
    song = Song.create("Song")
    clip = VideoClip.create(name="a", path=Path("a.mp4"), start_seconds=0.0, duration_seconds=2.0)
    song.add_video_clip(clip)
    snapshot = VideoClipSnapshot.from_clip(clip)
    song.remove_video_clips_by_ids({clip.id})

    stack = UndoStack()
    stack.push(DeleteVideoClipsCommand(clips=[snapshot]))

    stack.undo(song)
    assert [c.id for c in song.video_clips] == [clip.id]

    stack.redo(song)
    assert song.video_clips == []


def test_edit_video_clip_move_undo_redo() -> None:
    song = Song.create("Song")
    clip = VideoClip.create(name="a", path=Path("a.mp4"), start_seconds=0.0, duration_seconds=2.0)
    song.add_video_clip(clip)

    old_transform = (clip.start_seconds, clip.source_in_seconds, clip.duration_seconds)
    clip.start_seconds = 5.0  # simulate a drag-move already applied to the live clip
    new_transform = (clip.start_seconds, clip.source_in_seconds, clip.duration_seconds)

    stack = UndoStack()
    stack.push(EditVideoClipsCommand(changes={clip.id: (old_transform, new_transform)}))

    stack.undo(song)
    assert song.video_clip_by_id(clip.id).start_seconds == 0.0

    stack.redo(song)
    assert song.video_clip_by_id(clip.id).start_seconds == 5.0


def test_edit_video_clip_keeps_source_out_in_sync() -> None:
    song = Song.create("Song")
    clip = VideoClip.create(
        name="a", path=Path("a.mp4"), start_seconds=0.0, source_in_seconds=1.0, duration_seconds=2.0
    )
    song.add_video_clip(clip)

    old_transform = (clip.start_seconds, clip.source_in_seconds, clip.duration_seconds)
    new_transform = (0.0, 1.5, 3.0)  # trimmed in-point + new duration

    cmd = EditVideoClipsCommand(changes={clip.id: (old_transform, new_transform)})
    cmd.redo(song)
    edited = song.video_clip_by_id(clip.id)
    assert edited.source_in_seconds == 1.5
    assert edited.duration_seconds == 3.0
    assert edited.source_out_seconds == 4.5

    cmd.undo(song)
    reverted = song.video_clip_by_id(clip.id)
    assert reverted.source_in_seconds == 1.0
    assert reverted.duration_seconds == 2.0
    assert reverted.source_out_seconds == 3.0
