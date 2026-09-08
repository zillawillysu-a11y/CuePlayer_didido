"""Song.video_clips persistence: round-trip, Unicode paths, and legacy migration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cueplayer.domain.models import Project, VideoClip
from cueplayer.persistence.project_store import load_project, save_project


def test_video_clip_roundtrip(tmp_path: Path) -> None:
    project = Project.create("演唱會")
    song = project.songs[0]
    project_dir = tmp_path / "中文專案"
    media = project_dir / "中文影片" / "開場.mp4"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"ftyp")
    clip = VideoClip.create(
        name="開場",
        path=media,
        start_seconds=1.5,
        source_in_seconds=0.5,
        duration_seconds=3.25,
    )
    clip.locked = True
    clip.hidden = False
    song.add_video_clip(clip)

    path = project_dir / "show.cueplayer.json"
    save_project(project, path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["songs"][0]["video_clips"][0]["path"] == "中文影片/開場.mp4"
    loaded = load_project(path)

    assert len(loaded.songs[0].video_clips) == 1
    loaded_clip = loaded.songs[0].video_clips[0]
    assert loaded_clip.id == clip.id
    assert loaded_clip.name == "開場"
    assert loaded_clip.path.resolve() == media.resolve()
    assert loaded_clip.start_seconds == 1.5
    assert loaded_clip.source_in_seconds == 0.5
    assert loaded_clip.duration_seconds == 3.25
    assert loaded_clip.source_out_seconds == 3.75
    assert loaded_clip.locked is True
    assert loaded_clip.hidden is False


def test_video_clip_still_image_roundtrip(tmp_path: Path) -> None:
    project = Project.create("演唱會")
    song = project.songs[0]
    project_dir = tmp_path / "show_dir"
    media = project_dir / "中文素材" / "標題.png"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"PNG")
    clip = VideoClip.create(
        name="標題卡",
        path=media,
        start_seconds=1.0,
        duration_seconds=5.0,
        media_kind="still",
        source_duration_seconds=0.0,
    )
    song.add_video_clip(clip)

    path = project_dir / "show.cueplayer.json"
    save_project(project, path)
    loaded = load_project(path)

    loaded_clip = loaded.songs[0].video_clips[0]
    assert loaded_clip.media_kind == "still"
    assert loaded_clip.source_duration_seconds == 0.0
    assert loaded_clip.path.resolve() == media.resolve()


def test_video_clip_volume_and_track_mute_roundtrip(tmp_path: Path) -> None:
    project = Project.create("演唱會")
    song = project.songs[0]
    clip = VideoClip.create(name="開場", path=Path("開場.mp4"), volume=0.35)
    song.add_video_clip(clip)
    song.video_track_muted = True

    path = tmp_path / "show.cueplayer.json"
    save_project(project, path)
    loaded = load_project(path)

    assert loaded.songs[0].video_clips[0].volume == pytest.approx(0.35)
    assert loaded.songs[0].video_track_muted is True


def test_song_music_volume_roundtrip(tmp_path: Path) -> None:
    """Dedicated music-bed gain for Video/Music alignment balancing (see AudioEngine.set_music_volume)."""
    project = Project.create("演唱會")
    song = project.songs[0]
    song.music_volume = 0.42

    path = tmp_path / "show.cueplayer.json"
    save_project(project, path)
    loaded = load_project(path)

    assert loaded.songs[0].music_volume == pytest.approx(0.42)


def test_song_music_volume_missing_field_defaults_to_unity(tmp_path: Path) -> None:
    """Older project files predate the Music volume fader."""
    project = Project.create("Legacy")
    path = tmp_path / "show.cueplayer.json"
    save_project(project, path)

    data = json.loads(path.read_text(encoding="utf-8"))
    del data["songs"][0]["music_volume"]
    path.write_text(json.dumps(data), encoding="utf-8")

    loaded = load_project(path)
    assert loaded.songs[0].music_volume == 1.0


def test_song_video_lane_height_roundtrip(tmp_path: Path) -> None:
    project = Project.create("演唱會")
    song = project.songs[0]
    song.video_lane_height = 96.0

    path = tmp_path / "show.cueplayer.json"
    save_project(project, path)
    loaded = load_project(path)

    assert loaded.songs[0].video_lane_height == pytest.approx(96.0)


def test_song_video_lane_height_missing_field_defaults(tmp_path: Path) -> None:
    project = Project.create("Legacy")
    path = tmp_path / "show.cueplayer.json"
    save_project(project, path)

    data = json.loads(path.read_text(encoding="utf-8"))
    del data["songs"][0]["video_lane_height"]
    path.write_text(json.dumps(data), encoding="utf-8")

    loaded = load_project(path)
    assert loaded.songs[0].video_lane_height == pytest.approx(40.0)


def test_video_clip_volume_missing_field_defaults_to_unity(tmp_path: Path) -> None:
    """Older project files predate the per-clip volume fader."""
    project = Project.create("Legacy")
    clip = VideoClip.create(name="x", path=Path("x.mp4"))
    project.songs[0].add_video_clip(clip)
    path = tmp_path / "show.cueplayer.json"
    save_project(project, path)

    data = json.loads(path.read_text(encoding="utf-8"))
    del data["songs"][0]["video_clips"][0]["volume"]
    del data["songs"][0]["video_track_muted"]
    path.write_text(json.dumps(data), encoding="utf-8")

    loaded = load_project(path)
    assert loaded.songs[0].video_clips[0].volume == 1.0
    assert loaded.songs[0].video_track_muted is False


def test_video_clip_default_empty_list(tmp_path: Path) -> None:
    project = Project.create("Untitled")
    path = tmp_path / "show.cueplayer.json"
    save_project(project, path)
    loaded = load_project(path)
    assert loaded.songs[0].video_clips == []


def test_video_clip_missing_duration_field_is_derived_from_source_range(tmp_path: Path) -> None:
    """Older project files won't have `duration_seconds`; derive it from source in/out."""
    project = Project.create("Legacy")
    clip = VideoClip.create(name="x", path=Path("x.mp4"), start_seconds=0.0, duration_seconds=4.0)
    project.songs[0].add_video_clip(clip)
    path = tmp_path / "show.cueplayer.json"
    save_project(project, path)

    data = json.loads(path.read_text(encoding="utf-8"))
    del data["songs"][0]["video_clips"][0]["duration_seconds"]
    path.write_text(json.dumps(data), encoding="utf-8")

    loaded = load_project(path)
    assert loaded.songs[0].video_clips[0].duration_seconds == 4.0


