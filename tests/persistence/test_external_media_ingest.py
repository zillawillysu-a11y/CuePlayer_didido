"""Detect / ingest media dropped from outside the project folder."""

from __future__ import annotations

from pathlib import Path

from cueplayer.domain.models import AudioTrack, Project, SetlistCategory, VideoClip
from cueplayer.persistence.media_layout import (
    ingest_external_media_into_project,
    scan_external_media,
)
from cueplayer.persistence.project_store import load_project, save_project


def test_scan_external_media_finds_outside_project(tmp_path: Path) -> None:
    project_dir = tmp_path / "show"
    project_dir.mkdir()
    project_file = project_dir / "show.cueplayer.json"
    outside = tmp_path / "Downloads" / "新歌.wav"
    outside.parent.mkdir()
    outside.write_bytes(b"RIFF")

    project = Project.create("Show")
    cat = SetlistCategory.create("開場")
    project.setlist_categories.append(cat)
    song = project.songs[0]
    song.name = "曲目"
    song.category_id = cat.id
    song.audio_tracks.append(
        AudioTrack(id="a1", name="Main", path=outside, role="main")
    )
    save_project(project, project_file)

    found = scan_external_media(project, project_file=project_file)
    assert len(found) == 1
    assert found[0].basename == "新歌.wav"
    assert found[0].kind == "audio"


def test_scan_ignores_files_already_under_media(tmp_path: Path) -> None:
    project_dir = tmp_path / "show"
    project_dir.mkdir()
    project_file = project_dir / "show.cueplayer.json"
    inside = project_dir / "Media" / "_Unfiled" / "Song" / "main.wav"
    inside.parent.mkdir(parents=True)
    inside.write_bytes(b"RIFF")

    project = Project.create("Show")
    song = project.songs[0]
    song.name = "Song"
    song.audio_tracks.append(
        AudioTrack(id="a1", name="Main", path=inside, role="main")
    )
    assert scan_external_media(project, project_file=project_file) == []


def test_scan_ignores_files_under_project_root_outside_media(tmp_path: Path) -> None:
    """Legacy flat files under the project root are relocated by Save sync, not this prompt."""
    project_dir = tmp_path / "show"
    project_dir.mkdir()
    project_file = project_dir / "show.cueplayer.json"
    loose = project_dir / "loose.wav"
    loose.write_bytes(b"RIFF")
    project = Project.create("Show")
    project.songs[0].audio_tracks.append(
        AudioTrack(id="a1", name="Main", path=loose, role="main")
    )
    assert scan_external_media(project, project_file=project_file) == []


def test_ingest_copies_external_into_media_and_leaves_original(tmp_path: Path) -> None:
    project_dir = tmp_path / "show"
    project_dir.mkdir()
    project_file = project_dir / "show.cueplayer.json"
    outside_audio = tmp_path / "src" / "bed.wav"
    outside_video = tmp_path / "src" / "loop.mp4"
    outside_audio.parent.mkdir()
    outside_audio.write_bytes(b"AUDIO")
    outside_video.write_bytes(b"VIDEO")

    project = Project.create("Show")
    cat = SetlistCategory.create("第一幕")
    project.setlist_categories.append(cat)
    song = project.songs[0]
    song.name = "開場"
    song.category_id = cat.id
    song.audio_tracks.append(
        AudioTrack(id="a1", name="Main", path=outside_audio, role="main")
    )
    song.video_clips.append(
        VideoClip.create("Loop", outside_video, duration_seconds=1.0)
    )

    external = scan_external_media(project, project_file=project_file)
    assert len(external) == 2
    result = ingest_external_media_into_project(
        project, project_file=project_file, only=external
    )
    assert len(result.copied) == 2
    assert result.failed == []
    assert outside_audio.is_file()
    assert outside_video.is_file()

    dest_audio = project_dir / "Media" / "第一幕" / "開場" / "bed.wav"
    dest_video = project_dir / "Media" / "第一幕" / "開場" / "loop.mp4"
    assert dest_audio.is_file()
    assert dest_video.is_file()
    assert Path(song.audio_tracks[0].path).resolve() == dest_audio.resolve()
    assert Path(song.video_clips[0].path).resolve() == dest_video.resolve()

    save_project(project, project_file)
    loaded = load_project(project_file)
    assert loaded.songs[0].audio_tracks[0].path.is_file()
    # Portable relative path under the project folder.
    raw = project_file.read_text(encoding="utf-8")
    assert "Media/第一幕/開場/bed.wav" in raw
