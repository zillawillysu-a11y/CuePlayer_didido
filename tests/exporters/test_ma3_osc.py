from pathlib import Path

from cueplayer.exporters.ma3_osc import (
    DONE_ADDRESS,
    SCAN_ADDRESS,
    decode_osc_string,
    encode_osc_string,
    live_scan_lua,
    resolve_ma3_scan_lua_dir,
    write_live_scan_lua,
)


def test_osc_string_round_trip_unicode() -> None:
    packet = encode_osc_string(SCAN_ADDRESS, "abc|sequence|中文")
    assert decode_osc_string(packet) == (SCAN_ADDRESS, "abc|sequence|中文")


def test_ma3_scanner_lua_is_read_only_and_reports_required_pools() -> None:
    lua = live_scan_lua(osc_output_line=2)
    assert "DataPool()" in lua
    assert "ObjectList(\"View 1 Thru 9999\")" in lua
    assert "SendOSC 2" in lua
    assert SCAN_ADDRESS in lua and DONE_ADDRESS in lua
    assert "return function()" not in lua
    for destructive in ("Store ", "Delete ", "Assign "):
        assert destructive not in lua


def test_write_live_scan_lua_utf8(tmp_path: Path) -> None:
    path = write_live_scan_lua(tmp_path, osc_output_line=3)
    assert path.name == "CuePlayer_MA3_Live_Scan.lua"
    assert "SendOSC 3" in path.read_text(encoding="utf-8")


def test_resolve_scan_lua_dir_from_ma3_library_locations(tmp_path: Path) -> None:
    library = tmp_path / "gma3_library"
    plugins = library / "datapools" / "plugins"
    assert resolve_ma3_scan_lua_dir(library) == plugins
    assert resolve_ma3_scan_lua_dir(library / "datapools") == plugins
    assert resolve_ma3_scan_lua_dir(library / "datapools" / "sequences") == plugins
    assert resolve_ma3_scan_lua_dir(plugins) == plugins