def test_video_clip_missing_duration_and_source_out_falls_back_to_default(tmp_path: Path) -> None:
    project = Project.create("Legacy")
    clip = VideoClip.create(name="x", path=Path("x.mp4"))
    project.songs[0].add_video_clip(clip)
    path = tmp_path / "show.cueplayer.json"
    save_project(project, path)

    data = json.loads(path.read_text(encoding="utf-8"))
    raw_clip = data["songs"][0]["video_clips"][0]
    del raw_clip["duration_seconds"]
    raw_clip["source_out_seconds"] = None
    path.write_text(json.dumps(data), encoding="utf-8")

    loaded = load_project(path)
    assert loaded.songs[0].video_clips[0].duration_seconds == 5.0


def test_video_clip_multiple_clips_preserve_order(tmp_path: Path) -> None:
    project = Project.create("Show")
    song = project.songs[0]
    song.add_video_clip(
        VideoClip.create(name="b", path=Path("b.mp4"), start_seconds=10.0, duration_seconds=2.0)
    )
    song.add_video_clip(
        VideoClip.create(name="a", path=Path("a.mp4"), start_seconds=0.0, duration_seconds=2.0)
    )
    path = tmp_path / "show.cueplayer.json"
    save_project(project, path)
    loaded = load_project(path)
    assert [c.name for c in loaded.songs[0].video_clips] == ["a", "b"]
