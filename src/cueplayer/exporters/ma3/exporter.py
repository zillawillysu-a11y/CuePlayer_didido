"""grandMA3 exporter — Sequence + Timecode XML + install Macro."""

from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

from cueplayer.exporters.common import (
    SongExportPlan,
    export_event_time_seconds,
    format_ma3_cue_no_attr,
    format_ma3_offset_seconds,
    format_ma_cue_number,
    ma3_cue_destination_handle,
    parse_page_executor,
    sanitize_ma_name,
    timecode_span_seconds,
)
from cueplayer.exporters.xml_write import ma3_guid, write_xml

MA3_TARGET_VERSION = "2.3.2"
MA3_DATA_VERSION = "2.4.2.2"  # matches collected golden XML from this machine

# Attributes copied from a real onPC export that successfully imports.
# "Appearance" is a default built-in grandMA3 Appearance name (present on
# every show, no user setup needed) — Willy's real "cues keep their
# baked-in names" reference file always carries it on the Sequence; our
# generated XML previously omitted it entirely.
_SEQUENCE_ATTRS = {
    "Appearance": "Cue Point Main",
    "AutoStart": "Yes",
    "AutoStop": "Yes",
    "AutoFix": "No",
    "AutoStomp": "No",
    "SoftLTP": "Yes",
    "XFadeReload": "No",
    "SwapProtect": "No",
    "KillProtect": "No",
    "UseExecutorTime": "Yes",
    "OffwhenOverridden": "Yes",
    "SequMIB": "Enabled",
    "AutoPrePos": "Yes",
    "WrapAround": "Yes",
    "MasterGoMode": "None",
    "SpeedfromRate": "No",
    "Tracking": "Yes",
    "IncludeLinkLastGo": "Yes",
    "RateScale": "One",
    "SpeedScale": "One",
    "PreferCueAppearance": "No",
    "ExecutorDisplayMode": "Data and\rAppearance",
    "Action": "Pool Default",
}

# View Layout editor grid → MA3 raw ViewWidget units. Confirmed against
# SONGVIEW.xml (a real onPC View export): its widgets span X 0-36, Y 0-20 —
# exactly 2x an 18x10 grid — so grid units convert with a flat *2.
MA3_VIEW_GRID_UNIT = 2

# Per-song-view Pool Type → MA3 <ViewWidget> shape. Keys normally use the
# same ``type`` strings CuePlayer's View Layout editor already uses. Effects
# additionally use ``type:mode`` because real onPC exports show fixed Template
# EFX and per-song Song EFX are different PresetAll pools. Only confirmed
# shapes are populated; write_song_view skips anything else rather than guess.
_MA3_POOL_WIDGET_SHAPES: dict[str, dict[str, object]] = {
    "sequence": {
        "widget_name": "WindowSequencePool",
        "pool_type": 0,
        "settings_tag": "SequencePoolSettings",
        "settings_attrs": {
            "FontSize": "Default",
            "RequestDefaultTitlebuttons": "No",
            "ShowEmpty": "Yes",
            "PoolColor": "A67D00FF",
            "EmptyColor": "7A7A7DA0",
            "ForNoneColor": "FFFFFFA0",
            "ForSomeColor": "FFD700FF",
            "ForAllColor": "00FF00FF",
            "RightClickToEdit": "Yes",
            "ExecutorStyle": "No",
            "Action": "Select",
        },
        "window_color": "91BD34A4",
    },
    "groups": {
        "widget_name": "WindowGroupPool",
        "pool_type": 0,
        "settings_tag": "GroupPoolSettings",
        "settings_attrs": {
            "FontSize": "Default",
            "RequestDefaultTitlebuttons": "No",
            "ShowEmpty": "Yes",
            "PoolColor": "004080FF",
            "EmptyColor": "7A7A7DA0",
            "ForNoneColor": "FFFFFFA0",
            "ForSomeColor": "FFD700FF",
            "ForAllColor": "00FF00FF",
            "RightClickToEdit": "Yes",
            "PoolType": "None",
            "ExecutorStyle": "No",
        },
        "window_color": "75656E63",
    },
    "effects:fixed": {
        "widget_name": "WindowPresetPool",
        "pool_type": 22,
        "settings_tag": "PresetAllPoolSettings",
        "settings_attrs": {
            "FontSize": "Default",
            "RequestDefaultTitlebuttons": "No",
            "ShowEmpty": "Yes",
            "PoolColor": "008080FF",
            "EmptyColor": "7A7A7DA0",
            "ForNoneColor": "67676EFF",
            "ForSomeColor": "FFD700FF",
            "ForAllColor": "00FF00FF",
            "RightClickToEdit": "Yes",
            "PoolType": "None",
            "ExecutorStyle": "No",
            "DisplayMode": "Text and\rSymbol",
            "Action": "SelFix/At",
        },
        "window_color": "75656E63",
    },
    "effects:perSong": {
        "widget_name": "WindowPresetPool",
        "pool_type": 24,
        "settings_tag": "PresetAllPoolSettings",
        "settings_attrs": {
            "FontSize": "Default",
            "RequestDefaultTitlebuttons": "No",
            "ShowEmpty": "Yes",
            "PoolColor": "008080FF",
            "EmptyColor": "7A7A7DA0",
            "ForNoneColor": "67676EFF",
            "ForSomeColor": "FFD700FF",
            "ForAllColor": "00FF00FF",
            "RightClickToEdit": "Yes",
            "PoolType": "None",
            "ExecutorStyle": "No",
            "DisplayMode": "Text and\rSymbol",
            "Action": "SelFix/At",
        },
        "window_color": "91BD34A4",
    },
    "macros": {
        "widget_name": "WindowMacroPool",
        "pool_type": 0,
        "settings_tag": "MacroPoolSettings",
        "settings_attrs": {
            "FontSize": "Default",
            "RequestDefaultTitlebuttons": "No",
            "ShowEmpty": "Yes",
            "PoolColor": "800000FF",
            "EmptyColor": "7A7A7DA0",
            "ForNoneColor": "FFFFFFA0",
            "ForSomeColor": "FFD700FF",
            "ForAllColor": "00FF00FF",
            "RightClickToEdit": "Yes",
            "PoolType": "None",
            "ExecutorStyle": "No",
            "Action": "Call",
        },
        "window_color": "91BD4E4C",
    },
}

