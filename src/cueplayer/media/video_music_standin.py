"""Music-lane display bound to the shared VideoWaveformArtifact.

Playback PCM remains VideoAudioMixer. Progressive updates never construct a
full-duration AudioBuffer / peak pyramid — the Timeline paints the artifact
peak structure directly.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from cueplayer.diagnostics import perf as perf_diag
from cueplayer.domain.models import VideoClip
from cueplayer.media.audio_loader import AudioBuffer
from cueplayer.media.video_limits import clip_source_duration_seconds
from cueplayer.media.video_waveform_artifact import (
    VideoWaveformArtifact,
    artifact_store,
    waveform_build_is_paused,
)


def try_music_standin_artifact_from_disk(
    clip: VideoClip, *, timeline_duration: float
) -> VideoWaveformArtifact | None:
    """Warm hydrate shared artifact from disk — no source decode."""
    del timeline_duration
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
    if art is None or art.coverage_ratio <= 0:
        return None
    if perf_diag.is_enabled():
        perf_diag.count("waveform_artifact.consumer_main_lane")
    return art


def try_music_standin_from_disk(
    clip: VideoClip, *, timeline_duration: float
) -> AudioBuffer | None:
    """Deprecated AudioBuffer warm path — prefer artifact binding.

    Kept for callers that still expect an AudioBuffer; returns None so the
    progressive artifact path is used instead (no O(duration) rebuild).
    """
    del clip, timeline_duration
    return None


def audio_from_artifact(
    path: Path,
    clip: VideoClip,
    art: VideoWaveformArtifact,
    *,
    timeline_duration: float,
) -> AudioBuffer:
    """Compatibility mapper — avoided on progressive updates.

    Only used by legacy tests that still assert an AudioBuffer shape. Prefer
    ``TimelineWidget.set_artifact_waveform``.
    """
    # Local import keeps the hot progressive path free of pyramid work unless
    # a test explicitly asks for a buffer snapshot.
    import numpy as np

    from cueplayer.media.audio_loader import build_peak_pyramid
    from cueplayer.media.video_waveform_artifact import signed_overview_from_artifact

    if perf_diag.is_enabled():
        perf_diag.count("waveform_artifact.consumer_main_lane")
    overview = signed_overview_from_artifact(art)
    total_dur = max(0.05, float(timeline_duration), float(clip.end_seconds))
    hz = max(1.0, float(art.peaks_per_second))
    total_frames = max(1, int(round(total_dur * hz)))
    out = np.full(total_frames, np.nan, dtype=np.float32)

    src_in = max(0.0, float(clip.source_in_seconds))
    span = max(0.05, float(clip.source_span_seconds or clip.duration_seconds))
    clip_start = max(0.0, float(clip.start_seconds))
    clip_end = min(total_dur, float(clip.end_seconds))
    i0 = max(0, min(total_frames, int(round(clip_start * hz))))
    i1 = max(i0, min(total_frames, int(round(clip_end * hz))))
    if i1 > i0 and overview.size > 0:
        n = i1 - i0
        local_t = np.arange(n, dtype=np.float64) / hz
        if clip.media_kind == "still":
            src_t = np.full(n, src_in, dtype=np.float64)
        else:
            src_t = src_in + np.mod(local_t, span)
        src_i = np.round(src_t * hz).astype(np.int64)
        valid = (src_i >= 0) & (src_i < overview.size)
        dest = np.arange(i0, i1, dtype=np.int64)
        ok_dest = dest[valid]
        ok_src = src_i[valid]
        vals = overview[ok_src]
        finite = np.isfinite(vals)
        out[ok_dest[finite]] = vals[finite]

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


def build_music_standin_from_video(
    clip: VideoClip,
    *,
    timeline_duration: float,
    cancel_check: Callable[[], bool] | None = None,
    on_progress: Callable[[VideoWaveformArtifact], None] | None = None,
    pause_check: Callable[[], bool] | None = None,
) -> VideoWaveformArtifact | None:
    """
    Shared artifact for the Music lane (progressive partials OK).

    Safe to call from a background worker (may wait). GUI must bind via
    ``set_artifact_waveform`` — never rebuild a full-duration AudioBuffer on
    each progress tick.
    """
    path = Path(clip.path)
    if not path.is_file() or clip.media_kind == "still":
        return None

    def _cancelled() -> bool:
        return bool(cancel_check and cancel_check())

    if _cancelled():
        return None

    del timeline_duration  # Timeline maps artifact bins via clip geometry.
    source_duration = max(
        clip_source_duration_seconds(clip),
        float(clip.source_span_seconds or clip.duration_seconds or 0.0),
        0.05,
    )

    def _on_art(art: VideoWaveformArtifact) -> None:
        if on_progress is None or _cancelled():
            return
        if perf_diag.is_enabled():
            perf_diag.count("waveform_artifact.consumer_main_lane")
        on_progress(art)

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
    if perf_diag.is_enabled():
        perf_diag.count("waveform_artifact.consumer_main_lane")
    return art
