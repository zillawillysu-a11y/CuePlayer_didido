"""Show-wide MA Sequence / Fader patch allocation."""

from __future__ import annotations

import pytest

from cueplayer.domain.models import Mark, MaExportSettings, Project, Song
from cueplayer.exporters.show_patch import build_show_patch, pool_collisions, sequence_chain_labels


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
    assert [b.sequence_name for b in slots[0].buttons] == ["Hit", "Crash"]
    assert slots[1].main_sequence_name == "SongB"
    assert [b.executor for b in slots[1].buttons] == ["2.201", "2.202"]
    labels = sequence_chain_labels(slots)
    assert "SongA" in labels[0]
    assert "Hit" in labels[1]

    from cueplayer.exporters.show_patch import plans_from_show_patch

    plans = plans_from_show_patch(slots, settings)
    assert plans[0].profile.main_sequence_name == "SongA"
    assert plans[0].profile.timecode_name == "SongA"
    assert plans[0].profile.page_name == "SongA"
    assert plans[1].profile.page_name == "SongB"
    assert plans[1].profile.page == 2
    # Default start TC 01:00:00:00 → 3600s OffsetTCSlot
    assert abs(plans[0].profile.start_offset_seconds - 3600.0) < 1e-6


def test_ma3_sequence_pools_reserve_a_fixed_block_per_song() -> None:
    """Real-hardware feedback: MA3's Sequence pools used to pack tightly
    (no reserved gap between songs), unlike MA2 and unlike Effect/Group
    pools which already reserved a fixed per-song block on both consoles —
    Willy asked for MA3 to match that pattern too, so later manual edits
    (adding marks/buttons) don't require renumbering every song after it."""
    project = Project.create("Show")
    project.songs = [
        _song_with_buttons("第一首", ma="SongA", button_names=["Hit", "Crash"]),
        _song_with_buttons("第二首", ma="SongB", button_names=["Hit", "Crash"]),
    ]
    settings = MaExportSettings(
        console="ma3",
        sequence_pool_start=1,
        main_executor="1.101",
        button_executor_start="1.201",
        page_per_song=True,
        ma2_sequence_slots_per_song=20,
    )
    slots = build_show_patch(project.songs, settings)
    # SongA uses 3 slots (Main + 2 buttons) but reserves the full 20-slot
    # block, same as MA2 — SongB starts at 1 + 20 = 21, not 1 + 3 = 4.
    assert slots[0].main_sequence == 1
    assert slots[1].main_sequence == 21


