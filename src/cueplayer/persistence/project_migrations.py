"""Project JSON schema migrations (isolated from Repository).

``ProjectRepository`` only load/save. ``load_project`` calls
``migrate_project_dict`` here before ``project_from_dict`` builds domain objects.

Rules for this module:
- Transform raw ``dict`` payloads only.
- Do not import UI, playback, or repository.
- Do not validate business rules beyond structural schema upgrades.
- Do not auto-repair missing media files.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from cueplayer.domain.models import SCHEMA_VERSION


class SchemaError(ValueError):
    """Raised when a project schema cannot be migrated or is too new."""


def migrate_project_dict(data: dict[str, Any], from_version: int) -> dict[str, Any]:
    """Migrate older project dicts up to ``SCHEMA_VERSION``.

    Returns a new dict (shallow-copied root); song entries may be replaced.
    """
    if from_version > SCHEMA_VERSION:
        raise SchemaError(
            f"Project schema_version {from_version} is newer than supported {SCHEMA_VERSION}."
        )

    migrated: dict[str, Any] = dict(data)
    version = int(from_version)

    if version == 0:
        migrated.setdefault("songs", [])
        version = 1

    if version == 1:
        _migrate_v1_to_v2(migrated)
        version = 2

    if version == 2:
        _migrate_v2_to_v3(migrated)
        version = 3

    if version != SCHEMA_VERSION:
        raise SchemaError(f"No migration path from schema_version {from_version}.")

    migrated["schema_version"] = SCHEMA_VERSION
    return migrated


def _migrate_v1_to_v2(data: dict[str, Any]) -> None:
    """Ensure each song has ``variants`` / ``selected_variant_id`` (from audio_tracks)."""
    songs = data.get("songs")
    if not isinstance(songs, list):
        return
    for song in songs:
        if not isinstance(song, dict):
            continue
        _ensure_song_variants_from_audio_tracks(song)


def _migrate_v2_to_v3(data: dict[str, Any]) -> None:
    """Add per-song LTC clip fields (schema v3).

    Legacy songs keep today's behavior: ``ltc_source_mode = "auto"``
    (resolved from project AudioOutputSettings) and an empty clip list.
    """
    songs = data.get("songs")
    if not isinstance(songs, list):
        return
    for song in songs:
        if not isinstance(song, dict):
            continue
        song.setdefault("ltc_source_mode", "auto")
        clips = song.get("ltc_clips")
        if not isinstance(clips, list):
            song["ltc_clips"] = []
            continue
        cleaned: list[dict[str, Any]] = []
        for clip in clips:
            if not isinstance(clip, dict):
                continue
            clip_id = str(clip.get("id") or "")
            if not clip_id:
                clip_id = str(uuid4())
            cleaned.append(
                {
                    "id": clip_id,
                    "timeline_start_seconds": float(
                        clip.get("timeline_start_seconds", 0.0) or 0.0
                    ),
                    "duration_seconds": float(
                        clip.get("duration_seconds", 0.0) or 0.0
                    ),
                    "start_timecode": str(
                        clip.get("start_timecode", "01:00:00:00") or "01:00:00:00"
                    ),
                }
            )
        song["ltc_clips"] = cleaned


def _ensure_song_variants_from_audio_tracks(song: dict[str, Any]) -> None:
    existing = song.get("variants")
    if isinstance(existing, list) and len(existing) > 0:
        if not song.get("selected_variant_id"):
            song["selected_variant_id"] = _pick_selected_variant_id(existing, song)
        return

    tracks = song.get("audio_tracks")
    if not isinstance(tracks, list) or not tracks:
        song.setdefault("variants", [])
        song.setdefault("selected_variant_id", None)
        return

    variants: list[dict[str, Any]] = []
    selected: str | None = None
    for track in tracks:
        if not isinstance(track, dict):
            continue
        track_id = str(track.get("id") or uuid4())
        variant_id = f"variant-{track_id}"
        role = str(track.get("role") or "reference")
        hidden = bool(track.get("hidden", False))
        variants.append(
            {
                "id": variant_id,
                "name": str(track.get("name") or "Variant"),
                "kind": "audio",
                "path": track.get("path", ""),
                "anchor_offset": float(track.get("offset_seconds", 0.0) or 0.0),
                "enabled": not hidden,
                "metadata": {
                    "legacy_track_id": track_id,
                    "legacy_role": role,
                },
            }
        )
        if selected is None and role == "main":
            selected = variant_id
    if selected is None and variants:
        selected = str(variants[0]["id"])
    song["variants"] = variants
    song["selected_variant_id"] = selected


def _pick_selected_variant_id(
    variants: list[Any], song: dict[str, Any]
) -> str | None:
    explicit = song.get("selected_variant_id")
    if explicit:
        return str(explicit)
    for item in variants:
        if isinstance(item, dict) and item.get("id"):
            return str(item["id"])
    return None
