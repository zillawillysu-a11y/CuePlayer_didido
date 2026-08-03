"""Stable ValidationCode identifiers (e.g. MA001)."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Prefix (2–4 uppercase letters) + three digits. MA*** reserved for MA export.
_CODE_PATTERN = re.compile(r"^[A-Z]{2,4}\d{3}$")


def is_valid_code_format(value: object) -> bool:
    """True when ``value`` matches ``^[A-Z]{2,4}\\d{3}$`` (e.g. ``MA001``)."""
    try:
        text = str(value).strip().upper()
    except Exception:  # noqa: BLE001
        return False
    return bool(_CODE_PATTERN.fullmatch(text))


@dataclass(frozen=True, slots=True)
class ValidationCode:
    """Immutable validation rule / issue code.

    Naming rules
    ------------
    - Format: ``PREFIXNNN`` where PREFIX is 2–4 A–Z letters and NNN is three digits.
    - MA export preflight uses the ``MA`` prefix (``MA001`` … ``MA999``).
    - Other domains may use other prefixes (e.g. ``TC``, ``MEDIA``) later.
    - Codes are stable public identifiers — do not renumber once shipped.
    - One primary code per rule; messages carry human detail.
    """

    value: str

    def __post_init__(self) -> None:
        normalized = str(self.value or "").strip().upper()
        if not is_valid_code_format(normalized):
            raise ValueError(
                f"invalid ValidationCode {self.value!r}; "
                "expected PREFIXNNN (2–4 letters + 3 digits), e.g. MA001"
            )
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value

    @property
    def prefix(self) -> str:
        match = re.match(r"^([A-Z]{2,4})\d{3}$", self.value)
        return match.group(1) if match else ""

    @property
    def number(self) -> int:
        return int(self.value[-3:])


def coerce_validation_code(value: object) -> ValidationCode:
    """Build a ``ValidationCode`` from a string or existing code."""
    if isinstance(value, ValidationCode):
        return value
    return ValidationCode(str(value))
