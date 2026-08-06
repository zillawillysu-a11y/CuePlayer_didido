"""Tests for manifest models, paths, and UTF-8 serialization (seams 2–4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cueplayer.converter.errors import (
    InvalidManifestError,
    UnsafeArtifactPathError,
    UnsupportedManifestVersionError,
)
from cueplayer.converter.manifest import (
    dict_to_manifest,
    dumps_manifest,
    loads_manifest,
    manifest_to_dict,
    validate_artifacts_exist,
    validate_manifest_v1,
    validate_relative_artifact_path,
)
from cueplayer.converter.models import (
    CONVERSION_VERSION,
    MANIFEST_SCHEMA,
    AudioChannelInfo,
    AudioSampleTiming,
    MediaPackageManifest,
    ProxyArtifactRef,
    RationalRate,
    SourceFingerprint,
    VideoTiming,
)


def _timing() -> AudioSampleTiming:
    return AudioSampleTiming(
        sample_rate=48000,
        source_start_sample=0,
        proxy_start_sample=0,
        leading_trim_samples=0,
        trailing_trim_samples=0,
        decoded_sample_count=1000,
    )


def _channels() -> AudioChannelInfo:
    return AudioChannelInfo(
        channel_count=2,
        channel_layout="stereo",
        channel_order=("L", "R"),
    )


def _manifest(package_id: str = "abc123", *, with_video: bool = True) -> MediaPackageManifest:
    video = None
    if with_video:
        video = VideoTiming(
            start_pts=0,
            time_base=RationalRate(1, 30000),
            frame_rate=RationalRate(30000, 1001),
            decoded_frame_count=100,
        )
    return MediaPackageManifest(
        schema=MANIFEST_SCHEMA,
        conversion_version=CONVERSION_VERSION,
        package_id=package_id,
        generation_relpath=f"generations/{package_id}",
        created_utc="2026-08-06T00:00:00Z",
        preset="cueplayer_optimized",
        audio_timing=_timing(),
        audio_channels=_channels(),
        video_timing=video,
        originals={
            "audio": SourceFingerprint(path="原版.wav", size_bytes=10, mtime_ns=20),
            "video": SourceFingerprint(path="影片/演出.mp4", size_bytes=30, mtime_ns=40),
        },
        artifacts=(
            ProxyArtifactRef(
                path=f"generations/{package_id}/audio/main.proxy.wav",
                role="audio_proxy",
            ),
            ProxyArtifactRef(
                path=f"generations/{package_id}/video/vj.proxy.mp4",
                role="video_proxy",
            ),
        ),
    )


def test_manifest_v1_round_trip() -> None:
    original = _manifest()
    restored = loads_manifest(dumps_manifest(original))
    assert restored.package_id == original.package_id
    assert restored.audio_timing.decoded_sample_count == 1000
    assert restored.artifacts[0].path.endswith("main.proxy.wav")


def test_chinese_paths_round_trip_unchanged() -> None:
    original = _manifest()
    text = dumps_manifest(original)
    assert "原版.wav" in text
    assert "影片/演出.mp4" in text
    restored = loads_manifest(text)
    assert restored.originals["audio"].path == "原版.wav"
    assert restored.originals["video"].path == "影片/演出.mp4"


def test_exact_30000_1001_survives_serialization() -> None:
    restored = loads_manifest(dumps_manifest(_manifest()))
    assert restored.video_timing is not None
    assert restored.video_timing.frame_rate.numerator == 30000
    assert restored.video_timing.frame_rate.denominator == 1001


def test_exact_60000_1001_survives_serialization() -> None:
    m = _manifest()
    video = VideoTiming(
        start_pts=0,
        time_base=RationalRate(1, 60000),
        frame_rate=RationalRate(60000, 1001),
        decoded_frame_count=200,
    )
    m2 = MediaPackageManifest(
        schema=m.schema,
        conversion_version=m.conversion_version,
        package_id=m.package_id,
        generation_relpath=m.generation_relpath,
        created_utc=m.created_utc,
        preset=m.preset,
        audio_timing=m.audio_timing,
        audio_channels=m.audio_channels,
        video_timing=video,
        originals=m.originals,
        artifacts=m.artifacts,
    )
    restored = loads_manifest(dumps_manifest(m2))
    assert restored.video_timing is not None
    assert restored.video_timing.frame_rate.numerator == 60000
    assert restored.video_timing.frame_rate.denominator == 1001


@pytest.mark.parametrize("den", [0, -1])
def test_invalid_denominator_rejected(den: int) -> None:
    with pytest.raises(InvalidManifestError):
        RationalRate(30000, den)


def test_sample_fields_remain_integers() -> None:
    restored = loads_manifest(dumps_manifest(_manifest()))
    assert type(restored.audio_timing.sample_rate) is int
    assert type(restored.audio_timing.source_start_sample) is int
    assert type(restored.audio_timing.decoded_sample_count) is int


def test_missing_required_fields_rejected() -> None:
    data = manifest_to_dict(_manifest())
    del data["package_id"]
    with pytest.raises(InvalidManifestError):
        dict_to_manifest(data)


def test_unsupported_schema_rejected() -> None:
    data = manifest_to_dict(_manifest())
    data["schema"] = "other"
    with pytest.raises(UnsupportedManifestVersionError):
        dict_to_manifest(data)


def test_unsupported_version_rejected() -> None:
    data = manifest_to_dict(_manifest())
    data["conversion_version"] = 99
    with pytest.raises(UnsupportedManifestVersionError):
        dict_to_manifest(data)


def test_absolute_artifact_path_rejected() -> None:
    with pytest.raises(UnsafeArtifactPathError):
        validate_relative_artifact_path("/tmp/x.wav", package_id="abc123")


def test_windows_drive_path_rejected() -> None:
    with pytest.raises(UnsafeArtifactPathError):
        validate_relative_artifact_path("C:/media/x.wav", package_id="abc123")


def test_unc_path_rejected() -> None:
    with pytest.raises(UnsafeArtifactPathError):
        validate_relative_artifact_path("//server/share/x.wav", package_id="abc123")


def test_traversal_path_rejected() -> None:
    with pytest.raises(UnsafeArtifactPathError):
        validate_relative_artifact_path(
            "generations/abc123/../escape.wav",
            package_id="abc123",
        )


def test_path_outside_declared_generation_rejected() -> None:
    with pytest.raises(UnsafeArtifactPathError):
        validate_relative_artifact_path(
            "generations/other/audio/main.proxy.wav",
            package_id="abc123",
        )


def test_channel_count_order_mismatch_rejected() -> None:
    with pytest.raises(InvalidManifestError):
        AudioChannelInfo(channel_count=2, channel_layout="stereo", channel_order=("L",))


def test_final_manifest_rejects_lifecycle_status() -> None:
    data = manifest_to_dict(_manifest())
    data["status"] = "ready"
    with pytest.raises(InvalidManifestError):
        dict_to_manifest(data)


def test_missing_referenced_artifact_prevents_validation(tmp_path: Path) -> None:
    package_root = tmp_path / "cueplayer_media"
    package_root.mkdir()
    gen = package_root / "generations" / "abc123" / "audio"
    gen.mkdir(parents=True)
    # intentionally do not create artifact files
    manifest = _manifest("abc123")
    validate_manifest_v1(manifest)
    with pytest.raises(InvalidManifestError):
        validate_artifacts_exist(manifest, package_root)
