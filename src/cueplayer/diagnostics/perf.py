"""Lightweight performance diagnostics (off by default).

Enable with environment variable ``CUEPLAYER_PERF=1`` or ``set_enabled(True)``.

When enabled, reports are appended to a log file (see ``log_path()``) after each
song activate and when ``flush_report()`` is called. Never touches the audio
RT callback.

Rules
-----
- Never call from the PortAudio / real-time audio callback.
- Spans are UI-thread or worker-thread wall times only.
- Zero overhead when disabled (hot paths check ``is_enabled()`` first).
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def _env_enabled() -> bool:
    raw = str(os.environ.get("CUEPLAYER_PERF", "") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _env_log_path() -> Path | None:
    raw = str(os.environ.get("CUEPLAYER_PERF_LOG", "") or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


_enabled: bool = _env_enabled()
_lock = threading.Lock()
_log_path: Path | None = _env_log_path()
_announced_path = False


@dataclass
class _PerfState:
    spans: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    counters: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    attrs: dict[str, Any] = field(default_factory=dict)
    last_activate_ms: dict[str, float] = field(default_factory=dict)


_state = _PerfState()


def set_enabled(enabled: bool) -> None:
    """Enable or disable diagnostics at runtime (tests / Tools later)."""
    global _enabled
    _enabled = bool(enabled)


def is_enabled() -> bool:
    return bool(_enabled)


def log_path() -> Path:
    """Writable log file for human-readable perf reports."""
    global _log_path
    if _log_path is not None:
        return _log_path
    override = _env_log_path()
    if override is not None:
        _log_path = override
        return _log_path
    # Prefer LocalAppData on Windows; fall back to temp.
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME")
    if base:
        folder = Path(base) / "CuePlayer"
    else:
        folder = Path(tempfile.gettempdir()) / "CuePlayer"
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except Exception:  # noqa: BLE001
        folder = Path(tempfile.gettempdir())
    _log_path = folder / "cueplayer_perf.log"
    return _log_path


def set_log_path(path: Path | str) -> None:
    global _log_path
    _log_path = Path(path)


def clear() -> None:
    with _lock:
        _state.spans.clear()
        _state.counters.clear()
        _state.attrs.clear()
        _state.last_activate_ms.clear()
        # Always bump session id (even when PERF disabled) so UI tick-interval
        # baselines reset and cannot record multi-million-ms fake maxima.
        _state.attrs["perf.session_id"] = (
            f"cleared-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        )
    try:
        from cueplayer.diagnostics import video_sm_trace as sm_trace

        sm_trace.clear()
    except Exception:
        pass


def count(name: str, n: int = 1) -> None:
    if not _enabled:
        return
    with _lock:
        _state.counters[name] += int(n)


def note(key: str, value: Any) -> None:
    if not _enabled:
        return
    with _lock:
        _state.attrs[str(key)] = value


def record_ms(name: str, elapsed_ms: float) -> None:
    if not _enabled:
        return
    with _lock:
        _state.spans[name].append(float(elapsed_ms))


@contextmanager
def span(name: str, **attrs: Any) -> Iterator[None]:
    """Wall-clock span. No-op when diagnostics are disabled."""
    if not _enabled:
        yield
        return
    t0 = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        with _lock:
            _state.spans[name].append(elapsed_ms)
            if attrs:
                for k, v in attrs.items():
                    _state.attrs[f"{name}.{k}"] = v
            if name.startswith("activate."):
                _state.last_activate_ms[name] = elapsed_ms


def snapshot() -> dict[str, Any]:
    """JSON-serializable summary of recorded spans / counters."""
    with _lock:
        span_summary: dict[str, Any] = {}
        for name, samples in sorted(_state.spans.items()):
            if not samples:
                continue
            span_summary[name] = {
                "count": len(samples),
                "last_ms": round(samples[-1], 3),
                "mean_ms": round(sum(samples) / len(samples), 3),
                "max_ms": round(max(samples), 3),
                "total_ms": round(sum(samples), 3),
            }
        return {
            "enabled": _enabled,
            "spans": span_summary,
            "counters": dict(sorted(_state.counters.items())),
            "attrs": dict(_state.attrs),
            "last_activate_ms": dict(_state.last_activate_ms),
            "log_path": str(log_path()) if _enabled else "",
        }


def report_text() -> str:
    snap = snapshot()
    if not snap["enabled"] and not snap["spans"] and not snap["counters"]:
        return "CUEPLAYER_PERF: disabled (set CUEPLAYER_PERF=1 to enable)\n"
    lines = ["CUEPLAYER_PERF report", ""]
    if snap.get("log_path"):
        lines.append(f"log_path: {snap['log_path']}")
        lines.append("")
    # Always surface video pipeline proof first (Task 2 round 2).
    attrs = snap.get("attrs") or {}
    pipeline = attrs.get("video.pipeline_mode", "(unset — not Task2+ build?)")
    lines.append(f"video.pipeline_mode: {pipeline}")
    lines.append(f"video.worker_inflight: {attrs.get('video.worker_inflight', False)}")
    lines.append("")
    expected_video_counters = (
        "video.async_schedule",
        "video.async_coalesce",
        "video.async_stale_drop",
        "video.async_decoded",
        "video.async_invalidate",
        "video.schedule.source.engine",
        "video.schedule.source.scrub",
        "video.update_position.calls",
        "video.emit.calls",
        "video.scrub.raw_position_events",
        "video.scrub.preview_ticks",
        "video.scrub.preview_requests",
        "video.scrub.preview_presented",
        "video.scrub.preview_coalesced",
        "video.scrub.preview_stale_drop",
        "video.scrub.pause_priority_requests",
        "video.scrub.final_land_requests",
        "video.scrub.final_land_presented",
        "video.scrub.final_land_superseded",
        "video.scrub.final_land_cache_hit",
        "video.scrub.final_land_cache_miss",
        "video.scrub.engine_requests_blocked_during_land",
        "video.scrub.engine_requests_dropped_during_land",
        "video.scrub.final_land_overwritten_attempts",
        "video.scrub.final_land_completed",
        "video.scrub.resume_started",
        "video.scrub.resume_completed",
        "video.scrub.engine_requests_blocked_after_land",
        "video.scrub.valid_frames_rejected_after_land",
        "video.scrub.min_present_seconds_cleared",
        "video.scrub.final_land_retry",
        "video.scrub.final_land_deadline_exit",
        "video.scrub.final_land_recoverable_failure",
        "video.scrub.final_land_completed_without_resume",
        "video.scrub.resume_timeout",
        "video.black_present.attempt",
        "video.null_image_rejected",
        "video.zero_size_frame_rejected",
        "video.decoder_reset.worker",
        "video.async_empty_keep_last",
        "video.scrub.resume_required",
        "video.scrub.resume_not_required",
        "video.scrub.resume_recovery_started",
        "video.scrub.resume_recovered",
        "video.scrub.resume_recovery_completed",
        "video.scrub.preview_stale_drop",
        "video.scrub.engine_requests_gated_during_scrub",
        "video.scrub.final_land_completed_playing",
        "video.scrub.final_land_completed_paused",
        "video.scrub.final_land_completed_gap",
        "video.scrub.final_land_completed_out_of_range",
        "video.scrub.preview_superseded_after_decode",
        "video.scrub.preview_generation_mismatch",
        "video.scrub.preview_decoder_reset",
        "video.scrub.preview_reject_reason.generation_mismatch",
        "video.scrub.preview_reject_reason.beyond_tolerance",
        "video.scrub.preview_reject_reason.session_changed",
        "video.scrub.preview_reject_reason.far_cancel",
        # Round 8 — post-land submit + playback lateness (no gen starvation)
        "video.scrub.post_land_submit_attempt",
        "video.scrub.post_land_submit_success",
        "post_land_submit_attempt",
        "post_land_submit_success",
        "video.playback.frame_accept",
        "video.playback.decode_completed",
        "video.playback.decode_presented",
        "video.playback.decode_starved",
        "video.playback.inflight_supersede_count",
        "video.playback.frame_drop.reason.too_late",
        "video.playback.frame_drop.reason.session_changed",
        "video.playback.frame_drop.reason.newer_already_presented",
        "video.playback.frame_drop.reason.generation_mismatch",
        # Round 8b — deterministic seek / handoff / no-black
        "video.seek.deadline_timeout",
        "video.seek.eof_hit",
        "video.seek.decoder_recreated",
        "video.seek.deadline_timeout_unrecovered",
    )
    counters = snap.get("counters") or {}
    lines.append("Video pipeline counters (0 if unused this session):")
    for name in expected_video_counters:
        lines.append(f"  {name}: {int(counters.get(name, 0))}")
    lines.append("")
    # Instrumentation live check — empty Dense Mark dumps are usually session-start
    # / after-activate sections or scrub-only sessions before scrub was hooked.
    lines.append("INSTRUMENTATION LIVE CHECK:")
    lines.append(f"  enabled: {snap.get('enabled')}")
    fanout_calls = int(counters.get("ui.position_fanout.calls", 0))
    scrub_calls = int(counters.get("ui.scrub_fanout.calls", 0))
    lines.append(f"  ui.position_fanout.calls: {fanout_calls}")
    lines.append(f"  ui.scrub_fanout.calls: {scrub_calls}")
    lines.append(
        f"  last tick source: {attrs.get('perf.position_tick_source', '(none)')}"
    )
    lines.append(
        f"  last tick song_time: {attrs.get('perf.position_tick_song_time', '(none)')}"
    )
    tick_mono = attrs.get("perf.position_tick_mono")
    if isinstance(tick_mono, (int, float)):
        ago_ms = max(0.0, (time.monotonic() - float(tick_mono)) * 1000.0)
        lines.append(f"  last tick age_ms: {ago_ms:.1f}")
    else:
        lines.append("  last tick age_ms: (none)")
    if fanout_calls <= 0 and scrub_calls <= 0:
        lines.append(
            "  RESULT: INVALID — no UI position ticks recorded. "
            "Play or scrub for several seconds, then Tools → Write Performance Report. "
            "Ignore session-start / after-activate sections for Dense Mark A/B."
        )
    else:
        lines.append("  RESULT: OK — position path observed")
    lines.append("")
    # Dense Mark / position-fanout A/B (Sprint 8 Task 2).
    lines.append("Dense Mark / position-fanout (A/B):")
    for name in (
        "ui.position_fanout",
        "ui.position_fanout.total_ms",
        "ui.scrub_fanout",
        "ui.scrub_fanout.total_ms",
        "timeline.set_position",
        "mark.lookup_ms",
        "mark.geometry_ms",
        "mark.paint_ms",
        "now_card.position_sync_ms",
        "cue_list.position_sync_ms",
        "overview.position_sync_ms",
        "monitor.position_sync_ms",
        "remote.position_sync_ms",
        "video.schedule_ms",
        "repaint.request_dispatch",
        "video.frame_ready_to_present_ms",
        "video.present.queue_delay_ms",
        "perf.position_tick_interval_ms",
    ):
        if name in (snap.get("spans") or {}):
            st = snap["spans"][name]
            lines.append(
                f"  span {name}: n={st['count']} mean={st['mean_ms']:.2f} max={st['max_ms']:.2f}"
            )
        else:
            lines.append(f"  span {name}: (none)")
    for name in (
        "mark.total_count",
        "mark.visible_count",
        "mark.count_in_current_second",
        "mark.count_near_playhead",
        "mark.crossings_per_position_update",
        "timeline.zoom_pps",
        "ui.position_fanout.slow_song_time",
        "ui.position_fanout.slow_marks_near",
        "ui.position_fanout.slow_video_ready_waiting",
        "ui.position_fanout.slow_worker_runtime",
        "video.seek.frames_to_target",
        "video.seek.keyframe_pts",
        "video.seek.keyframe_distance_s",
        "video.seek.requested_time",
        "video.seek.gop_frames_estimate",
    ):
        lines.append(f"  note {name}: {attrs.get(name, '(unset)')}")
    for name in (
        "ui.position_fanout.calls",
        "ui.scrub_fanout.calls",
        "ui.position_fanout.slow_samples",
        "now_card.position_sync.skipped_unchanged",
        "now_card.position_sync.updated",
        "remote.position_fanout.noop",
        "mark.crossings_total",
    ):
        lines.append(f"  counter {name}: {int(counters.get(name, 0))}")
    lines.append("")
    # Cached timeline / zoom / activation poster (measured fix).
    lines.append("Cached Timeline / Zoom / Activation Poster:")
    for name in (
        "timeline.mark_backdrop.rebuild_ms",
        "timeline.dynamic_overlay.paint_ms",
        "timeline.zoom.temporary_transform_ms",
        "timeline.zoom.overview_ms",
        "video.activation_poster_present_ms",
        "video.empty_widget_visible_ms",
        "video.first_valid_frame_after_song_activate_ms",
        "video.frame_ready_to_present_ms",
        "video.present.queue_delay_ms",
        "video.present_delayed_by_timeline_ms",
    ):
        if name in (snap.get("spans") or {}):
            st = snap["spans"][name]
            lines.append(
                f"  span {name}: n={st['count']} mean={st['mean_ms']:.2f} max={st['max_ms']:.2f}"
            )
        else:
            lines.append(f"  span {name}: (none)")
    for name in (
        "timeline.mark_backdrop.cache_hit",
        "timeline.mark_backdrop.cache_miss",
        "timeline.mark_backdrop.draw_marker_shape_count",
        "timeline.zoom.raw_events",
        "timeline.zoom.coalesced_events",
        "timeline.zoom.final_rebuilds",
        "video.frames_ready_while_ui_busy",
    ):
        lines.append(f"  counter {name}: {int(counters.get(name, 0))}")
    for name in (
        "video.activation_poster.source",
        "video.preview_state",
        "video.land.stage.dominant",
        "video.land.stage.request_id",
        "video.land.stage.song_time",
        "video.land.stage.media_time",
        "timeline.mark_backdrop.last_static_shape_count",
        "timeline.mark_backdrop.last_overlay_shape_count",
        "timeline.zoom.annotation_sprite_count",
    ):
        lines.append(f"  note {name}: {attrs.get(name, '(unset)')}")
    for name in (
        "video.land.stage.queue_wait_ms",
        "video.land.stage.lock_wait_ms",
        "video.land.stage.keyframe_seek_ms",
        "video.land.stage.decode_forward_ms",
        "video.land.stage.convert_ms",
        "video.land.stage.decode_total_ms",
        "cue_list.mark_id_at_row.calls",
        "cue_list.position_sync_ms",
    ):
        if name.endswith("_ms") and name in (snap.get("spans") or {}):
            st = snap["spans"][name]
            lines.append(
                f"  span {name}: n={st['count']} mean={st['mean_ms']:.2f} max={st['max_ms']:.2f}"
            )
        else:
            lines.append(f"  counter {name}: {int(counters.get(name, 0))}")
    lines.append("")
    lines.append(
        f"video.pipeline_state: {attrs.get('video.pipeline_state', '(unset)')}"
    )
    lines.append(
        f"video.scrub.final_land_generation: "
        f"{attrs.get('video.scrub.final_land_generation', '(unset)')}"
    )
    lines.append(
        f"video.scrub.pre_scrub_was_playing: "
        f"{attrs.get('video.scrub.pre_scrub_was_playing', '(unset)')}"
    )
    lines.append(
        f"video.scrub.min_present_seconds_value: "
        f"{attrs.get('video.scrub.min_present_seconds_value', '(unset)')}"
    )
    lines.append(
        f"video.scrub.final_land_first_relevant_source: "
        f"{attrs.get('video.scrub.final_land_first_relevant_source', '(unset)')}"
    )
    lines.append("")
    # Round 7 — Video state-machine trace (land → resume freeze diagnosis).
    try:
        from cueplayer.diagnostics import video_sm_trace as sm_trace

        lines.append(sm_trace.report_text(limit=100).rstrip())
        lines.append("")
    except Exception:
        lines.append("VIDEO_SM: (unavailable)")
        lines.append("")
    expected_video_spans = (
        "video.decode.async",
        "video.decode.sync",
        "video.convert",
        "video.present",
        "ui.position_fanout",
    )
    spans = snap.get("spans") or {}
    lines.append("Video/UI spans present:")
    for name in expected_video_spans:
        if name in spans:
            st = spans[name]
            lines.append(
                f"  {name}: n={st['count']} mean={st['mean_ms']:.2f} max={st['max_ms']:.2f}"
            )
        else:
            lines.append(f"  {name}: (none this session)")
    lines.append("")
    if snap["last_activate_ms"]:
        lines.append("Last activate spans (ms):")
        for k, v in sorted(snap["last_activate_ms"].items()):
            lines.append(f"  {k}: {v:.2f}")
        lines.append("")
    if snap["spans"]:
        lines.append("Span summary:")
        for name, stats in snap["spans"].items():
            lines.append(
                f"  {name}: n={stats['count']} last={stats['last_ms']:.2f} "
                f"mean={stats['mean_ms']:.2f} max={stats['max_ms']:.2f}"
            )
        lines.append("")
    if snap["counters"]:
        lines.append("Counters:")
        for name, value in snap["counters"].items():
            lines.append(f"  {name}: {value}")
        lines.append("")
    if snap["attrs"]:
        lines.append("Attrs:")
        for k, v in sorted(snap["attrs"].items()):
            lines.append(f"  {k}: {v}")
        lines.append("")
    return "\n".join(lines)


def flush_report(*, label: str = "", clear_after: bool = False) -> Path | None:
    """Append ``report_text()`` to the perf log. Returns log path when written."""
    if not _enabled:
        return None
    path = log_path()
    stamp = datetime.now(timezone.utc).isoformat()
    header = f"===== {stamp} {label} =====\n" if label else f"===== {stamp} =====\n"
    body = report_text()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(header)
            fh.write(body)
            if not body.endswith("\n"):
                fh.write("\n")
            fh.write("\n")
    except Exception:  # noqa: BLE001
        return None
    # Also echo a short pointer to the console when launched from a terminal.
    global _announced_path
    try:
        if not _announced_path:
            print(f"CUEPLAYER_PERF log: {path}", flush=True)
            _announced_path = True
        if label:
            print(f"CUEPLAYER_PERF flushed ({label}) → {path}", flush=True)
    except Exception:  # noqa: BLE001
        pass
    if clear_after:
        # Keep last_activate attrs; clear growing span/counter histories.
        with _lock:
            _state.spans.clear()
            _state.counters.clear()
    try:
        from cueplayer.diagnostics import video_sm_trace as sm_trace

        sm_trace.flush_log(force=True)
    except Exception:
        pass
    return path


def announce_if_enabled() -> str:
    """Startup banner; returns log path string when enabled, else empty."""
    if not _enabled:
        return ""
    path = log_path()
    # New app process → new session section; clear prior in-memory spans so a
    # manual dump cannot mix yesterday's Task1 numbers with this run.
    clear()
    session_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    note("perf.session_id", session_id)
    note("video.pipeline_mode", "async_latest_wins")
    msg = f"CUEPLAYER_PERF=1 — session={session_id} — writing reports to {path}"
    try:
        print(msg, flush=True)
    except Exception:  # noqa: BLE001
        try:
            buf = getattr(sys.stdout, "buffer", None)
            if buf is not None:
                buf.write((msg + "\n").encode("utf-8", errors="replace"))
                buf.flush()
        except Exception:  # noqa: BLE001
            pass
    flush_report(label=f"session-start:{session_id}")
    return str(path)
