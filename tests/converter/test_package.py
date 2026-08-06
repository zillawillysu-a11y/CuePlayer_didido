"""Tests for generation staging, atomic publish, and fail/cancel safety."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from cueplayer.converter.errors import PackageCleanupError, PackagePublishError
from cueplayer.converter.manifest import dumps_manifest, read_manifest_json
from cueplayer.converter.models import (
    CONVERSION_VERSION,
    MANIFEST_SCHEMA,
    AudioChannelInfo,
    AudioSampleTiming,
    MediaPackageManifest,
    ProxyArtifactRef,
    SourceFingerprint,
)
from cueplayer.converter.package import (
    cancel_generation,
    create_generation_skeleton,
    create_package_root,
    discard_unpublished_generation,
    is_package_ready,
    list_orphan_generations,
    publish_manifest,
    write_partial_manifest,
)


def _build_manifest(package_id: str, *, audio_name: str = "main.proxy.wav") -> MediaPackageManifest:
    return MediaPackageManifest(
        schema=MANIFEST_SCHEMA,
        conversion_version=CONVERSION_VERSION,
        package_id=package_id,
        generation_relpath=f"generations/{package_id}",
        created_utc="2026-08-06T00:00:00Z",
        preset="cueplayer_optimized",
        audio_timing=AudioSampleTiming(
            sample_rate=48000,
            source_start_sample=0,
            proxy_start_sample=0,
            leading_trim_samples=0,
            trailing_trim_samples=0,
            decoded_sample_count=100,
        ),
        audio_channels=AudioChannelInfo(
            channel_count=2,
            channel_layout="stereo",
            channel_order=("L", "R"),
        ),
        video_timing=None,
        originals={
            "audio": SourceFingerprint(path="原版.wav", size_bytes=11, mtime_ns=22),
        },
        artifacts=(
            ProxyArtifactRef(
                path=f"generations/{package_id}/audio/{audio_name}",
                role="audio_proxy",
            ),
        ),
    )


def _prepare_artifacts(handle, *, filename: str = "main.proxy.wav") -> MediaPackageManifest:
    artifact = handle.generation_dir / "audio" / filename
    artifact.write_bytes(b"PROXY")
    return _build_manifest(handle.package_id, audio_name=filename)


def test_new_generation_does_not_touch_originals(tmp_path: Path) -> None:
    original = tmp_path / "原版.wav"
    original.write_bytes(b"ORIGINAL-BYTES")
    before_mtime = original.stat().st_mtime_ns
    before_bytes = original.read_bytes()

    root = create_package_root(tmp_path / "out中文")
    handle = create_generation_skeleton(root)

    assert handle.generation_dir.is_dir()
    assert (handle.generation_dir / "audio").is_dir()
    assert original.read_bytes() == before_bytes
    assert original.stat().st_mtime_ns == before_mtime
    assert not is_package_ready(root)


def test_partial_manifest_never_ready(tmp_path: Path) -> None:
    root = create_package_root(tmp_path)
    handle = create_generation_skeleton(root)
    write_partial_manifest(root, {"package_id": handle.package_id, "status": "running"})
    assert (root / "manifest.partial.json").is_file()
    assert not (root / "manifest.json").exists()
    assert not is_package_ready(root)


def test_valid_generation_publishes_final_manifest(tmp_path: Path) -> None:
    root = create_package_root(tmp_path)
    handle = create_generation_skeleton(root)
    manifest = _prepare_artifacts(handle)
    write_partial_manifest(root, {"package_id": handle.package_id})
    published = publish_manifest(root, manifest)
    assert published.name == "manifest.json"
    assert is_package_ready(root)
    loaded = read_manifest_json(published)
    assert loaded.package_id == handle.package_id
    assert loaded.generation_relpath == f"generations/{handle.package_id}"
    assert not (root / "manifest.partial.json").exists()


def test_previous_manifest_remains_during_staging(tmp_path: Path) -> None:
    root = create_package_root(tmp_path)
    first = create_generation_skeleton(root)
    first_manifest = _prepare_artifacts(first)
    publish_manifest(root, first_manifest)

    second = create_generation_skeleton(root)
    write_partial_manifest(root, {"package_id": second.package_id})
    # Still ready with previous generation while staging.
    assert is_package_ready(root)
    assert read_manifest_json(root / "manifest.json").package_id == first.package_id
    assert second.generation_dir.is_dir()


def test_successful_publish_replaces_only_final_pointer(tmp_path: Path) -> None:
    root = create_package_root(tmp_path)
    first = create_generation_skeleton(root)
    first_manifest = _prepare_artifacts(first)
    publish_manifest(root, first_manifest)
    first_dir = first.generation_dir
    assert first_dir.is_dir()

    second = create_generation_skeleton(root)
    second_manifest = _prepare_artifacts(second, filename="main.proxy.wav")
    publish_manifest(root, second_manifest)

    assert read_manifest_json(root / "manifest.json").package_id == second.package_id
    assert first_dir.is_dir()  # previous generation contents preserved


def test_validation_failure_preserves_previous_package(tmp_path: Path) -> None:
    root = create_package_root(tmp_path)
    first = create_generation_skeleton(root)
    first_manifest = _prepare_artifacts(first)
    publish_manifest(root, first_manifest)

    second = create_generation_skeleton(root)
    bad = _build_manifest(second.package_id)  # artifacts missing on disk
    with pytest.raises(PackagePublishError):
        publish_manifest(root, bad)
    assert read_manifest_json(root / "manifest.json").package_id == first.package_id
    assert is_package_ready(root)


def test_cancel_removes_only_unpublished_generation(tmp_path: Path) -> None:
    root = create_package_root(tmp_path)
    first = create_generation_skeleton(root)
    publish_manifest(root, _prepare_artifacts(first))

    second = create_generation_skeleton(root)
    write_partial_manifest(root, {"package_id": second.package_id})
    cancel_generation(root, second.package_id)

    assert not second.generation_dir.exists()
    assert first.generation_dir.exists()
    assert read_manifest_json(root / "manifest.json").package_id == first.package_id
    assert (root / "manifest.failed.json").is_file()


def test_cleanup_failure_does_not_invalidate_previous(tmp_path: Path) -> None:
    root = create_package_root(tmp_path)
    first = create_generation_skeleton(root)
    publish_manifest(root, _prepare_artifacts(first))

    second = create_generation_skeleton(root)
    with mock.patch("cueplayer.converter.package.shutil.rmtree", side_effect=OSError("boom")):
        with pytest.raises(PackageCleanupError):
            discard_unpublished_generation(root, second.package_id)
    assert is_package_ready(root)
    assert read_manifest_json(root / "manifest.json").package_id == first.package_id


def test_crash_partial_state_not_ready(tmp_path: Path) -> None:
    root = create_package_root(tmp_path)
    handle = create_generation_skeleton(root)
    write_partial_manifest(root, {"package_id": handle.package_id, "status": "running"})
    _prepare_artifacts(handle)
    assert not is_package_ready(root)


def test_manifest_without_artifacts_on_disk_not_ready(tmp_path: Path) -> None:
    root = create_package_root(tmp_path)
    handle = create_generation_skeleton(root)
    manifest = _build_manifest(handle.package_id)
    (root / "manifest.json").write_text(dumps_manifest(manifest), encoding="utf-8")
    assert not is_package_ready(root)


def test_orphan_generation_not_treated_as_active(tmp_path: Path) -> None:
    root = create_package_root(tmp_path)
    first = create_generation_skeleton(root)
    publish_manifest(root, _prepare_artifacts(first))
    orphan = create_generation_skeleton(root)
    orphans = list_orphan_generations(root)
    assert orphan.package_id in orphans
    assert first.package_id not in orphans
    assert read_manifest_json(root / "manifest.json").package_id == first.package_id


def test_active_generation_never_overwritten(tmp_path: Path) -> None:
    root = create_package_root(tmp_path)
    first = create_generation_skeleton(root, package_id="fixedid01")
    publish_manifest(root, _prepare_artifacts(first))
    with pytest.raises(PackagePublishError):
        create_generation_skeleton(root, package_id="fixedid01")


def test_atomic_replace_failure_preserves_previous_manifest(tmp_path: Path) -> None:
    root = create_package_root(tmp_path)
    first = create_generation_skeleton(root)
    publish_manifest(root, _prepare_artifacts(first))
    second = create_generation_skeleton(root)
    second_manifest = _prepare_artifacts(second)
    with mock.patch(
        "cueplayer.converter.package.atomic_replace_text",
        side_effect=OSError("replace failed"),
    ):
        with pytest.raises(PackagePublishError):
            publish_manifest(root, second_manifest)
    assert read_manifest_json(root / "manifest.json").package_id == first.package_id


def test_chinese_output_path_works(tmp_path: Path) -> None:
    out = tmp_path / "專案媒體" / "輸出"
    root = create_package_root(out)
    handle = create_generation_skeleton(root)
    publish_manifest(root, _prepare_artifacts(handle))
    assert is_package_ready(root)


def test_unsafe_output_artifact_paths_rejected(tmp_path: Path) -> None:
    root = create_package_root(tmp_path)
    handle = create_generation_skeleton(root)
    (handle.generation_dir / "audio" / "main.proxy.wav").write_bytes(b"x")
    bad = _build_manifest(handle.package_id)
    # Force an absolute artifact path into the model by reconstructing
    from cueplayer.converter.models import ProxyArtifactRef as Ref

    with pytest.raises(Exception):
        # Construction via publish path validation
        forced = MediaPackageManifest(
            schema=bad.schema,
            conversion_version=bad.conversion_version,
            package_id=bad.package_id,
            generation_relpath=bad.generation_relpath,
            created_utc=bad.created_utc,
            preset=bad.preset,
            audio_timing=bad.audio_timing,
            audio_channels=bad.audio_channels,
            video_timing=None,
            originals=bad.originals,
            artifacts=(Ref(path="C:/evil.wav", role="audio_proxy"),),
        )
        publish_manifest(root, forced)


def test_refusing_delete_active_generation(tmp_path: Path) -> None:
    root = create_package_root(tmp_path)
    first = create_generation_skeleton(root)
    publish_manifest(root, _prepare_artifacts(first))
    with pytest.raises(PackageCleanupError):
        discard_unpublished_generation(root, first.package_id)
