"""Show-wide MA Sequence / Fader patch allocation."""

from __future__ import annotations

from cueplayer.domain.models import Mark, MaExportSettings, Project, Song
from cueplayer.exporters.show_patch import build_show_patch, sequence_chain_labels


def _song_with_buttons(name: str, *, ma: str, button_names: list[str]) -> Song:
    song = Song.create(name)
    song.ma_export_name = ma
    # Rename button lanes to Hit / Crash style names.
    for lane in song.mark_lanes:
        if lane.lane_type == "top_button" and 2 <= lane.index < 2 + len(button_names):
            lane.name = button_names[lane.index - 2]
    song.marks = [Mark.create(1, 1.0, "c1")]
    for i, _name in enumerate(button_names, start=2):
        song.marks.append(Mark.create(i, float(i), f"b{i}"))
    return song


def test_show_patch_uses_english_sequence_names() -> None:
    project = Project.create("Show")
    project.songs = [
        _song_with_buttons("第一首", ma="SongA", button_names=["Hit", "Crash"]),
        _song_with_buttons("第二首", ma="SongB", button_names=["Hit", "Crash"]),
    ]
    settings = MaExportSettings(
        sequence_pool_start=1,
        main_executor="1.101",
        button_executor_start="1.201",
        page_per_song=True,
    )
    slots = build_show_patch(project.songs, settings)
    assert slots[0].display_name == "SongA"
    assert slots[0].page == 1
    assert slots[1].page == 2
    assert slots[0].main_sequence_name == "SongA_Main"
    assert [b.sequence_name for b in slots[0].buttons] == ["SongA_Hit", "SongA_Crash"]
    assert slots[1].main_sequence_name == "SongB_Main"
    assert [b.executor for b in slots[1].buttons] == ["2.201", "2.202"]
    labels = sequence_chain_labels(slots)
    assert "SongA_Main" in labels[0]
    assert "SongA_Hit" in labels[1]

    from cueplayer.exporters.show_patch import plans_from_show_patch

    plans = plans_from_show_patch(slots, settings)
    assert plans[0].profile.page_name == "SongA"
    assert plans[1].profile.page_name == "SongB"
    assert plans[1].profile.page == 2
    # Default start TC 01:00:00:00 → 3600s OffsetTCSlot
    assert abs(plans[0].profile.start_offset_seconds - 3600.0) < 1e-6


def test_ma3_show_export_one_macro(tmp_path) -> None:
    from cueplayer.exporters.ma3 import Ma3Exporter
    from cueplayer.exporters.show_patch import build_show_patch, plans_from_show_patch
    from cueplayer.exporters.xml_inspect import load_xml_root, xml_tag_local

    project = Project.create("Show")
    project.songs = [
        _song_with_buttons("第一首", ma="SongA", button_names=["Hit"]),
        _song_with_buttons("第二首", ma="SongB", button_names=["Hit"]),
    ]
    for song in project.songs:
        song.start_timecode = "01:00:00:00"
    settings = MaExportSettings(
        console="ma3",
        sequence_pool_start=1,
        main_executor="1.101",
        button_executor_start="1.201",
        page_per_song=True,
        export_mode="full",
    )
    slots = build_show_patch(project.songs, settings)
    plans = plans_from_show_patch(slots, settings)
    paths = Ma3Exporter().export_show_to_directory(plans, tmp_path)

    assert "show:macro" in paths
    assert paths["show:macro"].name == "CuePlayer_Show_Install.xml"
    # No per-song macros
    assert not any(k.endswith(":macro") and k != "show:macro" for k in paths)

    root = load_xml_root(paths["show:macro"])
    commands = [
        line.get("Command", "")
        for line in root.iter()
        if xml_tag_local(line.tag) == "MacroLine"
    ]
    assert any("SongA_Main" in c for c in commands)
    assert any("SongB_Main" in c for c in commands)
    assert any('Property "OffsetTCSlot" "1h00m00.00"' in c for c in commands)
    assert sum(1 for c in commands if "Import Timecode" in c) == 2


