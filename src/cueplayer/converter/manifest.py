"""UTF-8 manifest serialization and validation for media packages (MC-1)."""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from cueplayer.converter.errors import (
    InvalidManifestError,
    UnsafeArtifactPathError,
    UnsupportedManifestVersionError,
)
from cueplayer.converter.models import (
    CONVERSION_VERSION,
    FORBIDDEN_LIFECYCLE_KEYS,
    MANIFEST_SCHEMA,
    AudioChannelInfo,
    AudioSampleTiming,
    MediaPackageManifest,
    ProxyArtifactRef,
    SourceFingerprint,
    VideoTiming,
)

_FORBIDDEN_STATUS_KEYS = FORBIDDEN_LIFECYCLE_KEYS


def normalize_relpath(path: str) -> str:
    """Portable relative path using forward slashes."""
    text = str(path).replace("\\", "/").strip()
    if not text:
        raise UnsafeArtifactPathError("artifact path must be non-empty")
    return text


def validate_relative_artifact_path(
    path: str,
    *,
    package_id: str,
    package_root: Path | None = None,
) -> str:
    """Validate an artifact path relative to cueplayer_media/.

    Must live under ``generations/<package-id>/``, reject abs/drive/UNC/`..`.
    """
    text = normalize_relpath(path)
    lower = text.casefold()

    if text.startswith("/") or text.startswith("\\"):
        raise UnsafeArtifactPathError(f"absolute artifact path rejected: {path!r}")
    if len(text) >= 2 and text[1] == ":" and text[0].isalpha():
        raise UnsafeArtifactPathError(f"Windows drive path rejected: {path!r}")
    if text.startswith("//") or text.startswith("\\\\") or lower.startswith("unc:"):
        raise UnsafeArtifactPathError(f"UNC path rejected: {path!r}")
    if ".." in PurePosixPath(text).parts:
        raise UnsafeArtifactPathError(f"traversal path rejected: {path!r}")

    expected_prefix = f"generations/{package_id}/"
    if not text.startswith(expected_prefix):
        raise UnsafeArtifactPathError(
            f"artifact path must be under {expected_prefix!r}, got {path!r}"
        )
    if text.rstrip("/") == f"generations/{package_id}":
        raise UnsafeArtifactPathError("artifact path must reference a file inside the generation")

    if package_root is not None:
        root = Path(package_root).resolve()
        candidate = (root / PurePosixPath(text)).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise UnsafeArtifactPathError(
                f"artifact path escapes package root: {path!r}"
            ) from exc

    return text


def manifest_to_dict(manifest: MediaPackageManifest) -> dict[str, Any]:
    originals = {key: fp.to_dict() for key, fp in manifest.originals.items()}
    data: dict[str, Any] = {
        "schema": manifest.schema,
        "conversion_version": manifest.conversion_version,
        "package_id": manifest.package_id,
        "generation_relpath": manifest.generation_relpath,
        "created_utc": manifest.created_utc,
        "preset": manifest.preset,
        "tool": {"name": manifest.tool_name, "version": manifest.tool_version},
        "audio_timing": manifest.audio_timing.to_dict(),
        "audio_channels": manifest.audio_channels.to_dict(),
        "originals": originals,
        "artifacts": [a.to_dict() for a in manifest.artifacts],
    }
    if manifest.video_timing is not None:
        data["video_timing"] = manifest.video_timing.to_dict()
    if manifest.extra:
        # Never allow lifecycle status into the final ready document.
        for key in _FORBIDDEN_STATUS_KEYS:
            if key in manifest.extra:
                raise InvalidManifestError("final manifest must not contain lifecycle status")
        data["extra"] = dict(manifest.extra)
    return data


