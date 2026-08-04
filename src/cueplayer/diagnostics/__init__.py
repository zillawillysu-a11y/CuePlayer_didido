"""Diagnostics package — optional timing / audit helpers (not on audio RT path)."""

from __future__ import annotations

from cueplayer.diagnostics.perf import (
    clear,
    count,
    is_enabled,
    note,
    record_ms,
    report_text,
    set_enabled,
    snapshot,
    span,
)

__all__ = [
    "clear",
    "count",
    "is_enabled",
    "note",
    "record_ms",
    "report_text",
    "set_enabled",
    "snapshot",
    "span",
]
