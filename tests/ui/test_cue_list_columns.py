"""Cue List column order helpers — behavior lock after domain migration.

Imports via the **UI shim** keep backward compatibility. Domain is the source
of truth; shim must re-export identical objects.
"""

from __future__ import annotations

import importlib
import inspect

from cueplayer.ui.cue_list_columns import (
    CUE_LIST_FIELD_LABELS,
    CUE_LIST_FIELDS,
    DEFAULT_CUE_LIST_COLUMN_ORDER,
    LOGICAL_INDEX_BY_FIELD,
    normalize_cue_list_column_order,
)

_PUBLIC = (
    "CUE_LIST_FIELDS",
    "DEFAULT_CUE_LIST_COLUMN_ORDER",
    "CUE_LIST_FIELD_LABELS",
    "LOGICAL_INDEX_BY_FIELD",
    "normalize_cue_list_column_order",
)


def test_default_column_order_is_time_type_cue_id_note() -> None:
    assert DEFAULT_CUE_LIST_COLUMN_ORDER == ["time", "type", "cue_id", "note"]


def test_cue_list_fields_tuple_matches_default_order() -> None:
    assert list(CUE_LIST_FIELDS) == DEFAULT_CUE_LIST_COLUMN_ORDER
    assert len(CUE_LIST_FIELDS) == 4


def test_field_labels_cover_every_field_exactly() -> None:
    assert set(CUE_LIST_FIELD_LABELS) == set(CUE_LIST_FIELDS)
    assert CUE_LIST_FIELD_LABELS == {
        "time": "Time",
        "type": "Type",
        "cue_id": "Cue ID",
        "note": "Note",
    }


def test_logical_index_is_enumerate_of_fields() -> None:
    assert LOGICAL_INDEX_BY_FIELD == {
        "time": 0,
        "type": 1,
        "cue_id": 2,
        "note": 3,
    }
    for field, index in LOGICAL_INDEX_BY_FIELD.items():
        assert CUE_LIST_FIELDS[index] == field


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


def test_normalize_none_and_empty_yield_default() -> None:
    assert normalize_cue_list_column_order(None) == list(DEFAULT_CUE_LIST_COLUMN_ORDER)
    assert normalize_cue_list_column_order([]) == list(DEFAULT_CUE_LIST_COLUMN_ORDER)


def test_normalize_strips_and_lowercases_keys() -> None:
    assert normalize_cue_list_column_order(["  NOTE ", "Time", "TYPE"]) == [
        "note",
        "time",
        "type",
        "cue_id",
    ]


def test_normalize_preserves_first_seen_valid_order() -> None:
    assert normalize_cue_list_column_order(
        ["note", "cue_id", "time", "type"]
    ) == ["note", "cue_id", "time", "type"]


def test_normalize_is_idempotent() -> None:
    samples = [
        None,
        [],
        ["note"],
        ["bogus", "NOTE", "note", "time"],
        ["type", "cue_id", "time", "note"],
    ]
    for raw in samples:
        once = normalize_cue_list_column_order(raw)
        assert normalize_cue_list_column_order(once) == once
        assert len(once) == len(CUE_LIST_FIELDS)
        assert set(once) == set(CUE_LIST_FIELDS)


def test_normalize_always_returns_full_permutation() -> None:
    for raw in (None, ["note"], ["x", "y"], list(reversed(CUE_LIST_FIELDS))):
        out = normalize_cue_list_column_order(raw)
        assert sorted(out) == sorted(CUE_LIST_FIELDS)


def test_domain_module_has_no_ui_toolkit_imports() -> None:
    """Domain leaf must stay Qt-free."""
    mod = importlib.import_module("cueplayer.domain.cue_list_columns")
    source = inspect.getsource(mod)
    for banned in ("PySide6", "PyQt", "QtWidgets", "QtCore", "QtGui"):
        assert banned not in source


def test_ui_shim_reexports_identical_objects() -> None:
    ui_mod = importlib.import_module("cueplayer.ui.cue_list_columns")
    dom_mod = importlib.import_module("cueplayer.domain.cue_list_columns")
    for name in _PUBLIC:
        assert getattr(ui_mod, name) is getattr(dom_mod, name)
    assert set(ui_mod.__all__) == set(_PUBLIC)


def test_domain_public_api_matches_shim() -> None:
    from cueplayer.domain import cue_list_columns as dom

    assert dom.normalize_cue_list_column_order(["note"]) == [
        "note",
        "time",
        "type",
        "cue_id",
    ]


def test_project_store_imports_normalize_from_domain_not_ui() -> None:
    """Step 1 clears forbidden persistence→ui edge."""
    source = inspect.getsource(
        importlib.import_module("cueplayer.persistence.project_store")
    )
    assert (
        "from cueplayer.domain.cue_list_columns import normalize_cue_list_column_order"
        in source
    )
    assert "from cueplayer.ui.cue_list_columns import" not in source
