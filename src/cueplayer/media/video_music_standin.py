"""Music-lane display buffer derived from the shared VideoWaveformArtifact.

Playback PCM remains VideoAudioMixer. This module never full-rate-decodes
embedded audio for waveform display and never uses sparse probes.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np

from cueplayer.diagnostics import perf as perf_diag
from cueplayer.domain.models import VideoClip
from cueplayer.media.audio_loader import AudioBuffer, build_peak_pyramid
from cueplayer.media.video_limits import clip_source_duration_seconds
from cueplayer.media.video_waveform_artifact import (
    VideoWaveformArtifact,
    artifact_store,
    signed_overview_from_artifact,
    waveform_build_is_paused,
)


def _buffer_from_signed_overview(
    path: Path,
    *,
    overview: np.ndarray,
    overview_hz: float,
    timeline_duration: float,
    clip: VideoClip,
) -> AudioBuffer:
    """Place source-time overview peaks onto the song timeline (NaN = pending)."""
    total_dur = max(0.05, float(timeline_duration), float(clip.end_seconds))
    hz = max(1.0, float(overview_hz))
    total_frames = max(1, int(round(total_dur * hz)))
    out = np.full(total_frames, np.nan, dtype=np.float32)

    src_in = max(0.0, float(clip.source_in_seconds))
    span = max(0.05, float(clip.source_span_seconds or clip.duration_seconds))
    clip_start = max(0.0, float(clip.start_seconds))
    clip_end = min(total_dur, float(clip.end_seconds))

    i0 = int(round(clip_start * hz))
    i1 = int(round(clip_end * hz))
    i0 = max(0, min(total_frames, i0))
    i1 = max(i0, min(total_frames, i1))
    if i1 <= i0 or overview.size == 0:
        finite = np.nan_to_num(out, nan=0.0)
        samples = np.stack([finite, finite], axis=1).astype(np.float32)
        _, levels = build_peak_pyramid(samples, int(round(hz)))
        return AudioBuffer(
            path=path,
            sample_rate=int(round(hz)),
            samples=samples,
            mono=out,
            peak_levels=levels,
        )

    n = i1 - i0
    local_t = np.arange(n, dtype=np.float64) / hz
    if clip.media_kind == "still":
        src_t = np.full(n, src_in, dtype=np.float64)
    else:
        src_t = src_in + np.mod(local_t, span)
    src_i = np.round(src_t * hz).astype(np.int64)
    valid = (src_i >= 0) & (src_i < overview.size)
    dest = np.arange(i0, i1, dtype=np.int64)
    for d, src_idx, ok in zip(dest, src_i, valid):
        if not ok:
            continue
        val = overview[int(src_idx)]
        if np.isfinite(val):
            out[int(d)] = float(val)

    finite = np.nan_to_num(out, nan=0.0).astype(np.float32)
    samples = np.stack([finite, finite], axis=1)
    _, levels = build_peak_pyramid(samples, int(round(hz)))
    return AudioBuffer(
        path=path,
        sample_rate=int(round(hz)),
        samples=samples,
        mono=out.astype(np.float32, copy=False),
        peak_levels=levels,
    )


def audio_from_artifact(
    path: Path,
    clip: VideoClip,
    art: VideoWaveformArtifact,
    *,
    timeline_duration: float,
) -> AudioBuffer:
    if perf_diag.is_enabled():
        perf_diag.count("waveform_artifact.consumer_main_lane")
    overview = signed_overview_from_artifact(art)
    return _buffer_from_signed_overview(
        path,
        overview=overview,
        overview_hz=float(art.peaks_per_second),
        timeline_duration=timeline_duration,
        clip=clip,
    )


def try_music_standin_from_disk(
    clip: VideoClip, *, timeline_duration: float
) -> AudioBuffer | None:
    """Warm hydrate Music stand-in from shared artifact disk — no decode."""
    if clip.media_kind == "still":
        return None
    path = Path(clip.path)
    if not path.is_file():
        return None
    duration = max(
        clip_source_duration_seconds(clip),
        float(clip.source_span_seconds or clip.duration_seconds or 0.0),
        0.05,
    )
    art = artifact_store().get_or_load_disk(path, duration_seconds=duration)
    if art is None or not art.complete:
        return None
    return audio_from_artifact(
        path, clip, art, timeline_duration=timeline_duration
    )


def build_music_standin_from_video(
    clip: VideoClip,
    *,
    timeline_duration: float,
    cancel_check: Callable[[], bool] | None = None,
    on_progress: Callable[[AudioBuffer], None] | None = None,
    pause_check: Callable[[], bool] | None = None,
) -> AudioBuffer | None:
    """
    Display AudioBuffer for the Music lane from the shared artifact.

    Safe to call from a background worker (may wait). GUI must use
    ``try_music_standin_from_disk`` / ``ensure_building`` instead of blocking.
    """
    path = Path(clip.path)
    if not path.is_file() or clip.media_kind == "still":
        return None

    def _cancelled() -> bool:
        return bool(cancel_check and cancel_check())

    if _cancelled():
        return None

    timeline_duration = max(0.05, float(timeline_duration), float(clip.end_seconds))
    source_duration = max(
        clip_source_duration_seconds(clip),
        float(clip.source_span_seconds or clip.duration_seconds or 0.0),
        0.05,
    )

    def _on_art(art: VideoWaveformArtifact) -> None:
        if on_progress is None or _cancelled():
            return
        on_progress(
            audio_from_artifact(
                path, clip, art, timeline_duration=timeline_duration
            )
        )

    def _pause() -> bool:
        if pause_check is not None and pause_check():
            return True
        return waveform_build_is_paused()

    art = artifact_store().wait_in_worker(
        path,
        duration_seconds=source_duration,
        cancel_check=cancel_check,
        pause_check=_pause,
        on_update=_on_art,
    )
    if art is None or _cancelled():
        return None
    return audio_from_artifact(
        path, clip, art, timeline_duration=timeline_duration
    )
