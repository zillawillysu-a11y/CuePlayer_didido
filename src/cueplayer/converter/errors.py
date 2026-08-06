"""Typed errors for CuePlayer media-package foundation (MC-1)."""

from __future__ import annotations


class ConverterError(Exception):
    """Base error for converter package / manifest operations."""


class InvalidManifestError(ConverterError):
    """Manifest JSON is missing fields, mistyped, or otherwise invalid."""


class UnsupportedManifestVersionError(InvalidManifestError):
    """Manifest schema or conversion_version is not supported."""


class UnsafeArtifactPathError(ConverterError):
    """Artifact path is absolute, traverses, or escapes the package root."""


class InvalidSampleMappingError(ConverterError):
    """Sample timing fields or source→proxy mapping are out of range."""


class PackagePublishError(ConverterError):
    """Final manifest publication failed (validation or atomic replace)."""


class PackageCleanupError(ConverterError):
    """Best-effort cleanup of an unpublished generation failed when reporting is required."""
