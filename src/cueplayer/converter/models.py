"""Dependency-light models for CuePlayer media packages (MC-1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence
from uuid import uuid4

from cueplayer.converter.errors import InvalidManifestError, InvalidSampleMappingError, UnsupportedManifestVersionError

MANIFEST_SCHEMA = "cueplayer.media_package"
CONVERSION_VERSION = 1
FORBIDDEN_LIFECYCLE_KEYS = frozenset({"status", "lifecycle_status", "state"})


def new_package_id() -> str:
    return uuid4().hex


def is_source_sample_in_range(
    *,
    source_sample: int,
    source_start_sample: int,
    decoded_sample_count: int,
) -> bool:
    if decoded_sample_count < 0:
        return False
    return source_start_sample <= source_sample < source_start_sample + decoded_sample_count


def map_source_to_proxy_sample(
    *,
    source_sample: int,
    source_start_sample: int,
    proxy_start_sample: int,
    decoded_sample_count: int,
    leading_trim_samples: int | None = None,
) -> int:
    """Map source-domain sample → proxy sample.

    ``proxy_sample = proxy_start_sample + (source_sample - source_start_sample)``

    ``leading_trim_samples`` is descriptive metadata only and must never
    participate in the affine calculation.
    """
    del leading_trim_samples
    if type(source_sample) is not int:
        raise InvalidSampleMappingError("source_sample must be an int")
    if type(source_start_sample) is not int:
        raise InvalidSampleMappingError("source_start_sample must be an int")
    if type(proxy_start_sample) is not int:
        raise InvalidSampleMappingError("proxy_start_sample must be an int")
    if type(decoded_sample_count) is not int:
        raise InvalidSampleMappingError("decoded_sample_count must be an int")
    if decoded_sample_count < 0:
        raise InvalidSampleMappingError("decoded_sample_count must be >= 0")
    if source_start_sample < 0 or proxy_start_sample < 0:
        raise InvalidSampleMappingError("start samples must be >= 0")
    if not is_source_sample_in_range(
        source_sample=source_sample,
        source_start_sample=source_start_sample,
        decoded_sample_count=decoded_sample_count,
    ):
        raise InvalidSampleMappingError(
            f"source_sample {source_sample} outside "
            f"[{source_start_sample}, {source_start_sample + decoded_sample_count})"
        )
    return proxy_start_sample + (source_sample - source_start_sample)


def _require_int(value: object, name: str) -> int:
    if type(value) is not int:
        raise InvalidManifestError(f"{name} must be an int")
    return value


def _require_nonneg_int(value: object, name: str, *, allow_zero: bool = True) -> int:
    n = _require_int(value, name)
    if allow_zero:
        if n < 0:
            raise InvalidManifestError(f"{name} must be >= 0")
    elif n <= 0:
        raise InvalidManifestError(f"{name} must be > 0")
    return n


@dataclass(frozen=True)
class RationalRate:
    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        _require_int(self.numerator, "numerator")
        den = _require_int(self.denominator, "denominator")
        if den <= 0:
            raise InvalidManifestError("rational denominator must be greater than zero")

    def to_dict(self) -> dict[str, int]:
        return {"numerator": self.numerator, "denominator": self.denominator}

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], *, label: str = "rate") -> RationalRate:
        if not isinstance(raw, Mapping):
            raise InvalidManifestError(f"{label} must be an object")
        try:
            num = raw["numerator"]
            den = raw["denominator"]
        except KeyError as exc:
            raise InvalidManifestError(f"{label} missing numerator/denominator") from exc
        return cls(numerator=_require_int(num, f"{label}.numerator"),
                   denominator=_require_int(den, f"{label}.denominator"))


@dataclass(frozen=True)
class VideoTiming:
    start_pts: int
    time_base: RationalRate
    frame_rate: RationalRate
    decoded_frame_count: int

    def __post_init__(self) -> None:
        _require_int(self.start_pts, "start_pts")
        count = _require_int(self.decoded_frame_count, "decoded_frame_count")
        if count < 0:
            raise InvalidManifestError("decoded_frame_count must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_pts": self.start_pts,
            "time_base": self.time_base.to_dict(),
            "frame_rate": self.frame_rate.to_dict(),
            "decoded_frame_count": self.decoded_frame_count,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> VideoTiming:
        if not isinstance(raw, Mapping):
            raise InvalidManifestError("video timing must be an object")
        try:
            return cls(
                start_pts=_require_int(raw["start_pts"], "start_pts"),
                time_base=RationalRate.from_dict(raw["time_base"], label="time_base"),
                frame_rate=RationalRate.from_dict(raw["frame_rate"], label="frame_rate"),
                decoded_frame_count=_require_int(raw["decoded_frame_count"], "decoded_frame_count"),
            )
        except KeyError as exc:
            raise InvalidManifestError(f"video timing missing field: {exc}") from exc


@dataclass(frozen=True)
class AudioSampleTiming:
    sample_rate: int
    source_start_sample: int
    proxy_start_sample: int
    leading_trim_samples: int
    trailing_trim_samples: int
    decoded_sample_count: int

    def __post_init__(self) -> None:
        _require_nonneg_int(self.sample_rate, "sample_rate", allow_zero=False)
        _require_nonneg_int(self.source_start_sample, "source_start_sample")
        _require_nonneg_int(self.proxy_start_sample, "proxy_start_sample")
        _require_nonneg_int(self.leading_trim_samples, "leading_trim_samples")
        _require_nonneg_int(self.trailing_trim_samples, "trailing_trim_samples")
        _require_nonneg_int(self.decoded_sample_count, "decoded_sample_count")

    def to_dict(self) -> dict[str, int]:
        return {
            "sample_rate": self.sample_rate,
            "source_start_sample": self.source_start_sample,
            "proxy_start_sample": self.proxy_start_sample,
            "leading_trim_samples": self.leading_trim_samples,
            "trailing_trim_samples": self.trailing_trim_samples,
            "decoded_sample_count": self.decoded_sample_count,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> AudioSampleTiming:
        if not isinstance(raw, Mapping):
            raise InvalidManifestError("audio timing must be an object")
        keys = (
            "sample_rate",
            "source_start_sample",
            "proxy_start_sample",
            "leading_trim_samples",
            "trailing_trim_samples",
            "decoded_sample_count",
        )
        values: dict[str, int] = {}
        for key in keys:
            if key not in raw:
                raise InvalidManifestError(f"audio timing missing field: {key}")
            values[key] = _require_int(raw[key], key)
        return cls(**values)


def validate_audio_timing_fields(timing: AudioSampleTiming) -> None:
    if timing.sample_rate <= 0:
        raise InvalidSampleMappingError("sample_rate must be > 0")
    if timing.decoded_sample_count < 0:
        raise InvalidSampleMappingError("decoded_sample_count must be >= 0")
    if timing.leading_trim_samples < 0 or timing.trailing_trim_samples < 0:
        raise InvalidSampleMappingError("trim fields must be >= 0")


@dataclass(frozen=True)
class AudioChannelInfo:
    channel_count: int
    channel_layout: str
    channel_order: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_nonneg_int(self.channel_count, "channel_count", allow_zero=False)
        if not isinstance(self.channel_layout, str) or not self.channel_layout.strip():
            raise InvalidManifestError("channel_layout must be a non-empty string")
        if len(self.channel_order) != self.channel_count:
            raise InvalidManifestError("channel_order length must match channel_count")
        for label in self.channel_order:
            if not isinstance(label, str) or not label.strip():
                raise InvalidManifestError("channel_order entries must be non-empty strings")

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel_count": self.channel_count,
            "channel_layout": self.channel_layout,
            "channel_order": list(self.channel_order),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> AudioChannelInfo:
        if not isinstance(raw, Mapping):
            raise InvalidManifestError("channel info must be an object")
        try:
            count = _require_int(raw["channel_count"], "channel_count")
            layout = raw["channel_layout"]
            order = raw["channel_order"]
        except KeyError as exc:
            raise InvalidManifestError(f"channel info missing field: {exc}") from exc
        if not isinstance(layout, str):
            raise InvalidManifestError("channel_layout must be a string")
        if not isinstance(order, Sequence) or isinstance(order, (str, bytes)):
            raise InvalidManifestError("channel_order must be a list of strings")
        return cls(channel_count=count, channel_layout=layout, channel_order=tuple(str(x) for x in order))


@dataclass(frozen=True)
class SourceFingerprint:
    path: str
    size_bytes: int
    mtime_ns: int
    content_hash: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not self.path:
            raise InvalidManifestError("fingerprint path must be a non-empty string")
        _require_nonneg_int(self.size_bytes, "size_bytes")
        _require_int(self.mtime_ns, "mtime_ns")
        if self.content_hash is not None and not isinstance(self.content_hash, str):
            raise InvalidManifestError("content_hash must be a string or null")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "mtime_ns": self.mtime_ns,
        }
        if self.content_hash is not None:
            out["content_hash"] = self.content_hash
        return out

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> SourceFingerprint:
        if not isinstance(raw, Mapping):
            raise InvalidManifestError("fingerprint must be an object")
        try:
            path = raw["path"]
            size = raw["size_bytes"]
            mtime = raw["mtime_ns"]
        except KeyError as exc:
            raise InvalidManifestError(f"fingerprint missing field: {exc}") from exc
        content_hash = raw.get("content_hash")
        if not isinstance(path, str):
            raise InvalidManifestError("fingerprint path must be a string")
        if content_hash is not None and not isinstance(content_hash, str):
            raise InvalidManifestError("content_hash must be a string or null")
        return cls(
            path=path,
            size_bytes=_require_int(size, "size_bytes"),
            mtime_ns=_require_int(mtime, "mtime_ns"),
            content_hash=content_hash,
        )


@dataclass(frozen=True)
class ProxyArtifactRef:
    path: str
    role: str

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not self.path.strip():
            raise InvalidManifestError("artifact path must be a non-empty string")
        if not isinstance(self.role, str) or not self.role.strip():
            raise InvalidManifestError("artifact role must be a non-empty string")

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "role": self.role}

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ProxyArtifactRef:
        if not isinstance(raw, Mapping):
            raise InvalidManifestError("artifact ref must be an object")
        try:
            path = raw["path"]
            role = raw["role"]
        except KeyError as exc:
            raise InvalidManifestError(f"artifact ref missing field: {exc}") from exc
        if not isinstance(path, str) or not isinstance(role, str):
            raise InvalidManifestError("artifact path/role must be strings")
        return cls(path=path, role=role)


@dataclass(frozen=True)
class MediaPackageManifest:
    """Final ready-only Media Package Manifest v1 (no lifecycle status field)."""

    schema: str
    conversion_version: int
    package_id: str
    generation_relpath: str
    created_utc: str
    preset: str
    audio_timing: AudioSampleTiming
    audio_channels: AudioChannelInfo
    video_timing: VideoTiming | None
    originals: Mapping[str, SourceFingerprint]
    artifacts: tuple[ProxyArtifactRef, ...]
    tool_name: str = "cueplayer-media-converter"
    tool_version: str = "0.1.0"
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema != MANIFEST_SCHEMA:
            raise UnsupportedManifestVersionError(f"unsupported schema: {self.schema!r}")
        if self.conversion_version != CONVERSION_VERSION:
            raise UnsupportedManifestVersionError(
                f"unsupported conversion_version: {self.conversion_version}"
            )
        if not isinstance(self.package_id, str) or not self.package_id:
            raise InvalidManifestError("package_id must be a non-empty string")
        expected_gen = f"generations/{self.package_id}"
        if self.generation_relpath != expected_gen:
            raise InvalidManifestError(
                f"generation_relpath must be {expected_gen!r}, got {self.generation_relpath!r}"
            )
        if not isinstance(self.created_utc, str) or not self.created_utc:
            raise InvalidManifestError("created_utc must be a non-empty string")
        if not isinstance(self.preset, str) or not self.preset:
            raise InvalidManifestError("preset must be a non-empty string")
        if not self.originals:
            raise InvalidManifestError("originals must not be empty")
        if not self.artifacts:
            raise InvalidManifestError("artifacts must not be empty")
        for key in FORBIDDEN_LIFECYCLE_KEYS:
            if key in self.extra:
                raise InvalidManifestError("final manifest must not contain lifecycle status")
