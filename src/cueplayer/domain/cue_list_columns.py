"""Cue List table column order (drag header to reorder).

Domain helper: field ids, labels, logical indices, and order normalization.
UI and persistence consume this module; keep it Qt-free.
"""

from __future__ import annotations

CUE_LIST_FIELDS: tuple[str, ...] = ("time", "type", "cue_id", "note")
DEFAULT_CUE_LIST_COLUMN_ORDER: list[str] = ["time", "type", "cue_id", "note"]
CUE_LIST_FIELD_LABELS: dict[str, str] = {
    "time": "Time",
    "type": "Type",
    "cue_id": "Cue ID",
    "note": "Note",
}
LOGICAL_INDEX_BY_FIELD: dict[str, int] = {field: index for index, field in enumerate(CUE_LIST_FIELDS)}


def normalize_cue_list_column_order(order: list[str] | None) -> list[str]:
    """Return a full permutation of cue-list fields (default: Time, Type, Cue ID, Note)."""
    valid: list[str] = []
    if order:
        for field in order:
            key = str(field).strip().lower()
            if key in LOGICAL_INDEX_BY_FIELD and key not in valid:
                valid.append(key)
    for field in DEFAULT_CUE_LIST_COLUMN_ORDER:
        if field not in valid:
            valid.append(field)
    return valid[: len(CUE_LIST_FIELDS)]