def test_show_patch_can_export_only_selected_button_content(tmp_path) -> None:
    from cueplayer.exporters.ma2 import Ma2Exporter
    from cueplayer.exporters.xml_inspect import load_xml_root, xml_tag_local
    from cueplayer.exporters.show_patch import plans_from_show_patch

    song = _song_with_buttons("Song", ma="SongA", button_names=["Hit", "Crash"])
    settings = MaExportSettings(
        console="ma2",
        sequence_pool_start=201,
        main_executor="201.130",
        button_executor_start="201.101",
        export_content_by_song={song.id: {"main": False, "buttons": [3]}},
    )
    slots = build_show_patch([song], settings)
    slot = slots[0]
    assert slot.include_main is False
    assert slot.main_cue_count == 0
    assert slot.sequence_span == 1
    assert [button.lane_index for button in slot.buttons] == [3]
    assert slot.buttons[0].sequence == 201
    assert sequence_chain_labels(slots) == ["Seq 201 Crash (201.101)"]

    plan = plans_from_show_patch(slots, settings)[0]
    assert plan.main_cues == []
    assert plan.profile.include_main is False
    assert [lane.sequence_pool for lane in plan.button_lanes] == [201]

    paths = Ma2Exporter().export_to_directory(plan, tmp_path)
    assert "main_sequence" not in paths
    assert "button_sequence_3" in paths
    assert not any("_main.xml" in path.name for path in paths.values())
    root = load_xml_root(paths["timecode"])
    tracks = [element for element in root.iter() if xml_tag_local(element.tag) == "Track"]
    assert len(tracks) == 1
    assert tracks[0].get("index") == "0"
    assert tracks[0].find("{http://schemas.malighting.de/grandma2/xml/MA}Object").get("name") == "Crash"

    from cueplayer.exporters.ma3 import Ma3Exporter

    ma3_settings = MaExportSettings(
        console="ma3",
        sequence_pool_start=201,
        main_executor="201.130",
        button_executor_start="201.101",
        export_content_by_song={song.id: {"main": False, "buttons": [3]}},
    )
    ma3_plan = plans_from_show_patch(build_show_patch([song], ma3_settings), ma3_settings)[0]
    ma3_paths = Ma3Exporter().export_to_directory(ma3_plan, tmp_path / "ma3")
    assert "main_sequence" not in ma3_paths
    assert "button_sequence_3" in ma3_paths
    ma3_tc = load_xml_root(ma3_paths["timecode"])
    track_names = [element.get("Name") for element in ma3_tc.iter() if xml_tag_local(element.tag) == "Track"]
    assert track_names == ["Crash"]


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
    # Real grandMA3 Import syntax is "Import <Type> Library "<file>" At
    # <Type> <Pool>" — confirmed against MA Lighting's own documentation
    # (help.malighting.com/grandMA3 Import keyword page); the older
    # "Import Sequence <Pool> "<file>"" shape (no Library/At) silently
    # failed to land sequences at their intended pool on real hardware.
    assert any(c.startswith("Import Sequence Library") and "At Sequence" in c for c in commands)
    assert any(c.startswith("Import Timecode Library") and "At Timecode" in c for c in commands)
    assert sum(1 for c in commands if "Import Timecode" in c) == 2
    # Sequence/Timecode Name and every Timecode setting are already baked
    # as attributes on their own XML element — no "Label"/"Set Property"
    # command re-asserts them anymore (pure duplication, and it bloated a
    # many-song show's install macro).
    assert not any(cmd.startswith("Label Sequence") and "Cue" not in cmd for cmd in commands)
    assert not any(cmd.startswith("Label Timecode") for cmd in commands)
    assert not any("Property" in cmd for cmd in commands)

    # Main Sequence/Timecode use the bare song name (no "_Main"/"_TC"
    # suffix): the Song Change workflow's Page Change macro selects them by
    # exact name match against the $song global variable ("Select Sequence
    # $"song".", "Select Timecode $"song"."); a suffix here would make that
    # lookup never match on import. Baked straight into each XML file.
    main_seq_a = load_xml_root(paths["SongA:main_sequence"])
    seq_a = next(el for el in main_seq_a.iter() if xml_tag_local(el.tag) == "Sequence")
    assert seq_a.get("Name") == "SongA"
    tc_a = load_xml_root(paths["SongA:timecode"])
    tc_a_el = next(el for el in tc_a.iter() if xml_tag_local(el.tag) == "Timecode")
    assert tc_a_el.get("Name") == "SongA"
    assert tc_a_el.get("OffsetTCSlot") == "1h00m00.00"

    # The Song List Sequence and Song Change Macros files are Imported by
    # this same show install macro — writing them to disk isn't enough on
    # its own, MA3 only reads an explicit Import command.
    assert "show:song_list" in paths
    assert "show:fixed_macros" in paths
    assert "show:song_macros" in paths
    assert any(
        c.startswith("Import Sequence Library") and "CuePlayer_Song_List" in c
        for c in commands
    )
    assert any(
        c.startswith("Import Macro Library") and "CuePlayer_Fixed_Macros" in c
        for c in commands
    )
    assert any(
        c.startswith("Import Macro Library") and "CuePlayer_Song_Macros" in c
        for c in commands
    )


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
        song_list_sequence_pool=777,
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
    preset_timecode = Ma2Exporter().build_show_timecode_xml(
        [plans[0]], name="SongA", main_preset_cue_id=0.5
    )
    assert 'Cue name="Cue 1"><No>1</No><No>1</No><No>2</No>' in preset_timecode
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
    assert 'Import "Show_Install_Song_List" At Sequence 777' in lua
    assert 'Label Page 200 "CuePlayer Template Page"' in lua
    assert 'Assign Sequence 777 At Page 1.200.130' in lua
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
    assert widgets[1].get("scroll_offset") == "200"  # Effect starts at 201.
    assert widgets[1].get("anz_rows") == "5"
    assert widgets[1].get("anz_cols") == "16"
    assert widgets[2].get("scroll_index") == "0"

    view_2_root = ET.parse(paths["show:view_2"]).getroot()
    view_2 = view_2_root.find("ma:View", ns)
    assert view_2 is not None
    view_2_widgets = view_2.findall("ma:Widget", ns)
    assert view_2_widgets[1].get("scroll_offset") == "300"  # Next 100 slots.
    assert view_2_widgets[2].get("scroll_offset") == "20"  # Sequence 21 first.
    assert view_2_widgets[2].get("scroll_index") == "20"
    plugin_xml = paths["show:plugin_xml"].read_text(encoding="utf-8")
    assert 'luafile="Show_Install_export.lua"' in plugin_xml
    assert 'name="Show_Install"' in plugin_xml


