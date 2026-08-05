"""Structured Video state-machine trace (Sprint 8 Task 2 Round 7).

Diagnosis-only instrumentation. Enabled when ``CUEPLAYER_PERF=1`` (same gate
as ``cueplayer.diagnostics.perf``). Never call from the audio RT callback.

Events (canonical names)::

    SCRUB_PREVIEW_ENTER
    SCRUB_PREVIEW_REQUEST
    SCRUB_PREVIEW_PRESENT
    FINAL_LAND_REQUEST
    FINAL_LAND_DECODE_BEGIN
    FINAL_LAND_DECODE_DONE
    FINAL_LAND_PRESENT
    RESUME_BEGIN
    SCHEDULE_NEXT_PLAY   # who schedules the next play frame after land
    FIRST_PLAY_FRAME
    PLAY_PRESENT
    STALE_DROP
    DISCARD

Each event records: state, generation, worker_id, song_time, media_time,
request_id, stale/discard reason (if any), plus optional fields.
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
    "STALE_DROP",
    "DISCARD",
)


def clear() -> None:
    global _request_seq, _first_play_after_land, _land_present_mono, _resume_begin_mono
    with _lock:
        _events.clear()
        _request_seq = 0
        _first_play_after_land = False
        _land_present_mono = None
        _resume_begin_mono = None


def next_request_id() -> int:
    global _request_seq
    with _lock:
        _request_seq += 1
        return int(_request_seq)


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
    payload: dict[str, Any] = {
        "event": str(event),
        "t_mono": round(now, 6),
        "state": state,
        "generation": generation,
        "worker_id": worker_id,
        "song_time": None if song_time is None else round(float(song_time), 6),
        "media_time": None if media_time is None else round(float(media_time), 6),
        "request_id": request_id,
        "reason": reason,
        "scheduler": scheduler,
        "kind": kind,
        "inflight": inflight,
        "session_gen": session_gen,
    }
    if extra:
        for k, v in extra.items():
            if k not in payload:
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
    # Always mirror to the perf log as a one-line breadcrumb.
    try:
        path = perf_diag.log_path()
        line = (
            f"VIDEO_SM {event}"
            f" state={compact.get('state')}"
            f" gen={compact.get('generation')}"
            f" req={compact.get('request_id')}"
            f" song={compact.get('song_time')}"
            f" media={compact.get('media_time')}"
            f" worker={compact.get('worker_id')}"
            f" sched={compact.get('scheduler')}"
            f" reason={compact.get('reason')}"
            f" inflight={compact.get('inflight')}"
            f"\n"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:
        pass


def report_text(*, limit: int = 80) -> str:
    """Human-readable tail of the SM ring buffer."""
    evs = events()
    if not evs:
        return "VIDEO_SM: (no events)\n"
    lines = [f"VIDEO_SM events (last {min(limit, len(evs))} of {len(evs)}):", ""]
    for e in evs[-limit:]:
        parts = [e.get("event", "?")]
        for key in (
            "state",
            "generation",
            "request_id",
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
            e for e in evs
            if e.get("event") == "SCHEDULE_NEXT_PLAY"
            and float(e.get("t_mono", 0)) >= float(land["t_mono"])
        ]
        lines.append(f"SCHEDULE_NEXT_PLAY after land: {len(schedulers)}")
        for e in schedulers[:12]:
            lines.append(
                f"  scheduler={e.get('scheduler')} gen={e.get('generation')} "
                f"inflight={e.get('inflight')} reason={e.get('reason')} "
                f"song={e.get('song_time')}"
            )
    lines.append("")
    return "\n".join(lines)
