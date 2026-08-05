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
    )
    counters = snap.get("counters") or {}
    lines.append("Video pipeline counters (0 if unused this session):")
    for name in expected_video_counters:
        lines.append(f"  {name}: {int(counters.get(name, 0))}")
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