def test_ma2_rejects_song_list_sequence_collision(tmp_path) -> None:
    from cueplayer.exporters.ma2 import Ma2Exporter
    from cueplayer.exporters.show_patch import build_show_patch, plans_from_show_patch

    project = Project.create("Show")
    settings = MaExportSettings(sequence_pool_start=1)
    plans = plans_from_show_patch(build_show_patch(project.songs, settings), settings)
    with pytest.raises(ValueError, match="Song List Sequence 1 conflicts"):
        Ma2Exporter().export_show_to_directory(
            plans, tmp_path, song_list_sequence_pool=1
        )


def test_ma2_export_matches_selected_3960_library(tmp_path) -> None:
    from cueplayer.exporters.ma2 import Ma2Exporter
    from cueplayer.exporters.show_patch import build_show_patch, plans_from_show_patch

    scanner_library = tmp_path / "gma2_V_3.9.60" / "importexport"
    scanner_paths = Ma2Exporter().write_live_scan_plugin(scanner_library)
    assert scanner_paths["plugin_xml"].is_file()
    scanner_xml = scanner_paths["plugin_xml"].read_text(encoding="utf-8")
    assert "CuePlayer Live Scan" in scanner_xml
    assert "3.9.60/MA.xsd" in scanner_xml
    assert "CUEPLAYER_SCAN_BEGIN" in scanner_paths["plugin_lua"].read_text(encoding="utf-8")

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
    assert widgets[1].get("scroll_offset") == "304"
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
        assert widgets[1].get("scroll_offset") == str(200 + (index - 1) * 100)


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
    assert widget.get("scroll_offset") == "400"  # MA2 displays scroll offset + 1.


def test_ma2_macro_widget_keeps_its_screen_position_with_fixed_start_scroll(tmp_path) -> None:
    from xml.etree import ElementTree as ET

    from cueplayer.exporters.ma2 import Ma2Exporter
    from cueplayer.exporters.show_patch import build_show_patch, plans_from_show_patch

    project = Project.create("Show")
    project.songs = [_song_with_buttons("Song", ma="Song", button_names=[])]
    settings = MaExportSettings(console="ma2")
    plans = plans_from_show_patch(build_show_patch(project.songs, settings), settings)
    layout = [
        {"type": "sequence", "mode": "perSong", "x": 0, "y": 0, "w": 10, "h": 1, "start": 201, "stride": 20},
        {"type": "macros", "mode": "fixed", "x": 10, "y": 0, "w": 6, "h": 1, "start": 191, "stride": 1},
    ]
    paths = Ma2Exporter().export_show_to_directory(plans, tmp_path, view_layout=layout)
    root = ET.parse(paths["show:view_1"]).getroot()
    namespace = "{http://schemas.malighting.de/grandma2/xml/MA}"
    widgets = root.findall(f"{namespace}View/{namespace}Widget")
    macro = next(widget for widget in widgets if widget.get("type") == "4d414352")
    sequence = next(widget for widget in widgets if widget.get("type") == "53455155")
    assert sequence.get("index") == "2"
    assert sequence.get("x") is None
    assert macro.get("index") == "3"
    assert macro.get("x") == "10"
    assert macro.get("y") is None
    assert macro.get("has_focus") == "true"
    assert macro.get("has_scrollfocus") == "true"
    assert macro.get("scroll_offset") == "190"
    assert macro.get("scroll_index") == "190"
    # MA2's importer requires the native-export attribute order.  In
    # particular, x must precede the widget size for Macro placement to apply.
    text = paths["show:view_1"].read_text(encoding="utf-8")
    assert (
        'type="4d414352" display_nr="2" has_focus="true" '
        'has_scrollfocus="true" x="10" anz_rows="1" anz_cols="6" '
        'scroll_offset="190" scroll_index="190"'
    ) in text


