"""Shared drag-and-drop MIME helpers."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMimeData, QUrl

from cueplayer.ui.drag_drop import (
    AUDIO_SUFFIXES,
    audio_paths_from_mime,
    local_paths_from_mime,
    mime_looks_like_file_drop,
    rejected_audio_drop_reason,
    rejected_setlist_drop_reason,
    setlist_import_paths_from_mime,
    video_paths_from_mime,
)


def test_audio_suffixes_include_common_windows_types() -> None:
    assert ".wav" in AUDIO_SUFFIXES
    assert ".mp3" in AUDIO_SUFFIXES
    assert ".m4a" in AUDIO_SUFFIXES


def test_mime_looks_like_file_drop_with_urls() -> None:
    mime = QMimeData()
    assert mime_looks_like_file_drop(mime) is False
    mime.setUrls([QUrl.fromLocalFile(str(Path("C:/tmp/a.wav")))])
    assert mime_looks_like_file_drop(mime) is True


def test_mime_looks_like_file_drop_uri_list_without_urls() -> None:
    mime = QMimeData()
    mime.setData("text/uri-list", b"file:///C:/tmp/a.wav\r\n")
    assert mime_looks_like_file_drop(mime) is True


def test_audio_paths_from_mime_filters_by_suffix(tmp_path: Path) -> None:
    wav = tmp_path / "歌.wav"
    txt = tmp_path / "notes.txt"
    wav.write_bytes(b"RIFF")
    txt.write_text("x", encoding="utf-8")
    mime = QMimeData()
    mime.setUrls(
        [
            QUrl.fromLocalFile(str(wav)),
            QUrl.fromLocalFile(str(txt)),
            QUrl.fromLocalFile(str(tmp_path / "missing.mp3")),
        ]
    )
    paths = audio_paths_from_mime(mime)
    assert [p.name for p in paths] == ["歌.wav", "missing.mp3"]


def test_video_paths_from_mime_filters_by_suffix(tmp_path: Path) -> None:
    mp4 = tmp_path / "clip.mp4"
    wav = tmp_path / "song.wav"
    mp4.write_bytes(b"x")
    wav.write_bytes(b"RIFF")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(mp4)), QUrl.fromLocalFile(str(wav))])
    paths = video_paths_from_mime(mime)
    assert [p.name for p in paths] == ["clip.mp4"]


def test_local_paths_from_uri_list_without_has_urls() -> None:
    from PySide6.QtCore import QMimeData

    mime = QMimeData()
    mime.setData(
        "text/uri-list",
        b"file:///C:/Music/test%20song.wav\r\nfile:///D:/clips/intro.mp4\r\n",
    )
    paths = local_paths_from_mime(mime)
    assert len(paths) == 2
    assert paths[0].name == "test song.wav"
    assert paths[1].name == "intro.mp4"


def test_audio_paths_from_uri_list(tmp_path: Path) -> None:
    wav = tmp_path / "track.wav"
    wav.write_bytes(b"RIFF")
    uri = wav.as_uri().encode("utf-8")
    mime = QMimeData()
    mime.setData("text/uri-list", uri + b"\r\n")
    paths = audio_paths_from_mime(mime)
    assert len(paths) == 1
    assert paths[0].name == "track.wav"


def test_rejected_drop_reason_mentions_extension(tmp_path: Path) -> None:
    bad = tmp_path / "clip.mp4"
    bad.write_bytes(b"x")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(bad))])
    msg = rejected_audio_drop_reason(mime)
    assert ".mp4" in msg or "mp4" in msg


def test_setlist_import_paths_accepts_audio_and_video(tmp_path: Path) -> None:
    wav = tmp_path / "a.wav"
    mp4 = tmp_path / "b.mp4"
    wav.write_bytes(b"RIFF")
    mp4.write_bytes(b"x")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(wav)), QUrl.fromLocalFile(str(mp4))])
    paths = setlist_import_paths_from_mime(mime)
    assert [p.name for p in paths] == ["a.wav", "b.mp4"]


def test_rejected_setlist_drop_reason_mentions_video(tmp_path: Path) -> None:
    bad = tmp_path / "notes.txt"
    bad.write_text("x", encoding="utf-8")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(bad))])
    msg = rejected_setlist_drop_reason(mime)
    assert "video" in msg.lower() or ".txt" in msg
