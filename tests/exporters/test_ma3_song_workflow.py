"""MA3 Song List Sequence + Song Change Macros (shared song-navigation
workflow) — mirrors the already-working MA2 song_list/song_change_macros
pair, in MA3's SetGlobalVariable/MacroLine syntax."""

from __future__ import annotations

from pathlib import Path

from cueplayer.exporters.common import ExportCue, MaExportProfile, SongExportPlan
from cueplayer.exporters.ma3 import Ma3Exporter
from cueplayer.exporters.xml_inspect import load_xml_root, xml_tag_local


def _plan(name: str, *, bpm: float = 120.0, mode: str = "full") -> SongExportPlan:
    return SongExportPlan(
        song_name=name,
        profile=MaExportProfile(
            console="ma3",
            fps=30.0,
            page=1,
            page_name=name,
            sequence_pool_start=1,
            main_executor="1.101",
            export_mode=mode,  # type: ignore[arg-type]
            # Bare song name (matches show_patch.py's real MA3 wiring,
            # which build_export_plan()/plans_from_show_patch() do
            # automatically) — this helper builds the plan directly, so
            # it must set it explicitly to test the real shape.
            main_sequence_name=name,
        ),
        song_bpm=bpm,
    )


def _macro_lines(macro_el) -> list[tuple[str, bool]]:
    return [
        (line.get("Command"), line.get("Enabled") != "No")
        for line in macro_el
        if xml_tag_local(line.tag) == "MacroLine"
    ]


def test_song_list_sequence_has_one_cue_per_song_with_no_extra_data(tmp_path: Path) -> None:
    plans = [_plan("Rarely Think of It"), _plan("Remains in Our Blood")]
    path = tmp_path / "song_list.xml"

    Ma3Exporter().write_song_list_sequence(plans, path, name="CuePlayer_Song_List")

    root = load_xml_root(path)
    assert xml_tag_local(root.tag) == "GMA3"
    sequence = next(el for el in root if xml_tag_local(el.tag) == "Sequence")
    assert sequence.get("Name") == "CuePlayer_Song_List"

    cues = [el for el in sequence if xml_tag_local(el.tag) == "Cue"]
    names = [cue.get("Name") for cue in cues]
    assert names == ["OffCue", "CueZero", "Rarely Think of It", "Remains in Our Blood"]

    song_cues = cues[2:]
    assert [c.get("No") for c in song_cues] == ["  1", "  2"]
    for cue, plan in zip(song_cues, plans):
        part = next(el for el in cue if xml_tag_local(el.tag) == "Part")
        assert part.get("Command") == f'Macro "{plan.song_name}"'
        assert part.get("Name") == plan.song_name

    # Willy's decision: no Recipe/Preset/DependencyExport data — that's
    # console-specific show data (tied to his own Group 72) this exporter
    # has no way to generate generically. A bare Command is enough to import.
    all_tags = {xml_tag_local(el.tag) for el in root.iter()}
    assert "Recipe" not in all_tags
    assert "Preset" not in all_tags
    assert "DependencyExport" not in all_tags


def test_song_change_macros_fixed_definitions_match_reference(tmp_path: Path) -> None:
    plans = [_plan("Rarely Think of It", bpm=93.0)]
    path = tmp_path / "song_change.xml"

    Ma3Exporter().write_song_change_macros(
        plans, path, song_list_name="CuePlayer_Song_List", include_songs=False
    )

    root = load_xml_root(path)
    macros = {m.get("Name"): m for m in root if xml_tag_local(m.tag) == "Macro"}
    assert set(macros) == {
        "Showbegin", "Go To Template Page", "Go To Song Page",
        "Jump To Song", "Previous Song", "Next Song", "Page Change",
        "Set Songviewbutton",
    }

    assert _macro_lines(macros["Showbegin"]) == [
        ("ClearAll", True),
        ('Top Sequence "*CuePlayer_Song_List"', True),
    ]
    assert _macro_lines(macros["Go To Template Page"]) == [
        ('Page "*Template Page"', True),
    ]
    # Matches the reference exactly: this line is disabled by default.
    assert _macro_lines(macros["Go To Song Page"]) == [('Page $"Song"', False)]
    assert _macro_lines(macros["Jump To Song"]) == [
        ('Load Sequence "*CuePlayer_Song_List"', True),
    ]
    assert _macro_lines(macros["Previous Song"]) == [
        ('Go- Sequence "*CuePlayer_Song_List"', True),
    ]
    assert _macro_lines(macros["Next Song"]) == [
        ('Go+ Sequence "*CuePlayer_Song_List"', True),
    ]
    assert _macro_lines(macros["Page Change"]) == [
        ('Page $"song"', True),
        ("Off Sequence 201 Thru", True),
        ("Off Timecode 1 Thru", True),
        ("<<< Timecode 1 Thru", True),
        ('Select Sequence $"song".', True),
        ("Goto Cue 0.5", True),
        ('Assign View $"song" At ViewButton $"songviewbutton"', True),
        ("Master 3.1 At BPM $songbpm", True),
        ('Select Timecode $"song"', True),
        ('Go+ Timecode $"song"', True),
    ]
    assert _macro_lines(macros["Set Songviewbutton"]) == [
        ('SetGlobalVariable "songviewbutton" "1.20"', True),
    ]