def test_ma2_widget_with_nonzero_x_is_focusable_for_native_placement(tmp_path) -> None:
    from xml.etree import ElementTree as ET

    from cueplayer.exporters.ma2 import Ma2Exporter
    from cueplayer.exporters.show_patch import build_show_patch, plans_from_show_patch

    project = Project.create("Show")
    project.songs = [_song_with_buttons("Song", ma="Song", button_names=[])]
    settings = MaExportSettings(console="ma2")
    plans = plans_from_show_patch(build_show_patch(project.songs, settings), settings)
    layout = [
        {"type": "sequence", "mode": "perSong", "x": 11, "y": 1, "w": 5, "h": 1, "start": 201, "stride": 20},
        {"type": "matricks", "mode": "fixed", "x": 12, "y": 0, "w": 4, "h": 1, "start": 1, "stride": 1},
    ]
    paths = Ma2Exporter().export_show_to_directory(plans, tmp_path, view_layout=layout)
    root = ET.parse(paths["show:view_1"]).getroot()
    namespace = "{http://schemas.malighting.de/grandma2/xml/MA}"
    widgets = root.findall(f"{namespace}View/{namespace}Widget")
    sequence = next(widget for widget in widgets if widget.get("type") == "53455155")
    matricks = next(widget for widget in widgets if widget.get("type") == "4d415458")
    assert sequence.get("x") == "11"
    assert sequence.get("has_focus") == "true"
    assert matricks.get("x") == "12"
    assert matricks.get("has_focus") == "true"


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
    widgets = root.findall(f"{namespace}View/{namespace}Widget")
    types = [widget.get("type") for widget in widgets]
    assert types == [
        "43414d50", "46494c54", "464f524d", "47524f55", "494d4750", "4c415950",
        "5346494c", "4d415458", "50414743", "50414745", "54434f44", "54435350",
        "54494d50", "444d5850", "56494557", "57454c54",
    ]
    assert [widget.get("index") for widget in widgets] == [str(index) for index in range(16)]
    assert all(widget.get("scroll_offset") is None for widget in widgets)
    assert all(widget.get("has_focus") == "true" for widget in widgets[1:])
    assert all(widget.get("has_scrollfocus") == "true" for widget in widgets[1:])


def test_ma2_per_song_auxiliary_pool_keeps_its_song_scroll_range(tmp_path) -> None:
    from xml.etree import ElementTree as ET

    from cueplayer.exporters.ma2 import Ma2Exporter
    from cueplayer.exporters.show_patch import build_show_patch, plans_from_show_patch

    project = Project.create("Show")
    project.songs = [
        _song_with_buttons("SongA", ma="SongA", button_names=[]),
        _song_with_buttons("SongB", ma="SongB", button_names=[]),
    ]
    settings = MaExportSettings(console="ma2")
    plans = plans_from_show_patch(build_show_patch(project.songs, settings), settings)
    layout = [
        {"type": "camera", "mode": "perSong", "x": 3, "y": 0, "w": 2, "h": 1, "start": 1, "stride": 10},
        {"type": "groups", "mode": "fixed", "x": 6, "y": 0, "w": 2, "h": 1, "start": 41, "stride": 1},
        {"type": "macros", "mode": "fixed", "x": 10, "y": 0, "w": 2, "h": 1, "start": 191, "stride": 1},
    ]
    paths = Ma2Exporter().export_show_to_directory(plans, tmp_path, view_layout=layout)
    root = ET.parse(paths["show:view_2"]).getroot()
    namespace = "{http://schemas.malighting.de/grandma2/xml/MA}"
    widgets = root.findall(f"{namespace}View/{namespace}Widget")
    camera = next(widget for widget in widgets if widget.get("type") == "43414d50")
    groups = next(widget for widget in widgets if widget.get("type") == "47524f55")
    macros = next(widget for widget in widgets if widget.get("type") == "4d414352")
    assert camera.get("scroll_offset") == "10"
    assert camera.get("scroll_index") == "10"
    assert groups.get("scroll_offset") == "40"
    assert groups.get("scroll_index") == "40"
    assert macros.get("scroll_offset") == "190"
    assert macros.get("scroll_index") == "190"


