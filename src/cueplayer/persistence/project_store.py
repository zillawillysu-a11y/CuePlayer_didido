"""UTF-8 JSON project persistence with schema versioning."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cueplayer.domain.models import (
    SCHEMA_VERSION,
    AudioTrack,
    MarkLane,
    Project,
    Song,
    VideoClip,
)


class SchemaError(ValueError):
    """Raised when a project file cannot be migrated or parsed."""


def _path_to_str(path: Path) -> str:
    return str(path)


def _str_to_path(value: str) -> Path:
    return Path(value)


def project_to_dict(project: Project) -> dict[str, Any]:
    return {
        "schema_version": project.schema_version,
        "id": project.id,
        "name": project.name,
        "songs": [
            {
                "id": song.id,
                "name": song.name,
                "start_timecode": song.start_timecode,
                "fps": song.fps,
                "audio_tracks": [
                    {
                        "id": track.id,
                        "name": track.name,
                        "path": _path_to_str(track.path),
                        "role": track.role,
                        "color": track.color,
                        "muted": track.muted,
                        "solo": track.solo,
                        "locked": track.locked,
                        "hidden": track.hidden,
                        "offset_seconds": track.offset_seconds,
                    }
                    for track in song.audio_tracks
                ],
                "video_clips": [
                    {
                        "id": clip.id,
                        "name": clip.name,
                        "path": _path_to_str(clip.path),
                        "start_seconds": clip.start_seconds,
                        "source_in_seconds": clip.source_in_seconds,
                        "source_out_seconds": clip.source_out_seconds,
                        "locked": clip.locked,
                        "hidden": clip.hidden,
                    }
                    for clip in song.video_clips
                ],
                "mark_lanes": [
                    {
                        "index": lane.index,
                        "name": lane.name,
                        "lane_type": lane.lane_type,
                        "color": lane.color,
                        "shortcut": lane.shortcut,
                        "visible": lane.visible,
                        "locked": lane.locked,
                        "export_enabled": lane.export_enabled,
                    }
                    for lane in song.mark_lanes
                ],
            }
            for song in project.songs
        ],
    }


def project_from_dict(data: dict[str, Any]) -> Project:
    version = int(data.get("schema_version", 0))
    data = migrate_project_dict(data, version)

    songs: list[Song] = []
    for song_data in data.get("songs", []):
        audio_tracks = [
            AudioTrack(
                id=track["id"],
                name=track["name"],
                path=_str_to_path(track["path"]),
                role=track.get("role", "reference"),
                color=track.get("color", "#2BB673"),
                muted=bool(track.get("muted", False)),
                solo=bool(track.get("solo", False)),
                locked=bool(track.get("locked", False)),
                hidden=bool(track.get("hidden", False)),
                offset_seconds=float(track.get("offset_seconds", 0.0)),
            )
            for track in song_data.get("audio_tracks", [])
        ]
        video_clips = [
            VideoClip(
                id=clip["id"],
                name=clip["name"],
                path=_str_to_path(clip["path"]),
                start_seconds=float(clip.get("start_seconds", 0.0)),
                source_in_seconds=float(clip.get("source_in_seconds", 0.0)),
                source_out_seconds=clip.get("source_out_seconds"),
                locked=bool(clip.get("locked", False)),
                hidden=bool(clip.get("hidden", False)),
            )
            for clip in song_data.get("video_clips", [])
        ]
        mark_lanes = [
            MarkLane(
                index=int(lane["index"]),
                name=lane["name"],
                lane_type=lane.get("lane_type", "top_button"),
                color=lane.get("color", "#4C8BF5"),
                shortcut=lane.get("shortcut", ""),
                visible=bool(lane.get("visible", True)),
                locked=bool(lane.get("locked", False)),
                export_enabled=bool(lane.get("export_enabled", True)),
            )
            for lane in song_data.get("mark_lanes", [])
        ]
        songs.append(
            Song(
                id=song_data["id"],
                name=song_data["name"],
                start_timecode=song_data.get("start_timecode", "01:00:00:00"),
                fps=float(song_data.get("fps", 30.0)),
                audio_tracks=audio_tracks,
                video_clips=video_clips,
                mark_lanes=mark_lanes,
            )
        )

    return Project(
        id=data["id"],
        name=data["name"],
        schema_version=int(data["schema_version"]),
        songs=songs,
    )


def migrate_project_dict(data: dict[str, Any], from_version: int) -> dict[str, Any]:
    """Migrate older project dicts up to SCHEMA_VERSION."""
    if from_version > SCHEMA_VERSION:
        raise SchemaError(
            f"Project schema_version {from_version} is newer than supported {SCHEMA_VERSION}."
        )

    migrated = dict(data)
    version = from_version
    if version == 0:
        migrated.setdefault("schema_version", SCHEMA_VERSION)
        migrated.setdefault("songs", [])
        version = 1

    if version != SCHEMA_VERSION:
        raise SchemaError(f"No migration path from schema_version {from_version}.")

    migrated["schema_version"] = SCHEMA_VERSION
    return migrated


def save_project(project: Project, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = project_to_dict(project)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    path.write_text(text + "\n", encoding="utf-8")


def load_project(path: Path) -> Project:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise SchemaError("Project file root must be a JSON object.")
    return project_from_dict(data)
