"""Shared Explorer drag-and-drop MIME helpers (Windows-safe)."""

from __future__ import annotations

from pathlib import Path

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
    for fmt in mime.formats():
        key = str(fmt).lower()
        if "uri-list" in key or "filename" in key or "cf_hdrop" in key:
            return True
    return False


def _paths_from_mime(mime, *, suffixes: frozenset[str]) -> list[Path]:  # noqa: ANN001
    if mime is None or not mime.hasUrls():
        return []
    out: list[Path] = []
    seen: set[str] = set()
    for url in mime.urls():
        if not url.isLocalFile():
            continue
        path = Path(url.toLocalFile())
        if path.suffix.lower() not in suffixes:
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def audio_paths_from_mime(mime) -> list[Path]:  # noqa: ANN001
    return _paths_from_mime(mime, suffixes=AUDIO_SUFFIXES)


def video_paths_from_mime(mime) -> list[Path]:  # noqa: ANN001
    return _paths_from_mime(mime, suffixes=frozenset(VIDEO_SUFFIXES))


def rejected_audio_drop_reason(mime) -> str:  # noqa: ANN001
    """Human-readable why a file drop onto the setlist was ignored."""
    if mime is None or not mime.hasUrls():
        return "Drop ignored (not a local file drag)"
    names: list[str] = []
    for url in mime.urls():
        if not url.isLocalFile():
            names.append("(non-local URL)")
            continue
        path = Path(url.toLocalFile())
        suf = path.suffix.lower() or "(no extension)"
        if suf not in AUDIO_SUFFIXES:
            names.append(f"{path.name} [{suf}]")
        elif not path.exists():
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
    if mime is None or not mime.hasUrls():
        return "Drop ignored (not a local file drag)"
    names: list[str] = []
    for url in mime.urls():
        if not url.isLocalFile():
            names.append("(non-local URL)")
            continue
        path = Path(url.toLocalFile())
        suf = path.suffix.lower() or "(no extension)"
        if suf not in AUDIO_SUFFIXES and suf not in VIDEO_SUFFIXES:
            names.append(f"{path.name} [{suf}]")
        elif not path.exists():
            names.append(f"{path.name} (not found)")
    if names:
        return "Unsupported file type: " + ", ".join(names[:3])
    return "Drop ignored"
