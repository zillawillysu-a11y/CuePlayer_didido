"""Build a Music-lane AudioBuffer from a video clip's embedded audio.

Used when a song has video but no separate music file — the main waveform
should still show something useful for marking (rehearsal videos, etc.).
Long sources are downsampled into an overview buffer so we never allocate
full-rate PCM for a multi-hour file.

Heavy / multi-hour clips use a *sparse* probe pattern (short seeks with large
gaps) so the build finishes quickly and yields ``av_path_lock`` often enough
for Preview + VideoAudioMixer (Web Remote Listen) to keep decoding.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

import numpy as np

from cueplayer.domain.models import VideoClip
from cueplayer.media.audio_loader import AudioBuffer, build_peak_pyramid
from cueplayer.media.video_audio_loader import MAX_VIDEO_AUDIO_DECODE_SECONDS, load_video_audio
from cueplayer.media.video_limits import clip_is_heavy

# Overview rate for long videos — enough for timeline marking when zoomed out,
# ~1.6 MB mono per hour.
_OVERVIEW_HZ = 400
# Dense overview (non-heavy): decode this much source audio per pass.
# Shorter windows release ``av_path_lock`` more often so Preview/seek stay alive.
_OVERVIEW_WINDOW_SECONDS = 10.0
# Heavy clips: short probe + large step so a 2h file does not monopolize PyAV.
_HEAVY_PROBE_SECONDS = 1.25
_HEAVY_MAX_PROBES = 360
_HEAVY_MIN_STEP_SECONDS = 12.0
# Yield the path lock between probes so mixer / Preview can run.
_HEAVY_YIELD_SECONDS = 0.04


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

    # For each output frame inside the clip, sample from PCM by source time.
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
    Absolute-only peaks used to draw as a comb under the midline only.
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


def build_music_standin_from_video(
    clip: VideoClip,
    *,
    timeline_duration: float,
    cancel_check: Callable[[], bool] | None = None,
) -> AudioBuffer | None:
    """
    Return a display/playback-style AudioBuffer for the Music lane, or None
    when the video has no audio stream.

    ``cancel_check`` (optional) is polled between overview windows — return
    True to abort early (song switch / newer standin token) so long builds
    do not keep holding ``av_path_lock`` after the user has moved on.
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

    # Long rehearsal: sparse overview across the whole timeline length.
    overview_hz = _OVERVIEW_HZ
    total_frames = max(1, int(round(timeline_duration * overview_hz)))
    overview = np.zeros(total_frames, dtype=np.float32)

    heavy = clip_is_heavy(clip)
    if heavy:
        # Cap probe count so multi-hour files finish without starving Listen.
        probes = min(_HEAVY_MAX_PROBES, max(48, int(span / _HEAVY_MIN_STEP_SECONDS) + 1))
        step = max(_HEAVY_MIN_STEP_SECONDS, span / float(probes))
        window = min(_HEAVY_PROBE_SECONDS, step * 0.45, MAX_VIDEO_AUDIO_DECODE_SECONDS)
    else:
        step = 0.0  # contiguous advance from decode length
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
            t += step if heavy else window
            if heavy:
                time.sleep(_HEAVY_YIELD_SECONDS)
            continue
        peaks = _downsample_to_overview(chunk.samples, chunk.sample_rate, overview_hz)
        # Map chunk origin → timeline via clip.start + (src - src_in).
        origin = float(chunk.origin_seconds)
        for i, peak in enumerate(peaks):
            src_t = origin + (i / float(overview_hz))
            local = src_t - src_in
            if local < -1e-6 or local >= span:
                continue
            timeline_t = float(clip.start_seconds) + local
            idx = int(round(timeline_t * overview_hz))
            if 0 <= idx < total_frames:
                # Keep the stronger signed peak (not abs-max → unipolar).
                if abs(float(peak)) > abs(float(overview[idx])):
                    overview[idx] = float(peak)
        if heavy:
            t = origin + step
            time.sleep(_HEAVY_YIELD_SECONDS)
        else:
            t = origin + (chunk.frames / float(chunk.sample_rate))
            if t <= origin + 1e-3:
                t += window

    if _cancelled():
        return None
    stereo = np.stack([overview, overview], axis=1)
    return _buffer_from_stereo(path, overview_hz, stereo)