def test_manual_pool_override_pins_one_song_without_shifting_others() -> None:
    project = Project.create("Show")
    project.songs = [
        _song_with_buttons(f"Song{i}", ma=f"Song{i}", button_names=[]) for i in range(1, 4)
    ]
    settings = MaExportSettings(
        console="ma2",
        sequence_pool_start=1,
        timecode_pool_start=201,
        ma2_effect_pool_start=201,
        ma2_effect_slots_per_song=100,
        ma2_group_pool_start=1,
        ma2_group_slots_per_song=20,
        ma2_view_pool_start=201,
        ma2_song_macro_start=201,
        ma2_pool_overrides={
            project.songs[1].id: {
                "sequence": 900,
                "effects": 950,
                "groups": 30,
                "timecode": 500,
                "view": 600,
                "song_macro": 700,
            }
        },
    )
    slots = build_show_patch(project.songs, settings)

    # Song 2 (overridden) uses the manual numbers.
    assert slots[1].main_sequence == 900
    assert slots[1].effect_start == 950
    assert slots[1].group_start == 30
    assert slots[1].timecode_pool == 500
    assert slots[1].view_pool == 600
    assert slots[1].song_macro_pool == 700

    # Song 1 and Song 3 land exactly where they would if Song 2 had never
    # been overridden — the counter advances by each song's *default*
    # width regardless of any override, so overriding one song never
    # reshuffles anyone else's numbers.
    assert slots[0].main_sequence == 1
    assert slots[2].main_sequence == 41  # 1 + Song1's 20 + Song2's default 20
    assert slots[0].timecode_pool == 201
    assert slots[2].timecode_pool == 203  # 201, 202 (Song2 default), 203
    assert slots[0].effect_start == 201
    assert slots[2].effect_start == 401  # row-index formula: 201 + 2*100
    assert slots[0].view_pool == 201
    assert slots[2].view_pool == 203  # row-index formula: 201 + 2
    assert slots[0].song_macro_pool == 201
    assert slots[2].song_macro_pool == 203  # row-index formula: 201 + 2


def test_manual_sequence_override_carries_its_buttons_along() -> None:
    project = Project.create("Show")
    project.songs = [_song_with_buttons("Song", ma="Song", button_names=["Hit", "Crash"])]
    settings = MaExportSettings(
        console="ma2",
        sequence_pool_start=1,
        ma2_pool_overrides={project.songs[0].id: {"sequence": 500}},
    )
    slots = build_show_patch(project.songs, settings)
    assert slots[0].main_sequence == 500
    # Buttons stay relative to the overridden Main, not the raw counter.
    assert [b.sequence for b in slots[0].buttons] == [501, 502]


def test_pool_collisions_flags_overlapping_songs() -> None:
    project = Project.create("Show")
    project.songs = [
        _song_with_buttons("SongA", ma="SongA", button_names=[]),
        _song_with_buttons("SongB", ma="SongB", button_names=[]),
        _song_with_buttons("SongC", ma="SongC", button_names=[]),
    ]
    settings = MaExportSettings(
        console="ma2",
        sequence_pool_start=1,
        ma2_sequence_slots_per_song=20,
        ma2_pool_overrides={
            # Song B's Sequence override lands inside Song C's default range.
            project.songs[1].id: {"sequence": 41},
        },
    )
    slots = build_show_patch(project.songs, settings)
    collisions = pool_collisions(slots, settings)

    assert collisions["sequence"] == {project.songs[1].id, project.songs[2].id}
    assert collisions["timecode"] == set()
    assert collisions["effects"] == set()