def test_song_change_macros_per_song_definitions(tmp_path: Path) -> None:
    plans = [
        _plan("Rarely Think of It", bpm=93.0),
        _plan("Remains in Our Blood", bpm=120.0),
    ]
    path = tmp_path / "song_change.xml"

    Ma3Exporter().write_song_change_macros(plans, path, include_fixed=False)

    root = load_xml_root(path)
    macros = {m.get("Name"): m for m in root if xml_tag_local(m.tag) == "Macro"}
    assert list(macros) == ["Rarely Think of It", "Remains in Our Blood"]

    assert _macro_lines(macros["Rarely Think of It"]) == [
        ('SetGlobalVariable "song" "Rarely Think of It"', True),
        ('SetGlobalVariable "songbpm" "93"', True),
        ('Macro "PAGE CHANGE"', True),
    ]
    assert _macro_lines(macros["Remains in Our Blood"]) == [
        ('SetGlobalVariable "song" "Remains in Our Blood"', True),
        ('SetGlobalVariable "songbpm" "120"', True),
        ('Macro "PAGE CHANGE"', True),
    ]


def test_export_show_to_directory_accepts_show_name_and_writes_song_workflow(
    tmp_path: Path,
) -> None:
    """Regression test for the TypeError bug: the UI's MA3 export call site
    already passes show_name=, which the old signature rejected."""
    plans = [_plan("Rarely Think of It"), _plan("Remains in Our Blood")]

    paths = Ma3Exporter().export_show_to_directory(
        plans, tmp_path, show_name="CuePlayer"
    )

    assert "show:macro" in paths
    assert "show:song_list" in paths
    assert "show:fixed_macros" in paths
    assert "show:song_macros" in paths
    assert paths["show:song_list"].is_file()
    assert paths["show:fixed_macros"].is_file()
    assert paths["show:song_macros"].is_file()

    # Writing the files to disk is not enough on its own — real hardware
    # confirmed none of them get imported unless the show install macro
    # also carries an explicit Import command for each.
    root = load_xml_root(paths["show:macro"])
    commands = [
        line.get("Command", "")
        for line in root.iter()
        if xml_tag_local(line.tag) == "MacroLine"
    ]
    assert any(
        c.startswith("Import Sequence Library") and paths["show:song_list"].name in c
        for c in commands
    )
    assert any(
        c.startswith("Import Macro Library") and paths["show:fixed_macros"].name in c
        for c in commands
    )
    assert any(
        c.startswith("Import Macro Library") and paths["show:song_macros"].name in c
        for c in commands
    )
    # Fixed and per-song macros land at independent, separately
    # configurable starting positions — real hardware feedback: Willy has
    # a dedicated field for this and expects it honored, not one combined
    # block starting from a single hardcoded position.
    fixed_import = next(c for c in commands if paths["show:fixed_macros"].name in c)
    song_import = next(c for c in commands if paths["show:song_macros"].name in c)
    assert fixed_import.endswith("At Macro 101")
    assert song_import.endswith("At Macro 201")
    # Song List gets assigned to a fader — importing the pool object alone
    # left it with no way to trigger it from the console. Its Name is
    # already baked into the Song List XML, so no Label command is needed;
    # real hardware rejected "Label Executor ..." as an "Illegal object"
    # when that was tried instead.
    assert any(
        c.startswith("Assign Sequence") and "At Page 200.130" in c for c in commands
    )
    assert not any(c.startswith("Label Executor") for c in commands)
    assert not any(c.startswith("Label Sequence") and "Song_List" in c for c in commands)