# grandMA3's five All pools are separate PresetAll pool types. These values
# and colors come from Willy's SONGEXPORT0625.xml / ALL4.xml onPC exports.
for _all_key, _preset_type, _window_color in (
    ("all1", 20, "20202020"),
    ("all2", 21, "45464155"),
    ("all3", 22, "75656E63"),
    ("all4", 23, "B06E7031"),
    ("all5", 24, "91BD34A4"),
):
    _MA3_POOL_WIDGET_SHAPES[_all_key] = {
        "widget_name": "WindowPresetPool",
        "pool_type": _preset_type,
        "settings_tag": "PresetAllPoolSettings",
        "settings_attrs": dict(
            _MA3_POOL_WIDGET_SHAPES["effects:fixed"]["settings_attrs"]  # type: ignore[arg-type]
        ),
        "window_color": _window_color,
    }


def resolve_ma3_datapool_dirs(directory: Path) -> tuple[Path, Path, Path, Path]:
    """
    Map a user-chosen folder to MA3 library subfolders.

    Returns (sequences_dir, timecodes_dir, macros_dir, views_dir).

    Sequences/Timecodes/Macros live under .../gma3_library/datapools/...;
    Views are a different library category entirely — real hardware
    confirmed they live under .../gma3_library/userprofiles/views, a
    sibling of datapools, not a datapools subfolder.

    Accepts:
    - gma3_library
    - gma3_library/datapools
    - …/datapools/sequences (or timecodes / macros)
    - any other folder → creates datapools/{sequences,timecodes,macros}
      and userprofiles/views under it
    """
    root = Path(directory)
    name = root.name.lower()
    if name == "datapools":
        base = root
    elif name in ("sequences", "timecodes", "macros") and root.parent.name.lower() == "datapools":
        base = root.parent
    elif (root / "datapools").exists() or name == "gma3_library":
        base = root / "datapools"
    else:
        base = root / "datapools"
    library_root = base.parent
    return (
        base / "sequences",
        base / "timecodes",
        base / "macros",
        library_root / "userprofiles" / "views",
    )


