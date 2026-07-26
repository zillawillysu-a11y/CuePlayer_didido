"""Copy/paste video clips via undo snapshots (domain-level, no Qt keyboard)."""

from __future__ import annotations

from pathlib import Path

from cueplayer.domain.models import Song, VideoClip
from cueplayer.domain.undo import AddVideoClipsCommand, UndoStack, VideoClipSnapshot


def test_paste_from_clipboard_snapshot_at_playhead_is_undoable() -> None:
    song = Song.create("Song")
    original = VideoClip.create(
        name="開場",
        path=Path("中文/開場.mp4"),
        start_seconds=2.0,
        source_in_seconds=0.5,
        duration_seconds=3.0,
        volume=0.6,
        media_kind="video",
        source_duration_seconds=10.0,
    )
    original.locked = True
    song.add_video_clip(original)

    clipboard = [VideoClipSnapshot.from_clip(original)]
    paste_at = 7.0
    anchor = min(snap.start_seconds for snap in clipboard)
    pasted = VideoClip.create(
        name=f"{clipboard[0].name} copy",
        path=Path(clipboard[0].path),
        start_seconds=paste_at,
        source_in_seconds=clipboard[0].source_in_seconds,
        duration_seconds=clipboard[0].duration_seconds,
        volume=clipboard[0].volume,
        media_kind="still" if clipboard[0].media_kind == "still" else "video",
        source_duration_seconds=clipboard[0].source_duration_seconds,
    )
    pasted.locked = clipboard[0].locked
    song.add_video_clip(pasted)

    stack = UndoStack()
    stack.push(AddVideoClipsCommand(clips=[VideoClipSnapshot.from_clip(pasted)]))
    assert len(song.video_clips) == 2

    stack.undo(song)
    assert len(song.video_clips) == 1
    assert song.video_clips[0].id == original.id

    stack.redo(song)
    assert len(song.video_clips) == 2
    copy = next(c for c in song.video_clips if c.id != original.id)
    assert copy.name == "開場 copy"
    assert copy.path == Path("中文/開場.mp4")
    assert copy.start_seconds == paste_at
    assert copy.source_in_seconds == 0.5
    assert copy.duration_seconds == 3.0
    assert copy.volume == 0.6
    assert copy.locked is True
    assert copy.source_duration_seconds == 10.0


def test_multi_clip_paste_preserves_relative_spacing() -> None:
    song = Song.create("Song")
    a = VideoClip.create(name="a", path=Path("a.mp4"), start_seconds=1.0, duration_seconds=2.0)
    b = VideoClip.create(name="b", path=Path("b.mp4"), start_seconds=4.0, duration_seconds=2.0)
    clipboard = [VideoClipSnapshot.from_clip(a), VideoClipSnapshot.from_clip(b)]
    anchor = min(s.start_seconds for s in clipboard)
    paste_at = 10.0
    new_clips = []
    for snap in clipboard:
        offset = snap.start_seconds - anchor
        clip = VideoClip.create(
            name=f"{snap.name} copy",
            path=Path(snap.path),
            start_seconds=paste_at + offset,
            duration_seconds=snap.duration_seconds,
        )
        new_clips.append(clip)
    assert [c.start_seconds for c in new_clips] == [10.0, 13.0]
