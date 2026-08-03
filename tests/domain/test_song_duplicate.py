"""Duplicate setlist song: copy marks/media/settings with fresh ids."""

from __future__ import annotations

from pathlib import Path

from cueplayer.domain.models import AudioTrack, Mark, Song, VideoClip


def test_song_duplicate_copies_marks_and_media_with_new_ids(tmp_path: Path) -> None:
    song = Song.create("Original")
    song.setlist_number = 2.0
    song.ma_export_name = "Original_EN"
    song.bpm = 128.0
    song.row_color = "#336699"
    audio = tmp_path / "music.wav"
    audio.write_bytes(b"wav")
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"mp4")
    song.audio_tracks = [
        AudioTrack(id="audio-a", name="music", path=audio, role="main"),
    ]
    clip = VideoClip.create(
        name="clip",
        path=video,
        start_seconds=1.0,
        duration_seconds=4.0,
    )
    song.add_video_clip(clip)
    mark = song.add_mark(1, 3.5, display_name="Drop")
    mark.ma_export_name = "Drop_EN"

    dup = song.duplicate(name="Original v2", setlist_number=3.0)

    assert dup.id != song.id
    assert dup.name == "Original v2"
    assert dup.setlist_number == 3.0
    assert dup.ma_export_name == "Original_EN"
    assert dup.bpm == 128.0
    assert dup.row_color == "#336699"
    assert len(dup.mark_lanes) == len(song.mark_lanes)
    assert len(dup.marks) == 1
    assert dup.marks[0].id != mark.id
    assert dup.marks[0].time_seconds == 3.5
    assert dup.marks[0].display_name == "Drop"
    assert dup.marks[0].ma_export_name == "Drop_EN"
    assert len(dup.audio_tracks) == 1
    assert dup.audio_tracks[0].id != "audio-a"
    assert dup.audio_tracks[0].path == audio
    assert len(dup.video_clips) == 1
    assert dup.video_clips[0].id != clip.id
    assert dup.video_clips[0].path == video
    assert dup.video_clips[0].start_seconds == 1.0


def test_song_duplicate_default_name_suffix() -> None:
    song = Song.create("主歌")
    dup = song.duplicate()
    assert dup.name == "主歌 (copy)"
