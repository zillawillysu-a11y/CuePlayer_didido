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
    assert slots[0].main_sequence == 1
    assert slots[1].main_sequence == 21
    assert slots[0].main_sequence_name == "SongA"
    assert [b.sequence_name for b in slots[0].buttons] == ["SongA_Hit", "SongA_Crash"]
    assert slots[1].main_sequence_name == "SongB"
    assert [b.executor for b in slots[1].buttons] == ["2.201", "2.202"]
    labels = sequence_chain_labels(slots)
    assert "SongA" in labels[0]
    assert "SongA_Hit" in labels[1]

    from cueplayer.exporters.show_patch import plans_from_show_patch

    plans = plans_from_show_patch(slots, settings)
    assert plans[0].profile.main_sequence_name == "SongA"
    assert plans[0].profile.timecode_name == "SongA"
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
    paths = Ma2Exporter().export_show_to_directory(
        plans,
        tmp_path,
        show_install_name="Show_Install",
        add_main_preset_cue=True,
        main_preset_cue_id=0.5,
    )

    assert "show:plugin_xml" in paths
    assert "show:plugin_lua" in paths
    assert "show:macro_xml" in paths  # setup-only backup
    assert paths["show:plugin_xml"].name == "Show_Install_export.xml"
    assert paths["show:plugin_lua"].name == "Show_Install_export.lua"
    assert paths["show:macro_xml"].name == "Show_Install_install_macro.xml"
    assert paths["show:song_list"].name == "Show_Install_Song_List.xml"
    assert paths["show:fixed_macros"].name == "Show_Install_Fixed_Macros.xml"
    assert paths["show:song_macros"].name == "Show_Install_Song_Macros.xml"
    assert paths["show:view_1"].name == "Show_Install_View_1.xml"
    assert paths["show:view_2"].name == "Show_Install_View_2.xml"

    song_list = paths["show:song_list"].read_text(encoding="utf-8")
    fixed_macros = paths["show:fixed_macros"].read_text(encoding="utf-8")
    song_macros = paths["show:song_macros"].read_text(encoding="utf-8")
    assert 'name="SHOW BEGIN"' not in song_list
    assert 'number="0" sub_number="5"' not in song_list
    assert 'name="CuePlayer Song List"' in song_list
    assert 'name="SongA"' in song_list and 'name="SongB"' in song_list
    assert 'Macro "SongA"' in song_list
    assert 'name="Page Change"' in fixed_macros
    assert 'name="Set Songviewbutton"' in fixed_macros
    assert "SetVar $songviewbutton = 1.20" in fixed_macros
    assert 'name="Page Change"' not in song_macros
    assert 'SetVar $song = "SongA"' in song_macros
    assert "SetVar $songbpm = 120" in song_macros
    assert 'Assign View $"song" At ViewButton $songviewbutton' in fixed_macros

    lua = paths["show:plugin_lua"].read_text(encoding="utf-8")
    macro = paths["show:macro_xml"].read_text(encoding="utf-8")
    # CuePoints-style: Store main + buttons (no Import Sequence XML).
    assert 'Store Sequence 1 Cue 1 "ZhuGe"' in lua or "Store Sequence 1 Cue 1" in lua
    assert 'Store Sequence 1 Cue 0.5 "Preset" /noconfirm' in lua
    assert 'Store Sequence 21 Cue 0.5 "Preset" /noconfirm' in lua
    assert 'name="SongA"' in lua
    assert 'name="SongA_TC"' not in lua
    assert 'Label Sequence 1 "SongA"' in lua
    assert 'Label Sequence 1 "SongA_Main"' not in lua
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
    assert "At Timecode 201" in lua and "At Timecode 202" in lua
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
    assert (
        'Import "Show_Install_Fixed_Macros" At Macro 101 /path="macros"'
        in lua
    )
    assert (
        'Import "Show_Install_Song_Macros" At Macro 201 /path="macros"'
        in lua
    )
    assert 'Import "Show_Install_Song_List" At Sequence 41' in lua
    assert 'Label Page 200 "CuePlayer Template Page"' in lua
    assert 'Assign Sequence 41 At Page 1.200.130' in lua
    assert 'Label Executor 200.130 "CuePlayer Song List"' in lua
    assert 'Import "Show_Install_View_1" At View 201' in lua
    assert 'Label View 201 "SongA"' in lua
    assert 'Import "Show_Install_View_2" At View 202' in lua
    assert 'Label View 202 "SongB"' in lua
    assert plans[0].profile.sequence_pool_start == 1
    assert plans[0].button_lanes[0].sequence_pool == 2
    assert plans[1].profile.sequence_pool_start == 21
    assert plans[1].button_lanes[0].sequence_pool == 22
    assert lua.rindex('Macro "Set Songviewbutton"') > lua.rindex("At Timecode")
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

    view_root = ET.parse(paths["show:view_1"]).getroot()
    ns = {"ma": "http://schemas.malighting.de/grandma2/xml/MA"}
    view = view_root.find("ma:View", ns)
    assert view is not None
    assert view.get("name") == "SongA"
    assert view.get("display_mask") == "4"
    widgets = view.findall("ma:Widget", ns)
    assert [widget.get("type") for widget in widgets] == [
        "454e4749",
        "454e4749",
        "53455155",
        "4d414352",
    ]
    assert widgets[1].get("scroll_offset") == "120"  # Effect starts at 201.
    assert widgets[1].get("anz_rows") == "5"
    assert widgets[1].get("anz_cols") == "16"
    assert widgets[2].get("scroll_index") == "0"

    view_2_root = ET.parse(paths["show:view_2"]).getroot()
    view_2 = view_2_root.find("ma:View", ns)
    assert view_2 is not None
    view_2_widgets = view_2.findall("ma:Widget", ns)
    assert view_2_widgets[1].get("scroll_offset") == "220"  # Next 100 slots.
    assert view_2_widgets[2].get("scroll_offset") == "20"  # Sequence 21 first.
    assert view_2_widgets[2].get("scroll_index") == "20"
    plugin_xml = paths["show:plugin_xml"].read_text(encoding="utf-8")
    assert 'luafile="Show_Install_export.lua"' in plugin_xml
    assert 'name="Show_Install"' in plugin_xml