def test_ma2_show_export_cuepoints_plugin(tmp_path) -> None:
    from cueplayer.exporters.ma2 import Ma2Exporter
    from cueplayer.exporters.show_patch import build_show_patch, plans_from_show_patch

    project = Project.create("Show")
    project.songs = [
        _song_with_buttons("第一首", ma="SongA", button_names=["Hit"]),
        _song_with_buttons("第二首", ma="SongB", button_names=["Hit"]),
    ]
    for song in project.songs:
        song.start_timecode = "01:00:00:00"
        song.marks[0].display_name = "主歌"
    settings = MaExportSettings(
        console="ma2",
        sequence_pool_start=1,
        main_executor="1.101",
        button_executor_start="1.102",
        page_per_song=True,
        export_mode="full",
    )
    slots = build_show_patch(project.songs, settings)
    plans = plans_from_show_patch(slots, settings)
    paths = Ma2Exporter().export_show_to_directory(plans, tmp_path, show_install_name="Show_Install")

    assert "show:plugin_xml" in paths
    assert "show:plugin_lua" in paths
    assert "show:macro_xml" in paths  # setup-only backup
    assert paths["show:plugin_xml"].name == "Show_Install_export.xml"
    assert paths["show:plugin_lua"].name == "Show_Install_export.lua"
    assert paths["show:macro_xml"].name == "Show_Install_install_macro.xml"

    lua = paths["show:plugin_lua"].read_text(encoding="utf-8")
    macro = paths["show:macro_xml"].read_text(encoding="utf-8")
    # CuePoints-style: Store main + buttons (no Import Sequence XML).
    assert 'Store Sequence 1 Cue 1 "ZhuGe"' in lua or "Store Sequence 1 Cue 1" in lua
    assert "Store Sequence" in lua and "Store Sequence" in macro
    assert 'Import "' not in macro  # setup-only — no TC/Seq Import
    assert "At Page 1.1.101" in lua
    assert "At Page 1.1.102" in lua
    assert "At Page 1.2.102" in lua
    assert "Assign Top Executor" in lua
    assert "SelectDrive 1" in lua
    assert "importexport" in lua
    assert 'Import "' in lua and "At Timecode" in lua
    # One Timecode Import per song (not one merged show TC).
    assert lua.count("At Timecode") == 2
    assert "Show_Install_TC_" in lua
    assert "At Timecode 1" in lua and "At Timecode 2" in lua
    # Song-relative FPS frames on the TC timeline (not hour+ absolute).
    assert 'time="108' not in lua
    assert "/Offset=1h" in lua
    assert 'Runs="Endless Repeat"' in lua
    assert 'SwitchOff="Keep Playbacks"' in lua
    assert 'StatusCall="Off"' in lua
    assert 'TimeUnit="1/100 Seconds"' not in lua
    assert '/TimeUnit="30 FPS"' in lua
    assert "/TimeUnit=0" not in lua
    assert "/Slot=1" in lua
    assert '/RecordMode="Go"' in lua
    assert 'record_mode="Go"' in lua
    assert 'frame_format="30 FPS"' in lua
    assert lua.count("/Offset=") == 2
    assert "<No>30</No><No>1</No><No>1</No><No>102</No>" in lua
    assert "<No>30</No><No>1</No><No>2</No><No>101</No>" in lua
    # Each song's tracks live in their own Timecode XML blob (not one combined).
    assert lua.count("<Timecode ") == 2
    assert 'command="Top"' in lua
    assert "ButtonPage 1" in lua and "ButtonPage 2" in lua
    assert "FaderPage 1" in lua
    # Honor user Button 起始 (102).
    assert plans[0].button_lanes[0].executor.endswith(".102")
    assert plans[1].button_lanes[0].executor == "2.102"
    # Per-song TC still written for timecode-only re-export / inspection.
    assert paths["SongA:timecode"].is_file()
    from cueplayer.exporters.xml_inspect import load_xml_root, xml_tag_local

    tc_a = load_xml_root(paths["SongA:timecode"])
    tc_el = next(el for el in tc_a.iter() if xml_tag_local(el.tag) == "Timecode")
    assert tc_el.get("frame_format") == "30 FPS"
    assert int(tc_el.get("lenght", "0")) < 10_000
    times = [
        int(ev.get("time", "0"))
        for ev in tc_a.iter()
        if xml_tag_local(ev.tag) == "Event"
    ]
    assert times and all(t < 10_000 for t in times)

    from xml.etree import ElementTree as ET

    def sequ_index(path) -> str:
        root = ET.parse(path).getroot()
        ns = {"ma": "http://schemas.malighting.de/grandma2/xml/MA"}
        sequ = root.find("ma:Sequ", ns)
        assert sequ is not None
        return sequ.get("index") or ""

    assert sequ_index(paths["SongA:main_sequence"]) == "0"
    assert sequ_index(paths["SongB:main_sequence"]) == "0"
    plugin_xml = paths["show:plugin_xml"].read_text(encoding="utf-8")
    assert 'luafile="Show_Install_export.lua"' in plugin_xml
    assert 'name="Show_Install"' in plugin_xml
