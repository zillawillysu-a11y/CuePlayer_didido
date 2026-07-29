"""Portable relative media paths for project bundles."""

from __future__ import annotations

import json
from pathlib import Path

from cueplayer.domain.models import AudioTrack, Project, VideoClip
from cueplayer.persistence.media_paths import from_storage_path, to_storage_path
from cueplayer.persistence.project_store import load_project, save_project


def test_to_storage_path_relative_under_project(tmp_path: Path) -> None:
    project_dir = tmp_path / "show"
    media = project_dir / "media" / "主歌.wav"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"RIFF")
    stored = to_storage_path(media, project_dir)
    assert stored == "media/主歌.wav"
    assert not Path(stored).is_absolute()


def test_to_storage_path_absolute_outside_project(tmp_path: Path) -> None:
    project_dir = tmp_path / "show"
    project_dir.mkdir()
    outside = tmp_path / "elsewhere" / "ref.wav"
    outside.parent.mkdir()
    outside.write_bytes(b"RIFF")
    stored = to_storage_path(outside, project_dir)
    assert Path(stored).is_absolute()
    assert Path(stored) == outside.resolve()


def test_bundle_survives_move_to_any_path(tmp_path: Path) -> None:
    """Whole project folder can be relocated; relative media still resolves."""
    original = tmp_path / "OriginalShow"
    media_dir = original / "媒體"
    media_dir.mkdir(parents=True)
    audio = media_dir / "曲目一.wav"
    video = media_dir / "Loop.mp4"
    audio.write_bytes(b"RIFF")
    video.write_bytes(b"ftyp")
    project_file = original / "show.cueplayer.json"

    project = Project.create("Bundle Test")
    song = project.songs[0]
    song.audio_tracks.append(
        AudioTrack(id="a1", name="Main", path=audio, role="main")
    )
    song.video_clips.append(VideoClip.create("Loop", video, duration_seconds=2.0))
    save_project(project, project_file)

    raw = json.loads(project_file.read_text(encoding="utf-8"))
    assert raw["songs"][0]["audio_tracks"][0]["path"] == "媒體/曲目一.wav"
    assert raw["songs"][0]["video_clips"][0]["path"] == "媒體/Loop.mp4"

    relocated = tmp_path / "D_drive" / "Tour" / "MovedShow"
    relocated.parent.mkdir(parents=True)
    original.rename(relocated)
    new_project_file = relocated / "show.cueplayer.json"

    loaded = load_project(new_project_file)
    track = loaded.songs[0].audio_tracks[0]
    clip = loaded.songs[0].video_clips[0]
    assert track.path.is_file()
    assert clip.path.is_file()
    assert track.path.name == "曲目一.wav"
    assert clip.path.name == "Loop.mp4"


def test_from_storage_path_absolute_passthrough(tmp_path: Path) -> None:
    abs_path = tmp_path / "x.wav"
    abs_path.write_bytes(b"x")
    resolved = from_storage_path(str(abs_path), tmp_path / "show")
    assert resolved == abs_path