def test_pool_collisions_empty_when_no_overlap() -> None:
    project = Project.create("Show")
    project.songs = [
        _song_with_buttons("SongA", ma="SongA", button_names=[]),
        _song_with_buttons("SongB", ma="SongB", button_names=[]),
    ]
    settings = MaExportSettings(console="ma2")
    slots = build_show_patch(project.songs, settings)
    collisions = pool_collisions(slots, settings)
    assert all(not ids for ids in collisions.values())


def test_ma2_view_and_effects_pool_overrides_change_real_export(tmp_path) -> None:
    from cueplayer.exporters.ma2 import Ma2Exporter
    from cueplayer.exporters.show_patch import plans_from_show_patch
    from xml.etree import ElementTree as ET

    project = Project.create("Show")
    project.songs = [
        _song_with_buttons("SongA", ma="SongA", button_names=[]),
        _song_with_buttons("SongB", ma="SongB", button_names=[]),
    ]
    settings = MaExportSettings(
        console="ma2",
        ma2_pool_overrides={project.songs[1].id: {"view": 900, "effects": 950}},
    )
    plans = plans_from_show_patch(build_show_patch(project.songs, settings), settings)
    paths = Ma2Exporter().export_show_to_directory(
        plans,
        tmp_path,
        view_pool_start=201,
        effect_pool_start=201,
        effect_slots_per_song=100,
        pool_overrides=settings.ma2_pool_overrides,
    )

    lua = paths["show:plugin_lua"].read_text(encoding="utf-8")
    assert "At View 900" in lua
    assert 'Label View 900 "SongB"' in lua
    assert "At View 202" not in lua  # the un-overridden default for song 2

    root = ET.parse(paths["show:view_2"]).getroot()
    ns = {"ma": "http://schemas.malighting.de/grandma2/xml/MA"}
    effects_widget = root.findall("ma:View/ma:Widget", ns)[1]
    assert effects_widget.get("scroll_offset") == "949"  # 950 - 1


def test_ma2_song_macro_override_splits_into_per_song_imports(tmp_path) -> None:
    from cueplayer.exporters.ma2 import Ma2Exporter
    from cueplayer.exporters.show_patch import plans_from_show_patch

    project = Project.create("Show")
    project.songs = [
        _song_with_buttons("SongA", ma="SongA", button_names=[]),
        _song_with_buttons("SongB", ma="SongB", button_names=[]),
        _song_with_buttons("SongC", ma="SongC", button_names=[]),
    ]
    settings = MaExportSettings(
        console="ma2",
        ma2_pool_overrides={project.songs[1].id: {"song_macro": 700}},
    )
    plans = plans_from_show_patch(build_show_patch(project.songs, settings), settings)
    paths = Ma2Exporter().export_show_to_directory(
        plans,
        tmp_path,
        song_macro_start=201,
        pool_overrides=settings.ma2_pool_overrides,
    )

    assert "show:song_macros" not in paths  # split path, not the combined file
    assert paths["show:song_macro_1"].name == "CuePlayer_Show_Install_Song_Macro_1.xml"
    assert paths["show:song_macro_2"].name == "CuePlayer_Show_Install_Song_Macro_2.xml"
    assert paths["show:song_macro_3"].name == "CuePlayer_Show_Install_Song_Macro_3.xml"

    lua = paths["show:plugin_lua"].read_text(encoding="utf-8")
    assert 'Import "CuePlayer_Show_Install_Song_Macro_1" At Macro 201 /path="macros"' in lua
    assert 'Import "CuePlayer_Show_Install_Song_Macro_2" At Macro 700 /path="macros"' in lua
    assert 'Import "CuePlayer_Show_Install_Song_Macro_3" At Macro 203 /path="macros"' in lua
    assert 'At Macro 202 /path="macros"' not in lua  # song 3's un-overridden default


