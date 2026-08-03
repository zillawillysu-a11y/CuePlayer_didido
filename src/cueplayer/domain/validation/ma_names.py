"""MA-safe label checks for preflight (domain-only; no exporter import)."""

from __future__ import annotations

import re

# Matches grandMA-safe ASCII labels CuePlayer aims for after sanitize.
# Spaces are rejected here — operators should store underscore form in ma_export_name.
_SAFE_LABEL_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_NON_ASCII_RE = re.compile(r"[^\x00-\x7f]")


def is_blank(value: object) -> bool:
    return value is None or not str(value).strip()


def has_non_ascii(value: object) -> bool:
    text = str(value or "")
    return bool(_NON_ASCII_RE.search(text))


def is_valid_ma_export_name(value: object) -> bool:
    """True when an explicit MA Export Name is non-empty ASCII-safe (no spaces)."""
    if is_blank(value):
        return False
    text = str(value).strip()
    if has_non_ascii(text):
        return False
    return bool(_SAFE_LABEL_RE.fullmatch(text))


def normalize_sequence_key(value: object) -> str:
    """Case-folded key for duplicate sequence detection."""
    return str(value or "").strip().casefold()


def parse_executor_ref(value: object) -> tuple[int, int] | None:
    """Parse ``page.executor``; return None when unusable."""
    text = str(value or "").strip()
    if not text:
        return None
    if "." in text:
        page_s, exec_s = text.split(".", 1)
        page_s, exec_s = page_s.strip(), exec_s.strip()
        if not page_s.isdigit() or not exec_s.isdigit():
            return None
        page, executor = int(page_s), int(exec_s)
    elif text.isdigit():
        page, executor = 1, int(text)
    else:
        return None
    if page < 1 or executor < 1:
        return None
    return page, executor


def format_executor(page: int, executor: int) -> str:
    return f"{int(page)}.{int(executor)}"
