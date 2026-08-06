"""Build a Music-lane AudioBuffer from a video clip's embedded audio.

Used when a song has video but no separate music file — the main waveform
should still show something useful for marking (rehearsal videos, etc.).

Long / heavy sources share ``EmbeddedWaveformArtifactStore`` with the Video
Track lane — one continuous low-resolution scan (no sparse 12 s probes, no
dual full-rate PCM caches).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np

from cueplayer.diagnostics import perf as perf_diag
from cueplayer.domain.models import VideoClip
from cueplayer.media.audio_loader import AudioBuffer, build_peak_pyramid
from cueplayer.media.video_audio_loader import MAX_VIDEO_AUDIO_DECODE_SECONDS, load_video_audio
from cueplayer.media.video_limits import clip_is_heavy, clip_source_duration_seconds
from cueplayer.media.video_waveform_artifact import (
    EmbeddedWaveformArtifact,
    artifact_store,
    signed_overview_from_artifact,
)

# Overview rate for medium-length videos (non-heavy continuous path).
_OVERVIEW_HZ = 400
_OVERVIEW_WINDOW_SECONDS = 10.0


def _buffer_from_stereo(
    path: Path,
    sample_rate: int,
    samples: np.ndarray,
) -> AudioBuffer:
    if samples.ndim == 1:
        samples = np.stack([samples, samples], axis=1)
    elif samples.shape[1] == 1:
        samples = np.repeat(samples, 2, axis=1)
    elif samples.shape[1] > 2:
        samples = samples[:, :2]
    samples = np.ascontiguousarray(samples, dtype=np.float32)
    mono, levels = build_peak_pyramid(samples, int(sample_rate))
    return AudioBuffer(
        path=path,
        sample_rate=int(sample_rate),
        samples=samples,
        mono=mono,
        peak_levels=levels,
    )


def _buffer_from_signed_overview(
    path: Path,
    *,
    overview: np.ndarray,
    overview_hz: float,
    timeline_duration: float,
    clip: VideoClip,
) -> AudioBuffer:
    """Place source-time overview peaks onto the song timeline.

    Pending (NaN) bins stay NaN so the Music painter skips them — they must
    not render as fabricated zero silence.
    """
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
        stereo = np.stack([out, out], axis=1)
        # Pyramid cannot use NaN — finite-zero scaffold; mono keeps NaN for paint.
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
    idx = np.round(src_t * hz).astype(np.int64)
    # overview is indexed from source 0 at overview_hz (== artifact pps).
    valid = (idx >= 0) & (idx < overview.size)
    dest = np.arange(i0, i1, dtype=np.int64)
    for d, src_i, ok in zip(dest, idx, valid, strict=False):
        if not ok:
            continue
        val = overview[int(src_i)]
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


def _place_on_timeline(
    *,
    path: Path,
    clip: VideoClip,
    pcm: np.ndarray,
    pcm_rate: int,
    pcm_origin_source: float,
    timeline_duration: float,
) -> AudioBuffer:
    """Map source PCM onto the song timeline (silence before clip.start)."""
    total_dur = max(0.05, float(timeline_duration), float(clip.end_seconds))
    total_frames = max(1, int(round(total_dur * pcm_rate)))
    out = np.zeros((total_frames, 2), dtype=np.float32)

    src_in = max(0.0, float(clip.source_in_seconds))
    span = max(0.05, float(clip.source_span_seconds or clip.duration_seconds))
    clip_start = max(0.0, float(clip.start_seconds))

    if pcm.ndim == 1:
        stereo = np.stack([pcm, pcm], axis=1)
    elif pcm.shape[1] == 1:
        stereo = np.repeat(pcm, 2, axis=1)
    else:
        stereo = pcm[:, :2]

    clip_end = min(total_dur, float(clip.end_seconds))
    i0 = int(round(clip_start * pcm_rate))
    i1 = int(round(clip_end * pcm_rate))
    i0 = max(0, min(total_frames, i0))
    i1 = max(i0, min(total_frames, i1))
    if i1 <= i0 or stereo.shape[0] == 0:
        return _buffer_from_stereo(path, pcm_rate, out)

    n = i1 - i0
    local_t = (np.arange(n, dtype=np.float64) / float(pcm_rate))
    if clip.media_kind == "still":
        src_t = np.full(n, src_in, dtype=np.float64)
    else:
        src_t = src_in + np.mod(local_t, span)
    idx = np.round((src_t - float(pcm_origin_source)) * pcm_rate).astype(np.int64)
    valid = (idx >= 0) & (idx < stereo.shape[0])
    if np.any(valid):
        dest = np.arange(i0, i1, dtype=np.int64)[valid]
        out[dest] = stereo[idx[valid]]
    return _buffer_from_stereo(path, pcm_rate, out)


def _downsample_to_overview(samples: np.ndarray, src_rate: int, overview_hz: int) -> np.ndarray:
    """Peak-hold downsample stereo/mono float32 to overview_hz mono.

    Keeps the sample with the largest absolute value **with sign** so the
    Music-lane painter (bipolar mid±peak) fills both halves of the lane.
    """
    if samples.ndim == 2:
        mono = samples.mean(axis=1).astype(np.float32)
    else:
        mono = np.asarray(samples, dtype=np.float32)
    if mono.size == 0 or src_rate <= 0:
        return np.zeros(1, dtype=np.float32)
    ratio = max(1, int(round(src_rate / float(overview_hz))))
    buckets = max(1, mono.size // ratio)
    usable = buckets * ratio
    chunk = mono[:usable].reshape(buckets, ratio)
    idx = np.argmax(np.abs(chunk), axis=1)
    return chunk[np.arange(buckets), idx].astype(np.float32)


def _audio_from_artifact(
    path: Path,
    clip: VideoClip,
    art: EmbeddedWaveformArtifact,
    *,
    timeline_duration: float,
) -> AudioBuffer:
    if perf_diag.is_enabled():
        perf_diag.count("video_waveform.artifact.consumer_main_lane")
    overview = signed_overview_from_artifact(art)
    return _buffer_from_signed_overview(
        path,
        overview=overview,
        overview_hz=float(art.peaks_per_second),
        timeline_duration=timeline_duration,
        clip=clip,
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
    Return a display AudioBuffer for the Music lane, or None when the video
    has no audio stream.

    ``cancel_check`` is polled between overview windows / artifact chunks.
    ``on_progress`` may receive partial buffers (pending regions are NaN).
    ``pause_check`` (optional) throttles the shared artifact while playing.
    """
    path = Path(clip.path)
    if not path.is_file() or clip.media_kind == "still":
        return None

    def _cancelled() -> bool:
        return bool(cancel_check and cancel_check())

    if _cancelled():
        return None

    src_in = max(0.0, float(clip.source_in_seconds))
    span = max(0.05, float(clip.source_span_seconds or clip.duration_seconds))
    timeline_duration = max(0.05, float(timeline_duration), float(clip.end_seconds))
    source_duration = max(
        clip_source_duration_seconds(clip),
        span,
        0.05,
    )

    # Short enough: one decode at native rate.
    if span <= MAX_VIDEO_AUDIO_DECODE_SECONDS and not clip_is_heavy(clip):
        if _cancelled():
            return None
        buf = load_video_audio(
            path, start_seconds=src_in, max_duration_seconds=span
        )
        if buf is None:
            return None
        return _place_on_timeline(
            path=path,
            clip=clip,
            pcm=buf.samples,
            pcm_rate=buf.sample_rate,
            pcm_origin_source=float(buf.origin_seconds),
            timeline_duration=timeline_duration,
        )

    # Heavy / long: shared continuous artifact (Music + Video lane).
    if clip_is_heavy(clip) or span > MAX_VIDEO_AUDIO_DECODE_SECONDS:
        store = artifact_store()

        def _on_art(art: EmbeddedWaveformArtifact) -> None:
            if on_progress is None or _cancelled():
                return
            buf = _audio_from_artifact(
                path, clip, art, timeline_duration=timeline_duration
            )
            on_progress(buf)

        art = store.build_or_wait(
            path,
            duration_seconds=source_duration,
            cancel_check=cancel_check,
            pause_check=pause_check,
            on_update=_on_art,
        )
        if art is None or _cancelled():
            return None
        return _audio_from_artifact(
            path, clip, art, timeline_duration=timeline_duration
        )

    # Medium non-heavy: contiguous overview windows (legacy path).
    overview_hz = _OVERVIEW_HZ
    total_frames = max(1, int(round(timeline_duration * overview_hz)))
    overview = np.full(total_frames, np.nan, dtype=np.float32)

    window = min(_OVERVIEW_WINDOW_SECONDS, MAX_VIDEO_AUDIO_DECODE_SECONDS)
    t = src_in
    end = src_in + span
    while t < end - 1e-6:
        if _cancelled():
            return None
        chunk = load_video_audio(
            path, start_seconds=t, max_duration_seconds=min(window, end - t)
        )
        if chunk is None or chunk.frames <= 0:
            t += window
            continue
        peaks = _downsample_to_overview(chunk.samples, chunk.sample_rate, overview_hz)
        origin = float(chunk.origin_seconds)
        for i, peak in enumerate(peaks):
            src_t = origin + (i / float(overview_hz))
            local = src_t - src_in
            if local < -1e-6 or local >= span:
                continue
            timeline_t = float(clip.start_seconds) + local
            idx = int(round(timeline_t * overview_hz))
            if 0 <= idx < total_frames:
                if not np.isfinite(overview[idx]) or abs(float(peak)) > abs(
                    float(overview[idx])
                ):
                    overview[idx] = float(peak)
        t = origin + (chunk.frames / float(chunk.sample_rate))
        if t <= origin + 1e-3:
            t += window

    if _cancelled():
        return None
    # Remaining NaN → true uncovered pending; convert only leading/covered.
    # For medium path we treated missing chunks as skipped — mark decoded
    # gaps inside the clip as silence (0) only where we attempted decode.
    finite = np.nan_to_num(overview, nan=0.0)
    stereo = np.stack([finite, finite], axis=1)
    return _buffer_from_stereo(path, overview_hz, stereo)
