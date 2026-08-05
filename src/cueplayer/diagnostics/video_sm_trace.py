"""Structured Video state-machine trace (Sprint 8 Task 2 Round 7+).

Diagnosis-only instrumentation. Enabled when ``CUEPLAYER_PERF=1`` (same gate
as ``cueplayer.diagnostics.perf``). Never call from the audio RT callback.

Windows VIDEO_SM is the source of truth for the post-land freeze. Do **not**
assume a cause until the log distinguishes:

A. Worker genuinely occupied (SEEKING / DECODING / WAITING_FRAME)
B. Resume/play scheduler stopped issuing work (IDLE + no SCHEDULE_NEXT_PLAY)

Worker runtime states::

    IDLE
    SEEKING
    DECODING
    WAITING_FRAME
    PRESENTING
    CANCELLED

Events (canonical names)::

    SCRUB_PREVIEW_ENTER / REQUEST / PRESENT
    FINAL_LAND_REQUEST / DECODE_BEGIN / DECODE_DONE / PRESENT
    RESUME_BEGIN
    SCHEDULE_NEXT_PLAY
    FIRST_PLAY_FRAME / PLAY_PRESENT
    WORKER_RUNTIME
    STALE_DROP / DISCARD

Each event records: pipeline state, generation, worker_id, song/media time,
request_id, worker_runtime, current_request_id, reason/scheduler.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

from cueplayer.diagnostics import perf as perf_diag

# Ring buffer kept in-process for tests / Tools dump.
_MAX_EVENTS = 2000
_events: deque[dict[str, Any]] = deque(maxlen=_MAX_EVENTS)
_lock = threading.Lock()
_request_seq = 0
_first_play_after_land = False
_land_present_mono: float | None = None
_resume_begin_mono: float | None = None

# Live worker runtime (updated from decode worker / UI present path).
_worker_runtime = "IDLE"
_worker_runtime_request_id: int | None = None
_worker_runtime_changed_mono: float | None = None
_current_request_id: int | None = None

# Buffered VIDEO_SM file lines — never open the log on every tick (Windows
# cProfile showed video_sm_trace.trace ~1.17s from per-event file I/O).
_pending_log_lines: list[str] = []
_MAX_PENDING_LOG_LINES = 400
_last_log_flush_mono = 0.0
_LOG_FLUSH_INTERVAL_S = 1.0


class WorkerRuntime:
    IDLE = "IDLE"
    SEEKING = "SEEKING"
    DECODING = "DECODING"
    WAITING_FRAME = "WAITING_FRAME"
    PRESENTING = "PRESENTING"
    CANCELLED = "CANCELLED"


WORKER_RUNTIME_STATES = (
    WorkerRuntime.IDLE,
    WorkerRuntime.SEEKING,
    WorkerRuntime.DECODING,
    WorkerRuntime.WAITING_FRAME,
    WorkerRuntime.PRESENTING,
    WorkerRuntime.CANCELLED,
)

EVENT_NAMES = (
    "SCRUB_PREVIEW_ENTER",
    "SCRUB_PREVIEW_REQUEST",
    "SCRUB_PREVIEW_PRESENT",
    "FINAL_LAND_REQUEST",
    "FINAL_LAND_DECODE_BEGIN",
    "FINAL_LAND_DECODE_DONE",
    "FINAL_LAND_PRESENT",
    "RESUME_BEGIN",
    "SCHEDULE_NEXT_PLAY",
    "FIRST_PLAY_FRAME",
    "PLAY_PRESENT",
    "WORKER_RUNTIME",
    "STALE_DROP",
    "DISCARD",
)


def clear() -> None:
    global _request_seq, _first_play_after_land, _land_present_mono, _resume_begin_mono
    global _worker_runtime, _worker_runtime_request_id, _worker_runtime_changed_mono
    global _current_request_id, _last_log_flush_mono
    with _lock:
        _events.clear()
        _pending_log_lines.clear()
        _request_seq = 0
        _first_play_after_land = False
        _land_present_mono = None
        _resume_begin_mono = None
        _worker_runtime = WorkerRuntime.IDLE
        _worker_runtime_request_id = None
        _worker_runtime_changed_mono = None
        _current_request_id = None
        _last_log_flush_mono = 0.0


def flush_log(*, force: bool = False) -> None:
    """Flush buffered VIDEO_SM lines to the perf log (call from Tools dump)."""
    global _last_log_flush_mono
    with _lock:
        if not _pending_log_lines:
            return
        now = time.perf_counter()
        if (
            not force
            and _last_log_flush_mono > 0.0
            and (now - _last_log_flush_mono) < _LOG_FLUSH_INTERVAL_S
            and len(_pending_log_lines) < _MAX_PENDING_LOG_LINES
        ):
            return
        lines = list(_pending_log_lines)
        _pending_log_lines.clear()
        _last_log_flush_mono = now
    try:
        path = perf_diag.log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.writelines(lines)
    except Exception:
        pass


def _queue_log_line(line: str) -> None:
    with _lock:
        _pending_log_lines.append(line)
        overflow = len(_pending_log_lines) >= _MAX_PENDING_LOG_LINES
    if overflow:
        flush_log(force=True)


def next_request_id() -> int:
    global _request_seq, _current_request_id
    with _lock:
        _request_seq += 1
        _current_request_id = int(_request_seq)
        return int(_request_seq)


def set_current_request_id(request_id: int | None) -> None:
    global _current_request_id
    with _lock:
        _current_request_id = None if request_id is None else int(request_id)


def current_request_id() -> int | None:
    with _lock:
        return _current_request_id


def worker_runtime() -> str:
    with _lock:
        return str(_worker_runtime)


def worker_snapshot() -> dict[str, Any]:
    with _lock:
        age_ms = None
        if _worker_runtime_changed_mono is not None:
            age_ms = round((time.perf_counter() - _worker_runtime_changed_mono) * 1000.0, 1)
        return {
            "worker_runtime": str(_worker_runtime),
            "worker_runtime_request_id": _worker_runtime_request_id,
            "current_request_id": _current_request_id,
            "worker_runtime_age_ms": age_ms,
        }


def set_worker_runtime(
    runtime: str,
    *,
    request_id: int | None = None,
    reason: str | None = None,
    pipeline_state: str | None = None,
    generation: int | None = None,
    song_time: float | None = None,
    kind: str | None = None,
    emit_event: bool = True,
) -> None:
    """Update live worker runtime; optionally emit WORKER_RUNTIME."""
    if not perf_diag.is_enabled():
        return
    runtime = str(runtime)
    if runtime not in WORKER_RUNTIME_STATES:
        runtime = WorkerRuntime.IDLE
    global _worker_runtime, _worker_runtime_request_id, _worker_runtime_changed_mono
    global _current_request_id
    changed = False
    with _lock:
        prev = _worker_runtime
        if request_id is not None:
            _current_request_id = int(request_id)
            _worker_runtime_request_id = int(request_id)
        if prev != runtime:
            _worker_runtime = runtime
            _worker_runtime_changed_mono = time.perf_counter()
            changed = True
        snap_req = _worker_runtime_request_id
        snap_cur = _current_request_id
    if not changed and not emit_event:
        return
    if emit_event and changed:
        trace(
            "WORKER_RUNTIME",
            state=pipeline_state,
            generation=generation,
            request_id=snap_req if snap_req is not None else snap_cur,
            song_time=song_time,
            kind=kind,
            reason=reason or f"{prev}->{runtime}",
            extra={
                "worker_runtime": runtime,
                "worker_runtime_prev": prev,
                "current_request_id": snap_cur,
            },
        )
    else:
        # Keep attrs fresh even without a new event line.
        perf_diag.note("video.sm.worker_runtime", runtime)
        perf_diag.note("video.sm.current_request_id", snap_cur)


def events() -> list[dict[str, Any]]:
    with _lock:
        return list(_events)


def events_named(name: str) -> list[dict[str, Any]]:
    return [e for e in events() if e.get("event") == name]


def mark_land_present() -> None:
    global _land_present_mono, _first_play_after_land
    with _lock:
        _land_present_mono = time.perf_counter()
        _first_play_after_land = True


def mark_resume_begin() -> None:
    global _resume_begin_mono
    with _lock:
        _resume_begin_mono = time.perf_counter()


def consume_first_play_pending() -> bool:
    """Return True once for the first play present after FINAL_LAND_PRESENT."""
    global _first_play_after_land
    with _lock:
        if not _first_play_after_land:
            return False
        _first_play_after_land = False
        return True


def gap_ms_since_land_present() -> float | None:
    with _lock:
        if _land_present_mono is None:
            return None
        return (time.perf_counter() - _land_present_mono) * 1000.0


def gap_ms_since_resume_begin() -> float | None:
    with _lock:
        if _resume_begin_mono is None:
            return None
        return (time.perf_counter() - _resume_begin_mono) * 1000.0


def classify_post_land_gap(*, window_ms: float = 2000.0) -> dict[str, Any]:
    """Heuristic A/B classifier from the in-process ring (not a proof).

    A = worker occupied during the gap (SEEKING/DECODING/WAITING_FRAME seen
        while SCHEDULE_NEXT_PLAY keeps arriving, often coalesce_worker_busy).
    B = scheduler quiet while worker IDLE (no play schedules after RESUME).
    unknown = insufficient / mixed evidence — Windows log is source of truth.
    """
    evs = events()
    land = next((e for e in reversed(evs) if e.get("event") == "FINAL_LAND_PRESENT"), None)
    resume = next((e for e in reversed(evs) if e.get("event") == "RESUME_BEGIN"), None)
    first = next((e for e in reversed(evs) if e.get("event") == "FIRST_PLAY_FRAME"), None)
    if land is None:
        return {"hypothesis": "unknown", "reason": "no_FINAL_LAND_PRESENT"}
    t0 = float(land["t_mono"])
    t1 = float(first["t_mono"]) if first is not None else time.perf_counter()
    gap_ms = (t1 - t0) * 1000.0
    post = [e for e in evs if float(e.get("t_mono", 0)) >= t0]
    schedules = [e for e in post if e.get("event") == "SCHEDULE_NEXT_PLAY"]
    occupied = [
        e
        for e in post
        if e.get("event") == "WORKER_RUNTIME"
        and e.get("worker_runtime")
        in (
            WorkerRuntime.SEEKING,
            WorkerRuntime.DECODING,
            WorkerRuntime.WAITING_FRAME,
        )
    ]
    idle_runtime = [
        e
        for e in post
        if e.get("event") == "WORKER_RUNTIME" and e.get("worker_runtime") == WorkerRuntime.IDLE
    ]
    coalesce = [e for e in schedules if e.get("reason") == "coalesce_worker_busy"]
    hypothesis = "unknown"
    reason = "mixed_or_short_gap"
    if gap_ms >= 200.0:
        if schedules and (occupied or coalesce):
            hypothesis = "A_worker_occupied"
            reason = "schedules_while_worker_busy_or_coalesce"
        elif resume is not None and not schedules and (
            not occupied or (idle_runtime and not occupied)
        ):
            hypothesis = "B_scheduler_stopped"
            reason = "resume_begin_but_no_schedule_next_play"
        elif schedules and not occupied and not coalesce:
            # Schedules submitted while snapshot looked idle — still need decode begin.
            decode_begins = [
                e
                for e in post
                if e.get("event") in ("WORKER_RUNTIME", "FINAL_LAND_DECODE_BEGIN")
                and (
                    e.get("worker_runtime") in (WorkerRuntime.SEEKING, WorkerRuntime.DECODING)
                    or e.get("event") == "FINAL_LAND_DECODE_BEGIN"
                )
            ]
            if not decode_begins and gap_ms >= window_ms:
                hypothesis = "B_scheduler_or_worker_not_starting"
                reason = "schedule_without_seek_decode_runtime"
            elif decode_begins:
                hypothesis = "A_worker_occupied"
                reason = "schedule_then_seek_or_decode"
    return {
        "hypothesis": hypothesis,
        "reason": reason,
        "gap_ms": round(gap_ms, 1),
        "schedule_count": len(schedules),
        "coalesce_count": len(coalesce),
        "occupied_runtime_events": len(occupied),
        "idle_runtime_events": len(idle_runtime),
        "has_first_play_frame": first is not None,
        "note": "Windows VIDEO_SM log is source of truth; this is a local heuristic only.",
    }


def trace(
    event: str,
    *,
    state: str | None = None,
    generation: int | None = None,
    worker_id: str | int | None = None,
    song_time: float | None = None,
    media_time: float | None = None,
    request_id: int | None = None,
    reason: str | None = None,
    scheduler: str | None = None,
    kind: str | None = None,
    inflight: bool | None = None,
    session_gen: int | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Append one structured SM event (no-op when perf diagnostics disabled)."""
    if not perf_diag.is_enabled():
        return
    now = time.perf_counter()
    if worker_id is None:
        worker_id = threading.current_thread().name
    snap = worker_snapshot()
    req = request_id if request_id is not None else snap.get("current_request_id")
    payload: dict[str, Any] = {
        "event": str(event),
        "t_mono": round(now, 6),
        "state": state,
        "generation": generation,
        "worker_id": worker_id,
        "song_time": None if song_time is None else round(float(song_time), 6),
        "media_time": None if media_time is None else round(float(media_time), 6),
        "request_id": req,
        "current_request_id": snap.get("current_request_id"),
        "worker_runtime": snap.get("worker_runtime"),
        "worker_runtime_request_id": snap.get("worker_runtime_request_id"),
        "worker_runtime_age_ms": snap.get("worker_runtime_age_ms"),
        "reason": reason,
        "scheduler": scheduler,
        "kind": kind,
        "inflight": inflight,
        "session_gen": session_gen,
    }
    if extra:
        for k, v in extra.items():
            if k not in payload or payload[k] is None:
                payload[k] = v
    # Drop None noise for readability in logs.
    compact = {k: v for k, v in payload.items() if v is not None or k in ("event", "t_mono")}
    with _lock:
        _events.append(compact)
        n = len(_events)
    perf_diag.count(f"video.sm.{event}")
    perf_diag.note("video.sm.last_event", event)
    perf_diag.note("video.sm.last_payload", compact)
    perf_diag.note("video.sm.event_count", n)
    perf_diag.note("video.sm.worker_runtime", snap.get("worker_runtime"))
    perf_diag.note("video.sm.current_request_id", snap.get("current_request_id"))
    # Buffer file I/O — flush on Tools dump / interval / overflow.
    try:
        line = (
            f"VIDEO_SM {event}"
            f" state={compact.get('state')}"
            f" gen={compact.get('generation')}"
            f" req={compact.get('request_id')}"
            f" cur_req={compact.get('current_request_id')}"
            f" worker_runtime={compact.get('worker_runtime')}"
            f" song={compact.get('song_time')}"
            f" media={compact.get('media_time')}"
            f" worker={compact.get('worker_id')}"
            f" sched={compact.get('scheduler')}"
            f" reason={compact.get('reason')}"
            f" inflight={compact.get('inflight')}"
            f"\n"
        )
        _queue_log_line(line)
        flush_log(force=False)
    except Exception:
        pass