def test_install_commands_use_the_real_grandma3_import_syntax(tmp_path: Path) -> None:
    """Regression test for the real-hardware bug report: the old
    "Import Sequence <Pool> "<file>"" shape (no Library/At) doesn't match
    grandMA3's actual Import keyword syntax and silently failed to place
    sequences at their intended pool, instead landing wherever MA3 chose."""
    plan = _plan("Rarely Think of It")
    commands = Ma3Exporter().install_commands_for_plan(plan)

    seq_import = next(c for c in commands if c.startswith("Import Sequence Library"))
    assert seq_import.startswith('Import Sequence Library "')
    assert " At Sequence 1" in seq_import

    tc_import = next(c for c in commands if c.startswith("Import Timecode Library"))
    assert tc_import.startswith('Import Timecode Library "')
    assert " At Timecode" in tc_import


def test_install_commands_do_not_label_individual_cues(tmp_path: Path) -> None:
    """Willy's real-hardware feedback: a Label-Sequence-Cue-after-Import
    approach was not reliable (only the Preset cue picked up its name; the
    real note-driven cues never did). Cue names now come purely from the
    exported Sequence XML (write_main_sequence bakes Cue/@Name + Part/@Name)
    — install_commands_for_plan must not emit any per-cue Label command."""
    plan = _plan("Rarely Think of It")
    plan.main_cues = [
        ExportCue(1, "Verse", ma_export_name="Verse", time_seconds=1.0),
        ExportCue(2, "Chorus", ma_export_name="Chorus", time_seconds=2.0),
        ExportCue(3, "Cue 3", time_seconds=3.0),
    ]

    commands = Ma3Exporter().install_commands_for_plan(plan)

    assert not any(c.startswith("Label Sequence 1 Cue ") for c in commands)
    # Sequence Name is baked into the XML itself (write_main_sequence) —
    # no "Label Sequence" command for it at all anymore.
    assert not any(c.startswith("Label Sequence 1 ") for c in commands)

    # No leftover suffix on the name real Page Change needs to match by
    # exact name against the $song global variable.
    assert plan.profile.main_sequence_name == "Rarely Think of It"
    assert not any("_Main" in c for c in commands)


def test_main_sequence_bakes_cue_and_part_names_matching_reference_shape(
    tmp_path: Path,
) -> None:
    """Matches the real onPC-exported reference (CUESONGCLAUDE.xml) Willy
    provided: Sequence carries Appearance="Cue Point Main" (a default
    built-in grandMA3 Appearance, previously missing from our generated
    XML), and every named Cue's Part also repeats the Name attribute —
    including the Preset (0.5) cue, which our code previously left
    unnamed at the Part level."""
    plan = _plan("Rarely Think of It")
    plan.main_cues = [
        ExportCue(1, "Verse", ma_export_name="Verse", time_seconds=1.0),
    ]
    path = tmp_path / "main.xml"

    Ma3Exporter().write_main_sequence(plan, path, include_preset_cue=True)

    root = load_xml_root(path)
    sequ = next(el for el in root.iter() if xml_tag_local(el.tag) == "Sequence")
    assert sequ.get("Appearance") == "Cue Point Main"

    cues = {
        cue.get("Name"): cue
        for cue in root.iter()
        if xml_tag_local(cue.tag) == "Cue"
    }
    preset_part = next(p for p in cues["Preset"] if xml_tag_local(p.tag) == "Part")
    assert preset_part.get("Name") == "Preset"
    verse_part = next(p for p in cues["Verse"] if xml_tag_local(p.tag) == "Part")
    assert verse_part.get("Name") == "Verse"


def test_song_change_macro_pool_defaults_to_201(tmp_path: Path) -> None:
    """Real-hardware feedback: the macro pool defaulted to 1 instead of the
    201 Willy expected — matching MaExportSettings.ma2_song_macro_start's
    existing default."""
    plans = [_plan("Rarely Think of It")]

    paths = Ma3Exporter().export_show_to_directory(plans, tmp_path, show_name="CuePlayer")

    root = load_xml_root(paths["show:macro"])
    commands = [
        line.get("Command", "")
        for line in root.iter()
        if xml_tag_local(line.tag) == "MacroLine"
    ]
    assert any(
        c.startswith("Import Macro Library") and c.endswith("At Macro 201")
        for c in commands
    )