def dict_to_manifest(raw: Mapping[str, Any]) -> MediaPackageManifest:
    if not isinstance(raw, Mapping):
        raise InvalidManifestError("manifest must be a JSON object")

    for key in _FORBIDDEN_STATUS_KEYS:
        if key in raw:
            raise InvalidManifestError("final manifest must not contain lifecycle status")

    schema = raw.get("schema")
    if schema != MANIFEST_SCHEMA:
        raise UnsupportedManifestVersionError(f"unsupported schema: {schema!r}")

    version = raw.get("conversion_version")
    if type(version) is not int or version != CONVERSION_VERSION:
        raise UnsupportedManifestVersionError(
            f"unsupported conversion_version: {version!r}"
        )

    try:
        package_id = raw["package_id"]
        generation_relpath = raw["generation_relpath"]
        created_utc = raw["created_utc"]
        preset = raw["preset"]
        audio_timing_raw = raw["audio_timing"]
        audio_channels_raw = raw["audio_channels"]
        originals_raw = raw["originals"]
        artifacts_raw = raw["artifacts"]
    except KeyError as exc:
        raise InvalidManifestError(f"manifest missing field: {exc}") from exc

    if not isinstance(package_id, str) or not package_id:
        raise InvalidManifestError("package_id must be a non-empty string")
    if not isinstance(generation_relpath, str):
        raise InvalidManifestError("generation_relpath must be a string")
    if generation_relpath != f"generations/{package_id}":
        raise InvalidManifestError(
            f"generation_relpath must be 'generations/{package_id}'"
        )

    tool = raw.get("tool") or {}
    if not isinstance(tool, Mapping):
        raise InvalidManifestError("tool must be an object")
    tool_name = str(tool.get("name") or "cueplayer-media-converter")
    tool_version = str(tool.get("version") or "0.1.0")

    if not isinstance(originals_raw, Mapping) or not originals_raw:
        raise InvalidManifestError("originals must be a non-empty object")
    originals = {
        str(key): SourceFingerprint.from_dict(value)
        for key, value in originals_raw.items()
    }

    if not isinstance(artifacts_raw, list) or not artifacts_raw:
        raise InvalidManifestError("artifacts must be a non-empty list")
    artifacts: list[ProxyArtifactRef] = []
    for item in artifacts_raw:
        ref = ProxyArtifactRef.from_dict(item)
        validate_relative_artifact_path(ref.path, package_id=package_id)
        artifacts.append(ref)

    video_timing = None
    if "video_timing" in raw and raw["video_timing"] is not None:
        video_timing = VideoTiming.from_dict(raw["video_timing"])

    extra = raw.get("extra") or {}
    if not isinstance(extra, Mapping):
        raise InvalidManifestError("extra must be an object")
    for key in _FORBIDDEN_STATUS_KEYS:
        if key in extra:
            raise InvalidManifestError("final manifest must not contain lifecycle status")

    return MediaPackageManifest(
        schema=schema,
        conversion_version=version,
        package_id=package_id,
        generation_relpath=generation_relpath,
        created_utc=str(created_utc),
        preset=str(preset),
        audio_timing=AudioSampleTiming.from_dict(audio_timing_raw),
        audio_channels=AudioChannelInfo.from_dict(audio_channels_raw),
        video_timing=video_timing,
        originals=originals,
        artifacts=tuple(artifacts),
        tool_name=tool_name,
        tool_version=tool_version,
        extra=dict(extra),
    )


def dumps_manifest(manifest: MediaPackageManifest) -> str:
    return json.dumps(manifest_to_dict(manifest), ensure_ascii=False, indent=2) + "\n"


def loads_manifest(text: str) -> MediaPackageManifest:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvalidManifestError(f"invalid JSON: {exc}") from exc
    return dict_to_manifest(raw)


def validate_manifest_v1(manifest: MediaPackageManifest) -> None:
    """Validate structural rules for a ready final manifest."""
    if manifest.schema != MANIFEST_SCHEMA:
        raise UnsupportedManifestVersionError(f"unsupported schema: {manifest.schema!r}")
    if manifest.conversion_version != CONVERSION_VERSION:
        raise UnsupportedManifestVersionError(
            f"unsupported conversion_version: {manifest.conversion_version}"
        )
    for key in FORBIDDEN_LIFECYCLE_KEYS:
        if key in manifest.extra:
            raise InvalidManifestError("final manifest must not contain lifecycle status")
    for artifact in manifest.artifacts:
        validate_relative_artifact_path(artifact.path, package_id=manifest.package_id)


def validate_artifacts_exist(manifest: MediaPackageManifest, package_root: Path) -> None:
    """Require every referenced artifact file to exist under package_root."""
    root = Path(package_root)
    for artifact in manifest.artifacts:
        rel = validate_relative_artifact_path(
            artifact.path,
            package_id=manifest.package_id,
            package_root=root,
        )
        full = root / PurePosixPath(rel)
        if not full.is_file():
            raise InvalidManifestError(f"missing referenced artifact: {rel}")


def write_manifest_json(path: Path, manifest: MediaPackageManifest) -> None:
    path = Path(path)
    text = dumps_manifest(manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_manifest_json(path: Path) -> MediaPackageManifest:
    return loads_manifest(Path(path).read_text(encoding="utf-8"))


def write_json_file(path: Path, payload: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")


def atomic_replace_text(target: Path, text: str) -> None:
    """Write text via a same-directory temp file then ``os.replace``."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, target)
