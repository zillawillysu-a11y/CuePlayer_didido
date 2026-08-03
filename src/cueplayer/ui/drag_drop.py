"""Shared Explorer drag-and-drop MIME helpers (Windows-safe)."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent

from cueplayer.media.video_loader import STILL_IMAGE_SUFFIXES

AUDIO_SUFFIXES = frozenset(
    {
        ".wav",
        ".flac",
        ".ogg",
        ".oga",
        ".mp3",
        ".aiff",
        ".aif",
        ".aifc",
        ".m4a",
        ".aac",
        ".wma",
        ".opus",
        ".caf",
        ".wv",
    }
)

VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}) | set(STILL_IMAGE_SUFFIXES)


def mime_looks_like_file_drop(mime) -> bool:  # noqa: ANN001
    """
    Optimistic check for Explorer → app file drags on Windows.

    During dragEnter, some hosts omit usable URLs until the actual drop;
    rejecting too early means the drop never arrives.
    """
    if mime is None:
        return False
    if mime.hasUrls():
        return True
    if mime.hasFormat("text/uri-list"):
        return True
    for fmt in mime.formats():
        key = str(fmt).lower()
        if "uri-list" in key or "filename" in key or "cf_hdrop" in key or "filecontents" in key:
            return True
    return False


def _path_from_uri_line(line: str) -> Path | None:
    raw = line.strip()
    if not raw or raw.startswith("#"):
        return None
    if raw.startswith("file:"):
        parsed = urlparse(raw)
        local = unquote(parsed.path or "")
        if len(local) >= 3 and local[0] == "/" and local[2] == ":":
            local = local[1:]  # /C:/... → C:/...
        return Path(local) if local else None
    if len(raw) >= 2 and raw[1] == ":":
        return Path(raw)
    return None


def _path_dedupe_key(path: Path) -> str:
    text = str(path).replace("\\", "/")
    if len(text) >= 3 and text[0] == "/" and text[2] == ":":
        text = text[1:]
    return text.lower()


def local_paths_from_mime(mime) -> list[Path]:  # noqa: ANN001
    """All local file paths in a drop, including text/uri-list without hasUrls()."""
    if mime is None:
        return []
    out: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        key = _path_dedupe_key(path)
        if key in seen:
            return
        seen.add(key)
        out.append(path)

    if mime.hasUrls():
        for url in mime.urls():
            if url.isLocalFile():
                add(Path(url.toLocalFile()))

    for fmt in mime.formats():
        if "uri-list" not in str(fmt).lower():
            continue
        raw = bytes(mime.data(fmt))
        text = raw.decode("utf-8", errors="ignore")
        for line in text.splitlines():
            path = _path_from_uri_line(line)
            if path is not None:
                add(path)
    return out


def _paths_from_mime(mime, *, suffixes: frozenset[str]) -> list[Path]:  # noqa: ANN001
    out: list[Path] = []
    for path in local_paths_from_mime(mime):
        if path.suffix.lower() in suffixes:
            out.append(path)
    return out


def audio_paths_from_mime(mime) -> list[Path]:  # noqa: ANN001
    return _paths_from_mime(mime, suffixes=AUDIO_SUFFIXES)


def video_paths_from_mime(mime) -> list[Path]:  # noqa: ANN001
    return _paths_from_mime(mime, suffixes=frozenset(VIDEO_SUFFIXES))


def setlist_import_paths_from_mime(mime) -> list[Path]:  # noqa: ANN001
    """Audio + video paths for Setlist import, preserving Explorer drop order."""
    allowed = AUDIO_SUFFIXES | frozenset(VIDEO_SUFFIXES)
    out: list[Path] = []
    seen: set[str] = set()
    for path in local_paths_from_mime(mime):
        if path.suffix.lower() not in allowed:
            continue
        key = _path_dedupe_key(path)
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def rejected_setlist_drop_reason(mime) -> str:  # noqa: ANN001
    """Human-readable why a file drop onto the Setlist was ignored."""
    paths = local_paths_from_mime(mime)
    if not paths:
        return (
            "Drop ignored — try running CuePlayer as a normal user (not Administrator) "
            "and drop onto the Setlist table or left panel"
        )
    allowed = AUDIO_SUFFIXES | frozenset(VIDEO_SUFFIXES)
    names: list[str] = []
    for path in paths:
        suf = path.suffix.lower() or "(no extension)"
        if suf not in allowed:
            names.append(f"{path.name} [{suf}]")
        elif not path.is_file():
            names.append(f"{path.name} (not found)")
    if names:
        return (
            "Unsupported / missing media: "
            + ", ".join(names[:3])
            + " — use audio (wav/mp3/…) or video (mp4/mov/mkv/…)"
        )
    return "Drop ignored"


def accept_file_drag(event: QDragEnterEvent | QDragMoveEvent) -> None:
    """Accept an Explorer file drag on Windows (explicit Copy + accept)."""
    event.setDropAction(Qt.DropAction.CopyAction)
    event.accept()


def accept_file_drop(event: QDropEvent) -> None:
    event.setDropAction(Qt.DropAction.CopyAction)
    event.accept()


def rejected_audio_drop_reason(mime) -> str:  # noqa: ANN001
    """Human-readable why a file drop onto the setlist was ignored."""
    paths = local_paths_from_mime(mime)
    if not paths:
        return (
            "Drop ignored — try running CuePlayer as a normal user (not Administrator) "
            "and drop onto the Setlist table or Video lane"
        )
    names: list[str] = []
    for path in paths:
        suf = path.suffix.lower() or "(no extension)"
        if suf not in AUDIO_SUFFIXES:
            names.append(f"{path.name} [{suf}]")
        elif not path.is_file():
            names.append(f"{path.name} (not found)")
    if names:
        return (
            "Unsupported / missing audio: "
            + ", ".join(names[:3])
            + " — use wav/mp3/flac/ogg/aiff/m4a…"
        )
    return "Drop ignored"


def rejected_file_drop_reason(mime) -> str:  # noqa: ANN001
    """Why a generic file drop was ignored (audio or video)."""
    paths = local_paths_from_mime(mime)
    if not paths:
        return (
            "Drop ignored — try running CuePlayer as a normal user (not Administrator) "
            "and drop onto the Setlist or Video lane"
        )
    names: list[str] = []
    for path in paths:
        suf = path.suffix.lower() or "(no extension)"
        if suf not in AUDIO_SUFFIXES and suf not in VIDEO_SUFFIXES:
            names.append(f"{path.name} [{suf}]")
        elif not path.is_file():
            names.append(f"{path.name} (not found)")
    if names:
        return "Unsupported file type: " + ", ".join(names[:3])
    return "Drop ignored"
