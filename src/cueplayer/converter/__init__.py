"""CuePlayer media converter package foundation (MC-1)."""

from __future__ import annotations

from cueplayer.converter.errors import (
    ConverterError,
    InvalidManifestError,
    InvalidSampleMappingError,
    PackageCleanupError,
    PackagePublishError,
    UnsafeArtifactPathError,
    UnsupportedManifestVersionError,
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
    is_source_sample_in_range,
    map_source_to_proxy_sample,
    new_package_id,
    validate_audio_timing_fields,
)

__all__ = [
    "CONVERSION_VERSION",
    "MANIFEST_SCHEMA",
    "AudioChannelInfo",
    "AudioSampleTiming",
    "ConverterError",
    "InvalidManifestError",
    "InvalidSampleMappingError",
    "MediaPackageManifest",
    "PackageCleanupError",
    "PackagePublishError",
    "ProxyArtifactRef",
    "RationalRate",
    "SourceFingerprint",
    "UnsafeArtifactPathError",
    "UnsupportedManifestVersionError",
    "VideoTiming",
    "is_source_sample_in_range",
    "map_source_to_proxy_sample",
    "new_package_id",
    "validate_audio_timing_fields",
]
