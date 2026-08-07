"""Downsampled peak envelopes for video-clip lane waveforms."""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from cueplayer.diagnostics import perf as perf_diag
from cueplayer.domain.models import VideoClip
from cueplayer.media.audio_loader import PeakLevel, build_peak_pyramid, choose_peak_level
from cueplayer.media.video_audio_cache import get_video_audio_mono_for_waveform
from cueplayer.media.video_limits import (
    clip_source_duration_seconds,
    clip_uses_waveform_artifact,
)
from cueplayer.media.video_waveform_artifact import (
    EmbeddedWaveformArtifact,
    artifact_store,
    signed_overview_from_artifact,
    waveform_build_is_paused,
)


@dataclass(frozen=True)
class ClipWaveformKey:
    path: str
    mtime_ns: int
    source_in: float
    source_out: float | None
    duration: float
    media_kind: str


@dataclass
class ClipWaveformPeaks:
    """Zoom-aware waveform data — same pyramid strategy as the main audio lane."""

    sample_rate: int
    mono_origin_seconds: float
    mono: np.ndarray  # display-normalized mono indexed by source time - origin
    peak_levels: list[PeakLevel]
    # Legacy single-resolution envelope (preview / tests).
    mins: np.ndarray
    maxs: np.ndarray
    # Optional coverage mask aligned with ``mono`` (1=decoded). Pending bins
    # must not paint as fabricated zero silence.
    coverage: np.ndarray | None = None


def build_clip_waveform_data(
    clip: VideoClip,
    *,
    mono: np.ndarray,
    sample_rate: int,
    mono_origin_seconds: float = 0.0,
    coverage: np.ndarray | None = None,
) -> ClipWaveformPeaks | None:
    """Build pyramid + mono for a clip's embedded audio (source-time indexed)."""
    if mono.size == 0 or sample_rate <= 0:
        return None
    duration = max(0.0, float(clip.duration_seconds))
    if duration <= 1e-9:
        return None

    # NaN = pending; pyramid build needs finite samples — replace pending with 0
    # only for pyramid construction, keep NaN mono for paint skip.
    finite = np.nan_to_num(mono, nan=0.0).astype(np.float32, copy=False)
    display, levels = build_peak_pyramid(finite.reshape(-1, 1), sample_rate)

    # Coarse overview buckets across clip timeline for instant preview paint.
    buckets = max(64, min(512, int(duration * 40)))
    span = max(0.0, clip.source_span_seconds)
    src_in = max(0.0, float(clip.source_in_seconds))
    origin = float(mono_origin_seconds)
    spb = duration / buckets
    half_window = max(1, int(round(sample_rate * max(spb / 2.0, 1.0 / buckets))))
    mins = np.zeros(buckets, dtype=np.float32)
    maxs = np.zeros(buckets, dtype=np.float32)
    t_mids = (np.arange(buckets, dtype=np.float64) + 0.5) * spb
    if clip.media_kind == "still":
        src_times = np.full(buckets, src_in, dtype=np.float64)
    elif span <= 1e-9:
        src_times = np.full(buckets, src_in, dtype=np.float64)
    else:
        src_times = src_in + np.mod(t_mids, span)
    centers = np.round((src_times - origin) * sample_rate).astype(np.int64)
    cov = coverage
    for b in range(buckets):
        center = int(centers[b])
        s0 = max(0, center - half_window)
        s1 = min(display.size, center + half_window)
        if s0 >= s1:
            continue
        if cov is not None:
            c0 = max(0, min(cov.size, s0))
            c1 = max(c0, min(cov.size, s1))
            if c0 >= c1 or not np.any(cov[c0:c1]):
                mins[b] = np.nan
                maxs[b] = np.nan
                continue
        segment = display[s0:s1]
        mins[b] = float(segment.min())
        maxs[b] = float(segment.max())

    return ClipWaveformPeaks(
        sample_rate=int(sample_rate),
        mono_origin_seconds=origin,
        mono=np.asarray(mono, dtype=np.float32),
        peak_levels=levels,
        mins=mins,
        maxs=maxs,
        coverage=(
            np.asarray(coverage, dtype=np.uint8) if coverage is not None else None
        ),
    )