def test_template_page_is_stored_and_labeled(tmp_path: Path) -> None:
    """Real-hardware feedback: nothing created the Page the fixed
    "Go To Template Page" macro (Page "*Template Page") depends on."""
    plans = [_plan("Rarely Think of It")]

    paths = Ma3Exporter().export_show_to_directory(plans, tmp_path, show_name="CuePlayer")

    root = load_xml_root(paths["show:macro"])
    commands = [
        line.get("Command", "")
        for line in root.iter()
        if xml_tag_local(line.tag) == "MacroLine"
    ]
    assert "Store Page 200" in commands
    assert 'Label Page 200 "Template Page"' in commands


def test_main_sequence_gets_a_preset_cue_at_0_5_when_song_list_is_on(
    tmp_path: Path,
) -> None:
    """Real-hardware feedback: Page Change's unconditional "Goto Cue 0.5"
    needs an actual Cue 0.5 to exist in every song's Main Sequence — it's
    referenced by raw number, not a "Preset" label the way MA2 does it."""
    plans = [_plan("Rarely Think of It")]

    with_song_list = Ma3Exporter().export_show_to_directory(
        plans, tmp_path / "with", show_name="CuePlayer", include_song_list=True
    )
    main_seq = load_xml_root(with_song_list["Rarely Think of It:main_sequence"])
    cue_nos = {
        cue.get("Name"): cue.get("No")
        for cue in main_seq.iter()
        if xml_tag_local(cue.tag) == "Cue"
    }
    assert cue_nos.get("Preset") == "0.500"

    # Without the Song Change workflow, Page Change never runs, so the
    # extra cue is not needed / not added.
    without_song_list = Ma3Exporter().export_show_to_directory(
        plans, tmp_path / "without", show_name="CuePlayer", include_song_list=False
    )
    main_seq2 = load_xml_root(without_song_list["Rarely Think of It:main_sequence"])
    names = [
        cue.get("Name") for cue in main_seq2.iter() if xml_tag_local(cue.tag) == "Cue"
    ]
    assert "Preset" not in names


def test_export_show_to_directory_can_skip_song_workflow(tmp_path: Path) -> None:
    plans = [_plan("Rarely Think of It")]

    paths = Ma3Exporter().export_show_to_directory(
        plans, tmp_path, show_name="CuePlayer", include_song_list=False
    )

    assert "show:macro" in paths
    assert "show:song_list" not in paths
    assert "show:fixed_macros" not in paths
    assert "show:song_macros" not in paths


def test_write_song_view_converts_grid_units_and_maps_pool_types(tmp_path: Path) -> None:
    """write_song_view is layout-driven — the same list of dicts the View
    Layout editor (ui/ma2_view_layout.py) produces for MA2, edited on an
    18x10 grid for MA3. Real hardware (SONGVIEW.xml) confirmed MA3's raw
    ViewWidget X/Y/W/H are exactly 2x the grid-cell coordinates (its
    WindowSequencePool sits at grid (0,0) size 18x1 → raw X=0 Y=0 W=36 H=2)."""
    plan = _plan("Rarely Think of It")
    path = tmp_path / "view.xml"
    layout = [
        {"type": "sequence", "x": 0, "y": 0, "w": 18, "h": 1},
        {"type": "groups", "x": 0, "y": 1, "w": 18, "h": 1},
    ]

    Ma3Exporter().write_song_view(plan, path, layout=layout)

    root = load_xml_root(path)
    view = next(el for el in root.iter() if xml_tag_local(el.tag) == "View")
    assert view.get("Name") == "Rarely_Think_of_It"
    assert view.get("ScreenContentMask") == "2"

    widgets = [el for el in root.iter() if xml_tag_local(el.tag) == "ViewWidget"]
    assert len(widgets) == 2
    seq, grp = widgets
    assert seq.get("Name") == "WindowSequencePool"
    assert (seq.get("X"), seq.get("Y"), seq.get("W"), seq.get("H")) == ("0", "0", "36", "2")
    assert grp.get("Name") == "WindowGroupPool"
    assert (grp.get("X"), grp.get("Y"), grp.get("W"), grp.get("H")) == ("0", "2", "36", "2")
    # Every widget gets its own unique Guid, not a shared/copy-pasted one.
    assert len({w.get("Guid") for w in widgets}) == 2


