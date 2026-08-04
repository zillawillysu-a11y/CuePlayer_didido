"""Diagnostics package — optional timing / audit helpers (not on audio RT path)."""

from __future__ import annotations

from cueplayer.diagnostics.perf import (
    announce_if_enabled,
    clear,
    count,
    flush_report,
    is_enabled,
    log_path,
    note,
    record_ms,
    report_text,
    set_enabled,
    set_log_path,
    snapshot,
    span,
)

__all__ = [
    "announce_if_enabled",
    "clear",
    "count",
    "flush_report",
    "is_enabled",
    "log_path",
    "note",
    "record_ms",
    "report_text",
    "set_enabled",
    "set_log_path",
    "snapshot",
    "span",
]
