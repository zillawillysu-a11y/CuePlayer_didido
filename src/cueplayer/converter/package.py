"""Generation-based media package lifecycle (MC-1)."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from cueplayer.converter.errors import PackageCleanupError, PackagePublishError
from cueplayer.converter.manifest import (
    atomic_replace_text,
    dumps_manifest,
    read_manifest_json,
    validate_artifacts_exist,
    validate_manifest_v1,
    write_json_file,
)
from cueplayer.converter.models import MediaPackageManifest, new_package_id

PACKAGE_DIR_NAME = "cueplayer_media"
GENERATIONS_DIR_NAME = "generations"
MANIFEST_NAME = "manifest.json"
PARTIAL_MANIFEST_NAME = "manifest.partial.json"
FAILED_MANIFEST_NAME = "manifest.failed.json"

_GENERATION_SUBDIRS = ("audio", "video", "peaks", "logs")


@dataclass(frozen=True)
class GenerationHandle:
    package_id: str
    package_root: Path
    generation_dir: Path

    @property
    def generation_relpath(self) -> str:
        return f"generations/{self.package_id}"


def package_root_for(output_dir: Path) -> Path:
    """Return ``<output_dir>/cueplayer_media`` (creates nothing)."""
    return Path(output_dir) / PACKAGE_DIR_NAME


def is_package_ready(package_root: Path) -> bool:
    """True only when final manifest.json exists, parses, and artifacts resolve."""
    path = Path(package_root) / MANIFEST_NAME
    if not path.is_file():
        return False
    try:
        manifest = read_manifest_json(path)
        validate_generation_for_publish(Path(package_root), manifest)
    except Exception:
        return False
    return True


def create_package_root(output_dir: Path) -> Path:
    root = package_root_for(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / GENERATIONS_DIR_NAME).mkdir(parents=True, exist_ok=True)
    return root


def create_generation_skeleton(
    package_root: Path,
    *,
    package_id: str | None = None,
) -> GenerationHandle:
    """Create a new immutable generation directory under package_root."""
    root = Path(package_root)
    if root.name != PACKAGE_DIR_NAME:
        raise PackagePublishError(f"package root must be named {PACKAGE_DIR_NAME!r}")
    root.mkdir(parents=True, exist_ok=True)
    (root / GENERATIONS_DIR_NAME).mkdir(parents=True, exist_ok=True)

    pid = package_id or new_package_id()
    gen_dir = root / GENERATIONS_DIR_NAME / pid
    if gen_dir.exists():
        raise PackagePublishError(f"generation already exists: {pid}")
    gen_dir.mkdir(parents=False, exist_ok=False)
    for name in _GENERATION_SUBDIRS:
        (gen_dir / name).mkdir(parents=False, exist_ok=False)
    return GenerationHandle(package_id=pid, package_root=root, generation_dir=gen_dir)


def write_partial_manifest(package_root: Path, payload: Mapping[str, Any]) -> Path:
    path = Path(package_root) / PARTIAL_MANIFEST_NAME
    data = dict(payload)
    data.setdefault("partial", True)
    write_json_file(path, data)
    return path


def write_failed_manifest(package_root: Path, payload: Mapping[str, Any]) -> Path:
    path = Path(package_root) / FAILED_MANIFEST_NAME
    data = dict(payload)
    data.setdefault("failed", True)
    write_json_file(path, data)
    return path


def validate_generation_for_publish(
    package_root: Path,
    manifest: MediaPackageManifest,
) -> None:
    validate_manifest_v1(manifest)
    validate_artifacts_exist(manifest, Path(package_root))
    gen = Path(package_root) / GENERATIONS_DIR_NAME / manifest.package_id
    if not gen.is_dir():
        raise PackagePublishError(f"generation directory missing: {manifest.package_id}")


def publish_manifest(package_root: Path, manifest: MediaPackageManifest) -> Path:
    """Validate then atomically publish final manifest.json; remove partial after."""
    root = Path(package_root)
    try:
        validate_generation_for_publish(root, manifest)
    except Exception as exc:
        raise PackagePublishError(str(exc)) from exc

    # Never overwrite the currently referenced generation contents — only the pointer.
    final_path = root / MANIFEST_NAME
    previous: MediaPackageManifest | None = None
    if final_path.is_file():
        try:
            previous = read_manifest_json(final_path)
        except Exception:
            previous = None
        if previous is not None and previous.package_id == manifest.package_id:
            raise PackagePublishError("refusing to republish over the active generation id")

    text = dumps_manifest(manifest)
    try:
        atomic_replace_text(final_path, text)
    except OSError as exc:
        raise PackagePublishError(f"atomic replace failed: {exc}") from exc

    partial = root / PARTIAL_MANIFEST_NAME
    if partial.exists():
        try:
            partial.unlink()
        except OSError:
            # Final is already published; partial leftover is non-fatal.
            pass
    return final_path


def discard_unpublished_generation(
    package_root: Path,
    package_id: str,
    *,
    write_failed: Mapping[str, Any] | None = None,
) -> None:
    """Best-effort remove a generation that was never published as ready."""
    root = Path(package_root)
    final = root / MANIFEST_NAME
    if final.is_file():
        try:
            active = read_manifest_json(final)
            if active.package_id == package_id:
                raise PackageCleanupError("refusing to delete the active published generation")
        except PackageCleanupError:
            raise
        except Exception:
            pass

    gen = root / GENERATIONS_DIR_NAME / package_id
    if write_failed is not None:
        write_failed_manifest(root, write_failed)
    if gen.exists():
        try:
            shutil.rmtree(gen)
        except OSError as exc:
            raise PackageCleanupError(f"failed to remove generation {package_id}: {exc}") from exc

    partial = root / PARTIAL_MANIFEST_NAME
    if partial.exists():
        try:
            data = json.loads(partial.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        if isinstance(data, dict) and data.get("package_id") == package_id:
            try:
                partial.unlink()
            except OSError as exc:
                raise PackageCleanupError(f"failed to remove partial manifest: {exc}") from exc


def cancel_generation(package_root: Path, package_id: str) -> None:
    discard_unpublished_generation(
        package_root,
        package_id,
        write_failed={"package_id": package_id, "reason": "cancelled"},
    )


def list_orphan_generations(package_root: Path) -> list[str]:
    """Generation ids present on disk that are not the active published package."""
    root = Path(package_root)
    gens_root = root / GENERATIONS_DIR_NAME
    if not gens_root.is_dir():
        return []
    active_id: str | None = None
    final = root / MANIFEST_NAME
    if final.is_file():
        try:
            active_id = read_manifest_json(final).package_id
        except Exception:
            active_id = None
    orphans: list[str] = []
    for child in gens_root.iterdir():
        if child.is_dir() and child.name != active_id:
            orphans.append(child.name)
    return sorted(orphans)
