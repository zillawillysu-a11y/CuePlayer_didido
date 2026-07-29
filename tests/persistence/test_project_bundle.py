"""Collect Project Bundle — portable folder with project JSON + Media/<Folder>/."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cueplayer.domain.models import AudioTrack, Project, SetlistCategory, VideoClip
from cueplayer.persistence.media_layout import (
    UNFILED_FOLDER,
    sync_rename_setlist_media_folder,
    sync_song_media_to_setlist_folder,
)
from cueplayer.persistence.project_bundle import collect_project_bundle
from cueplayer.persistence.project_store import load_project, save_project


def test_collect_bundle_layout_and_relative_paths(tmp_path: Path) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    audio = sources / "主歌.wav"
    video = sources / "Loop.mp4"
    audio.write_bytes(b"RIFFDATA")
    video.write_bytes(b"ftypdata")

    project = Project.create("巡演包")
    act = SetlistCategory.create("第一幕")
    project.setlist_categories.append(act)
    song = project.songs[0]
    song.category_id = act.id
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
    assert (dest / "Media" / "第一幕" / "主歌.wav").is_file()
    assert (dest / "Media" / "第一幕" / "Loop.mp4").is_file()
    assert (dest / "Media" / UNFILED_FOLDER).is_dir()
    assert len(result.copied) == 2
    assert result.missing == []

    raw = json.loads(result.project_path.read_text(encoding="utf-8"))
    assert raw["songs"][0]["audio_tracks"][0]["path"] == "Media/第一幕/主歌.wav"
    assert raw["songs"][0]["video_clips"][0]["path"] == "Media/第一幕/Loop.mp4"

    # Relocate whole bundle — still loads.
    moved = tmp_path / "USB" / "巡演包"
    moved.parent.mkdir(parents=True)
    dest.rename(moved)
    loaded = load_project(moved / "巡演包.cueplayer.json")
    assert loaded.songs[0].audio_tracks[0].path.is_file()
    assert loaded.songs[0].video_clips[0].path.is_file()


def test_collect_bundle_unfiled_when_no_category(tmp_path: Path) -> None:
    audio = tmp_path / "loose.wav"
    audio.write_bytes(b"x")
    project = Project.create("Loose")
    project.songs[0].audio_tracks.append(
        AudioTrack(id="a1", name="Main", path=audio, role="main")
    )
    result = collect_project_bundle(
        project, tmp_path / "out", project_filename="loose.cueplayer.json"
    )
    assert (result.media_dir / UNFILED_FOLDER / "loose.wav").is_file()
    raw = json.loads(result.project_path.read_text(encoding="utf-8"))
    assert raw["songs"][0]["audio_tracks"][0]["path"] == f"Media/{UNFILED_FOLDER}/loose.wav"


def test_collect_bundle_clones_audio_caches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cueplayer.media.audio_disk_cache as mod
    from cueplayer.media.audio_disk_cache import (
        audio_cache_key,
        load_all_ltc_channels,
        load_cached_audio,
        save_cached_audio,
        save_ltc_channel,
    )
    from cueplayer.media.audio_loader import AudioBuffer, build_peak_pyramid
    import numpy as np

    monkeypatch.setattr(mod, "_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(mod, "_LTC_CACHE_FILE", tmp_path / "cache" / "ltc_channels.json")

    sources = tmp_path / "sources"
    sources.mkdir()
    audio = sources / "曲.wav"
    audio.write_bytes(b"RIFFDATA")
    samples = np.zeros((2400, 2), dtype=np.float32)
    mono, levels = build_peak_pyramid(samples, 48000)
    save_cached_audio(
        audio,
        AudioBuffer(
            path=audio, sample_rate=48000, samples=samples, mono=mono, peak_levels=levels
        ),
    )
    key = audio_cache_key(audio)
    assert key is not None
    save_ltc_channel(key, 1)

    project = Project.create("Warm")
    project.songs[0].audio_tracks.append(
        AudioTrack(id="a1", name="Main", path=audio, role="main")
    )
    result = collect_project_bundle(
        project, tmp_path / "out", project_filename="warm.cueplayer.json"
    )
    bundled_audio = result.media_dir / UNFILED_FOLDER / "曲.wav"
    assert bundled_audio.is_file()
    assert load_cached_audio(bundled_audio) is not None
    new_key = audio_cache_key(bundled_audio)
    assert new_key is not None
    assert load_all_ltc_channels().get(new_key) == 1


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
    files = [p for p in (result.media_dir / UNFILED_FOLDER).iterdir() if p.is_file()]
    assert len(files) == 1
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
    names = sorted(p.name for p in (result.media_dir / UNFILED_FOLDER).iterdir() if p.is_file())
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


def test_sync_move_song_between_media_folders(tmp_path: Path) -> None:
    root = tmp_path / "show"
    media = root / "Media"
    act1 = media / "Act1"
    act2 = media / "Act2"
    act1.mkdir(parents=True)
    act2.mkdir(parents=True)
    wav = act1 / "song.wav"
    wav.write_bytes(b"audio")
    project_file = root / "show.cueplayer.json"

    project = Project.create("Show")
    c1 = SetlistCategory.create("Act1")
    c2 = SetlistCategory.create("Act2")
    project.setlist_categories.extend([c1, c2])
    song = project.songs[0]
    song.category_id = c1.id
    song.audio_tracks.append(AudioTrack(id="a1", name="Main", path=wav, role="main"))
    save_project(project, project_file)

    song.category_id = c2.id
    moved = sync_song_media_to_setlist_folder(
        project, song, project_file=project_file
    )
    assert moved == 1
    assert not wav.exists()
    dest = act2 / "song.wav"
    assert dest.is_file()
    assert Path(song.audio_tracks[0].path).resolve() == dest.resolve()


def test_sync_rename_setlist_media_folder(tmp_path: Path) -> None:
    root = tmp_path / "show"
    media = root / "Media" / "舊名"
    media.mkdir(parents=True)
    wav = media / "a.wav"
    wav.write_bytes(b"x")
    project_file = root / "show.cueplayer.json"

    project = Project.create("Show")
    cat = SetlistCategory.create("舊名")
    project.setlist_categories.append(cat)
    song = project.songs[0]
    song.category_id = cat.id
    song.audio_tracks.append(AudioTrack(id="a1", name="Main", path=wav, role="main"))
    save_project(project, project_file)

    cat.name = "新名"
    n = sync_rename_setlist_media_folder(
        project,
        project_file=project_file,
        old_name="舊名",
        new_name="新名",
    )
    assert n >= 1
    assert (root / "Media" / "新名" / "a.wav").is_file()
    assert not (root / "Media" / "舊名").exists()
    assert Path(song.audio_tracks[0].path).name == "a.wav"
    assert Path(song.audio_tracks[0].path).parent.name == "新名"


def test_sync_ignores_external_media(tmp_path: Path) -> None:
    root = tmp_path / "show"
    (root / "Media").mkdir(parents=True)
    external = tmp_path / "elsewhere" / "ext.wav"
    external.parent.mkdir()
    external.write_bytes(b"ext")
    project_file = root / "show.cueplayer.json"

    project = Project.create("Show")
    cat = SetlistCategory.create("Act")
    project.setlist_categories.append(cat)
    song = project.songs[0]
    song.category_id = cat.id
    song.audio_tracks.append(
        AudioTrack(id="a1", name="Main", path=external, role="main")
    )
    save_project(project, project_file)

    assert sync_song_media_to_setlist_folder(project, song, project_file=project_file) == 0
    assert external.is_file()
    assert Path(song.audio_tracks[0].path).resolve() == external.resolve()