def test_write_song_view_skips_unmapped_pool_types(tmp_path: Path) -> None:
    """Pool types with no confirmed MA3 <ViewWidget> shape yet (e.g.
    "camera", "effects") are skipped rather than guessed at."""
    plan = _plan("Rarely Think of It")
    path = tmp_path / "view.xml"
    layout = [
        {"type": "sequence", "x": 0, "y": 0, "w": 18, "h": 1},
        {"type": "camera", "x": 0, "y": 1, "w": 18, "h": 1},
        {"type": "effects", "x": 0, "y": 2, "w": 18, "h": 1},
    ]

    Ma3Exporter().write_song_view(plan, path, layout=layout)

    root = load_xml_root(path)
    widgets = [el for el in root.iter() if xml_tag_local(el.tag) == "ViewWidget"]
    assert len(widgets) == 1
    assert widgets[0].get("Name") == "WindowSequencePool"


def test_page_change_reads_songviewbutton_variable(tmp_path: Path) -> None:
    """Real reference (VIEWBUTTON.xml) sets a $songviewbutton global
    variable that Page Change should read back, instead of the hardcoded
    "At ViewButton 2.10" Phase 1 copied verbatim before Song View existed."""
    plans = [_plan("Rarely Think of It")]
    path = tmp_path / "macros.xml"

    Ma3Exporter().write_song_change_macros(
        plans, path, include_songs=False, viewbutton="2.10"
    )

    root = load_xml_root(path)
    commands = [
        line.get("Command", "")
        for line in root.iter()
        if xml_tag_local(line.tag) == "MacroLine"
    ]
    assert 'Assign View $"song" At ViewButton $"songviewbutton"' in commands
    assert not any("ViewButton 2.10" in c for c in commands)
    assert 'SetGlobalVariable "songviewbutton" "2.10"' in commands


def test_export_show_to_directory_writes_and_imports_song_views(
    tmp_path: Path,
) -> None:
    plans = [_plan("Rarely Think of It"), _plan("Remains in Our Blood")]

    with_views = Ma3Exporter().export_show_to_directory(
        plans,
        tmp_path / "with",
        show_name="CuePlayer",
        include_song_views=True,
        view_pool_start=201,
    )
    assert with_views["Rarely Think of It:view"].is_file()
    assert with_views["Remains in Our Blood:view"].is_file()

    root = load_xml_root(with_views["show:macro"])
    commands = [
        line.get("Command", "")
        for line in root.iter()
        if xml_tag_local(line.tag) == "MacroLine"
    ]
    assert any(
        c.startswith("Import View Library") and c.endswith("At View 201")
        for c in commands
    )
    assert 'Label View 201 "Rarely_Think_of_It"' in commands
    assert any(
        c.startswith("Import View Library") and c.endswith("At View 202")
        for c in commands
    )
    assert 'Label View 202 "Remains_in_Our_Blood"' in commands

    # view_layout actually reaches the written file's widget content, not
    # just the default (empty) shape.
    view_xml = load_xml_root(with_views["Rarely Think of It:view"])
    assert not [el for el in view_xml.iter() if xml_tag_local(el.tag) == "ViewWidget"]

    with_layout = Ma3Exporter().export_show_to_directory(
        [plans[0]],
        tmp_path / "with_layout",
        show_name="CuePlayer",
        include_song_views=True,
        view_layout=[{"type": "sequence", "x": 0, "y": 0, "w": 18, "h": 1}],
    )
    view_xml2 = load_xml_root(with_layout["Rarely Think of It:view"])
    widgets2 = [el for el in view_xml2.iter() if xml_tag_local(el.tag) == "ViewWidget"]
    assert len(widgets2) == 1
    assert widgets2[0].get("Name") == "WindowSequencePool"

    without_views = Ma3Exporter().export_show_to_directory(
        plans, tmp_path / "without", show_name="CuePlayer", include_song_views=False
    )
    assert "Rarely Think of It:view" not in without_views
    root2 = load_xml_root(without_views["show:macro"])
    commands2 = [
        line.get("Command", "")
        for line in root2.iter()
        if xml_tag_local(line.tag) == "MacroLine"
    ]
    assert not any("Import View Library" in c for c in commands2)
    assert not any(c.startswith("Label View") for c in commands2)
