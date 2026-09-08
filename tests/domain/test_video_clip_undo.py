"""Undo/redo for video clip add / delete / edit (move, trim, split, duplicate)."""

from __future__ import annotations

from pathlib import Path

from cueplayer.domain.models import Song, VideoClip
from cueplayer.domain.undo import (
    AddVideoClipsCommand,
    DeleteVideoClipsCommand,
    EditVideoClipsCommand,
    SplitVideoClipCommand,
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


def test_split_video_clip_undo_redo_is_atomic() -> None:
    # TEST S6: split is one undo entry — a single undo restores the original
    # single clip, a single redo re-creates the two split clips.
    song = Song.create("Song")
    clip = VideoClip.create(
        name="a", path=Path("a.mp4"), start_seconds=10.0, source_in_seconds=5.0, duration_seconds=20.0
    )
    song.add_video_clip(clip)

    original_before = (clip.start_seconds, clip.source_in_seconds, clip.duration_seconds)
    # Simulate the split already applied to the live clip (as MainWindow does).
    clip.duration_seconds = 8.0
    clip.source_out_seconds = clip.source_in_seconds + 8.0
    original_after = (clip.start_seconds, clip.source_in_seconds, clip.duration_seconds)
    second = VideoClip.create(
        name="a", path=Path("a.mp4"), start_seconds=18.0, source_in_seconds=13.0, duration_seconds=12.0
    )
    song.add_video_clip(second)

    stack = UndoStack()
    stack.push(
        SplitVideoClipCommand(
            original_id=clip.id,
            original_before=original_before,
            original_after=original_after,
            new_clip=VideoClipSnapshot.from_clip(second),
        )
    )

    stack.undo(song)
    assert [c.id for c in song.video_clips] == [clip.id]
    restored = song.video_clip_by_id(clip.id)
    assert (restored.start_seconds, restored.source_in_seconds, restored.duration_seconds) == original_before

    stack.redo(song)
    assert {c.id for c in song.video_clips} == {clip.id, second.id}
    left = song.video_clip_by_id(clip.id)
    right = song.video_clip_by_id(second.id)
    assert (left.start_seconds, left.source_in_seconds, left.duration_seconds) == original_after
    assert right.start_seconds == 18.0
    assert right.source_in_seconds == 13.0
    assert right.duration_seconds == 12.0
