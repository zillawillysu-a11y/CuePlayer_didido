"""Collect Project Bundle — portable folder with project JSON + Media/."""

from __future__ import annotations

import json
from pathlib import Path

from cueplayer.domain.models import AudioTrack, Project, VideoClip
from cueplayer.persistence.project_bundle import collect_project_bundle
from cueplayer.persistence.project_store import load_project


def test_collect_bundle_layout_and_relative_paths(tmp_path: Path) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    audio = sources / "主歌.wav"
    video = sources / "Loop.mp4"
    audio.write_bytes(b"RIFFDATA")
    video.write_bytes(b"ftypdata")

    project = Project.create("巡演包")
    song = project.songs[0]
    song.audio_tracks.append(
        AudioTrack(id="a1", name="Main", path=audio, role="main")
    )
    song.video_clips.append(VideoClip.create("Loop", video, duration_seconds=2.0))

    dest = tmp_path / "BundleOut"
    result = collect_project_bundle(
        project,
        dest,
        project_filename="巡演包.cueplayer.json",
        media_subdir="Media",
    )

    assert result.project_path == dest / "巡演包.cueplayer.json"
    assert result.project_path.is_file()
    assert result.media_dir == dest / "Media"
    assert (dest / "Media" / "主歌.wav").is_file()
    assert (dest / "Media" / "Loop.mp4").is_file()
    assert len(result.copied) == 2
    assert result.missing == []

    raw = json.loads(result.project_path.read_text(encoding="utf-8"))
    assert raw["songs"][0]["audio_tracks"][0]["path"] == "Media/主歌.wav"
    assert raw["songs"][0]["video_clips"][0]["path"] == "Media/Loop.mp4"

    # Relocate whole bundle — still loads.
    moved = tmp_path / "USB" / "巡演包"
    moved.parent.mkdir(parents=True)
    dest.rename(moved)
    loaded = load_project(moved / "巡演包.cueplayer.json")
    assert loaded.songs[0].audio_tracks[0].path.is_file()
    assert loaded.songs[0].video_clips[0].path.is_file()


def test_collect_bundle_dedupes_shared_source(tmp_path: Path) -> None:
    shared = tmp_path / "shared.wav"
    shared.write_bytes(b"SAME")
    project = Project.create("Share")
    song = project.songs[0]
    song.audio_tracks.append(
        AudioTrack(id="a1", name="Main", path=shared, role="main")
    )
    song.audio_tracks.append(
        AudioTrack(id="a2", name="Ref", path=shared, role="reference")
    )
    result = collect_project_bundle(
        project, tmp_path / "out", project_filename="share.cueplayer.json"
    )
    assert len(result.copied) == 1
    assert len(list(result.media_dir.iterdir())) == 1
    loaded = load_project(result.project_path)
    assert loaded.songs[0].audio_tracks[0].path == loaded.songs[0].audio_tracks[1].path


def test_collect_bundle_renames_basename_clash(tmp_path: Path) -> None:
    a = tmp_path / "one" / "same.wav"
    b = tmp_path / "two" / "same.wav"
    a.parent.mkdir(parents=True)
    b.parent.mkdir(parents=True)
    a.write_bytes(b"AAA")
    b.write_bytes(b"BBB")
    project = Project.create("Clash")
    project.songs[0].audio_tracks.append(
        AudioTrack(id="a1", name="A", path=a, role="main")
    )
    project.songs[0].audio_tracks.append(
        AudioTrack(id="a2", name="B", path=b, role="reference")
    )
    result = collect_project_bundle(
        project, tmp_path / "out", project_filename="clash.cueplayer.json"
    )
    names = sorted(p.name for p in result.media_dir.iterdir())
    assert names == ["same.wav", "same_2.wav"]
    assert len(result.renamed) == 1


def test_collect_bundle_reports_missing(tmp_path: Path) -> None:
    present = tmp_path / "ok.wav"
    present.write_bytes(b"ok")
    project = Project.create("Partial")
    project.songs[0].audio_tracks.append(
        AudioTrack(id="a1", name="Ok", path=present, role="main")
    )
    project.songs[0].audio_tracks.append(
        AudioTrack(
            id="a2",
            name="Gone",
            path=tmp_path / "nope" / "missing.wav",
            role="reference",
        )
    )
    result = collect_project_bundle(
        project, tmp_path / "out", project_filename="partial.cueplayer.json"
    )
    assert len(result.copied) == 1
    assert len(result.missing) == 1
    loaded = load_project(result.project_path)
    assert loaded.songs[0].audio_tracks[0].path.is_file()
    assert not loaded.songs[0].audio_tracks[1].path.is_file()