def test_ma2_song_macro_without_overrides_keeps_the_combined_import(tmp_path) -> None:
    """Backward compatibility: no override at all must still be one Import."""
    from cueplayer.exporters.ma2 import Ma2Exporter
    from cueplayer.exporters.show_patch import plans_from_show_patch

    project = Project.create("Show")
    project.songs = [
        _song_with_buttons("SongA", ma="SongA", button_names=[]),
        _song_with_buttons("SongB", ma="SongB", button_names=[]),
    ]
    settings = MaExportSettings(console="ma2")
    plans = plans_from_show_patch(build_show_patch(project.songs, settings), settings)
    paths = Ma2Exporter().export_show_to_directory(
        plans, tmp_path, song_macro_start=201, pool_overrides={}
    )

    assert "show:song_macros" in paths
    assert "show:song_macro_1" not in paths
    lua = paths["show:plugin_lua"].read_text(encoding="utf-8")
    assert 'Import "CuePlayer_Show_Install_Song_Macros" At Macro 201 /path="macros"' in lua


def _scanned(**kw) -> dict[str, int]:
    base = {"sequence": 508, "effect": 7998, "timecode": 37,
            "macro": 361, "view": 249, "group": 402}
    base.update(kw)
    return base


def test_start_after_scanned_clears_every_scanned_pool_maximum() -> None:
    """With the toggle on, no song may land on a number the console already
    uses — for any of the six Pool types."""
    project = Project.create("Show")
    project.songs = [
        _song_with_buttons(f"S{i}", ma=f"S{i}", button_names=[]) for i in range(1, 4)
    ]
    scanned = _scanned()
    settings = MaExportSettings(
        console="ma2",
        sequence_pool_start=201,
        timecode_pool_start=201,
        ma2_effect_pool_start=201,
        ma2_group_pool_start=201,
        ma2_view_pool_start=201,
        ma2_song_macro_start=201,
        ma2_scanned_pool_max=scanned,
        ma2_start_after_scanned=True,
    )
    slots = build_show_patch(project.songs, settings)

    assert all(slot.main_sequence > scanned["sequence"] for slot in slots)
    assert all(slot.effect_start > scanned["effect"] for slot in slots)
    assert all(slot.group_start > scanned["group"] for slot in slots)
    assert all(slot.timecode_pool > scanned["timecode"] for slot in slots)
    assert all(slot.view_pool > scanned["view"] for slot in slots)
    assert all(slot.song_macro_pool > scanned["macro"] for slot in slots)
    # First song starts exactly one past the scanned maximum.
    assert slots[0].main_sequence == scanned["sequence"] + 1
    assert slots[0].group_start == scanned["group"] + 1


def test_start_after_scanned_off_is_a_plain_export() -> None:
    """Toggle off must behave exactly as if no scan had ever happened."""
    project = Project.create("Show")
    project.songs = [_song_with_buttons("S", ma="S", button_names=[])]
    common = dict(
        console="ma2",
        sequence_pool_start=201,
        ma2_group_pool_start=201,
        ma2_scanned_pool_max=_scanned(),
    )
    off = build_show_patch(project.songs, MaExportSettings(**common, ma2_start_after_scanned=False))
    never_scanned = build_show_patch(
        project.songs,
        MaExportSettings(console="ma2", sequence_pool_start=201, ma2_group_pool_start=201),
    )
    assert off[0].main_sequence == never_scanned[0].main_sequence == 201
    assert off[0].group_start == never_scanned[0].group_start == 201


def test_manual_pin_wins_in_both_start_after_scanned_states() -> None:
    """A pin is a deliberate manual choice, so it must survive switching the
    toggle off rather than snapping back to the configured start. (Ticking
    the toggle clears pre-existing pins — that happens in the UI, see
    ShowPatchPage._on_start_after_scanned_toggled.)"""
    project = Project.create("Show")
    project.songs = [_song_with_buttons("S", ma="S", button_names=[])]
    settings = MaExportSettings(
        console="ma2",
        sequence_pool_start=201,
        ma2_scanned_pool_max=_scanned(),
        ma2_start_after_scanned=True,
        ma2_pool_overrides={project.songs[0].id: {"sequence": 700, "groups": 800}},
    )
    assert build_show_patch(project.songs, settings)[0].main_sequence == 700
    assert build_show_patch(project.songs, settings)[0].group_start == 800

    settings.ma2_start_after_scanned = False
    assert build_show_patch(project.songs, settings)[0].main_sequence == 700
    assert build_show_patch(project.songs, settings)[0].group_start == 800


