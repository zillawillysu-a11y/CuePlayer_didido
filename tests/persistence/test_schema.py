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
        ma3_song_viewbutton="2.10",
        song_list_sequence_pool=777,
        ma2_template_page=88,
        ma2_fixed_macro_start=2201,
        ma2_song_macro_start=3201,
        ma2_add_main_preset_cue=True,
        ma2_main_preset_cue_id=0.25,
        ma2_include_song_views=False,
        ma2_view_pool_start=501,
        ma2_effect_pool_start=601,
        ma2_effect_slots_per_song=137,
        ma2_sequence_slots_per_song=40,
        ma2_target_version="3.9.63.6",
        ma2_output_dir_follows_version=False,
        ma2_telnet_host="192.168.1.10",
        ma2_telnet_command_port=31000,
        ma2_telnet_monitor_port=31001,
        ma2_telnet_user="ScanUser",
        ma2_telnet_plugin_pool=999,
        ma2_telnet_plugin_import_path="/data/ma/actual/gma2/plugins",
        ma3_osc_host="192.168.1.30",
        ma3_osc_send_port=9000,
        ma3_osc_listen_port=9001,
        ma3_osc_output_line=2,
        ma3_scan_lua_path="C:/gma3/CuePlayer_MA3_Live_Scan.lua",
        ma3_scanned_pool_max={"sequence": 464, "view": 404},
        ma3_generator_pool_start=451,
        ma3_generator_slots_per_song=50,
        export_content_by_song={"song-id": {"main": False, "buttons": [2, 4]}},
        ma2_view_layout=[{"type": "effects", "mode": "perSong", "x": 2, "y": 1, "w": 12, "h": 4, "start": 601, "stride": 137}],
        ma3_view_layout=[{"type": "all5", "mode": "perSong", "x": 0, "y": 5, "w": 18, "h": 5, "start": 1091, "stride": 100}],
        ma2_pool_overrides={"song-id": {"sequence": 900, "timecode": 500}},
        ma2_start_after_scanned=True,
    )

    loaded = dict_to_ma_export(ma_export_to_dict(settings))

    assert loaded.ma2_include_fixed_macros is False
    assert loaded.ma2_include_song_macros is True
    assert loaded.ma2_include_song_list is False
    assert loaded.ma3_song_viewbutton == "2.10"
    assert loaded.song_list_sequence_pool == 777
    assert loaded.ma2_template_page == 88
    assert loaded.ma2_fixed_macro_start == 2201
    assert loaded.ma2_song_macro_start == 3201
    assert loaded.ma2_add_main_preset_cue is True
    assert loaded.ma2_main_preset_cue_id == 0.25
    assert loaded.ma2_include_song_views is False
    assert loaded.ma2_view_pool_start == 501
    assert loaded.ma2_effect_pool_start == 601
    assert loaded.ma2_effect_slots_per_song == 137
    assert loaded.ma2_sequence_slots_per_song == 40
    assert loaded.ma2_target_version == "3.9.63.6"
    assert loaded.ma2_output_dir_follows_version is False
    assert loaded.ma2_telnet_host == "192.168.1.10"
    assert loaded.ma2_telnet_command_port == 31000
    assert loaded.ma2_telnet_monitor_port == 31001
    assert loaded.ma2_telnet_user == "ScanUser"
    assert loaded.ma2_telnet_plugin_pool == 999
    assert loaded.ma2_telnet_plugin_import_path == "/data/ma/actual/gma2/plugins"
    assert loaded.ma3_osc_host == "192.168.1.30"
    assert loaded.ma3_osc_send_port == 9000
    assert loaded.ma3_osc_listen_port == 9001
    assert loaded.ma3_osc_output_line == 2
    assert loaded.ma3_scan_lua_path == "C:/gma3/CuePlayer_MA3_Live_Scan.lua"
    assert loaded.ma3_scanned_pool_max == {"sequence": 464, "view": 404}
    assert loaded.ma3_generator_pool_start == 451
    assert loaded.ma3_generator_slots_per_song == 50
    assert loaded.ma2_view_layout[0]["w"] == 12
    assert loaded.ma2_view_layout[0]["stride"] == 137
    assert loaded.ma3_view_layout[0]["type"] == "all5"
    assert loaded.ma3_view_layout[0]["start"] == 1091
    assert loaded.export_content_by_song == {
        "song-id": {"main": False, "buttons": [2, 4]}
    }
    assert loaded.ma2_pool_overrides == {
        "song-id": {"sequence": 900, "timecode": 500}
    }
    assert loaded.ma2_start_after_scanned is True
    # Absent in an older project file = off, i.e. a plain export.
    assert dict_to_ma_export({}).ma2_start_after_scanned is False
    assert dict_to_ma_export({}).song_list_sequence_pool == 1001


def test_legacy_ma2_macro_start_loads_as_fixed_macro_start() -> None:
    loaded = dict_to_ma_export({"ma2_macro_pool_start": 1701})

    assert loaded.ma2_fixed_macro_start == 1701
    assert loaded.ma2_song_macro_start == 201


def test_legacy_default_allocations_migrate_to_current_safe_starts() -> None:
    loaded = dict_to_ma_export(
        {
            "timecode_pool_start": 1,
            "main_executor": "1.101",
            "button_executor_start": "1.201",
            "ma2_template_page": 100,
            "ma2_fixed_macro_start": 1001,
            "ma2_song_macro_start": 1009,
        }
    )

    assert loaded.timecode_pool_start == 201
    assert loaded.main_executor == "201.130"
    assert loaded.button_executor_start == "201.101"
    assert loaded.ma2_template_page == 200
    assert loaded.ma2_fixed_macro_start == 101
    assert loaded.ma2_song_macro_start == 201
