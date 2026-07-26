"""In-memory undo/redo for Cue mark and video clip edits."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from cueplayer.domain.models import Mark, Song, VideoClip


@dataclass(frozen=True)
class MarkSnapshot:
    id: str
    lane_index: int
    time_seconds: float
    display_name: str = ""
    ma_export_name: str | None = None

    @classmethod
    def from_mark(cls, mark: Mark) -> MarkSnapshot:
        return cls(
            id=mark.id,
            lane_index=mark.lane_index,
            time_seconds=mark.time_seconds,
            display_name=mark.display_name,
            ma_export_name=mark.ma_export_name,
        )

    def to_mark(self) -> Mark:
        return Mark(
            id=self.id,
            lane_index=self.lane_index,
            time_seconds=self.time_seconds,
            display_name=self.display_name,
            ma_export_name=self.ma_export_name,
        )


class UndoCommand(Protocol):
    label: str

    def undo(self, song: Song) -> None: ...

    def redo(self, song: Song) -> None: ...


@dataclass
class AddMarksCommand:
    marks: list[MarkSnapshot]
    label: str = "Add Mark"

    def undo(self, song: Song) -> None:
        ids = {m.id for m in self.marks}
        song.marks = [m for m in song.marks if m.id not in ids]

    def redo(self, song: Song) -> None:
        existing = {m.id for m in song.marks}
        for snap in self.marks:
            if snap.id not in existing:
                song.marks.append(snap.to_mark())
        song.sort_marks()


@dataclass
class DeleteMarksCommand:
    marks: list[MarkSnapshot]
    label: str = "Delete Mark"

    def undo(self, song: Song) -> None:
        existing = {m.id for m in song.marks}
        for snap in self.marks:
            if snap.id not in existing:
                song.marks.append(snap.to_mark())
        song.sort_marks()

    def redo(self, song: Song) -> None:
        ids = {m.id for m in self.marks}
        song.marks = [m for m in song.marks if m.id not in ids]


@dataclass
class MoveMarksCommand:
    """id → (old_time, new_time)."""

    times: dict[str, tuple[float, float]]
    label: str = "Move Mark"

    def undo(self, song: Song) -> None:
        for mark_id, (old_t, _new_t) in self.times.items():
            mark = song.mark_by_id(mark_id)
            if mark is not None:
                mark.time_seconds = old_t
        song.sort_marks()

    def redo(self, song: Song) -> None:
        for mark_id, (_old_t, new_t) in self.times.items():
            mark = song.mark_by_id(mark_id)
            if mark is not None:
                mark.time_seconds = new_t
        song.sort_marks()


@dataclass
class RenameMarkCommand:
    mark_id: str
    old_name: str
    new_name: str
    label: str = "Edit Note"

    def undo(self, song: Song) -> None:
        mark = song.mark_by_id(self.mark_id)
        if mark is not None:
            mark.display_name = self.old_name

    def redo(self, song: Song) -> None:
        mark = song.mark_by_id(self.mark_id)
        if mark is not None:
            mark.display_name = self.new_name


@dataclass(frozen=True)
class VideoClipSnapshot:
    id: str
    name: str
    path: str
    start_seconds: float
    source_in_seconds: float
    source_out_seconds: float | None
    duration_seconds: float
    locked: bool = False
    hidden: bool = False
    volume: float = 1.0
    media_kind: str = "video"
    source_duration_seconds: float | None = None

    @classmethod
    def from_clip(cls, clip: VideoClip) -> VideoClipSnapshot:
        return cls(
            id=clip.id,
            name=clip.name,
            path=str(clip.path),
            start_seconds=clip.start_seconds,
            source_in_seconds=clip.source_in_seconds,
            source_out_seconds=clip.source_out_seconds,
            duration_seconds=clip.duration_seconds,
            locked=clip.locked,
            hidden=clip.hidden,
            volume=clip.volume,
            media_kind=clip.media_kind,
            source_duration_seconds=clip.source_duration_seconds,
        )

    def to_clip(self) -> VideoClip:
        return VideoClip(
            id=self.id,
            name=self.name,
            path=Path(self.path),
            start_seconds=self.start_seconds,
            source_in_seconds=self.source_in_seconds,
            source_out_seconds=self.source_out_seconds,
            duration_seconds=self.duration_seconds,
            locked=self.locked,
            hidden=self.hidden,
            volume=self.volume,
            media_kind="still" if self.media_kind == "still" else "video",
            source_duration_seconds=self.source_duration_seconds,
        )


@dataclass
class AddVideoClipsCommand:
    clips: list[VideoClipSnapshot]
    label: str = "Add Video Clip"

    def undo(self, song: Song) -> None:
        ids = {c.id for c in self.clips}
        song.video_clips = [c for c in song.video_clips if c.id not in ids]

    def redo(self, song: Song) -> None:
        existing = {c.id for c in song.video_clips}
        for snap in self.clips:
            if snap.id not in existing:
                song.video_clips.append(snap.to_clip())
        song.sort_video_clips()


@dataclass
class DeleteVideoClipsCommand:
    clips: list[VideoClipSnapshot]
    label: str = "Delete Video Clip"

    def undo(self, song: Song) -> None:
        existing = {c.id for c in song.video_clips}
        for snap in self.clips:
            if snap.id not in existing:
                song.video_clips.append(snap.to_clip())
        song.sort_video_clips()

    def redo(self, song: Song) -> None:
        ids = {c.id for c in self.clips}
        song.video_clips = [c for c in song.video_clips if c.id not in ids]


ClipTransform = tuple[float, float, float]  # (start_seconds, source_in_seconds, duration_seconds)


@dataclass
class EditVideoClipsCommand:
    """Move / trim / nudge: id -> (old_transform, new_transform)."""

    changes: dict[str, tuple[ClipTransform, ClipTransform]]
    label: str = "Edit Video Clip"

    def _apply(self, song: Song, index: int) -> None:
        for clip_id, transforms in self.changes.items():
            clip = song.video_clip_by_id(clip_id)
            if clip is None:
                continue
            start, source_in, duration = transforms[index]
            clip.start_seconds = start
            clip.source_in_seconds = source_in
            clip.duration_seconds = duration
            clip.source_out_seconds = source_in + duration
        song.sort_video_clips()

    def undo(self, song: Song) -> None:
        self._apply(song, 0)

    def redo(self, song: Song) -> None:
        self._apply(song, 1)


class UndoStack:
    def __init__(self, *, limit: int = 100) -> None:
        self._limit = max(1, limit)
        self._undo: list[UndoCommand] = []
        self._redo: list[UndoCommand] = []

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()

    def push(self, command: UndoCommand) -> None:
        self._undo.append(command)
        if len(self._undo) > self._limit:
            self._undo.pop(0)
        self._redo.clear()

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self, song: Song) -> str | None:
        if not self._undo:
            return None
        command = self._undo.pop()
        command.undo(song)
        self._redo.append(command)
        return command.label

    def redo(self, song: Song) -> str | None:
        if not self._redo:
            return None
        command = self._redo.pop()
        command.redo(song)
        self._undo.append(command)
        return command.label
