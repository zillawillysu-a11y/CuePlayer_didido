"""Video Track lane peaks — views over the shared VideoWaveformArtifact."""

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
from cueplayer.media.audio_loader import PeakLevel, choose_peak_level
from cueplayer.media.video_limits import clip_source_duration_seconds
from cueplayer.media.video_waveform_artifact import (
    VideoWaveformArtifact,
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
    """Zoom-aware waveform data sourced from VideoWaveformArtifact."""

    sample_rate: int
    mono_origin_seconds: float
    mono: np.ndarray  # signed overview; NaN = pending
    peak_levels: list[PeakLevel]
    mins: np.ndarray  # source-aligned bipolar base
    maxs: np.ndarray
    coverage: np.ndarray | None = None


def timeline_to_clip_local(timeline_t: float, clip: VideoClip) -> float | None:
    if timeline_t < clip.start_seconds or timeline_t > clip.end_seconds:
        return None
    return timeline_t - clip.start_seconds


def clip_local_to_source_time(clip: VideoClip, clip_local_t: float) -> float:
    src_in = max(0.0, float(clip.source_in_seconds))
    if clip.media_kind == "still":
        return src_in
    span = max(0.0, clip.source_span_seconds)
    if span <= 1e-9:
        return src_in
    return src_in + (clip_local_t % span)


def peaks_from_artifact(
    clip: VideoClip, art: VideoWaveformArtifact
) -> ClipWaveformPeaks | None:
    """Map shared source artifact into clip paint peaks (trim/loop via sampling)."""
    if perf_diag.is_enabled():
        perf_diag.count("waveform_artifact.consumer_video_lane")
    if art.n_bins <= 0:
        return None
    sr = max(1, int(round(float(art.peaks_per_second))))
    mono = signed_overview_from_artifact(art)
    cov = np.asarray(art.coverage, dtype=np.uint8)
    mins = np.asarray(art.mins, dtype=np.float32).copy()
    maxs = np.asarray(art.maxs, dtype=np.float32).copy()
    pending = cov == 0
    mins[pending] = np.nan
    maxs[pending] = np.nan
    levels = list(art.levels) if art.levels else []
    if not levels:
        # Derive on the fly if disk lacked levels.
        art.rebuild_pyramid()
        levels = list(art.levels)
    return ClipWaveformPeaks(
        sample_rate=sr,
        mono_origin_seconds=float(art.origin_seconds),
        mono=mono,
        peak_levels=levels,
        mins=mins,
        maxs=maxs,
        coverage=cov,
    )


# Alias used by tests / older call sites.
peaks_from_embedded_artifact = peaks_from_artifact


def sample_clip_peaks_for_times(
    peaks: ClipWaveformPeaks,
    *,
    duration: float,
    clip_t0: float,
    clip_t1: float,
) -> tuple[float, float]:
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
    return float(np.nanmin(segment_lo)), float(np.nanmax(segment_hi))


def sample_source_peaks_for_clip_times(
    peaks: ClipWaveformPeaks,
    clip: VideoClip,
    *,
    clip_t0: float,
    clip_t1: float,
    samples_per_pixel: float,
) -> tuple[float, float]:
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
    # Prefer source-aligned bipolar envelope when present.
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
    return sample_source_peaks_for_clip_times(
        peaks,
        clip,
        clip_t0=clip_t0,
        clip_t1=clip_t1,
        samples_per_pixel=1.0,
    )


class VideoClipWaveformCache:
    """Per-clip view cache over the shared VideoWaveformArtifactStore."""

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
        # Keep shared artifact RAM/disk for warm hydrate across song switches.

    def _artifact_duration_for(self, clip: VideoClip) -> float:
        return max(
            clip_source_duration_seconds(clip),
            float(clip.source_span_seconds or clip.duration_seconds or 0.0),
            0.05,
        )

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

    def _try_hydrate(self, key: ClipWaveformKey, clip: VideoClip) -> ClipWaveformPeaks | None:
        duration = self._artifact_duration_for(clip)
        art = artifact_store().get_or_load_disk(
            Path(clip.path), duration_seconds=duration
        )
        if art is None or art.coverage_ratio <= 0:
            return None
        mapped = peaks_from_artifact(clip, art)
        if mapped is None:
            return None
        with self._lock:
            self._peaks[key] = mapped
            self._pending.discard(key)
        if perf_diag.is_enabled():
            perf_diag.count("waveform_artifact.sync_hydrate")
        return mapped

    def get_peaks(self, clip: VideoClip, *, allow_submit: bool = True) -> ClipWaveformPeaks | None:
        if clip.media_kind == "still":
            return None
        key = self.key_for(clip)
        with self._lock:
            if key in self._peaks:
                return self._peaks[key]
            if key in self._pending:
                return None
        hydrated = self._try_hydrate(key, clip)
        if hydrated is not None and (
            hydrated.coverage is None
            or np.all(hydrated.coverage != 0)
            or not allow_submit
        ):
            # Complete (or partial when submit disallowed) — return now.
            if hydrated.coverage is None or np.count_nonzero(hydrated.coverage) > 0:
                # Still ensure building if incomplete.
                if allow_submit and hydrated.coverage is not None and not np.all(
                    hydrated.coverage != 0
                ):
                    self._submit_build(key, clip)
                return hydrated
        if hydrated is not None:
            # Partial available — paint it and keep building.
            if allow_submit:
                self._submit_build(key, clip)
            return hydrated
        if not allow_submit:
            return None
        self._submit_build(key, clip)
        return None

    def _submit_build(self, key: ClipWaveformKey, clip: VideoClip) -> None:
        with self._lock:
            if key in self._pending:
                return
            self._pending.add(key)
            generation = self._generation
        self._executor.submit(self._build_async, generation, key, clip)

    def peaks_for_paint(
        self, clip: VideoClip, *, allow_submit: bool = True
    ) -> ClipWaveformPeaks | None:
        return self.get_peaks(clip, allow_submit=allow_submit)

    def preload(self, clips: list[VideoClip]) -> None:
        for clip in clips:
            if clip.media_kind == "still":
                continue
            self.get_peaks(clip)

    def flush_pending_gui_notify(self) -> None:
        self._notify_ready(force=True)

    def _notify_ready(self, *, force: bool = False, complete: bool = False) -> None:
        import time as _time

        now = _time.monotonic()
        if not force and not complete:
            if waveform_build_is_paused():
                if perf_diag.is_enabled():
                    perf_diag.count(
                        "waveform_artifact.gui_notify_suppressed_playing"
                    )
                return
            if self._gui_first_notified and (
                now - self._last_gui_notify_mono < self._gui_coalesce_s
            ):
                if perf_diag.is_enabled():
                    perf_diag.count("waveform_artifact.gui_notify_coalesced")
                return
        self._last_gui_notify_mono = now
        self._gui_first_notified = True
        if perf_diag.is_enabled():
            perf_diag.count("waveform_artifact.gui_notify")
            if complete:
                perf_diag.count("waveform_artifact.backdrop_rebuild_after_ready")
        cb = self._on_ready
        if cb is not None:
            cb()

    def _build_async(self, generation: int, key: ClipWaveformKey, clip: VideoClip) -> None:
        duration = self._artifact_duration_for(clip)
        path = Path(clip.path)

        def _on_update(art: VideoWaveformArtifact) -> None:
            with self._lock:
                if generation != self._generation:
                    return
                mapped = peaks_from_artifact(clip, art)
                if mapped is None:
                    return
                self._peaks[key] = mapped
                self._pending.discard(key)
            self._notify_ready(complete=bool(art.complete))

        def _cancel() -> bool:
            return generation != self._generation

        # Non-blocking ensure — worker may wait for completion.
        store = artifact_store()
        store.ensure_building(
            path,
            duration_seconds=duration,
            cancel_check=_cancel,
            pause_check=waveform_build_is_paused,
            on_update=_on_update,
        )
        art = store.wait_in_worker(
            path,
            duration_seconds=duration,
            cancel_check=_cancel,
            pause_check=waveform_build_is_paused,
            on_update=_on_update,
        )
        with self._lock:
            if generation != self._generation:
                return
            if art is not None:
                mapped = peaks_from_artifact(clip, art)
                if mapped is not None:
                    self._peaks[key] = mapped
            self._pending.discard(key)
        if art is not None:
            self._notify_ready(force=True, complete=bool(art.complete))
