"""Long / heavy video safety caps (rehearsal recordings)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cueplayer.domain.models import VideoClip
from cueplayer.media.scrub_frame_cache import ScrubFrameCache
from cueplayer.media.video_clip_waveform import VideoClipWaveformCache
from cueplayer.media.video_limits import (
    HEAVY_VIDEO_AUDIO_DECODE_SECONDS,
    HEAVY_VIDEO_SECONDS,
    MAX_VIDEO_AUDIO_DECODE_SECONDS,
    WAVEFORM_ARTIFACT_SECONDS,
    audio_decode_cap_for_clip,
    clip_is_heavy,
    clip_uses_waveform_artifact,
    source_needs_long_video_warning,
)
from cueplayer.playback.video_audio_mixer import VideoAudioMixer


def test_clip_is_heavy_for_hour_long_source() -> None:
    clip = VideoClip.create(
        name="rehearsal",
        path=Path("r.mp4"),
        duration_seconds=HEAVY_VIDEO_SECONDS,
        source_duration_seconds=3600.0,
    )
    assert clip_is_heavy(clip)
    assert audio_decode_cap_for_clip(clip) == HEAVY_VIDEO_AUDIO_DECODE_SECONDS


def test_short_clip_uses_normal_audio_cap() -> None:
    clip = VideoClip.create(
        name="song",
        path=Path("s.mp4"),
        duration_seconds=180.0,
        source_duration_seconds=180.0,
    )
    assert not clip_is_heavy(clip)
    assert audio_decode_cap_for_clip(clip) == MAX_VIDEO_AUDIO_DECODE_SECONDS


def test_song_length_clip_uses_waveform_artifact() -> None:
    clip = VideoClip.create(
        name="song",
        path=Path("s.mp4"),
        duration_seconds=WAVEFORM_ARTIFACT_SECONDS,
        source_duration_seconds=WAVEFORM_ARTIFACT_SECONDS,
    )
    assert not clip_is_heavy(clip)
    assert clip_uses_waveform_artifact(clip)
    short = VideoClip.create(
        name="sting",
        path=Path("t.mp4"),
        duration_seconds=10.0,
        source_duration_seconds=10.0,
    )
    assert not clip_uses_waveform_artifact(short)


def test_source_needs_long_video_warning_by_duration() -> None:
    assert source_needs_long_video_warning(duration_seconds=45 * 60)
    assert not source_needs_long_video_warning(duration_seconds=5 * 60)


def test_scrub_cache_skips_heavy_clips() -> None:
    clip = VideoClip.create(
        name="rehearsal",
        path=Path("r.mp4"),
        duration_seconds=3600.0,
        source_duration_seconds=3600.0,
    )
    cache = ScrubFrameCache()
    with patch.object(cache, "_executor") as executor:
        cache.ensure(clip)
        executor.submit.assert_not_called()


def test_waveform_preload_submits_heavy_clips_via_shared_artifact() -> None:
    """Heavy clips use the continuous artifact path — preload must submit."""
    clip = VideoClip.create(
        name="rehearsal",
        path=Path("r.mp4"),
        duration_seconds=3600.0,
        source_duration_seconds=3600.0,
    )
    cache = VideoClipWaveformCache()
    with patch.object(cache, "get_peaks") as get_peaks:
        cache.preload([clip])
        get_peaks.assert_called_once_with(clip)


def test_mixer_preload_still_loads_heavy_clips() -> None:
    """Heavy clips skip waveform/scrub, but must still get embedded audio."""
    clip = VideoClip.create(
        name="rehearsal",
        path=Path("r.mp4"),
        duration_seconds=3600.0,
        source_duration_seconds=3600.0,
    )
    mixer = VideoAudioMixer()
    mixer.set_song(MagicMock(video_clips=[clip]))
    with patch.object(mixer, "_executor") as executor:
        mixer.preload([clip])
        executor.submit.assert_called()
