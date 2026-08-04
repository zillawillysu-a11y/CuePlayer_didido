"""Lightweight performance diagnostics (off by default).

Enable with environment variable ``CUEPLAYER_PERF=1`` or ``set_enabled(True)``.

Rules
-----
- Never call from the PortAudio / real-time audio callback.
- Spans are UI-thread or worker-thread wall times only.
- Zero overhead when disabled (hot paths check ``is_enabled()`` first).
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator


def _env_enabled() -> bool:
    raw = str(os.environ.get("CUEPLAYER_PERF", "") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


_enabled: bool = _env_enabled()
_lock = threading.Lock()


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
        }


def report_text() -> str:
    snap = snapshot()
    if not snap["enabled"] and not snap["spans"] and not snap["counters"]:
        return "CUEPLAYER_PERF: disabled (set CUEPLAYER_PERF=1 to enable)\n"
    lines = ["CUEPLAYER_PERF report", ""]
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
