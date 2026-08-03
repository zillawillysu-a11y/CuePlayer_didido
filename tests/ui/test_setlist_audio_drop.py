"""Setlist Explorer audio-drop MIME helpers."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMimeData, QUrl

from cueplayer.ui.main_window import (
    _AUDIO_SUFFIXES,
    _audio_paths_from_mime,
    _mime_looks_like_file_drop,
    _rejected_drop_reason,
)


def test_audio_suffixes_include_common_windows_types() -> None:
    assert ".wav" in _AUDIO_SUFFIXES
    assert ".mp3" in _AUDIO_SUFFIXES
    assert ".m4a" in _AUDIO_SUFFIXES


def test_mime_looks_like_file_drop_with_urls() -> None:
    mime = QMimeData()
    assert _mime_looks_like_file_drop(mime) is False
    mime.setUrls([QUrl.fromLocalFile(str(Path("C:/tmp/a.wav")))])
    assert _mime_looks_like_file_drop(mime) is True


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
    paths = _audio_paths_from_mime(mime)
    assert [p.name for p in paths] == ["歌.wav", "missing.mp3"]


def test_rejected_drop_reason_mentions_extension(tmp_path: Path) -> None:
    bad = tmp_path / "clip.mp4"
    bad.write_bytes(b"x")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(bad))])
    msg = _rejected_drop_reason(mime)
    assert ".mp4" in msg or "mp4" in msg