def test_start_after_scanned_never_lowers_a_configured_start() -> None:
    """A configured start already past the scan must not be dragged back."""
    project = Project.create("Show")
    project.songs = [_song_with_buttons("S", ma="S", button_names=[])]
    settings = MaExportSettings(
        console="ma2",
        sequence_pool_start=9000,
        ma2_scanned_pool_max=_scanned(),
        ma2_start_after_scanned=True,
    )
    assert build_show_patch(project.songs, settings)[0].main_sequence == 9000


def test_start_after_scanned_is_inert_without_scan_data() -> None:
    project = Project.create("Show")
    project.songs = [_song_with_buttons("S", ma="S", button_names=[])]
    settings = MaExportSettings(
        console="ma2", sequence_pool_start=201, ma2_start_after_scanned=True
    )
    assert build_show_patch(project.songs, settings)[0].main_sequence == 201


def test_start_after_scanned_also_moves_page() -> None:
    """Page is a Pool too: the toggle must keep new Pages off ones MA2
    already has, just like Sequence/Effects/Groups/Timecode/View/Macro."""
    project = Project.create("Show")
    project.songs = [
        _song_with_buttons(f"S{i}", ma=f"S{i}", button_names=[]) for i in range(1, 3)
    ]
    settings = MaExportSettings(
        console="ma2",
        main_executor="1.101",
        ma2_scanned_pool_max=_scanned(page=12),
        ma2_start_after_scanned=True,
    )
    slots = build_show_patch(project.songs, settings)
    assert slots[0].page == 13
    assert slots[1].page == 14


def test_page_override_pins_one_song_page() -> None:
    project = Project.create("Show")
    project.songs = [
        _song_with_buttons("SongA", ma="SongA", button_names=[]),
        _song_with_buttons("SongB", ma="SongB", button_names=[]),
    ]
    settings = MaExportSettings(
        console="ma2",
        main_executor="1.101",
        ma2_pool_overrides={project.songs[0].id: {"page": 50}},
    )
    slots = build_show_patch(project.songs, settings)
    assert slots[0].page == 50
    # The other song's Page is untouched by the override.
    assert slots[1].page == 2


def test_page_override_flows_into_the_real_export_plan() -> None:
    """The exported plan.profile.page must match the overridden slot.page
    exactly, since button_executor_start embeds the Page number."""
    from cueplayer.exporters.show_patch import plans_from_show_patch

    project = Project.create("Show")
    project.songs = [_song_with_buttons("SongA", ma="SongA", button_names=["Hit"])]
    settings = MaExportSettings(
        console="ma2",
        main_executor="1.101",
        button_executor_start="1.201",
        ma2_pool_overrides={project.songs[0].id: {"page": 77}},
    )
    slots = build_show_patch(project.songs, settings)
    plans = plans_from_show_patch(slots, settings)
    assert slots[0].page == 77
    assert plans[0].profile.page == 77


def test_pool_collisions_flags_overlapping_page_when_page_per_song() -> None:
    project = Project.create("Show")
    project.songs = [
        _song_with_buttons("SongA", ma="SongA", button_names=[]),
        _song_with_buttons("SongB", ma="SongB", button_names=[]),
    ]
    settings = MaExportSettings(
        console="ma2",
        main_executor="1.101",
        page_per_song=True,
        ma2_pool_overrides={project.songs[1].id: {"page": 1}},
    )
    slots = build_show_patch(project.songs, settings)
    collisions = pool_collisions(slots, settings)
    assert collisions["page"] == {project.songs[0].id, project.songs[1].id}


def test_pool_collisions_page_empty_when_sharing_one_page_by_design() -> None:
    """page_per_song=False means every song is meant to share one Page —
    that is not a collision."""
    project = Project.create("Show")
    project.songs = [
        _song_with_buttons("SongA", ma="SongA", button_names=[]),
        _song_with_buttons("SongB", ma="SongB", button_names=[]),
    ]
    settings = MaExportSettings(console="ma2", main_executor="1.101", page_per_song=False)
    slots = build_show_patch(project.songs, settings)
    assert slots[0].page == slots[1].page
    collisions = pool_collisions(slots, settings)
    assert collisions["page"] == set()