def peaks_from_embedded_artifact(
    clip: VideoClip, art: EmbeddedWaveformArtifact
) -> ClipWaveformPeaks | None:
    """Map the shared source artifact into clip paint peaks (source-time indexed).

    Keeps full-resolution bipolar ``mins``/``maxs`` (not the 64–512 clip-local
    overview buckets) so Video Track paint can draw Music-lane-style strokes.
    """
    if perf_diag.is_enabled():
        perf_diag.count("video_waveform.artifact.consumer_video_lane")
    if art.n_bins <= 0:
        return None
    sr = max(1, int(round(float(art.peaks_per_second))))
    mono = signed_overview_from_artifact(art)
    cov = np.asarray(art.coverage, dtype=np.uint8)
    mins = np.asarray(art.mins, dtype=np.float32).copy()
    maxs = np.asarray(art.maxs, dtype=np.float32).copy()
    # Pending bins must not paint as fabricated zero silence.
    pending = cov == 0
    mins[pending] = np.nan
    maxs[pending] = np.nan
    finite = np.nan_to_num(mono, nan=0.0).astype(np.float32, copy=False)
    _display, levels = build_peak_pyramid(finite.reshape(-1, 1), sr)
    return ClipWaveformPeaks(
        sample_rate=sr,
        mono_origin_seconds=float(art.origin_seconds),
        mono=np.asarray(mono, dtype=np.float32),
        peak_levels=levels,
        mins=mins,
        maxs=maxs,
        coverage=cov,
    )


def timeline_to_clip_local(timeline_t: float, clip: VideoClip) -> float | None:
    """Map absolute timeline seconds to clip-local seconds, or None if outside."""
    if timeline_t < clip.start_seconds or timeline_t > clip.end_seconds:
        return None
    return timeline_t - clip.start_seconds


def clip_local_to_source_time(clip: VideoClip, clip_local_t: float) -> float:
    """Clip-local timeline seconds → source media seconds (trim + loop)."""
    src_in = max(0.0, float(clip.source_in_seconds))
    if clip.media_kind == "still":
        return src_in
    span = max(0.0, clip.source_span_seconds)
    if span <= 1e-9:
        return src_in
    return src_in + (clip_local_t % span)


def sample_clip_peaks_for_times(
    peaks: ClipWaveformPeaks,
    *,
    duration: float,
    clip_t0: float,
    clip_t1: float,
) -> tuple[float, float]:
    """Signed min/max for clip-local time span [clip_t0, clip_t1) — overview envelope."""
    n = int(peaks.mins.size)
    if n == 0 or duration <= 1e-9:
        return float("nan"), float("nan")
    clip_t0 = max(0.0, min(duration, clip_t0))
    clip_t1 = max(clip_t0, min(duration, clip_t1))
    b0 = int(clip_t0 / duration * n)
    b1 = min(n, max(b0 + 1, int(clip_t1 / duration * n)))
    segment_lo = peaks.mins[b0:b1]
    segment_hi = peaks.maxs[b0:b1]
    if segment_lo.size == 0:
        return float("nan"), float("nan")
    if np.all(np.isnan(segment_lo)) and np.all(np.isnan(segment_hi)):
        return float("nan"), float("nan")
    lo = float(np.nanmin(segment_lo))
    hi = float(np.nanmax(segment_hi))
    return lo, hi


