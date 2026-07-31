"""Cue List column order helpers."""

from __future__ import annotations

from cueplayer.ui.cue_list_columns import (
    DEFAULT_CUE_LIST_COLUMN_ORDER,
    normalize_cue_list_column_order,
)


def test_default_column_order_is_time_type_cue_id_note() -> None:
    assert DEFAULT_CUE_LIST_COLUMN_ORDER == ["time", "type", "cue_id", "note"]


def test_normalize_fills_missing_fields() -> None:
    assert normalize_cue_list_column_order(["note", "time"]) == [
        "note",
        "time",
        "type",
        "cue_id",
    ]


def test_normalize_drops_unknown_and_duplicates() -> None:
    assert normalize_cue_list_column_order(
        ["bogus", "cue_id", "cue_id", "type", "time"]
    ) == ["cue_id", "type", "time", "note"]
