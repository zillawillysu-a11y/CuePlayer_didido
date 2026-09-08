from datetime import datetime
from pathlib import Path

from cueplayer.domain.models import AudioTrack, Project, VideoClip
from cueplayer.domain.song_variant import SongVariant
from cueplayer.persistence.unused_media import (
    find_unused_media,
    quarantine_unused_media,
)


def test_unused_media_keeps_tracks_variants_and_video_with_unicode_paths(
    tmp_path: Path,
) -> None:
    root = tmp_path / "中文專案"
    media = root / "Media"
    media.mkdir(parents=True)
    project_file = root / "演出.cueplayer.json"
    track = media / "舊歌.wav"
    variant = media / "新版.flac"
    video = media / "參考影片.mp4"
    unused = media / "外層備份.wav"
    note = media / "請勿刪除.txt"
    for path in (track, variant, video, unused, note):
        path.write_bytes(path.name.encode("utf-8"))

    project = Project.create("演出")
    song = project.songs[0]
    song.audio_tracks = [AudioTrack("track", "Main", track, role="main")]
    song.variants = [SongVariant.create("新版", variant)]
    song.video_clips = [VideoClip.create("影片", video)]

    found = find_unused_media(project, project_file=project_file)

    assert [item.path for item in found] == [unused]


def test_quarantine_preserves_relative_layout_and_is_recoverable(tmp_path: Path) -> None:
    root = tmp_path / "show"
    source = root / "Media" / "Old Set" / "Song" / "unused.wav"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"unused")
    project_file = root / "show.cueplayer.json"
    project = Project.create("Show")
    files = find_unused_media(project, project_file=project_file)

    result = quarantine_unused_media(
        files,
        project_file=project_file,
        now=datetime(2026, 8, 15, 12, 34, 56),
    )

    expected = (
        root
        / ".cueplayer_trash"
        / "Unused Media 20260815_123456"
        / "Old Set"
        / "Song"
        / "unused.wav"
    )
    assert result.moved_files == (expected,)
    assert result.moved_bytes == 6
    assert expected.read_bytes() == b"unused"
    assert not source.exists()
