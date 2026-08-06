"""TDD seam 1: source→proxy integer sample mapping."""

from __future__ import annotations

import pytest

from cueplayer.converter.errors import InvalidManifestError, InvalidSampleMappingError
from cueplayer.converter.models import (
    AudioSampleTiming,
    map_source_to_proxy_sample,
    validate_audio_timing_fields,
)


def test_clean_wav_identity_maps_to_zero() -> None:
    assert (
        map_source_to_proxy_sample(
            source_sample=0,
            source_start_sample=0,
            proxy_start_sample=0,
            decoded_sample_count=100,
        )
        == 0
    )


def test_aac_leading_trim_maps_first_retained_to_zero() -> None:
    assert (
        map_source_to_proxy_sample(
            source_sample=2112,
            source_start_sample=2112,
            proxy_start_sample=0,
            decoded_sample_count=10_000,
            leading_trim_samples=2112,
        )
        == 0
    )


def test_aac_later_retained_sample_maps_without_double_trim() -> None:
    assert (
        map_source_to_proxy_sample(
            source_sample=6912,
            source_start_sample=2112,
            proxy_start_sample=0,
            decoded_sample_count=10_000,
            leading_trim_samples=2112,
        )
        == 4800
    )


def test_first_valid_source_sample_accepted() -> None:
    assert (
        map_source_to_proxy_sample(
            source_sample=100,
            source_start_sample=100,
            proxy_start_sample=5,
            decoded_sample_count=50,
        )
        == 5
    )


def test_last_valid_source_sample_accepted() -> None:
    assert (
        map_source_to_proxy_sample(
            source_sample=149,
            source_start_sample=100,
            proxy_start_sample=0,
            decoded_sample_count=50,
        )
        == 49
    )


def test_sample_before_valid_range_rejected() -> None:
    with pytest.raises(InvalidSampleMappingError):
        map_source_to_proxy_sample(
            source_sample=99,
            source_start_sample=100,
            proxy_start_sample=0,
            decoded_sample_count=50,
        )


def test_exclusive_end_sample_rejected() -> None:
    with pytest.raises(InvalidSampleMappingError):
        map_source_to_proxy_sample(
            source_sample=150,
            source_start_sample=100,
            proxy_start_sample=0,
            decoded_sample_count=50,
        )


def test_leading_trim_is_not_subtracted_twice() -> None:
    result = map_source_to_proxy_sample(
        source_sample=2112,
        source_start_sample=2112,
        proxy_start_sample=0,
        decoded_sample_count=5000,
        leading_trim_samples=2112,
    )
    assert result == 0
    assert result != -2112


def test_invalid_sample_rate_rejected() -> None:
    with pytest.raises(InvalidManifestError):
        AudioSampleTiming(
            sample_rate=0,
            source_start_sample=0,
            proxy_start_sample=0,
            leading_trim_samples=0,
            trailing_trim_samples=0,
            decoded_sample_count=1,
        )


def test_negative_trim_rejected() -> None:
    with pytest.raises(InvalidManifestError):
        AudioSampleTiming(
            sample_rate=48000,
            source_start_sample=0,
            proxy_start_sample=0,
            leading_trim_samples=-1,
            trailing_trim_samples=0,
            decoded_sample_count=1,
        )


def test_negative_decoded_count_rejected() -> None:
    with pytest.raises(InvalidManifestError):
        AudioSampleTiming(
            sample_rate=48000,
            source_start_sample=0,
            proxy_start_sample=0,
            leading_trim_samples=0,
            trailing_trim_samples=0,
            decoded_sample_count=-1,
        )


def test_validate_audio_timing_fields_ok() -> None:
    timing = AudioSampleTiming(
        sample_rate=48000,
        source_start_sample=0,
        proxy_start_sample=0,
        leading_trim_samples=0,
        trailing_trim_samples=0,
        decoded_sample_count=10,
    )
    validate_audio_timing_fields(timing)
