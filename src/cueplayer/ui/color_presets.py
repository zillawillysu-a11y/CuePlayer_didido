"""Persistent color presets + QColorDialog custom-color slots.

The Quick Color Pick popup (and Qt's color dialog bottom-left custom slots)
lose user-added colors on restart unless we save them. Shared helpers keep
both in sync via ``QSettings``.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog

_ORG = "CuePlayer"
_APP = "CuePlayer"
_KEY_USER_PRESETS = "colors/user_presets"
_KEY_DIALOG_CUSTOMS = "colors/dialog_custom_slots"

# Built-in swatches shown first in Quick Color Pick.
BUILTIN_PRESETS: list[str] = [
    "#E74C3C",
    "#E67E22",
    "#F1C40F",
    "#2ECC71",
    "#1ABC9C",
    "#3498DB",
    "#9B59B6",
    "#34495E",
    "#E91E63",
    "#3dd68c",
    "#ff5a5f",
    "#4a9eff",
]


def _settings() -> QSettings:
    return QSettings(_ORG, _APP)


def _normalize_hex(color: str | QColor) -> str | None:
    q = color if isinstance(color, QColor) else QColor(color)
    if not q.isValid():
        return None
    return q.name().lower()


def load_user_presets() -> list[str]:
    raw = _settings().value(_KEY_USER_PRESETS, [])
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        hex_color = _normalize_hex(str(item))
        if hex_color is None or hex_color in seen:
            continue
        seen.add(hex_color)
        out.append(hex_color)
    return out


def save_user_presets(colors: list[str]) -> None:
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in colors:
        hex_color = _normalize_hex(item)
        if hex_color is None or hex_color in seen:
            continue
        seen.add(hex_color)
        cleaned.append(hex_color)
    _settings().setValue(_KEY_USER_PRESETS, cleaned)


def all_presets() -> list[str]:
    """Built-ins first, then user presets (deduped)."""
    seen = {c.lower() for c in BUILTIN_PRESETS}
    out = list(BUILTIN_PRESETS)
    for hex_color in load_user_presets():
        if hex_color in seen:
            continue
        seen.add(hex_color)
        out.append(hex_color)
    return out


def add_user_preset(color: str) -> bool:
    """Append a custom color to the user preset list. Returns True if newly added."""
    hex_color = _normalize_hex(color)
    if hex_color is None:
        return False
    if hex_color in {c.lower() for c in BUILTIN_PRESETS}:
        return False
    presets = load_user_presets()
    if hex_color in presets:
        return False
    presets.append(hex_color)
    save_user_presets(presets)
    return True


def remove_user_preset(color: str) -> None:
    hex_color = _normalize_hex(color)
    if hex_color is None:
        return
    save_user_presets([c for c in load_user_presets() if c != hex_color])


def restore_color_dialog_customs() -> None:
    """Load Qt color-dialog custom slots (bottom-left) from QSettings."""
    raw = _settings().value(_KEY_DIALOG_CUSTOMS, [])
    if not isinstance(raw, list):
        return
    for i, item in enumerate(raw[:16]):
        hex_color = _normalize_hex(str(item)) if item else None
        if hex_color is None:
            continue
        QColorDialog.setCustomColor(i, QColor(hex_color))


def persist_color_dialog_customs() -> None:
    """Save Qt color-dialog custom slots after the user may have edited them."""
    colors: list[str] = []
    for i in range(16):
        raw = QColorDialog.customColor(i)
        q = raw if isinstance(raw, QColor) else QColor.fromRgba(int(raw))
        if q.isValid():
            colors.append(q.name().lower())
        else:
            colors.append("")
    _settings().setValue(_KEY_DIALOG_CUSTOMS, colors)


def get_color(
    initial: QColor | str,
    parent=None,  # noqa: ANN001
    title: str = "Choose Color",
) -> QColor:
    """``QColorDialog.getColor`` that restores/saves the bottom-left custom slots."""
    restore_color_dialog_customs()
    start = initial if isinstance(initial, QColor) else QColor(initial)
    chosen = QColorDialog.getColor(start, parent, title)
    persist_color_dialog_customs()
    return chosen
