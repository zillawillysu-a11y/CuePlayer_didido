"""In-memory undo/redo for Cue mark, video clip, and setlist edits."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from cueplayer.domain.models import Mark, Project, SetlistCategory, Song, VideoClip


@dataclass(frozen=True)
class MarkSnapshot:
    id: str
    lane_index: int
    time_seconds: float
    display_name: str = ""
    ma_export_name: str | None = None
    main_cue_id: str = ""

    @classmethod
    def from_mark(cls, mark: Mark) -> MarkSnapshot:
        return cls(
            id=mark.id,
            lane_index=mark.lane_index,
            time_seconds=mark.time_seconds,
            display_name=mark.display_name,
            ma_export_name=mark.ma_export_name,
            main_cue_id=mark.main_cue_id,
        )

    def to_mark(self) -> Mark:
        return Mark(
            id=self.id,
            lane_index=self.lane_index,
            time_seconds=self.time_seconds,
            display_name=self.display_name,
            ma_export_name=self.ma_export_name,
            main_cue_id=self.main_cue_id,
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


@dataclass
class UndoContext:
    """Project + current song for unified undo/redo."""

    project: Project
    current_song_id: str

    @property
    def song(self) -> Song:
        for s in self.project.songs:
            if s.id == self.current_song_id:
                return s
        return self.project.songs[0]


def _merge_setlist_state(live: Song, snap: Song) -> None:
    """Restore setlist-editable fields; keep marks / lanes on the live song."""
    live.setlist_number = snap.setlist_number
    live.category_id = snap.category_id
    live.name = snap.name
    live.ma_export_name = snap.ma_export_name
    live.bpm = snap.bpm
    live.row_color = snap.row_color
    live.start_timecode = snap.start_timecode
    live.fps = snap.fps
    live.duration_seconds = snap.duration_seconds
    live.audio_tracks = copy.deepcopy(snap.audio_tracks)
    live.video_clips = copy.deepcopy(snap.video_clips)


@dataclass(frozen=True)
class SetlistStateSnapshot:
    songs: tuple[Song, ...]
    categories: tuple[SetlistCategory, ...]

    @classmethod
    def capture(cls, project: Project) -> SetlistStateSnapshot:
        return cls(
            songs=tuple(copy.deepcopy(project.songs)),
            categories=tuple(copy.deepcopy(project.setlist_categories)),
        )

    def _fingerprint(self) -> tuple:
        song_fp = tuple(
            (
                s.id,
                float(s.setlist_number),
                s.category_id,
                s.name,
                s.ma_export_name,
                s.bpm,
                s.row_color or "",
                s.start_timecode,
                float(s.fps),
                len(s.audio_tracks),
                len(s.video_clips),
            )
            for s in self.songs
        )
        cat_fp = tuple(
            (c.id, c.name, bool(c.collapsed), c.row_color or "") for c in self.categories
        )
        return (song_fp, cat_fp)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SetlistStateSnapshot):
            return False
        return self._fingerprint() == other._fingerprint()

    def apply(self, project: Project) -> None:
        current_by_id = {s.id: s for s in project.songs}
        merged: list[Song] = []
        for snap in self.songs:
            live = current_by_id.get(snap.id)
            if live is None:
                merged.append(copy.deepcopy(snap))
            else:
                _merge_setlist_state(live, snap)
                merged.append(live)
        project.songs = merged
        project.setlist_categories = [copy.deepcopy(c) for c in self.categories]


@dataclass
class SetlistEditCommand:
    before: SetlistStateSnapshot
    after: SetlistStateSnapshot
    label: str
    current_song_id: str
    selected_song_ids: tuple[str, ...]

    def undo(self, ctx: UndoContext) -> None:
        self.before.apply(ctx.project)
        ctx.current_song_id = self.current_song_id

    def redo(self, ctx: UndoContext) -> None:
        self.after.apply(ctx.project)
        ctx.current_song_id = self.current_song_id


@dataclass
class SongScopedCommand:
    """Adapter: legacy mark/clip commands that operate on a single Song."""

    command: Any

    @property
    def label(self) -> str:
        return str(self.command.label)

    def undo(self, ctx: UndoContext) -> None:
        self.command.undo(ctx.song)

    def redo(self, ctx: UndoContext) -> None:
        self.command.redo(ctx.song)


_ContextCommand = SetlistEditCommand | SongScopedCommand


class UndoStack:
    def __init__(self, *, limit: int = 100) -> None:
        self._limit = max(1, limit)
        self._undo: list[_ContextCommand] = []
        self._redo: list[_ContextCommand] = []

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()

    def clear_song_scoped(self) -> None:
        self._undo = [c for c in self._undo if isinstance(c, SetlistEditCommand)]
        self._redo.clear()

    def push(self, command: Any) -> None:
        if isinstance(command, SetlistEditCommand):
            wrapped: _ContextCommand = command
        else:
            wrapped = SongScopedCommand(command)
        self._undo.append(wrapped)
        if len(self._undo) > self._limit:
            self._undo.pop(0)
        self._redo.clear()

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self, ctx: UndoContext | Song) -> tuple[str, SetlistEditCommand | None] | str | None:
        """Undo one step. Pass UndoContext for UI; pass Song for legacy domain tests."""
        if isinstance(ctx, Song):
            song = ctx
            project = Project.create("_undo")
            project.songs = [song]
            uctx = UndoContext(project=project, current_song_id=song.id)
            result = self._undo_one(uctx)
            return result[0] if result is not None else None
        return self._undo_one(ctx)

    def redo(self, ctx: UndoContext | Song) -> tuple[str, SetlistEditCommand | None] | str | None:
        if isinstance(ctx, Song):
            song = ctx
            project = Project.create("_undo")
            project.songs = [song]
            uctx = UndoContext(project=project, current_song_id=song.id)
            result = self._redo_one(uctx)
            return result[0] if result is not None else None
        return self._redo_one(ctx)

    def _undo_one(
        self, ctx: UndoContext
    ) -> tuple[str, SetlistEditCommand | None] | None:
        if not self._undo:
            return None
        command = self._undo.pop()
        command.undo(ctx)
        self._redo.append(command)
        setlist = command if isinstance(command, SetlistEditCommand) else None
        return command.label, setlist

    def _redo_one(
        self, ctx: UndoContext
    ) -> tuple[str, SetlistEditCommand | None] | None:
        if not self._redo:
            return None
        command = self._redo.pop()
        command.redo(ctx)
        self._undo.append(command)
        setlist = command if isinstance(command, SetlistEditCommand) else None
        return command.label, setlist
