"""Persistence unit tests."""

from __future__ import annotations

import pytest

from cueplayer.domain.models import MaExportSettings, SCHEMA_VERSION
from cueplayer.persistence.project_migrations import SchemaError, migrate_project_dict
from cueplayer.persistence.project_store import dict_to_ma_export, ma_export_to_dict


def test_migrate_version_zero() -> None:
    data = migrate_project_dict({"id": "abc", "name": "測試", "songs": []}, from_version=0)
    assert data["schema_version"] == SCHEMA_VERSION == 2


def test_reject_future_schema() -> None:
    with pytest.raises(SchemaError):
        migrate_project_dict({"schema_version": 99, "id": "x", "name": "y"}, from_version=99)


def test_ma2_full_export_options_round_trip() -> None:
    settings = MaExportSettings(
        ma2_include_fixed_macros=False,
        ma2_include_song_macros=True,
        ma2_include_song_list=False,
        ma2_template_page=88,
        ma2_fixed_macro_start=2201,
        ma2_song_macro_start=3201,
        ma2_add_main_preset_cue=True,
        ma2_main_preset_cue_id=0.25,
    )

    loaded = dict_to_ma_export(ma_export_to_dict(settings))

    assert loaded.ma2_include_fixed_macros is False
    assert loaded.ma2_include_song_macros is True
    assert loaded.ma2_include_song_list is False
    assert loaded.ma2_template_page == 88
    assert loaded.ma2_fixed_macro_start == 2201
    assert loaded.ma2_song_macro_start == 3201
    assert loaded.ma2_add_main_preset_cue is True
    assert loaded.ma2_main_preset_cue_id == 0.25


def test_legacy_ma2_macro_start_loads_as_fixed_macro_start() -> None:
    loaded = dict_to_ma_export({"ma2_macro_pool_start": 1701})

    assert loaded.ma2_fixed_macro_start == 1701
    assert loaded.ma2_song_macro_start == 1009
