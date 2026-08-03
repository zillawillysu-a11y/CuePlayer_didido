"""SongVariant persistence + schema v2 migration tests."""

from __future__ import annotations

import json
from pathlib import Path

from cueplayer.domain.models import SCHEMA_VERSION, AudioTrack, Project, Song
from cueplayer.domain.song_variant import SongVariant
from cueplayer.persistence.project_migrations import SchemaError, migrate_project_dict
from cueplayer.persistence.project_store import load_project, save_project
from cueplayer.repository.project_repository import ProjectRepository


def test_schema_version_is_two() -> None:
    assert SCHEMA_VERSION == 2


def test_migrate_v0_to_v2_empty_songs() -> None:
    data = migrate_project_dict({"id": "abc", "name": "測試", "songs": []}, from_version=0)
    assert data["schema_version"] == 2


def test_migrate_v1_builds_variants_from_audio_tracks() -> None:
    raw = {
        "schema_version": 1,
        "id": "p1",
        "name": "專案",
        "songs": [
            {
                "id": "s1",
                "name": "曲",
                "audio_tracks": [
                    {
                        "id": "t-old",
                        "name": "Old",
                        "path": "Media/old.wav",
                        "role": "reference",
                        "offset_seconds": 0.25,
                        "hidden": False,
                    },
                    {
                        "id": "t-main",
                        "name": "Main",
                        "path": "Media/main.wav",
                        "role": "main",
                        "offset_seconds": 0.0,
                    },
                ],
                "marks": [],
                "mark_lanes": [],
            }
        ],
    }
    migrated = migrate_project_dict(raw, from_version=1)
    assert migrated["schema_version"] == 2
    song = migrated["songs"][0]
    assert len(song["variants"]) == 2
    assert song["selected_variant_id"] == "variant-t-main"
    assert song["variants"][0]["anchor_offset"] == 0.25
    assert song["variants"][0]["metadata"]["legacy_role"] == "reference"


def test_reject_future_schema() -> None:
    import pytest

    with pytest.raises(SchemaError):
        migrate_project_dict({"schema_version": 99, "id": "x", "name": "y"}, from_version=99)


def test_round_trip_variants_unicode(tmp_path: Path) -> None:
    audio = tmp_path / "混音" / "主.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"wav")
    project = Project.create("燈光")
    song = Song.create("第一首")
    variant = SongVariant.create(
        "新版",
        audio,
        anchor_offset=0.1,
        metadata={"note": "試"},
    )
    song.variants = [variant]
    song.selected_variant_id = variant.id
    song.audio_tracks = [
        AudioTrack(id="main_audio", name="主", path=audio, role="main"),
    ]
    project.songs = [song]
    path = tmp_path / "專案.json"
    save_project(project, path)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 2
    assert data["songs"][0]["variants"][0]["name"] == "新版"
    assert "\\u" not in path.read_text(encoding="utf-8")

    loaded = load_project(path)
    assert loaded.schema_version == 2
    assert len(loaded.songs[0].variants) == 1
    assert loaded.songs[0].selected_variant_id == variant.id
    assert loaded.songs[0].variants[0].path == audio
    assert loaded.songs[0].variants[0].anchor_offset == 0.1
    assert loaded.songs[0].variants[0].metadata["note"] == "試"
    assert loaded.songs[0].selected_audio_path() == audio


def test_load_legacy_v1_file_via_repository(tmp_path: Path) -> None:
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    # Minimal v1-shaped JSON (pre-variants).
    payload = {
        "schema_version": 1,
        "id": "pid",
        "name": "Legacy",
        "songs": [
            {
                "id": "sid",
                "name": "Song",
                "start_timecode": "01:00:00:00",
                "fps": 30.0,
                "duration_seconds": 10.0,
                "audio_tracks": [
                    {
                        "id": "main_audio",
                        "name": "music",
                        "path": str(audio),
                        "role": "main",
                        "color": "#2BB673",
                        "muted": False,
                        "solo": False,
                        "locked": False,
                        "hidden": False,
                        "offset_seconds": 0.0,
                    }
                ],
                "video_clips": [],
                "mark_lanes": [],
                "marks": [],
            }
        ],
    }
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    repo = ProjectRepository()
    loaded = repo.load(path)
    assert loaded.schema_version == 2
    assert len(loaded.songs[0].variants) == 1
    assert loaded.songs[0].selected_variant() is not None
    assert loaded.songs[0].selected_audio_path() == audio

    repo.save(loaded, path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == 2
    assert saved["songs"][0]["variants"]
    assert saved["songs"][0]["audio_tracks"]  # Phase A: tracks still written
