"""LTC clip persistence tests (schema v3 migration + save/load round-trip)."""

from __future__ import annotations

from cueplayer.domain.ltc_clips import add_ltc_clip
from cueplayer.domain.models import SCHEMA_VERSION, Project, Song
from cueplayer.persistence.project_migrations import migrate_project_dict
from cueplayer.persistence.project_store import load_project, save_project
from cueplayer.repository.project_repository import ProjectRepository


def test_migrate_v2_adds_ltc_clip_defaults() -> None:
    raw = {
        "schema_version": 2,
        "id": "p1",
        "name": "專案",
        "songs": [
            {"id": "s1", "name": "曲", "marks": [], "mark_lanes": []}
        ],
    }
    migrated = migrate_project_dict(raw, from_version=2)
    assert migrated["schema_version"] == 3
    song = migrated["songs"][0]
    assert song["ltc_source_mode"] == "auto"
    assert song["ltc_clips"] == []


def test_migrate_v2_sanitizes_handwritten_clips() -> None:
    raw = {
        "schema_version": 2,
        "id": "p1",
        "name": "專案",
        "songs": [
            {
                "id": "s1",
                "name": "曲",
                "ltc_source_mode": "clip_generator",
                "ltc_clips": [
                    {"timeline_start_seconds": 5.0, "duration_seconds": 10.0},
                    "garbage-entry",
                    {
                        "id": "clip-1",
                        "timeline_start_seconds": 20.0,
                        "duration_seconds": 15.0,
                        "start_timecode": "02:00:00:00",
                    },
                ],
            }
        ],
    }
    migrated = migrate_project_dict(raw, from_version=2)
    clips = migrated["songs"][0]["ltc_clips"]
    assert len(clips) == 2
    assert clips[0]["id"]  # filled with a uuid
    assert clips[0]["start_timecode"] == "01:00:00:00"
    assert clips[1]["id"] == "clip-1"
    assert clips[1]["start_timecode"] == "02:00:00:00"


def test_ltc_clips_save_load_round_trip(tmp_path) -> None:
    project = Project.create("Unicode 專案 中文")
    song = Song(id="s1", name="測試歌", duration_seconds=120.0)
    song.ltc_source_mode = "clip_generator"
    clip_a = add_ltc_clip(
        song,
        timeline_start_seconds=10.0,
        duration_seconds=40.0,
        start_timecode="01:15:00:00",
    )
    clip_b = add_ltc_clip(
        song,
        timeline_start_seconds=60.0,
        duration_seconds=30.0,
        start_timecode="02:00:00:00",
    )
    project.songs.append(song)

    path = tmp_path / "proj_中文.json"
    save_project(project, path)
    loaded = load_project(path)

    loaded_song = [s for s in loaded.songs if s.id == song.id][0]
    assert loaded_song.ltc_source_mode == "clip_generator"
    assert [c.id for c in loaded_song.ltc_clips] == [clip_a.id, clip_b.id]
    assert loaded_song.ltc_clips[0].timeline_start_seconds == 10.0
    assert loaded_song.ltc_clips[0].duration_seconds == 40.0
    assert loaded_song.ltc_clips[0].start_timecode == "01:15:00:00"
    assert loaded_song.ltc_clips[1].start_timecode == "02:00:00:00"


def test_legacy_v2_project_loads_with_defaults(tmp_path) -> None:
    import json

    project = Project.create("舊專案")
    project.songs.append(Song(id="s1", name="舊歌"))
    path = tmp_path / "legacy.json"
    save_project(project, path)

    # Downgrade to a schema-v2 payload (drop the v3 fields).
    data = json.loads(path.read_text(encoding="utf-8"))
    data["schema_version"] = 2
    for song in data["songs"]:
        song.pop("ltc_source_mode", None)
        song.pop("ltc_clips", None)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    loaded = load_project(path)
    song = loaded.songs[0]
    assert song.ltc_source_mode == "auto"
    assert song.ltc_clips == []
    assert loaded.schema_version == SCHEMA_VERSION == 3


def test_repository_round_trip_keeps_clips(tmp_path) -> None:
    from pathlib import Path

    repo = ProjectRepository()
    project = Project.create("repo 專案")
    song = project.songs[0]
    clip = add_ltc_clip(
        song,
        timeline_start_seconds=0.0,
        duration_seconds=20.0,
        start_timecode="03:30:00:00",
    )
    path = Path(tmp_path) / "repo_專案.json"
    repo.save(project, path)
    loaded = repo.load(path)
    loaded_song = [s for s in loaded.songs if s.id == song.id][0]
    assert [c.id for c in loaded_song.ltc_clips] == [clip.id]
    assert loaded_song.ltc_source_mode == "clip_generator"