def test_ma2_export_matches_selected_3960_library(tmp_path) -> None:
    from cueplayer.exporters.ma2 import Ma2Exporter
    from cueplayer.exporters.show_patch import build_show_patch, plans_from_show_patch

    project = Project.create("Show")
    project.songs = [
        _song_with_buttons("First", ma="First", button_names=["Hit"])
    ]
    settings = MaExportSettings(console="ma2", export_mode="full")
    plans = plans_from_show_patch(build_show_patch(project.songs, settings), settings)
    library = tmp_path / "gma2_V_3.9.60" / "importexport"
    paths = Ma2Exporter().export_show_to_directory(plans, library)

    plugin_xml = paths["show:plugin_xml"].read_text(encoding="utf-8")
    plugin_lua = paths["show:plugin_lua"].read_text(encoding="utf-8")
    song_list = paths["show:song_list"].read_text(encoding="utf-8")
    fixed_macros = paths["show:fixed_macros"].read_text(encoding="utf-8")
    song_macros = paths["show:song_macros"].read_text(encoding="utf-8")
    for text in (plugin_xml, plugin_lua, song_list, fixed_macros, song_macros):
        assert "3.9.60/MA.xsd" in text
        assert 'stream_vers="60"' in text


def test_ma2_show_components_can_be_disabled_independently(tmp_path) -> None:
    from cueplayer.exporters.ma2 import Ma2Exporter
    from cueplayer.exporters.show_patch import build_show_patch, plans_from_show_patch

    project = Project.create("Show")
    project.songs = [_song_with_buttons("First", ma="First", button_names=[])]
    settings = MaExportSettings(console="ma2", export_mode="full")
    plans = plans_from_show_patch(build_show_patch(project.songs, settings), settings)
    paths = Ma2Exporter().export_show_to_directory(
        plans,
        tmp_path,
        include_fixed_macros=False,
        include_song_macros=True,
        include_song_list=False,
        include_song_views=False,
        template_page=77,
        fixed_macro_start=100,
        song_macro_start=200,
    )

    assert "show:fixed_macros" not in paths
    assert "show:song_list" not in paths
    assert "show:song_macros" in paths
    lua = paths["show:plugin_lua"].read_text(encoding="utf-8")
    assert (
        'Import "CuePlayer_Show_Install_Song_Macros" At Macro 200 /path="macros"'
        in lua
    )
    assert "Song_List" not in lua
    assert "Template Page" not in lua
    assert "At View" not in lua
    assert 'Macro "Set Songviewbutton"' not in lua


def test_ma2_main_preset_cue_rejects_existing_cue_id(tmp_path) -> None:
    from cueplayer.exporters.ma2 import Ma2Exporter
    from cueplayer.exporters.show_patch import build_show_patch, plans_from_show_patch

    project = Project.create("Show")
    project.songs = [_song_with_buttons("First", ma="First", button_names=[])]
    settings = MaExportSettings(console="ma2", export_mode="full")
    plans = plans_from_show_patch(build_show_patch(project.songs, settings), settings)

    import pytest

    with pytest.raises(ValueError, match="Preset Cue ID 1.*conflicts"):
        Ma2Exporter().export_show_to_directory(
            plans,
            tmp_path,
            add_main_preset_cue=True,
            main_preset_cue_id=1,
        )