class Ma3Exporter:
    target_version = MA3_TARGET_VERSION
    data_version = MA3_DATA_VERSION

    def export_plan_summary(self, plan: SongExportPlan) -> dict:
        return {
            "console": "ma3",
            "target_version": self.target_version,
            "data_version": self.data_version,
            "song_name": plan.song_name,
            "export_mode": plan.profile.export_mode,
            "main_cue_count": len(plan.main_cues),
            "button_lane_count": len(plan.button_lanes),
            "button_event_count": sum(len(lane.mark_times_seconds) for lane in plan.button_lanes),
            "sequence_pool_start": plan.profile.sequence_pool_start,
            "timecode_pool": plan.profile.timecode_pool,
            "data_pool": plan.profile.data_pool,
            "main_executor": plan.profile.main_executor,
            "ltc_latency_compensation_seconds": plan.profile.ltc_latency_compensation_seconds,
        }

    def export_to_directory(
        self,
        plan: SongExportPlan,
        directory: Path,
        *,
        include_macro: bool = True,
        include_preset_cue: bool = False,
        preset_cue_id: float = 0.5,
    ) -> dict[str, Path]:
        """
        Write into MA3 datapool folders:

        - Sequence XML → datapools/sequences/
        - Timecode XML → datapools/timecodes/
        - Install Macro → datapools/macros/ (optional; show export uses one shared macro)

        ``include_preset_cue`` adds a Cue at ``preset_cue_id`` (default 0.5)
        to the Main Sequence — the Song Change workflow's Page Change macro
        does ``Goto Cue 0.5`` unconditionally, referencing it by raw number
        (not by a "Preset" label the way MA2's equivalent macro does), so
        that cue must actually exist in the imported Sequence.
        """
        seq_dir, tc_dir, macro_dir, _view_dir = resolve_ma3_datapool_dirs(directory)
        for folder in (seq_dir, tc_dir, macro_dir):
            folder.mkdir(parents=True, exist_ok=True)

        paths: dict[str, Path] = {}

        if plan.profile.export_mode == "full":
            if plan.profile.include_main:
                paths["main_sequence"] = seq_dir / plan.profile.main_sequence_file
                self.write_main_sequence(
                    plan,
                    paths["main_sequence"],
                    include_preset_cue=include_preset_cue,
                    preset_cue_id=preset_cue_id,
                )
            if plan.button_lanes:
                for lane in plan.button_lanes:
                    key = f"button_sequence_{lane.lane_index}"
                    path = seq_dir / (lane.sequence_file or plan.profile.button_sequence_file)
                    paths[key] = path
                    self.write_button_sequence(plan, path, sequence_name=lane.sequence_name)
                paths["button_sequence"] = paths[
                    f"button_sequence_{plan.button_lanes[0].lane_index}"
                ]
            if include_macro:
                install_base = plan.profile.main_sequence_file
                if install_base.endswith("_main.xml"):
                    install_base = install_base[: -len("_main.xml")]
                else:
                    install_base = plan.song_name or "cueplayer"
                paths["macro"] = macro_dir / f"{install_base}_install_macro.xml"
                self.write_install_macro(plan, paths["macro"])

        paths["timecode"] = tc_dir / plan.profile.timecode_file
        self.write_timecode(plan, paths["timecode"])
        return paths

    def export_show_to_directory(
        self,
        plans: list[SongExportPlan],
        directory: Path,
        *,
        show_macro_name: str = "CuePlayer_Show_Install",
        show_name: str = "CuePlayer",
        include_song_list: bool = True,
        include_fixed_macros: bool = True,
        include_song_macros: bool = True,
        song_list_sequence_pool: int | None = None,
        # Matches MaExportSettings.ma2_fixed_macro_start / ma2_song_macro_start's
        # existing defaults — two independent macro pool starting positions
        # (fixed control macros vs. one-per-song macros), same as MA2's own
        # Console Setup fields already expose; reused here rather than
        # inventing separate MA3-only settings.
        fixed_macro_start: int = 101,
        song_macro_start: int = 201,
        # Matches MaExportSettings.ma2_template_page's existing default —
        # one below where per-song Pages conventionally start (201), so a
        # freshly-exported show doesn't need the two to be reconciled by hand.
        template_page: int = 200,
        # Executor the Song List Sequence is assigned to on the Template
        # Page, matching MA2's equivalent "song list on a fader" step.
        song_list_executor: int = 130,
        # Matches MaExportSettings.ma2_include_song_views/ma2_view_pool_start/
        # ma2_song_viewbutton's existing defaults — MA2 already has this
        # exact feature (write_song_view + Page Change's ViewButton
        # switch), reused here rather than inventing separate MA3 settings.
        include_song_views: bool = True,
        view_pool_start: int = 201,
        song_viewbutton: str = "2.10",
        # Same list of dicts MA2's export call site already passes
        # (project.ma_export.ma2_view_layout) — write_song_view maps each
        # entry's "type" to an MA3 <ViewWidget> shape where one exists.
        view_layout: list[dict[str, object]] | None = None,
    ) -> dict[str, Path]:
        """
        Export every song's Seq/TC files, plus one show-wide install Macro,
        plus the shared Song List Sequence and Song Change Macros (Jump/
        Previous/Next Song, Page Change split from the fixed macros; one
        macro per song, at its own starting Macro pool position).

        The Song List Sequence and both Macro files are Imported by the
        show install Macro itself (via extra_commands) — writing them to
        disk alone does not bring them onto the console; MA3 only reads an
        ``Import <Type> Library "<file>" At <Type> <Pool>`` command. The
        Song List is also Assigned to a fader on the Template Page and
        labeled, the same way MA2's equivalent step already works.
        """
        if not plans:
            return {}
        if include_song_list and song_list_sequence_pool is not None:
            requested_pool = max(1, int(song_list_sequence_pool))
            used_pools = {
                int(plan.profile.sequence_pool_start) for plan in plans
            } | {
                int(lane.sequence_pool)
                for plan in plans
                for lane in plan.button_lanes
                if lane.sequence_pool
            }
            if requested_pool in used_pools:
                raise ValueError(
                    f"Song List Sequence {requested_pool} conflicts with a song Main/Button Sequence."
                )
        seq_dir, _tc_dir, macro_dir, view_dir = resolve_ma3_datapool_dirs(directory)
        all_paths: dict[str, Path] = {}
        for plan in plans:
            # Per-song macros skipped — one show macro at the end. The
            # Preset Cue (0.5) is only meaningful when the Song Change
            # workflow's Page Change macro is actually going to reference
            # it, i.e. exactly when include_song_list is on.
            paths = self.export_to_directory(
                plan,
                directory,
                include_macro=False,
                include_preset_cue=include_song_list,
            )
            prefix = plan.song_name or "song"
            for key, path in paths.items():
                all_paths[f"{prefix}:{key}"] = path

        if any(p.profile.export_mode == "full" for p in plans):
            extra_commands: list[str] = []
            song_list_name = sanitize_ma_name(
                f"{show_name}_Song_List", fallback="CuePlayer_Song_List"
            )

            if include_song_list:
                extra_commands.extend(
                    [
                        f"Store Page {int(template_page)}",
                        f'Label Page {int(template_page)} "Template Page"',
                    ]
                )
                song_list_filename = f"{song_list_name}.xml"
                song_list_path = seq_dir / song_list_filename
                self.write_song_list_sequence(plans, song_list_path, name=song_list_name)
                all_paths["show:song_list"] = song_list_path

                # First free Sequence pool after every song's own Main +
                # button lanes (works whether or not each song reserves a
                # fixed per-song block — this always finds the true max).
                used_sequence_pools = [int(p.profile.sequence_pool_start) for p in plans]
                used_sequence_pools.extend(
                    int(lane.sequence_pool)
                    for p in plans
                    for lane in p.button_lanes
                    if lane.sequence_pool
                )
                song_list_pool = (
                    max(1, int(song_list_sequence_pool))
                    if song_list_sequence_pool is not None
                    else max(used_sequence_pools, default=0) + 1
                )
                extra_commands.append(
                    f'Import Sequence Library "{song_list_filename}" At Sequence {song_list_pool}'
                )
                # Importing the pool object alone leaves it with no fader —
                # Assign it to an executor on the Template Page. Its Name
                # is already baked into the Song List XML (write_song_list_
                # sequence), so no Label command is needed — "Label
                # Executor ..." was tried here previously and real hardware
                # rejected it as an "Illegal object".
                extra_commands.append(
                    f"Assign Sequence {song_list_pool} At Page "
                    f"{int(template_page)}.{int(song_list_executor)}"
                )

            if include_fixed_macros:
                fixed_name = sanitize_ma_name(
                    f"{show_name}_Fixed_Macros", fallback="CuePlayer_Fixed_Macros"
                )
                fixed_filename = f"{fixed_name}.xml"
                fixed_path = macro_dir / fixed_filename
                self.write_song_change_macros(
                    plans,
                    fixed_path,
                    song_list_name=song_list_name,
                    include_songs=False,
                    viewbutton=song_viewbutton,
                )
                all_paths["show:fixed_macros"] = fixed_path
                extra_commands.append(
                    f'Import Macro Library "{fixed_filename}" At Macro {int(fixed_macro_start)}'
                )

            if include_song_macros:
                song_change_name = sanitize_ma_name(
                    f"{show_name}_Song_Macros", fallback="CuePlayer_Song_Macros"
                )
                song_change_filename = f"{song_change_name}.xml"
                song_change_path = macro_dir / song_change_filename
                self.write_song_change_macros(
                    plans, song_change_path, include_fixed=False
                )
                all_paths["show:song_macros"] = song_change_path
                extra_commands.append(
                    f'Import Macro Library "{song_change_filename}" At Macro {int(song_macro_start)}'
                )

            if include_song_views:
                view_dir.mkdir(parents=True, exist_ok=True)
                for index, plan in enumerate(plans):
                    view_pool = int(view_pool_start) + index
                    view_name = sanitize_ma_name(
                        plan.song_name, fallback=f"Song{index + 1}"
                    )
                    view_filename = f"{view_name}_view.xml"
                    view_path = view_dir / view_filename
                    self.write_song_view(
                        plan, view_path, layout=view_layout, song_index=index
                    )
                    all_paths[f"{plan.song_name}:view"] = view_path
                    extra_commands.extend(
                        [
                            f'Import View Library "{view_filename}" At View {view_pool}',
                            f'Label View {view_pool} "{view_name}"',
                        ]
                    )

            if include_fixed_macros:
                # Initialize the global ViewButton variable immediately
                # after importing the fixed macros. Without this, Page Change
                # has no destination until the operator manually runs the
                # Set Songviewbutton macro once.
                extra_commands.append('Macro "Set Songviewbutton"')

            macro_path = macro_dir / f"{show_macro_name}.xml"
            self.write_show_install_macro(
                plans,
                macro_path,
                name=show_macro_name,
                extra_commands=extra_commands,
            )
            all_paths["show:macro"] = macro_path
        return all_paths

    def _root(self) -> ET.Element:
        return ET.Element("GMA3", {"DataVersion": self.data_version})

    def _cue_part(self, cue_el: ET.Element) -> ET.Element:
        return ET.SubElement(
            cue_el,
            "Part",
            {
                "Guid": ma3_guid(),
                "AlignRangeX": "No",
                "AlignRangeY": "No",
                "AlignRangeZ": "No",
                "PreserveGridPositions": "No",
                "MAgic": "No",
                "Mode": "0",
                "Action": "Pool Default",
            },
        )

    def write_main_sequence(
        self,
        plan: SongExportPlan,
        path: Path,
        *,
        include_preset_cue: bool = False,
        preset_cue_id: float = 0.5,
    ) -> None:
        root = self._root()
        attrs = {
            "Name": plan.profile.main_sequence_name,
            "Guid": ma3_guid(),
            **_SEQUENCE_ATTRS,
        }
        sequ = ET.SubElement(root, "Sequence", attrs)
        off = ET.SubElement(
            sequ,
            "Cue",
            {
                "Name": "OffCue",
                "Release": "Yes",
                "Assert": "Assert",
                "AllowDuplicates": "",
                "TrigType": "",
            },
        )
        self._cue_part(off)
        zero = ET.SubElement(sequ, "Cue", {"Name": "CueZero", "No": "  0"})
        self._cue_part(zero)

        if include_preset_cue:
            preset = ET.SubElement(
                sequ,
                "Cue",
                {
                    "Name": "Preset",
                    "No": format_ma3_cue_no_attr(float(preset_cue_id)),
                    "AllowDuplicates": "",
                },
            )
            preset_part = self._cue_part(preset)
            preset_part.set("Sync", "")
            preset_part.set("Morph", "")
            preset_part.set("Name", "Preset")

        for cue in plan.main_cues:
            # Name before No (matches CueZero pattern) so Import keeps the label.
            attrs: dict[str, str] = {}
            label = cue.cue_name_for_export()
            if label:
                attrs["Name"] = label
            attrs["No"] = format_ma3_cue_no_attr(cue.cue_number)
            attrs["AllowDuplicates"] = ""
            cue_el = ET.SubElement(sequ, "Cue", attrs)
            part = self._cue_part(cue_el)
            part.set("Sync", "")
            part.set("Morph", "")
            # Some MA3 builds read Part name when Cue Name is dropped on import.
            if label:
                part.set("Name", label)

        write_xml(root, path)

    def write_song_list_sequence(
        self,
        plans: list[SongExportPlan],
        path: Path,
        *,
        name: str = "CuePlayer_Song_List",
    ) -> None:
        """Write the shared Sequence used by Jump/Previous/Next Song macros.

        One Cue per song, each firing ``Macro "SongName"`` (see
        write_song_change_macros). Cues intentionally carry only Name/No/
        Command — not the Recipe/Preset/DependencyExport block a real onPC
        export also includes, since that references show-specific Group
        data this exporter has no way to generate generically; a bare
        Command is sufficient for the Cue to import and fire its macro.
        """
        root = self._root()
        attrs = {"Name": name, "Guid": ma3_guid(), **_SEQUENCE_ATTRS}
        sequ = ET.SubElement(root, "Sequence", attrs)
        off = ET.SubElement(
            sequ,
            "Cue",
            {
                "Name": "OffCue",
                "Release": "Yes",
                "Assert": "Assert",
                "AllowDuplicates": "",
                "TrigType": "",
            },
        )
        self._cue_part(off)
        zero = ET.SubElement(sequ, "Cue", {"Name": "CueZero", "No": "  0"})
        self._cue_part(zero)

        for index, plan in enumerate(plans, start=1):
            song_name = plan.song_name
            cue_el = ET.SubElement(
                sequ,
                "Cue",
                {
                    "Name": song_name,
                    "No": format_ma3_cue_no_attr(float(index)),
                    "AllowDuplicates": "",
                },
            )
            part = self._cue_part(cue_el)
            part.set("Sync", "")
            part.set("Morph", "")
            part.set("Name", song_name)
            part.set("Command", f'Macro "{song_name}"')

        write_xml(root, path)

    def write_song_view(
        self,
        plan: SongExportPlan,
        path: Path,
        *,
        layout: list[dict[str, object]] | None = None,
        song_index: int = 0,
    ) -> None:
        """Write the per-song Screen 3 View from the same View Layout
        editor data CuePlayer already uses for MA2 (``ma2_view_layout`` —
        a list of ``{"type", "x", "y", "w", "h", ...}`` dicts, edited on
        an 18x10 grid for MA3, see ``ui/ma2_view_layout.py``).

        Each entry's ``type`` is looked up in ``_MA3_POOL_WIDGET_SHAPES``;
        entries whose type has no confirmed MA3 shape yet are skipped
        rather than guessed. As in ``Ma2Exporter.write_song_view``,
        ``song_index`` advances per-song pools by their configured stride.
        MA3 View widgets use ``WindowScrollPositions.ScrollV`` to select their visible
        pool-number range. Real onPC exports encode this as first pool number
        minus one (for example pool 1409 uses ``1408,1408``).
        """
        root = self._root()
        view_name = sanitize_ma_name(plan.song_name, fallback="Song")
        view = ET.SubElement(
            root,
            "View",
            {
                "Name": view_name,
                "Guid": ma3_guid(),
                "ScreenContentMask": "2",
                "RequestedW": "Default",
                "RequestedH": "Default",
            },
        )

        for entry in layout or []:
            pool_type = str(entry.get("type", ""))
            mode = str(entry.get("mode", ""))
            spec = _MA3_POOL_WIDGET_SHAPES.get(f"{pool_type}:{mode}")
            if spec is None:
                spec = _MA3_POOL_WIDGET_SHAPES.get(pool_type)
            if spec is None:
                continue
            x = int(entry.get("x", 0)) * MA3_VIEW_GRID_UNIT
            y = int(entry.get("y", 0)) * MA3_VIEW_GRID_UNIT
            w = int(entry.get("w", 1)) * MA3_VIEW_GRID_UNIT
            h = int(entry.get("h", 1)) * MA3_VIEW_GRID_UNIT
            el = ET.SubElement(
                view,
                "ViewWidget",
                {
                    "Name": str(spec["widget_name"]),
                    "Guid": ma3_guid(),
                    "Display": "2",
                    "X": str(x),
                    "Y": str(y),
                    "W": str(w),
                    "H": str(h),
                    "PresetPoolType": str(spec["pool_type"]),
                    "SnapToBlockSize": "Yes",
                },
            )
            settings_attrs = dict(spec["settings_attrs"])  # type: ignore[arg-type]
            ET.SubElement(el, str(spec["settings_tag"]), {"Guid": ma3_guid(), **settings_attrs})
            ET.SubElement(el, "WindowAppearance", {"WindowColor": str(spec["window_color"])})
            first_pool = int(entry.get("start", 1))
            if mode == "perSong":
                first_pool += int(song_index) * int(entry.get("stride", 1))
            scroll_v = max(0, first_pool - 1)
            ET.SubElement(
                el,
                "WindowScrollPositions",
                {"ScrollH": "0,0", "ScrollV": f"{scroll_v},{scroll_v}"},
            )

        write_xml(root, path)

    # Fixed control macros, copied faithfully from a real onPC export
    # (SONGFIXEDMACRO.xml) — only the Song List's pool name is templated in
    # (via the "*name-search" prefix, the same MA-wide convention the MA2
    # exporter's equivalent macros already rely on); everything else here
    # is deliberately static text, not reinterpreted logic.
    def _fixed_song_change_macro_definitions(
        self, song_list_name: str, viewbutton: str = "2.10"
    ) -> list[tuple[str, list[tuple[str, bool]]]]:
        return [
            (
                "Showbegin",
                [
                    ("ClearAll", True),
                    (f'Top Sequence "*{song_list_name}"', True),
                ],
            ),
            ("Go To Template Page", [('Page "*Template Page"', True)]),
            ("Go To Song Page", [('Page $"Song"', False)]),
            ("Jump To Song", [(f'Load Sequence "*{song_list_name}"', True)]),
            ("Previous Song", [(f'Go- Sequence "*{song_list_name}"', True)]),
            ("Next Song", [(f'Go+ Sequence "*{song_list_name}"', True)]),
            (
                "Page Change",
                [
                    ('Page $"song"', True),
                    ("Off Sequence 201 Thru", True),
                    ("Off Timecode 1 Thru", True),
                    ("<<< Timecode 1 Thru", True),
                    ('Select Sequence $"song".', True),
                    ("Goto Cue 0.5", True),
                    ('Assign View $"song" At ViewButton $songviewbutton', True),
                    ("Master 3.1 At BPM $songbpm", True),
                    ('Select Timecode $"song"', True),
                    ('Go+ Timecode $"song"', True),
                ],
            ),
            (
                "Set Songviewbutton",
                [(f'SetGlobalVariable "songviewbutton" "{viewbutton}"', True)],
            ),
        ]

    def write_song_change_macros(
        self,
        plans: list[SongExportPlan],
        path: Path,
        *,
        song_list_name: str = "CuePlayer_Song_List",
        include_fixed: bool = True,
        include_songs: bool = True,
        viewbutton: str = "2.10",
    ) -> None:
        """Write the fixed control macros plus one macro per song.

        Each song macro just sets the two global variables Page Change
        reads (``song``, ``songbpm``) and calls it — matching a real
        working onPC export (SONGFIXEDMACRO.xml / "SONG 1+2 Macro.xml")
        rather than duplicating page-change logic per song.

        The fixed "Page Change" macro reads the View to assign from the
        ``songviewbutton`` global variable (``$songviewbutton``), set by
        the "Set Songviewbutton" fixed macro below — matches Willy's
        VIEWBUTTON.xml reference and MA2's already-proven equivalent
        (``$songviewbutton``, unquoted there since MA2's variable-read
        syntax has no quotes).
        """
        root = self._root()
        definitions: list[tuple[str, list[tuple[str, bool]]]] = []
        if include_fixed:
            definitions.extend(
                self._fixed_song_change_macro_definitions(song_list_name, viewbutton)
            )
        if include_songs:
            for plan in plans:
                song_name = plan.song_name
                bpm = f"{float(plan.song_bpm):g}"
                definitions.append(
                    (
                        song_name,
                        [
                            (f'SetGlobalVariable "song" "{song_name}"', True),
                            (f'SetGlobalVariable "songbpm" "{bpm}"', True),
                            ('Macro "PAGE CHANGE"', True),
                        ],
                    )
                )

        for macro_name, commands in definitions:
            macro = ET.SubElement(root, "Macro", {"Name": macro_name, "Guid": ma3_guid()})
            for command, enabled in commands:
                line_attrs = {"Guid": ma3_guid(), "Command": command}
                if not enabled:
                    line_attrs["Enabled"] = "No"
                ET.SubElement(macro, "MacroLine", line_attrs)

        write_xml(root, path)

    def write_button_sequence(
        self,
        plan: SongExportPlan,
        path: Path,
        *,
        sequence_name: str | None = None,
    ) -> None:
        root = self._root()
        attrs = {
            "Name": sequence_name or plan.profile.button_sequence_name,
            "Guid": ma3_guid(),
            **_SEQUENCE_ATTRS,
            "AutoPrePos": "No",
            "WrapAround": "No",
        }
        sequ = ET.SubElement(root, "Sequence", attrs)
        off = ET.SubElement(
            sequ,
            "Cue",
            {
                "Name": "OffCue",
                "Release": "Yes",
                "Assert": "Assert",
                "AllowDuplicates": "",
                "TrigType": "Follow",
            },
        )
        self._cue_part(off)
        zero = ET.SubElement(sequ, "Cue", {"Name": "CueZero", "No": "  0"})
        self._cue_part(zero)

        cue1 = ET.SubElement(sequ, "Cue", {"No": "  1", "AllowDuplicates": ""})
        part1 = self._cue_part(cue1)
        part1.set("Sync", "")
        part1.set("Morph", "")

        follow = f"{plan.profile.button_follow_seconds:.3f}"
        cue2 = ET.SubElement(
            sequ,
            "Cue",
            {
                "No": "  2",
                "AllowDuplicates": "",
                "TrigType": "Follow",
                "TrigTime": follow,
            },
        )
        part2 = self._cue_part(cue2)
        part2.set("Sync", "")
        part2.set("Morph", "")
        part2.set("CueInFade", "0.500")

        write_xml(root, path)

    def write_timecode(self, plan: SongExportPlan, path: Path) -> None:
        root = self._root()
        # Length covers media + tail past last cue (not just last event time).
        duration = export_event_time_seconds(timecode_span_seconds(plan), plan.profile)
        offset_text = format_ma3_offset_seconds(plan.profile.start_offset_seconds)
        # TCSlot: 1..8 = external slot (user default), -1 = none/internal.
        tc_slot = int(plan.profile.timecode_slot)
        tc_slot_attr = str(tc_slot) if tc_slot >= 0 else "-1"

        tc_attrs = {
            "Name": plan.profile.timecode_name,
            "Guid": ma3_guid(),
            "Cursor": f"{duration:.2f}",
            "Duration": f"{duration:.2f}",
            "LoopCount": "0",
            "TCSlot": tc_slot_attr,
            # Playback column (user screenshot defaults)
            "AutoStart": "Yes",
            "AutoStop": "Yes",
            "LoopMode": "Off",
            "SwitchOff": "Keep Playbacks",
            "AssertPrevEvents": "No",
            "RestartOption": "Continue",
            # Record (Playback and Record is set via install macro — UI name has spaces)
            "Goto": "as Go",
            # Display
            "TimeDisplayFormat": "10d11h23m45",
            "FrameReadout": "Seconds",
        }
        # CuePoints-style: song start LTC → OffsetTCSlot (UI: Offset TC Slot).
        tc_attrs["OffsetTCSlot"] = offset_text

        tc = ET.SubElement(
            root,
            "Timecode",
            tc_attrs,
        )
        group = ET.SubElement(tc, "TrackGroup", {"Play": "", "Rec": ""})
        ET.SubElement(group, "MarkerTrack", {"Name": "Marker", "Guid": ma3_guid()})

        pool = plan.profile.data_pool
        main_name = plan.profile.main_sequence_name
        main_target = f"ShowData.DataPools.{pool}.Sequences.{main_name}"
        main_track = ET.SubElement(
            group,
            "Track",
            {
                "Name": main_name,
                "Guid": ma3_guid(),
                "Target": main_target,
                "Play": "",
                "Rec": "",
            },
        )
        main_range = ET.SubElement(
            main_track,
            "TimeRange",
            {"Guid": ma3_guid(), "Duration": "To End", "Play": "", "Rec": ""},
        )
        main_cmds = ET.SubElement(main_range, "CmdSubTrack")
        # Numeric handles match onPC-exported golden XML (named ShowData paths
        # in Object/ValCueDestination fail to resolve Cue destinations on import).
        main_seq_idx = max(0, int(plan.profile.sequence_pool_start) - 1)
        for cue in plan.main_cues:
            cue_label = format_ma_cue_number(cue.cue_number)
            dest_handle = ma3_cue_destination_handle(cue.cue_number)
            t = export_event_time_seconds(cue.time_seconds, plan.profile)
            event = ET.SubElement(
                main_cmds,
                "CmdEvent",
                {
                    "Name": "Go+",
                    "Time": f"{t:.3f}",
                    "CueDestination": f"Cue {cue_label}",
                },
            )
            ET.SubElement(
                event,
                "RealtimeCmd",
                {
                    "Type": "Key",
                    "Source": "Original",
                    "UserProfile": "0",
                    "Environment": "0",
                    "User": "1",
                    "Status": "On",
                    "IsRealtime": "0",
                    "IsXFade": "0",
                    "IgnoreFollow": "0",
                    "IgnoreCommand": "0",
                    "Assert": "0",
                    "IgnoreNetwork": "0",
                    "FromTriggerNode": "0",
                    "IgnoreExecTime": "0",
                    "IssuedByTimecode": "0",
                    "FromLocalHardwareFader": "1",
                    "IgnoreExecXFade": "0",
                    "IsExecXFade": "0",
                    "Object": f"13.13.0.5.{main_seq_idx}",
                    "ExecToken": "Go+",
                    "ValCueDestination": f"0.5.{main_seq_idx}.{dest_handle}",
                },
            )

        if not plan.profile.include_main:
            group.remove(main_track)

        for lane_i, lane in enumerate(plan.button_lanes):
            button_name = lane.sequence_name or lane.resolved_ma_name()
            target = f"ShowData.DataPools.{pool}.Sequences.{button_name}"
            btn_pool = int(
                lane.sequence_pool
                or (plan.profile.sequence_pool_start + 1 + lane_i)
            )
            btn_seq_idx = max(0, btn_pool - 1)
            track = ET.SubElement(
                group,
                "Track",
                {
                    "Name": button_name,
                    "Guid": ma3_guid(),
                    "Target": target,
                    "Play": "",
                    "Rec": "",
                },
            )
            time_range = ET.SubElement(
                track,
                "TimeRange",
                {"Guid": ma3_guid(), "Duration": "To End", "Play": "", "Rec": ""},
            )
            cmds = ET.SubElement(time_range, "CmdSubTrack")
            for t in lane.mark_times_seconds:
                abs_t = export_event_time_seconds(t, plan.profile)
                event = ET.SubElement(
                    cmds,
                    "CmdEvent",
                    {
                        "Name": "Top",
                        "Time": f"{abs_t:.3f}",
                        "CueDestination": "Cue 1",
                    },
                )
                ET.SubElement(
                    event,
                    "RealtimeCmd",
                    {
                        "Type": "Key",
                        "Source": "Original",
                        "UserProfile": "0",
                        "Environment": "0",
                        "User": "1",
                        "Status": "On",
                        "IsRealtime": "1",
                        "IsXFade": "0",
                        "IgnoreFollow": "0",
                        "IgnoreCommand": "0",
                        "Assert": "0",
                        "IgnoreNetwork": "0",
                        "FromTriggerNode": "0",
                        "IgnoreExecTime": "0",
                        "IssuedByTimecode": "0",
                        "FromLocalHardwareFader": "1",
                        "IgnoreExecXFade": "0",
                        "IsExecXFade": "0",
                        "Object": f"13.13.0.5.{btn_seq_idx}",
                        "ExecToken": "Top",
                        "ValCueDestination": f"0.5.{btn_seq_idx}.1000",
                    },
                )

        write_xml(root, path)

    def install_commands_for_plan(self, plan: SongExportPlan) -> list[str]:
        """Command lines to install one song (Page / Seq / TC / OffsetTCSlot)."""
        main_seq = plan.profile.sequence_pool_start
        tc_pool = plan.profile.timecode_pool
        main_page, main_exec = parse_page_executor(plan.profile.main_executor)
        page_name = sanitize_ma_name(
            plan.profile.page_name or plan.song_name or "",
            fallback="",
        )

        commands: list[str] = []
        if page_name:
            commands.extend(
                [
                    f"Store Page {main_page}",
                    f'Label Page {main_page} "{page_name}"',
                ]
            )
        # Sequence/Timecode Name — and every "Set Timecode Property" value
        # below — are already baked into the object's own XML (write_main_
        # sequence/write_button_sequence/write_timecode all set them as
        # element attributes). A "Label"/"Set Property" command that just
        # re-asserts the same value Import already brought in is pure
        # duplication — cut here so a many-song show doesn't drag the
        # install macro out with hundreds of redundant lines. Cue names
        # follow the same rule (see write_main_sequence): baked into the
        # Sequence XML, never re-asserted via command.
        if plan.profile.include_main:
            commands.extend(
                [
                    f'Import Sequence Library "{plan.profile.main_sequence_file}" At Sequence {main_seq}',
                    f"Assign Sequence {main_seq} At Page {main_page}.{main_exec}",
                    f"Assign Go+ At Page {main_page}.{main_exec}",
                ]
            )
        for lane in plan.button_lanes:
            seq_pool = lane.sequence_pool or (main_seq + 1)
            seq_file = lane.sequence_file or plan.profile.button_sequence_file
            b_page, b_exec = parse_page_executor(lane.executor)
            commands.extend(
                [
                    f'Import Sequence Library "{seq_file}" At Sequence {seq_pool}',
                    f"Assign Sequence {seq_pool} At Page {b_page}.{b_exec}",
                    f"Assign Top At Page {b_page}.{b_exec}",
                ]
            )
        commands.append(
            f'Import Timecode Library "{plan.profile.timecode_file}" At Timecode {tc_pool}'
        )
        return commands

    def write_install_macro(self, plan: SongExportPlan, path: Path) -> None:
        """Per-song install Macro (still available for single-song export)."""
        self._write_macro_xml(
            path,
            name=f"CuePlayer {plan.song_name}",
            commands=self.install_commands_for_plan(plan),
        )

    def write_show_install_macro(
        self,
        plans: list[SongExportPlan],
        path: Path,
        *,
        name: str = "CuePlayer_Show_Install",
        extra_commands: list[str] | None = None,
    ) -> None:
        """One Macro that installs every exported song in show order.

        ``extra_commands`` (e.g. the Import commands for the Song List
        Sequence / Song Change Macros files) run after every song's own
        Import/Assign lines, so running this one macro is enough to bring
        in everything the show export wrote.
        """
        commands: list[str] = []
        for plan in plans:
            if plan.profile.export_mode != "full":
                continue
            commands.extend(self.install_commands_for_plan(plan))
        commands.extend(extra_commands or [])
        self._write_macro_xml(path, name=name, commands=commands)

    def _write_macro_xml(self, path: Path, *, name: str, commands: list[str]) -> None:
        root = self._root()
        macro = ET.SubElement(
            root,
            "Macro",
            {"Name": name, "Guid": ma3_guid()},
        )
        for i, command in enumerate(commands, start=1):
            ET.SubElement(
                macro,
                "MacroLine",
                {"Name": f"Line {i}", "Command": command, "Enabled": "Yes"},
            )
        write_xml(root, path)
