"""Missing media scan and folder basename relink."""

from __future__ import annotations

from pathlib import Path

from cueplayer.domain.media_relink import (
    apply_relink,
    relink_from_folder,
    scan_missing_media,
)
from cueplayer.domain.models import AudioTrack, Project, VideoClip


def _project_with_media(audio: Path, video: Path) -> Project:
    project = Project.create("Relink")
    song = project.songs[0]
    song.name = "Opening"
    song.audio_tracks.append(
        AudioTrack(id="aud1", name="Main", path=audio, role="main")
    )
    song.video_clips.append(
        VideoClip(id="vid1", name="VJ", path=video, duration_seconds=3.0)
    )
    return project


def test_scan_missing_media(tmp_path: Path) -> None:
    missing_audio = tmp_path / "gone" / "a.wav"
    missing_video = tmp_path / "gone" / "b.mp4"
    present = tmp_path / "here.wav"
    present.write_bytes(b"RIFF")
    project = _project_with_media(missing_audio, missing_video)
    project.songs[0].audio_tracks.append(
        AudioTrack(id="aud2", name="Ref", path=present, role="reference")
    )
    missing = scan_missing_media(project)
    assert len(missing) == 2
    kinds = {m.kind for m in missing}
    assert kinds == {"audio", "video"}


def test_apply_relink_file(tmp_path: Path) -> None:
    old = tmp_path / "old" / "song.wav"
    new = tmp_path / "new" / "song.wav"
    new.parent.mkdir(parents=True)
    new.write_bytes(b"RIFF")
    project = _project_with_media(old, tmp_path / "v.mp4")
    missing = scan_missing_media(project)
    audio_ref = next(m for m in missing if m.kind == "audio")
    assert apply_relink(project, audio_ref, new)
    assert project.songs[0].audio_tracks[0].path == new
    assert not any(m.kind == "audio" for m in scan_missing_media(project))


def test_relink_from_folder_by_basename(tmp_path: Path) -> None:
    old_audio = tmp_path / "was" / "曲目.wav"
    old_video = tmp_path / "was" / "Loop.mp4"
    bundle = tmp_path / "bundle" / "media"
    bundle.mkdir(parents=True)
    new_audio = bundle / "曲目.wav"
    new_video = bundle / "Loop.mp4"
    new_audio.write_bytes(b"RIFF")
    new_video.write_bytes(b"ftyp")

    project = _project_with_media(old_audio, old_video)
    missing = scan_missing_media(project)
    assert len(missing) == 2

    result = relink_from_folder(project, missing, tmp_path / "bundle")
    assert len(result.linked) == 2
    assert not result.unmatched
    assert not result.ambiguous
    assert project.songs[0].audio_tracks[0].path == new_audio.resolve() or (
        project.songs[0].audio_tracks[0].path == new_audio
    )
    assert scan_missing_media(project) == []


def test_relink_folder_ambiguous_same_basename(tmp_path: Path) -> None:
    old = tmp_path / "missing" / "same.wav"
    folder = tmp_path / "pool"
    (folder / "a").mkdir(parents=True)
    (folder / "b").mkdir(parents=True)
    (folder / "a" / "same.wav").write_bytes(b"1")
    (folder / "b" / "same.wav").write_bytes(b"2")
    project = Project.create("Ambiguous")
    project.songs[0].audio_tracks.append(
        AudioTrack(id="x", name="Main", path=old, role="main")
    )
    missing = scan_missing_media(project)
    result = relink_from_folder(project, missing, folder)
    assert result.linked == []
    assert len(result.ambiguous) == 1
    assert project.songs[0].audio_tracks[0].path == old
