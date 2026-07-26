"""Core domain models for Project / Song (MVP skeleton)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from uuid import uuid4

SCHEMA_VERSION = 1

LaneType = Literal["main", "top_button"]
AudioRole = Literal["main", "reference"]


def _new_id() -> str:
    return uuid4().hex


@dataclass
class MarkLane:
    index: int
    name: str
    lane_type: LaneType = "top_button"
    color: str = "#4C8BF5"
    shortcut: str = ""
    visible: bool = True
    locked: bool = False
    export_enabled: bool = True


@dataclass
class AudioTrack:
    id: str
    name: str
    path: Path
    role: AudioRole = "reference"
    color: str = "#2BB673"
    muted: bool = False
    solo: bool = False
    locked: bool = False
    hidden: bool = False
    offset_seconds: float = 0.0


@dataclass
class VideoClip:
    id: str
    name: str
    path: Path
    start_seconds: float = 0.0
    source_in_seconds: float = 0.0
    source_out_seconds: float | None = None
    locked: bool = False
    hidden: bool = False


@dataclass
class Song:
    id: str
    name: str
    start_timecode: str = "01:00:00:00"
    fps: float = 30.0
    audio_tracks: list[AudioTrack] = field(default_factory=list)
    video_clips: list[VideoClip] = field(default_factory=list)
    mark_lanes: list[MarkLane] = field(default_factory=list)

    @classmethod
    def create(cls, name: str) -> Song:
        lanes = [
            MarkLane(index=1, name="Main", lane_type="main", shortcut="1", color="#E74C3C"),
        ]
        for i in range(2, 10):
            lanes.append(
                MarkLane(
                    index=i,
                    name=f"Top Button {i}",
                    lane_type="top_button",
                    shortcut=str(i),
                )
            )
        return cls(id=_new_id(), name=name, mark_lanes=lanes)


@dataclass
class Project:
    id: str
    name: str
    schema_version: int = SCHEMA_VERSION
    songs: list[Song] = field(default_factory=list)

    @classmethod
    def create(cls, name: str) -> Project:
        return cls(id=_new_id(), name=name, songs=[Song.create("未命名歌曲")])
