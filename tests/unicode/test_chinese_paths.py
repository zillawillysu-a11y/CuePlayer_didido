"""Unicode / Chinese path persistence tests."""

from __future__ import annotations

import json
from pathlib import Path

from cueplayer.domain.models import AudioTrack, Project, VideoClip
from cueplayer.persistence.project_store import load_project, save_project


def test_chinese_project_round_trip(tmp_path: Path) -> None:
    project_dir = tmp_path / "專案資料夾" / "演唱會_測試"
    project_dir.mkdir(parents=True)
    media_dir = project_dir / "媒體"
    media_dir.mkdir()

    audio_path = media_dir / "主歌_舊版.wav"
    video_path = media_dir / "VJ_Loop_一.mp4"
    audio_path.write_bytes(b"RIFF")
    video_path.write_bytes(b"ftyp")

    project = Project.create("燈光編程專案")
    song = project.songs[0]
    song.name = "第一首歌"
    song.audio_tracks.append(
        AudioTrack(
            id="audio1",
            name="舊版音樂",
            path=audio_path,
            role="main",
        )
    )
    song.video_clips.append(
        VideoClip(
            id="video1",
            name="Loop 一",
            path=video_path,
            start_seconds=1.5,
        )
    )

    project_file = project_dir / "燈光編程專案.cueplayer.json"
    save_project(project, project_file)

    raw = project_file.read_text(encoding="utf-8")
    assert "燈光編程專案" in raw
    assert "主歌_舊版.wav" in raw
    assert "\\u" not in raw  # must not ASCII-escape Chinese

    loaded = load_project(project_file)
    assert loaded.name == "燈光編程專案"
    assert loaded.schema_version == 2
    assert loaded.songs[0].name == "第一首歌"
    assert loaded.songs[0].audio_tracks[0].path == audio_path
    assert loaded.songs[0].video_clips[0].path == video_path
    assert loaded.songs[0].mark_lanes[0].lane_type == "main"
    assert len(loaded.songs[0].mark_lanes) == 9


def test_schema_version_present_in_saved_json(tmp_path: Path) -> None:
    project = Project.create("Schema測試")
    path = tmp_path / "中文" / "schema.json"
    save_project(project, path)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 2
    assert data["name"] == "Schema測試"