def test_ma2_song_view_matches_s1_pool_scrolls(tmp_path) -> None:
    from xml.etree import ElementTree as ET

    from cueplayer.exporters.ma2 import Ma2Exporter
    from cueplayer.exporters.show_patch import build_show_patch, plans_from_show_patch

    project = Project.create("Show")
    project.songs = [_song_with_buttons("Intro", ma="Intro", button_names=[])]
    settings = MaExportSettings(
        console="ma2",
        export_mode="full",
        sequence_pool_start=244,
    )
    plans = plans_from_show_patch(build_show_patch(project.songs, settings), settings)
    paths = Ma2Exporter().export_show_to_directory(
        plans,
        tmp_path,
        view_pool_start=200,
        effect_pool_start=305,
    )

    root = ET.parse(paths["show:view_1"]).getroot()
    ns = {"ma": "http://schemas.malighting.de/grandma2/xml/MA"}
    widgets = root.findall("ma:View/ma:Widget", ns)
    assert widgets[1].get("scroll_offset") == "224"
    assert widgets[2].get("scroll_offset") == "243"
    lua = paths["show:plugin_lua"].read_text(encoding="utf-8")
    assert 'Import "CuePlayer_Show_Install_View_1" At View 200' in lua
    assert 'Label View 200 "Intro"' in lua


def test_ma2_song_views_put_each_sequence_block_in_first_cell(tmp_path) -> None:
    from xml.etree import ElementTree as ET

    from cueplayer.exporters.ma2 import Ma2Exporter
    from cueplayer.exporters.show_patch import build_show_patch, plans_from_show_patch

    project = Project.create("Show")
    project.songs = [
        _song_with_buttons(f"Song {index}", ma=f"Song{index}", button_names=[])
        for index in range(1, 4)
    ]
    settings = MaExportSettings(console="ma2", sequence_pool_start=1)
    plans = plans_from_show_patch(build_show_patch(project.songs, settings), settings)
    paths = Ma2Exporter().export_show_to_directory(
        plans,
        tmp_path,
        effect_pool_start=201,
        effect_slots_per_song=100,
    )
    ns = {"ma": "http://schemas.malighting.de/grandma2/xml/MA"}

    assert [plan.profile.sequence_pool_start for plan in plans] == [1, 21, 41]
    for index, expected_scroll in enumerate((0, 20, 40), start=1):
        root = ET.parse(paths[f"show:view_{index}"]).getroot()
        widgets = root.findall("ma:View/ma:Widget", ns)
        assert widgets[2].get("scroll_offset") == str(expected_scroll)
        assert widgets[2].get("scroll_index") == str(expected_scroll)
        assert widgets[1].get("scroll_offset") == str(120 + (index - 1) * 100)


def test_ma2_song_view_uses_custom_screen3_geometry(tmp_path) -> None:
    from xml.etree import ElementTree as ET

    from cueplayer.exporters.ma2 import Ma2Exporter
    from cueplayer.exporters.show_patch import build_show_patch, plans_from_show_patch

    project = Project.create("Show")
    project.songs = [_song_with_buttons("Song", ma="Song", button_names=[])]
    settings = MaExportSettings(console="ma2")
    plans = plans_from_show_patch(build_show_patch(project.songs, settings), settings)
    layout = [{"type": "effects", "mode": "perSong", "x": 2, "y": 3, "w": 12, "h": 4, "start": 401, "stride": 120}]
    paths = Ma2Exporter().export_show_to_directory(plans, tmp_path, view_layout=layout)

    root = ET.parse(paths["show:view_1"]).getroot()
    widget = root.find("{http://schemas.malighting.de/grandma2/xml/MA}View/{http://schemas.malighting.de/grandma2/xml/MA}Widget")
    assert widget is not None
    assert widget.get("x") == "2"
    assert widget.get("y") == "3"
    assert widget.get("anz_cols") == "12"
    assert widget.get("anz_rows") == "4"


def test_ma2_song_view_exports_verified_poolall_widget_codes(tmp_path) -> None:
    from xml.etree import ElementTree as ET

    from cueplayer.exporters.ma2 import Ma2Exporter
    from cueplayer.exporters.show_patch import build_show_patch, plans_from_show_patch

    project = Project.create("Show")
    project.songs = [_song_with_buttons("Song", ma="Song", button_names=[])]
    settings = MaExportSettings(console="ma2")
    plans = plans_from_show_patch(build_show_patch(project.songs, settings), settings)
    layout = [
        {"type": pool_type, "mode": "fixed", "x": index, "y": 0, "w": 1, "h": 1, "start": 1, "stride": 1}
        for index, pool_type in enumerate(("camera", "filters", "forms", "groups", "images", "layout", "masks", "matricks", "pagesChannel", "pagesExec", "timecode", "timecodeSlots", "timer", "universes", "views", "worlds"))
    ]
    paths = Ma2Exporter().export_show_to_directory(plans, tmp_path, view_layout=layout)
    root = ET.parse(paths["show:view_1"]).getroot()
    namespace = "{http://schemas.malighting.de/grandma2/xml/MA}"
    types = [widget.get("type") for widget in root.findall(f"{namespace}View/{namespace}Widget")]
    assert types == [
        "43414d50", "46494c54", "464f524d", "47524f55", "494d4750", "4c415950",
        "5346494c", "4d415458", "50414743", "50414745", "54434f44", "54435350",
        "54494d50", "444d5850", "56494557", "57454c54",
    ]
