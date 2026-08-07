"""Shared continuous low-resolution embedded-audio waveform for long videos.

One artifact per media file feeds both:
- Music-lane stand-in (video-only songs)
- Video Track clip-lane waveform

Design goals (Sprint 8 follow-up):
- Continuous source-time scan — no sparse 12 s probes / false silence islands
- Bounded min/max envelopes (never full-rate duration×48000 float PCM)
- Chunked decode that releases ``av_path_lock`` between windows
- Disk cache keyed by path + mtime/size + stream + format version
  (duration probe drift must not invalidate; sync hydrate on reload)
- Progressive coverage (pending ≠ zero silence)
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from cueplayer.diagnostics import perf as perf_diag
from cueplayer.media.video_audio_loader import load_video_audio

# Artifact schema — bump when on-disk layout changes.
ARTIFACT_FORMAT_VERSION = 4
# Overview density for heavy / multi-hour sources (song-length uses full PCM).
# 15 min → 180k bins ≈ 1.6 MB. Zoom-out paint uses adaptive step to stay smooth.
PEAKS_PER_SECOND = 200.0
# Hard cap (~2.7 h at 200 Hz; longer files thin the effective rate).
MAX_PEAK_BINS = 2_000_000
# Contiguous decode window; lock held only for this slice then released.
CHUNK_SECONDS = 8.0
# Yield so Preview / VideoAudioMixer can use av_path_lock. Keep short when
# idle — long yields made first-build feel "very very slow".
CHUNK_YIELD_SECONDS = 0.02
# While playback is active, yield longer between chunks (or pause entirely).
CHUNK_YIELD_WHILE_PLAYING_SECONDS = 0.25
# GUI progressive publishes are coalesced to this cadence (final is immediate).
PROGRESS_GUI_COALESCE_SECONDS = 1.5
# First-audio-stream index (CuePlayer always uses stream 0 today).
DEFAULT_AUDIO_STREAM_INDEX = 0

_CACHE_DIR = Path(
    os.environ.get(
        "CUEPLAYER_VIDEO_WAVE_CACHE",
        Path.home() / ".cache" / "cueplayer" / "video_waveforms",
    )
)

# When True, continuous artifact builds pause between chunks so Preview wins.
_playback_paused_builds = False
_playback_pause_lock = threading.Lock()


def set_waveform_build_paused(paused: bool) -> None:
    """Pause/resume long-video waveform extraction around Play/Stop."""
    global _playback_paused_builds
    with _playback_pause_lock:
        _playback_paused_builds = bool(paused)
    if perf_diag.is_enabled():
        perf_diag.note(
            "video_waveform.artifact.paused_for_playback", int(bool(paused))
        )


def waveform_build_is_paused() -> bool:
    with _playback_pause_lock:
        return bool(_playback_paused_builds)


@dataclass
class EmbeddedWaveformArtifact:
    """Source-time min/max envelope with explicit coverage mask."""

    path: str
    mtime_ns: int
    size: int
    stream_index: int
    format_version: int
    peaks_per_second: float
    origin_seconds: float
    duration_seconds: float
    mins: np.ndarray  # float32
    maxs: np.ndarray  # float32
    coverage: np.ndarray  # uint8, 1 = decoded
    complete: bool = False

    @property
    def n_bins(self) -> int:
        return int(self.mins.size)

    @property
    def decoded_duration_s(self) -> float:
        if self.n_bins <= 0 or self.peaks_per_second <= 0:
            return 0.0
        covered = int(np.count_nonzero(self.coverage))
        return float(covered) / float(self.peaks_per_second)

    @property
    def coverage_ratio(self) -> float:
        if self.n_bins <= 0:
            return 0.0
        return float(np.count_nonzero(self.coverage)) / float(self.n_bins)

    @property
    def memory_bytes(self) -> int:
        return int(
            self.mins.nbytes + self.maxs.nbytes + self.coverage.nbytes
        )

    def first_uncovered_source_time(self) -> float:
        """Resume point for incremental builds (source seconds)."""
        if self.n_bins <= 0:
            return float(self.origin_seconds)
        uncovered = np.flatnonzero(self.coverage == 0)
        if uncovered.size == 0:
            return float(self.origin_seconds + self.duration_seconds)
        return float(self.origin_seconds) + float(uncovered[0]) / float(
            self.peaks_per_second
        )


def artifact_bin_count(duration_seconds: float) -> int:
    dur = max(0.05, float(duration_seconds))
    n = int(np.ceil(dur * PEAKS_PER_SECOND))
    return max(1, min(MAX_PEAK_BINS, n))


def artifact_peaks_per_second_for_duration(duration_seconds: float) -> float:
    """Effective rate after MAX_PEAK_BINS clamp."""
    dur = max(0.05, float(duration_seconds))
    n = artifact_bin_count(dur)
    return float(n) / dur


def _stat_key(path: Path) -> tuple[str, int, int] | None:
    try:
        resolved = path.resolve()
        st = resolved.stat()
        return str(resolved), int(st.st_mtime_ns), int(st.st_size)
    except OSError:
        return None


def artifact_cache_key(
    path: Path,
    *,
    stream_index: int = DEFAULT_AUDIO_STREAM_INDEX,
    duration_seconds: float = 0.0,
) -> str | None:
    """Stable per-file key (mtime/size/format/pps).

    Duration is intentionally *not* part of the key: source-duration probe
    drift after save/reload must not invalidate a complete disk artifact.
    ``duration_seconds`` is kept for call-site compatibility only.
    """
    del duration_seconds
    meta = _stat_key(path)
    if meta is None:
        return None
    resolved, mtime_ns, size = meta
    raw = (
        f"{resolved}\0{mtime_ns}\0{size}\0{stream_index}\0"
        f"{ARTIFACT_FORMAT_VERSION}\0{PEAKS_PER_SECOND:.6f}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def _disk_path(cache_key: str) -> Path:
    return _CACHE_DIR / f"vwave_{cache_key}.npz"


def empty_artifact(
    path: Path,
    *,
    duration_seconds: float,
    stream_index: int = DEFAULT_AUDIO_STREAM_INDEX,
) -> EmbeddedWaveformArtifact | None:
    meta = _stat_key(path)
    if meta is None:
        return None
    resolved, mtime_ns, size = meta
    n = artifact_bin_count(duration_seconds)
    pps = float(n) / max(0.05, float(duration_seconds))
    return EmbeddedWaveformArtifact(
        path=resolved,
        mtime_ns=mtime_ns,
        size=size,
        stream_index=int(stream_index),
        format_version=ARTIFACT_FORMAT_VERSION,
        peaks_per_second=pps,
        origin_seconds=0.0,
        duration_seconds=max(0.05, float(duration_seconds)),
        mins=np.zeros(n, dtype=np.float32),
        maxs=np.zeros(n, dtype=np.float32),
        coverage=np.zeros(n, dtype=np.uint8),
        complete=False,
    )


def load_artifact_from_disk(cache_key: str) -> EmbeddedWaveformArtifact | None:
    path = _disk_path(cache_key)
    if not path.is_file():
        return None
    try:
        with np.load(path, allow_pickle=False) as data:
            if int(data["format_version"]) != ARTIFACT_FORMAT_VERSION:
                return None
            art = EmbeddedWaveformArtifact(
                path=str(data["path"]),
                mtime_ns=int(data["mtime_ns"]),
                size=int(data["size"]),
                stream_index=int(data["stream_index"]),
                format_version=int(data["format_version"]),
                peaks_per_second=float(data["peaks_per_second"]),
                origin_seconds=float(data["origin_seconds"]),
                duration_seconds=float(data["duration_seconds"]),
                mins=np.asarray(data["mins"], dtype=np.float32),
                maxs=np.asarray(data["maxs"], dtype=np.float32),
                coverage=np.asarray(data["coverage"], dtype=np.uint8),
                complete=bool(int(data["complete"])),
            )
        if not art.complete or art.n_bins <= 0:
            return None
        return art
    except Exception:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return None


def save_artifact_to_disk(cache_key: str, art: EmbeddedWaveformArtifact) -> None:
    if not art.complete:
        return
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        out = _disk_path(cache_key)
        tmp = out.with_name(out.stem + ".tmp")
        np.savez(
            str(tmp),
            path=np.asarray(art.path),
            mtime_ns=np.int64(art.mtime_ns),
            size=np.int64(art.size),
            stream_index=np.int32(art.stream_index),
            format_version=np.int32(art.format_version),
            peaks_per_second=np.float64(art.peaks_per_second),
            origin_seconds=np.float64(art.origin_seconds),
            duration_seconds=np.float64(art.duration_seconds),
            mins=art.mins.astype(np.float32, copy=False),
            maxs=art.maxs.astype(np.float32, copy=False),
            coverage=art.coverage.astype(np.uint8, copy=False),
            complete=np.int8(1 if art.complete else 0),
        )
        Path(str(tmp) + ".npz").replace(out)
    except Exception:
        pass


def _fill_chunk_peaks(
    art: EmbeddedWaveformArtifact,
    *,
    pcm: np.ndarray,
    pcm_rate: int,
    pcm_origin: float,
) -> int:
    """Aggregate a PCM window into artifact bins. Returns bins newly covered."""
    if pcm.size == 0 or pcm_rate <= 0 or art.n_bins <= 0:
        return 0
    if pcm.ndim == 2:
        mono = pcm.mean(axis=1).astype(np.float32, copy=False)
    else:
        mono = np.asarray(pcm, dtype=np.float32)
    if mono.size == 0:
        return 0

    pps = float(art.peaks_per_second)
    origin = float(art.origin_seconds)
    src_t0 = float(pcm_origin)
    # Map each PCM sample to a bin index, then reduce with peak-hold.
    idx = np.floor((src_t0 - origin + np.arange(mono.size, dtype=np.float64) / float(pcm_rate)) * pps).astype(
        np.int64
    )
    valid = (idx >= 0) & (idx < art.n_bins)
    if not np.any(valid):
        return 0
    idx = idx[valid]
    vals = mono[valid]
    # First-touch mins/maxs for newly covered bins via scatter.
    # Use nan-init workspace then merge into art.
    n = art.n_bins
    lo_acc = np.full(n, np.inf, dtype=np.float32)
    hi_acc = np.full(n, -np.inf, dtype=np.float32)
    np.minimum.at(lo_acc, idx, vals)
    np.maximum.at(hi_acc, idx, vals)
    touched = np.isfinite(lo_acc) & np.isfinite(hi_acc)
    if not np.any(touched):
        return 0
    newly = 0
    fresh = touched & (art.coverage == 0)
    if np.any(fresh):
        art.mins[fresh] = lo_acc[fresh]
        art.maxs[fresh] = hi_acc[fresh]
        art.coverage[fresh] = 1
        newly = int(np.count_nonzero(fresh))
    update = touched & (art.coverage != 0) & (~fresh)
    if np.any(update):
        art.mins[update] = np.minimum(art.mins[update], lo_acc[update])
        art.maxs[update] = np.maximum(art.maxs[update], hi_acc[update])
    return newly


def build_artifact_continuous(
    path: Path,
    *,
    duration_seconds: float,
    stream_index: int = DEFAULT_AUDIO_STREAM_INDEX,
    cancel_check: Callable[[], bool] | None = None,
    on_progress: Callable[[EmbeddedWaveformArtifact], None] | None = None,
    existing: EmbeddedWaveformArtifact | None = None,
    pause_check: Callable[[], bool] | None = None,
) -> EmbeddedWaveformArtifact | None:
    """Sequentially scan embedded audio into a bounded peak artifact.

    Holds ``av_path_lock`` only inside each ``load_video_audio`` chunk.
    """
    path = Path(path)
    art = existing
    if art is None:
        art = empty_artifact(
            path, duration_seconds=duration_seconds, stream_index=stream_index
        )
    if art is None:
        return None

    def _cancelled() -> bool:
        return bool(cancel_check and cancel_check())

    def _paused() -> bool:
        return bool(pause_check and pause_check())

    t0_wall = time.perf_counter()
    first_ready_ms: float | None = None
    worker_active_ms = 0.0
    av_window_ms_total = 0.0
    if perf_diag.is_enabled():
        perf_diag.count("video_waveform.artifact.build_started")
        perf_diag.note(
            "video_waveform.artifact.source_duration_s", float(art.duration_seconds)
        )

    from cueplayer.util.thread_priority import lower_background_thread_priority

    lower_background_thread_priority()

    end = float(art.origin_seconds) + float(art.duration_seconds)
    t = art.first_uncovered_source_time()
    # Contiguous advance — never jump by 12 s leaving zero gaps.
    while t < end - 1e-6:
        if _cancelled():
            if perf_diag.is_enabled():
                perf_diag.count("video_waveform.artifact.cancelled")
                perf_diag.note(
                    "video_waveform.artifact.worker_active_ms", worker_active_ms
                )
            return art
        while _paused() or waveform_build_is_paused():
            if _cancelled():
                if perf_diag.is_enabled():
                    perf_diag.count("video_waveform.artifact.cancelled")
                return art
            time.sleep(0.05)

        window = min(CHUNK_SECONDS, end - t)
        chunk_t0 = time.perf_counter()
        chunk = load_video_audio(
            path, start_seconds=t, max_duration_seconds=window
        )
        av_ms = (time.perf_counter() - chunk_t0) * 1000.0
        av_window_ms_total += av_ms
        worker_active_ms += av_ms
        if perf_diag.is_enabled():
            perf_diag.record_ms("video_waveform.artifact.av_window_ms", av_ms)
            perf_diag.count("video_waveform.artifact.chunks")

        if chunk is None or chunk.frames <= 0:
            # No audio in this window — mark bins as covered-empty (true silence)
            # so we do not leave "pending" forever on silent regions, and advance.
            _mark_silence_covered(art, t, window)
            t += window
            time.sleep(
                CHUNK_YIELD_WHILE_PLAYING_SECONDS
                if waveform_build_is_paused()
                else CHUNK_YIELD_SECONDS
            )
            continue

        fill_t0 = time.perf_counter()
        _fill_chunk_peaks(
            art,
            pcm=chunk.samples,
            pcm_rate=chunk.sample_rate,
            pcm_origin=float(chunk.origin_seconds),
        )
        worker_active_ms += (time.perf_counter() - fill_t0) * 1000.0
        decoded_span = chunk.frames / float(chunk.sample_rate)
        t = float(chunk.origin_seconds) + decoded_span
        if t <= float(chunk.origin_seconds) + 1e-3:
            t = float(chunk.origin_seconds) + window

        if first_ready_ms is None and art.coverage_ratio > 0:
            first_ready_ms = (time.perf_counter() - t0_wall) * 1000.0
            if perf_diag.is_enabled():
                perf_diag.note(
                    "video_waveform.artifact.first_peaks_ready_ms", first_ready_ms
                )

        if on_progress is not None:
            on_progress(art)

        if perf_diag.is_enabled():
            perf_diag.note(
                "video_waveform.artifact.decoded_duration_s", art.decoded_duration_s
            )
            perf_diag.note(
                "video_waveform.artifact.coverage_ratio", art.coverage_ratio
            )

        time.sleep(
            CHUNK_YIELD_WHILE_PLAYING_SECONDS
            if waveform_build_is_paused()
            else CHUNK_YIELD_SECONDS
        )

    # Ensure full coverage flag (silence-marked bins already covered).
    if np.all(art.coverage != 0) or art.coverage_ratio >= 0.999:
        art.coverage[:] = 1
        art.complete = True
    else:
        # Trailing unreachable — mark remaining as covered silence so paint
        # does not treat them as pending forever.
        art.coverage[art.coverage == 0] = 1
        art.complete = True

    if perf_diag.is_enabled():
        perf_diag.count("video_waveform.artifact.build_completed")
        perf_diag.note(
            "video_waveform.artifact.total_build_ms",
            (time.perf_counter() - t0_wall) * 1000.0,
        )
        perf_diag.note(
            "video_waveform.artifact.worker_active_ms", worker_active_ms
        )
        perf_diag.note(
            "video_waveform.artifact.av_window_ms_total", av_window_ms_total
        )
        perf_diag.note("video_waveform.artifact.peak_bins", art.n_bins)
        perf_diag.note("video_waveform.artifact.memory_bytes", art.memory_bytes)
        perf_diag.note(
            "video_waveform.artifact.coverage_ratio", art.coverage_ratio
        )
        perf_diag.note(
            "video_waveform.artifact.decoded_duration_s", art.decoded_duration_s
        )

    return art


def _mark_silence_covered(
    art: EmbeddedWaveformArtifact, start: float, duration: float
) -> None:
    pps = float(art.peaks_per_second)
    origin = float(art.origin_seconds)
    b0 = max(0, int(np.floor((start - origin) * pps)))
    b1 = min(art.n_bins, int(np.ceil((start + duration - origin) * pps)))
    if b0 >= b1:
        return
    # True silence: extrema stay 0, but coverage=1 so paint knows it is decoded.
    art.coverage[b0:b1] = 1


def signed_overview_from_artifact(art: EmbeddedWaveformArtifact) -> np.ndarray:
    """Peak-hold signed mono for Music-lane AudioBuffer (NaN = pending)."""
    out = np.full(art.n_bins, np.nan, dtype=np.float32)
    cov = art.coverage.astype(bool)
    if not np.any(cov):
        return out
    # Stronger extremum keeps sign (same idea as standin downsample).
    lo = art.mins
    hi = art.maxs
    pick_hi = np.abs(hi) >= np.abs(lo)
    chosen = np.where(pick_hi, hi, lo).astype(np.float32)
    out[cov] = chosen[cov]
    return out


def artifact_has_false_zero_gaps(art: EmbeddedWaveformArtifact) -> bool:
    """True if covered bins are interrupted by uncovered holes (sparse-probe smell)."""
    cov = art.coverage.astype(bool)
    if not np.any(cov):
        return False
    # Pending suffix after contiguous prefix is OK for progressive builds.
    first_uncovered = int(np.argmax(~cov)) if not np.all(cov) else art.n_bins
    if first_uncovered == 0 and not cov[0]:
        # Leading pending — also OK before first chunk.
        return False
    # Any uncovered after a covered bin before the progressive frontier?
    # Progressive frontier = last covered + 1 in a contiguous prefix from 0.
    prefix = 0
    while prefix < art.n_bins and cov[prefix]:
        prefix += 1
    if prefix >= art.n_bins:
        return False
    # Holes inside the prefix region should not exist; anything after prefix
    # pending is fine. If any covered appears after an uncovered hole:
    if np.any(cov[prefix:]):
        return True
    return False


@dataclass
class _JobState:
    cache_key: str
    art: EmbeddedWaveformArtifact
    future: Future | None = None
    generation: int = 0
    listeners: list[Callable[[EmbeddedWaveformArtifact], None]] = field(
        default_factory=list
    )


class EmbeddedWaveformArtifactStore:
    """Process-wide in-memory + disk store; one build per media key."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_key: dict[str, EmbeddedWaveformArtifact] = {}
        self._jobs: dict[str, _JobState] = {}
        self._generation = 0
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="vid-wave-art"
        )
        self._progress_coalesce_s = PROGRESS_GUI_COALESCE_SECONDS
        self._last_progress_emit: dict[str, float] = {}

    def clear(self) -> None:
        with self._lock:
            self._generation += 1
            self._by_key.clear()
            self._jobs.clear()
            self._last_progress_emit.clear()

    def peek(self, cache_key: str | None) -> EmbeddedWaveformArtifact | None:
        if not cache_key:
            return None
        with self._lock:
            return self._by_key.get(cache_key)

    def get_or_load_disk(
        self,
        path: Path,
        *,
        duration_seconds: float,
        stream_index: int = DEFAULT_AUDIO_STREAM_INDEX,
    ) -> EmbeddedWaveformArtifact | None:
        key = artifact_cache_key(
            path, stream_index=stream_index, duration_seconds=duration_seconds
        )
        if key is None:
            return None
        need = float(duration_seconds)

        def _usable(art: EmbeddedWaveformArtifact | None) -> EmbeddedWaveformArtifact | None:
            if art is None or not art.complete:
                return None
            if float(art.duration_seconds) + 0.5 < need:
                return None
            return art

        with self._lock:
            hit = _usable(self._by_key.get(key))
            if hit is not None:
                if perf_diag.is_enabled():
                    perf_diag.count("video_waveform.artifact.cache_hit")
                return hit
        disk = _usable(load_artifact_from_disk(key))
        if disk is not None:
            with self._lock:
                self._by_key[key] = disk
            if perf_diag.is_enabled():
                perf_diag.count("video_waveform.artifact.cache_hit")
            return disk
        if perf_diag.is_enabled():
            perf_diag.count("video_waveform.artifact.cache_miss")
        return None

    def build_or_wait(
        self,
        path: Path,
        *,
        duration_seconds: float,
        stream_index: int = DEFAULT_AUDIO_STREAM_INDEX,
        cancel_check: Callable[[], bool] | None = None,
        pause_check: Callable[[], bool] | None = None,
        on_update: Callable[[EmbeddedWaveformArtifact], None] | None = None,
    ) -> EmbeddedWaveformArtifact | None:
        """Synchronously obtain a complete/partial artifact (single-flight).

        Safe to call from Music stand-in or VideoClipWaveformCache workers —
        only one continuous decode runs per media key.
        """
        key = artifact_cache_key(
            path, stream_index=stream_index, duration_seconds=duration_seconds
        )
        if key is None:
            return None
        existing = self.get_or_load_disk(
            path, duration_seconds=duration_seconds, stream_index=stream_index
        )
        if (
            existing is not None
            and existing.complete
            and float(existing.duration_seconds) + 0.5 >= float(duration_seconds)
        ):
            if on_update is not None:
                on_update(existing)
            return existing

        wait_future: Future | None = None
        with self._lock:
            gen = self._generation
            job = self._jobs.get(key)
            if job is not None and job.future is not None and not job.future.done():
                if on_update is not None:
                    job.listeners.append(on_update)
                wait_future = job.future
                art_ref = job.art
            else:
                art_ref = existing or empty_artifact(
                    path,
                    duration_seconds=duration_seconds,
                    stream_index=stream_index,
                )
                if art_ref is None:
                    return None
                self._by_key[key] = art_ref
                listeners = [on_update] if on_update is not None else []
                job = _JobState(
                    cache_key=key,
                    art=art_ref,
                    generation=gen,
                    listeners=list(listeners),
                )
                self._jobs[key] = job

                def _run() -> EmbeddedWaveformArtifact | None:
                    def _progress(a: EmbeddedWaveformArtifact) -> None:
                        now = time.monotonic()
                        with self._lock:
                            if gen != self._generation:
                                return
                            self._by_key[key] = a
                            last = self._last_progress_emit.get(key, 0.0)
                            # Always publish completion; coalesce partials.
                            if (
                                not a.complete
                                and now - last < self._progress_coalesce_s
                                and last > 0.0
                            ):
                                return
                            # First partial: allow immediately (last==0).
                            self._last_progress_emit[key] = now
                            cbs = list(job.listeners)
                        if perf_diag.is_enabled():
                            perf_diag.count(
                                "video_waveform.artifact.progressive_publish"
                            )
                            if a.complete:
                                perf_diag.count(
                                    "video_waveform.artifact.final_publish"
                                )
                        for cb in cbs:
                            try:
                                cb(a)
                            except Exception:
                                pass

                    def _cancel() -> bool:
                        if gen != self._generation:
                            return True
                        return bool(cancel_check and cancel_check())

                    result = build_artifact_continuous(
                        path,
                        duration_seconds=duration_seconds,
                        stream_index=stream_index,
                        cancel_check=_cancel,
                        pause_check=pause_check,
                        on_progress=_progress,
                        existing=art_ref,
                    )
                    if result is None:
                        return None
                    with self._lock:
                        if gen != self._generation:
                            return result
                        self._by_key[key] = result
                        if result.complete:
                            save_artifact_to_disk(key, result)
                        cbs = list(job.listeners)
                        self._jobs.pop(key, None)
                    for cb in cbs:
                        try:
                            cb(result)
                        except Exception:
                            pass
                    return result

                wait_future = self._executor.submit(_run)
                job.future = wait_future

        assert wait_future is not None
        try:
            return wait_future.result(timeout=3600.0)
        except Exception:
            with self._lock:
                return self._by_key.get(key)


# Module singleton — Music standin + VideoClipWaveformCache share one builder.
_STORE = EmbeddedWaveformArtifactStore()


def artifact_store() -> EmbeddedWaveformArtifactStore:
    return _STORE


def publish_artifact(
    path: Path,
    art: EmbeddedWaveformArtifact,
    *,
    duration_seconds: float,
    stream_index: int = DEFAULT_AUDIO_STREAM_INDEX,
) -> None:
    """Publish a completed/partial artifact built on a consumer thread."""
    key = artifact_cache_key(
        path, stream_index=stream_index, duration_seconds=duration_seconds
    )
    if key is None:
        return
    store = _STORE
    with store._lock:  # noqa: SLF001
        store._by_key[key] = art  # noqa: SLF001
    if art.complete:
        save_artifact_to_disk(key, art)