def sample_source_peaks_for_clip_times(
    peaks: ClipWaveformPeaks,
    clip: VideoClip,
    *,
    clip_t0: float,
    clip_t1: float,
    samples_per_pixel: float,
) -> tuple[float, float]:
    """Peak min/max for a clip-local span using the source-time pyramid."""
    src0 = clip_local_to_source_time(clip, clip_t0)
    src1 = clip_local_to_source_time(clip, max(clip_t0, clip_t1 - 1e-9))
    sr = peaks.sample_rate
    origin = peaks.mono_origin_seconds
    s0 = int(round((src0 - origin) * sr))
    s1 = int(round((src1 - origin) * sr))
    s0 = max(0, s0)
    s1 = max(s0 + 1, min(peaks.mono.size, s1))
    if peaks.coverage is not None:
        c0 = max(0, min(peaks.coverage.size, s0))
        c1 = max(c0, min(peaks.coverage.size, s1))
        if c0 >= c1 or not np.any(peaks.coverage[c0:c1]):
            return float("nan"), float("nan")
    # Shared artifact: mins/maxs are source-aligned bipolar envelopes at the
    # same rate as mono — prefer them over the signed-collapse pyramid.
    if (
        peaks.mins.size == peaks.mono.size
        and peaks.maxs.size == peaks.mono.size
        and peaks.mins.size > 0
    ):
        lo_seg = peaks.mins[s0:s1]
        hi_seg = peaks.maxs[s0:s1]
        if lo_seg.size == 0 or (
            np.all(np.isnan(lo_seg)) and np.all(np.isnan(hi_seg))
        ):
            return float("nan"), float("nan")
        return float(np.nanmin(lo_seg)), float(np.nanmax(hi_seg))
    level = choose_peak_level(peaks.peak_levels, samples_per_pixel)
    if level is None:
        segment = peaks.mono[s0:s1]
        if segment.size == 0 or np.all(np.isnan(segment)):
            return float("nan"), float("nan")
        return float(np.nanmin(segment)), float(np.nanmax(segment))
    b0 = max(0, s0 // level.samples_per_bucket)
    b1 = min(level.maxs.size, max(b0 + 1, s1 // level.samples_per_bucket))
    return float(level.mins[b0:b1].min()), float(level.maxs[b0:b1].max())


def sample_source_raw_for_clip_times(
    peaks: ClipWaveformPeaks,
    clip: VideoClip,
    *,
    clip_t0: float,
    clip_t1: float,
) -> tuple[float, float]:
    """Raw mono min/max for a clip-local span (high zoom)."""
    src0 = clip_local_to_source_time(clip, clip_t0)
    src1 = clip_local_to_source_time(clip, max(clip_t0, clip_t1 - 1e-9))
    sr = peaks.sample_rate
    origin = peaks.mono_origin_seconds
    s0 = max(0, int(round((src0 - origin) * sr)))
    s1 = max(s0 + 1, min(peaks.mono.size, int(round((src1 - origin) * sr))))
    if peaks.coverage is not None:
        c0 = max(0, min(peaks.coverage.size, s0))
        c1 = max(c0, min(peaks.coverage.size, s1))
        if c0 >= c1 or not np.any(peaks.coverage[c0:c1]):
            return float("nan"), float("nan")
    if (
        peaks.mins.size == peaks.mono.size
        and peaks.maxs.size == peaks.mono.size
        and peaks.mins.size > 0
    ):
        lo_seg = peaks.mins[s0:s1]
        hi_seg = peaks.maxs[s0:s1]
        if lo_seg.size == 0 or (
            np.all(np.isnan(lo_seg)) and np.all(np.isnan(hi_seg))
        ):
            return float("nan"), float("nan")
        return float(np.nanmin(lo_seg)), float(np.nanmax(hi_seg))
    segment = peaks.mono[s0:s1]
    if segment.size == 0 or np.all(np.isnan(segment)):
        return float("nan"), float("nan")
    return float(np.nanmin(segment)), float(np.nanmax(segment))


def build_clip_waveform_data_from_path(clip: VideoClip) -> ClipWaveformPeaks | None:
    mono, sample_rate, origin = get_video_audio_mono_for_waveform(clip)
    if mono is None:
        return None
    return build_clip_waveform_data(
        clip,
        mono=mono,
        sample_rate=sample_rate,
        mono_origin_seconds=origin,
    )


class VideoClipWaveformCache:
    """Per-clip pyramid cache with background decode/build.

    Long/heavy sources share ``EmbeddedWaveformArtifactStore`` with the Music
    stand-in path — one continuous scan, never sparse probes / dual decoders.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._peaks: dict[ClipWaveformKey, ClipWaveformPeaks | None] = {}
        self._pending: set[ClipWaveformKey] = set()
        self._generation = 0
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="vid-wave")
        self._on_ready: Callable[[], None] | None = None
        self._last_gui_notify_mono = 0.0
        self._gui_first_notified = False
        self._gui_coalesce_s = 1.5

    def set_on_ready(self, callback: Callable[[], None] | None) -> None:
        self._on_ready = callback

    def clear(self) -> None:
        with self._lock:
            self._generation += 1
            self._peaks.clear()
            self._pending.clear()
            self._last_gui_notify_mono = 0.0
            self._gui_first_notified = False
        # Keep shared artifact RAM/disk so save→reload / song switch can
        # hydrate Video-lane peaks instantly. In-flight builds still see the
        # bumped generation via cancel_check and abort publishing.

    def _artifact_duration_for(self, clip: VideoClip) -> float:
        return max(
            clip_source_duration_seconds(clip),
            float(clip.source_span_seconds or clip.duration_seconds or 0.0),
            0.05,
        )

    def _try_hydrate_from_disk(
        self, key: ClipWaveformKey, clip: VideoClip
    ) -> ClipWaveformPeaks | None:
        """Sync disk/RAM artifact → paint peaks (no worker hop)."""
        if not clip_uses_waveform_artifact(clip):
            return None
        duration = self._artifact_duration_for(clip)
        art = artifact_store().get_or_load_disk(
            Path(clip.path), duration_seconds=duration
        )
        if art is None or not art.complete:
            return None
        if float(art.duration_seconds) + 0.5 < duration:
            return None
        mapped = peaks_from_embedded_artifact(clip, art)
        if mapped is None:
            return None
        with self._lock:
            self._peaks[key] = mapped
            self._pending.discard(key)
        if perf_diag.is_enabled():
            perf_diag.count("video_waveform.artifact.sync_hydrate")
        return mapped

    @staticmethod
    def _mtime_ns(path: Path) -> int:
        try:
            return os.stat(path).st_mtime_ns
        except OSError:
            return 0

    def key_for(self, clip: VideoClip) -> ClipWaveformKey:
        return ClipWaveformKey(
            path=str(clip.path),
            mtime_ns=self._mtime_ns(clip.path),
            source_in=round(float(clip.source_in_seconds), 6),
            source_out=(
                round(float(clip.source_out_seconds), 6)
                if clip.source_out_seconds is not None
                else None
            ),
            duration=round(float(clip.duration_seconds), 6),
            media_kind=str(clip.media_kind),
        )

    def get_peaks(self, clip: VideoClip, *, allow_submit: bool = True) -> ClipWaveformPeaks | None:
        key = self.key_for(clip)
        with self._lock:
            if key in self._peaks:
                return self._peaks[key]
            if key in self._pending:
                return None
        # Instant restore after save/reload when disk artifact exists.
        hydrated = self._try_hydrate_from_disk(key, clip)
        if hydrated is not None:
            return hydrated
        if not allow_submit:
            return None
        with self._lock:
            if key in self._peaks:
                return self._peaks[key]
            if key in self._pending:
                return None
            self._pending.add(key)
            generation = self._generation
        self._executor.submit(self._build_async, generation, key, clip)
        return None

    def peaks_for_paint(
        self, clip: VideoClip, *, allow_submit: bool = True
    ) -> ClipWaveformPeaks | None:
        return self.get_peaks(clip, allow_submit=allow_submit)

    def preload(self, clips: list[VideoClip]) -> None:
        for clip in clips:
            if clip.media_kind == "still":
                continue
            # Artifact path (disk hydrate or background build) for song-length+.
            self.get_peaks(clip)

    def flush_pending_gui_notify(self) -> None:
        """Force one GUI notify after Pause so progressive peaks become visible."""
        self._notify_ready(force=True)

    def _notify_ready(self, *, force: bool = False, complete: bool = False) -> None:
        """Coalesce progressive GUI invalidations; always allow final/complete."""
        import time as _time

        now = _time.monotonic()
        if not force and not complete:
            if waveform_build_is_paused():
                if perf_diag.is_enabled():
                    perf_diag.count(
                        "video_waveform.artifact.gui_notify_suppressed_playing"
                    )
                return
            if self._gui_first_notified and (
                now - self._last_gui_notify_mono < self._gui_coalesce_s
            ):
                if perf_diag.is_enabled():
                    perf_diag.count(
                        "video_waveform.artifact.gui_notify_coalesced"
                    )
                return
        self._last_gui_notify_mono = now
        self._gui_first_notified = True
        if perf_diag.is_enabled():
            perf_diag.count("video_waveform.artifact.gui_notify")
            if complete:
                perf_diag.count("video_waveform.backdrop_rebuild_after_ready")
        cb = self._on_ready
        if cb is not None:
            cb()

    def _build_async(self, generation: int, key: ClipWaveformKey, clip: VideoClip) -> None:
        try:
            if clip_uses_waveform_artifact(clip):
                peaks = self._build_from_shared_artifact(generation, key, clip)
            else:
                peaks = build_clip_waveform_data_from_path(clip)
        except Exception:
            peaks = None
        with self._lock:
            if generation != self._generation:
                return
            if peaks is not None:
                self._peaks[key] = peaks
            self._pending.discard(key)
        if peaks is not None:
            self._notify_ready(force=True, complete=True)

    def _build_from_shared_artifact(
        self, generation: int, key: ClipWaveformKey, clip: VideoClip
    ) -> ClipWaveformPeaks | None:
        store = artifact_store()
        duration = self._artifact_duration_for(clip)
        path = Path(clip.path)

        def _on_update(art: EmbeddedWaveformArtifact) -> None:
            with self._lock:
                if generation != self._generation:
                    return
                mapped = peaks_from_embedded_artifact(clip, art)
                if mapped is None:
                    return
                self._peaks[key] = mapped
                self._pending.discard(key)
            self._notify_ready(complete=bool(art.complete))

        def _cancel() -> bool:
            return generation != self._generation

        art = store.build_or_wait(
            path,
            duration_seconds=duration,
            cancel_check=_cancel,
            pause_check=waveform_build_is_paused,
            on_update=_on_update,
        )
        if art is None:
            return None
        return peaks_from_embedded_artifact(clip, art)