def report_text(*, limit: int = 100) -> str:
    """Human-readable tail of the SM ring buffer + A/B heuristic."""
    evs = events()
    snap = worker_snapshot()
    if not evs:
        return (
            "VIDEO_SM: (no events)\n"
            f"  live worker_runtime={snap.get('worker_runtime')} "
            f"current_request_id={snap.get('current_request_id')}\n"
        )
    lines = [f"VIDEO_SM events (last {min(limit, len(evs))} of {len(evs)}):", ""]
    for e in evs[-limit:]:
        parts = [e.get("event", "?")]
        for key in (
            "state",
            "generation",
            "request_id",
            "current_request_id",
            "worker_runtime",
            "song_time",
            "media_time",
            "worker_id",
            "scheduler",
            "reason",
            "kind",
            "inflight",
            "session_gen",
        ):
            if key in e and e[key] is not None:
                parts.append(f"{key}={e[key]}")
        lines.append("  " + " ".join(str(p) for p in parts))
    lines.append("")
    lines.append(
        f"live worker_runtime={snap.get('worker_runtime')} "
        f"worker_runtime_request_id={snap.get('worker_runtime_request_id')} "
        f"current_request_id={snap.get('current_request_id')} "
        f"age_ms={snap.get('worker_runtime_age_ms')}"
    )
    # Highlight land → first play gap if both present.
    land = next((e for e in reversed(evs) if e.get("event") == "FINAL_LAND_PRESENT"), None)
    first = next((e for e in reversed(evs) if e.get("event") == "FIRST_PLAY_FRAME"), None)
    if land is not None:
        lines.append("")
        if first is not None:
            gap = (float(first["t_mono"]) - float(land["t_mono"])) * 1000.0
            lines.append(f"LAND→FIRST_PLAY_FRAME gap_ms: {gap:.1f}")
        else:
            lines.append("LAND→FIRST_PLAY_FRAME gap_ms: (FIRST_PLAY_FRAME not seen yet)")
        schedulers = [
            e
            for e in evs
            if e.get("event") == "SCHEDULE_NEXT_PLAY"
            and float(e.get("t_mono", 0)) >= float(land["t_mono"])
        ]
        lines.append(f"SCHEDULE_NEXT_PLAY after land: {len(schedulers)}")
        for e in schedulers[:12]:
            lines.append(
                f"  scheduler={e.get('scheduler')} gen={e.get('generation')} "
                f"inflight={e.get('inflight')} reason={e.get('reason')} "
                f"worker_runtime={e.get('worker_runtime')} "
                f"req={e.get('request_id')} song={e.get('song_time')}"
            )
        cls = classify_post_land_gap()
        lines.append("")
        lines.append(
            "post_land_hypothesis (heuristic only): "
            f"{cls.get('hypothesis')} reason={cls.get('reason')} "
            f"gap_ms={cls.get('gap_ms')} schedules={cls.get('schedule_count')} "
            f"coalesce={cls.get('coalesce_count')} "
            f"occupied_rt={cls.get('occupied_runtime_events')}"
        )
        lines.append(
            "A = worker occupied; B = scheduler stopped issuing work; "
            "Windows VIDEO_SM log is source of truth — do not assume A."
        )
    lines.append("")
    return "\n".join(lines)
