"""grandMA2 exporter — Sequence + Timecode XML generation."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from cueplayer.exporters.common import (
    ExportCue,
    MaExportProfile,
    SongExportPlan,
    export_event_time_seconds,
    format_ma2_cue_link_name,
    format_ma_cue_number,
    ma2_phantom_cue_delete_range,
    ma2_timecode_assign_settings,
    ma2_timecode_cue_nos,
    MA2_TC_STEP_NONE,
    parse_page_executor,
    sanitize_ma_name,
    split_ma_cue_number,
    timecode_span_seconds,
)
from cueplayer.exporters.ma_default_dirs import resolve_ma2_pool_dirs
from cueplayer.exporters.xml_write import (
    MA2_NS,
    MA2_XSI,
    ma2_timecode_frame_format,
    ma2_timecode_frame_rate,
    seconds_to_ma2_frames,
    write_xml,
)

MA2_TARGET_VERSION = "3.9.61.5"
MA2_SCHEMA = "http://schemas.malighting.de/grandma2/xml/MA http://schemas.malighting.de/grandma2/xml/3.9.61/MA.xsd"


def _install_basename(plan: SongExportPlan) -> str:
    main = plan.profile.main_sequence_file
    if main.endswith("_main.xml"):
        return main[: -len("_main.xml")]
    return plan.song_name or "cueplayer"


def _xml_esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _lua_str(text: str) -> str:
    """Escape for Lua double-quoted string literals."""
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


def _lua_cmd_line(cmd: str) -> str:
    """One indented ``gma.cmd('…')`` line (CuePoints style)."""
    escaped = str(cmd).replace("\\", "\\\\").replace("'", "\\'")
    return f"  gma.cmd('{escaped}')"


def _ma2_store_cue_label(cue: ExportCue) -> str:
    """ASCII cue name for Store Sequence … Cue N \"…\" (empty = numbered only)."""
    return cue.cue_name_for_export() or ""


def _rel_event_frames(plan: SongExportPlan, mark_time: float) -> int:
    """
    Timecode timeline event time in frames at the profile FPS (song-relative).

    MA2 Import decodes XML ``time`` with the Timecode TimeUnit active at import
    (default 30 FPS). Changing TimeUnit later only changes display — so we write
    frames that match that default / ``frame_format``, not centiseconds.
    """
    seconds = export_event_time_seconds(mark_time, plan.profile)
    return seconds_to_ma2_frames(seconds, float(ma2_timecode_frame_rate(plan.profile.fps)))


def _timecode_length_frames(plan: SongExportPlan) -> int:
    """Song + tail Length in frames (past last cue so the final event can fire)."""
    seconds = export_event_time_seconds(timecode_span_seconds(plan), plan.profile)
    return seconds_to_ma2_frames(seconds, float(ma2_timecode_frame_rate(plan.profile.fps)))


class Ma2Exporter:
    target_version = MA2_TARGET_VERSION

    def __init__(self) -> None:
        self._stream_version = "61"

    def _configure_target_from_path(self, directory: Path) -> None:
        """Match XML headers to the selected gma2_V_3.9.xx library."""
        match = re.search(
            r"gma2_v_3\.9\.(\d+)",
            str(Path(directory)).replace("/", "\\"),
            flags=re.IGNORECASE,
        )
        self._stream_version = match.group(1) if match else "61"

    def _schema(self) -> str:
        return (
            "http://schemas.malighting.de/grandma2/xml/MA "
            "http://schemas.malighting.de/grandma2/xml/"
            f"3.9.{self._stream_version}/MA.xsd"
        )

    def export_plan_summary(self, plan: SongExportPlan) -> dict:
        return {
            "console": "ma2",
            "target_version": self.target_version,
            "song_name": plan.song_name,
            "export_mode": plan.profile.export_mode,
            "main_cue_count": len(plan.main_cues),
            "button_lane_count": len(plan.button_lanes),
            "button_event_count": sum(len(lane.mark_times_seconds) for lane in plan.button_lanes),
            "sequence_pool_start": plan.profile.sequence_pool_start,
            "timecode_pool": plan.profile.timecode_pool,
            "main_executor": plan.profile.main_executor,
            "ltc_latency_compensation_seconds": plan.profile.ltc_latency_compensation_seconds,
        }

    def export_to_directory(
        self,
        plan: SongExportPlan,
        directory: Path,
        *,
        include_plugin: bool = False,
        include_macro: bool = False,
    ) -> dict[str, Path]:
        self._configure_target_from_path(directory)
        import_dir, _plugins_dir, _macros_dir = resolve_ma2_pool_dirs(Path(directory))
        import_dir.mkdir(parents=True, exist_ok=True)
        paths: dict[str, Path] = {}

        if plan.profile.export_mode == "full":
            paths["main_sequence"] = import_dir / plan.profile.main_sequence_file
            self.write_main_sequence(plan, paths["main_sequence"])
            if plan.button_lanes:
                for lane in plan.button_lanes:
                    key = f"button_sequence_{lane.lane_index}"
                    path = import_dir / (lane.sequence_file or plan.profile.button_sequence_file)
                    paths[key] = path
                    self.write_button_sequence(
                        plan,
                        path,
                        sequence_name=lane.sequence_name,
                        sequence_pool=lane.sequence_pool or None,
                    )
                # Back-compat key for tests that look up the first button file.
                paths["button_sequence"] = paths[f"button_sequence_{plan.button_lanes[0].lane_index}"]
            if include_macro or include_plugin:
                install_paths = self.write_install_macro(plan, directory)
                paths.update(install_paths)
                if include_plugin:
                    paths.update(self.write_install_plugin(plan, directory))

        paths["timecode"] = import_dir / plan.profile.timecode_file
        self.write_timecode(plan, paths["timecode"])
        return paths

    def export_show_to_directory(
        self,
        plans: list[SongExportPlan],
        directory: Path,
        *,
        show_install_name: str = "CuePlayer_Show_Install",
        song_viewbutton: str = "1.20",
        include_fixed_macros: bool = True,
        include_song_macros: bool = True,
        include_song_list: bool = True,
        template_page: int = 100,
        fixed_macro_start: int = 1001,
        song_macro_start: int = 1009,
        add_main_preset_cue: bool = False,
        main_preset_cue_id: float = 0.5,
        include_song_views: bool = True,
        view_pool_start: int = 201,
        effect_pool_start: int = 201,
        sequence_slots_per_song: int = 20,
    ) -> dict[str, Path]:
        """
        Export Seq/TC files + CuePoints-style show Plugin.

        Plugin Stores all cues on the console, then writes one Timecode XML
        per song into importexport at runtime and Imports each (CuePoints flow).
        """
        if not plans:
            return {}
        directory = Path(directory)
        self._configure_target_from_path(directory)
        import_dir, _plugins_dir, _macros_dir = resolve_ma2_pool_dirs(directory)
        import_dir.mkdir(parents=True, exist_ok=True)
        all_paths: dict[str, Path] = {}
        for plan in plans:
            paths = self.export_to_directory(plan, directory, include_macro=False)
            prefix = plan.song_name or "song"
            for key, path in paths.items():
                all_paths[f"{prefix}:{key}"] = path

        if any(p.profile.export_mode == "full" for p in plans):
            plugin_paths = self.write_show_install_plugin(
                plans,
                directory,
                name=show_install_name,
                include_fixed_macros=include_fixed_macros,
                include_song_macros=include_song_macros,
                include_song_list=include_song_list,
                template_page=template_page,
                fixed_macro_start=fixed_macro_start,
                song_macro_start=song_macro_start,
                add_main_preset_cue=add_main_preset_cue,
                main_preset_cue_id=main_preset_cue_id,
                include_song_views=include_song_views,
                view_pool_start=view_pool_start,
                sequence_slots_per_song=sequence_slots_per_song,
            )
            all_paths["show:plugin_xml"] = plugin_paths["plugin_xml"]
            all_paths["show:plugin_lua"] = plugin_paths["plugin_lua"]
            if "macro_xml" in plugin_paths:
                all_paths["show:macro_xml"] = plugin_paths["macro_xml"]
            if include_song_list:
                all_paths["show:song_list"] = self.write_song_list_sequence(
                    plans,
                    directory,
                    name="CuePlayer Song List",
                    basename=f"{show_install_name}_Song_List",
                )
            if include_fixed_macros:
                all_paths["show:fixed_macros"] = self.write_song_change_macros(
                    plans,
                    directory,
                    basename=f"{show_install_name}_Fixed_Macros",
                    song_viewbutton=song_viewbutton,
                    include_fixed=True,
                    include_songs=False,
                )
            if include_song_macros:
                all_paths["show:song_macros"] = self.write_song_change_macros(
                    plans,
                    directory,
                    basename=f"{show_install_name}_Song_Macros",
                    song_viewbutton=song_viewbutton,
                    include_fixed=False,
                    include_songs=True,
                )
            if include_song_views:
                for index, plan in enumerate(plans):
                    all_paths[f"show:view_{index + 1}"] = self.write_song_view(
                        plan,
                        directory,
                        view_pool=int(view_pool_start) + index,
                        effect_pool_start=int(effect_pool_start) + index * 80,
                        basename=f"{show_install_name}_View_{index + 1}",
                    )
        return all_paths

    def write_song_list_sequence(
        self,
        plans: list[SongExportPlan],
        directory: Path,
        *,
        name: str = "CuePlayer Song List",
        basename: str = "CuePlayer_Song_List",
    ) -> Path:
        """Write the MA2 sequence used by Next/Previous/Jump To Song macros."""
        import_dir, _plugins_dir, _macros_dir = resolve_ma2_pool_dirs(Path(directory))
        import_dir.mkdir(parents=True, exist_ok=True)
        filename = sanitize_ma_name(basename, fallback="CuePlayer_Song_List")
        path = import_dir / f"{filename}.xml"
        root = self._root()
        self._info(root, name)
        sequ = ET.SubElement(
            root,
            f"{{{MA2_NS}}}Sequ",
            {
                "index": "0",
                # Keep spaces: the control macros deliberately resolve it with
                # the MA wildcard `"* Song List"`.
                "name": sanitize_ma_name(
                    name, fallback="CuePlayer_Song_List"
                ).replace("_", " "),
                "timecode_slot": "0",
            },
        )
        ET.SubElement(sequ, f"{{{MA2_NS}}}Cue", {"NIL_PLACEHOLDER": "true"})
        for index, plan in enumerate(plans, start=1):
            song_name = sanitize_ma_name(plan.song_name, fallback=f"Song{index}")
            cue = ET.SubElement(
                sequ, f"{{{MA2_NS}}}Cue", {"index": str(index - 1)}
            )
            ET.SubElement(
                cue,
                f"{{{MA2_NS}}}Number",
                {"number": str(index), "sub_number": "0"},
            )
            part = ET.SubElement(
                cue,
                f"{{{MA2_NS}}}CuePart",
                {"index": "0", "name": song_name},
            )
            macro_text = ET.SubElement(part, f"{{{MA2_NS}}}macro_text")
            macro_text.text = f'Macro "{song_name}"'
        write_xml(root, path, default_namespace=MA2_NS)
        self._fix_ma2_xsi(path)
        return path

    def write_song_change_macros(
        self,
        plans: list[SongExportPlan],
        directory: Path,
        *,
        basename: str = "CuePlayer_Song_Change",
        song_viewbutton: str = "1.20",
        include_fixed: bool = True,
        include_songs: bool = True,
    ) -> Path:
        """Write the user's MA2 Song Change workflow plus one macro per song."""
        _import_dir, _plugins_dir, macros_dir = resolve_ma2_pool_dirs(Path(directory))
        macros_dir.mkdir(parents=True, exist_ok=True)
        safe_base = sanitize_ma_name(basename, fallback="CuePlayer_Song_Change")
        path = macros_dir / f"{safe_base}.xml"
        viewbutton = str(song_viewbutton or "1.20").strip()
        viewbutton_parts = viewbutton.split(".")
        if len(viewbutton_parts) != 2 or not all(
            part.isdigit() for part in viewbutton_parts
        ):
            raise ValueError("MA2 Song ViewButton must look like 1.20")
        fixed_definitions: list[tuple[str, list[str]]] = [
            (
                "Show Begin",
                [
                    "ClearAll",
                    'Top Executor "* Template Page"."* Song List"',
                    'View "Show"',
                ],
            ),
            ("Go To Template Page", ['Page "* Template Page"']),
            ("Go To Song Page", ['Page $"Song"']),
            ("Jump To Song", ['Load Executor "* Template Page"."* Song List"']),
            ("Previous Song", ['GoBack Executor "* TEMPLATE PAGE"."* Song List"']),
            ("Next Song", ['Go Executor "* TEMPLATE PAGE"."* Song List"']),
            (
                "Page Change",
                [
                    'Page $"Song"',
                    'Off Page 1 Thru - Page "* TEMPLATE PAGE"',
                    'Off Timecode 1 Thru',
                    '<<< Timecode 1 Thru',
                    'Select Executor $"song"',
                    'Goto Cue "Preset"',
                    'Assign View $"song" At ViewButton $songviewbutton',
                    'SpecialMaster 3.1 At $songbpm',
                    'Select Timecode $"song"',
                    'Go Timecode $"song"',
                    'On SpecialMaster 3.1',
                ],
            ),
            ("Set Songviewbutton", [f'SetVar $songviewbutton = {viewbutton}']),
        ]
        song_definitions: list[tuple[str, list[str]]] = []
        for index, plan in enumerate(plans, start=1):
            song_name = sanitize_ma_name(plan.song_name, fallback=f"Song{index}")
            bpm = f"{float(plan.song_bpm):g}"
            song_definitions.append(
                (
                    song_name,
                    [
                        f'SetVar $song = "{song_name}"',
                        f"SetVar $songbpm = {bpm}",
                        'Macro "PAGE CHANGE"',
                    ],
                )
            )

        definitions = (
            (fixed_definitions if include_fixed else [])
            + (song_definitions if include_songs else [])
        )
        root = self._root()
        self._info(root, safe_base)
        for macro_index, (macro_name, commands) in enumerate(definitions):
            macro = ET.SubElement(
                root,
                f"{{{MA2_NS}}}Macro",
                {"index": str(macro_index), "name": macro_name},
            )
            for line_index, command in enumerate(commands):
                line = ET.SubElement(
                    macro,
                    f"{{{MA2_NS}}}Macroline",
                    {"index": str(line_index)},
                )
                ET.SubElement(line, f"{{{MA2_NS}}}text").text = command
        write_xml(root, path, default_namespace=MA2_NS)
        self._fix_ma2_xsi(path)
        return path

    def write_song_view(
        self,
        plan: SongExportPlan,
        directory: Path,
        *,
        view_pool: int,
        effect_pool_start: int,
        basename: str,
    ) -> Path:
        """Write the supplied Screen 3 song-pool layout as an importable View."""
        import_dir, _plugins_dir, _macros_dir = resolve_ma2_pool_dirs(Path(directory))
        import_dir.mkdir(parents=True, exist_ok=True)
        safe_base = sanitize_ma_name(basename, fallback=f"CuePlayer_View_{view_pool}")
        path = import_dir / f"{safe_base}.xml"
        root = self._root()
        view_name = sanitize_ma_name(plan.song_name, fallback=f"Song{view_pool}")
        self._info(root, view_name)
        view = ET.SubElement(
            root,
            f"{{{MA2_NS}}}View",
            {
                "index": "0",
                "name": view_name,
                "display_mask": "4",
            },
        )

        def add_widget(index: int, widget_type: str, **attrs: str) -> None:
            widget_attrs = {
                "index": str(index),
                "type": widget_type,
                "display_nr": "2",
                **attrs,
            }
            widget = ET.SubElement(view, f"{{{MA2_NS}}}Widget", widget_attrs)
            data = ET.SubElement(widget, f"{{{MA2_NS}}}Data")
            values = ("0", "0", "0", "3") if widget_type == "4d414352" else (
                "0",
                "1",
                "0",
                "3",
            )
            for value in values:
                ET.SubElement(data, f"{{{MA2_NS}}}Data").text = value

        # Template Effect page (1...) and Macro row are fixed for every song.
        add_widget(0, "454e4749", y="6", anz_rows="2", anz_cols="16")
        # Song Effect page: the reference layout shows 5 x 16 = 80 pool slots.
        effect_scroll = max(0, int(effect_pool_start) - 81)
        add_widget(
            1,
            "454e4749",
            y="1",
            anz_rows="5",
            anz_cols="16",
            scroll_offset=str(effect_scroll),
            scroll_index=str(effect_scroll),
        )
        # Sequence row starts on the song's allocated Main Sequence.
        sequence_scroll = max(0, int(plan.profile.sequence_pool_start) - 4)
        add_widget(
            2,
            "53455155",
            anz_rows="1",
            anz_cols="10",
            scroll_offset=str(sequence_scroll),
            scroll_index=str(sequence_scroll),
        )
        add_widget(
            3,
            "4d414352",
            has_focus="true",
            has_scrollfocus="true",
            x="10",
            anz_rows="1",
            anz_cols="6",
        )
        write_xml(root, path, default_namespace=MA2_NS)
        self._fix_ma2_xsi(path)
        return path

    def _fix_ma2_xsi(self, path: Path) -> None:
        text = path.read_text(encoding="utf-8")
        text = text.replace('NIL_PLACEHOLDER="true"', 'xsi:nil="true"')
        if "xmlns:xsi=" not in text:
            text = text.replace(
                "<MA ",
                '<MA xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" ',
                1,
            )
        path.write_text(text, encoding="utf-8")

    def _root(self) -> ET.Element:
        return ET.Element(
            f"{{{MA2_NS}}}MA",
            {
                f"{{{MA2_XSI}}}schemaLocation": self._schema(),
                "major_vers": "3",
                "minor_vers": "9",
                "stream_vers": self._stream_version,
            },
        )

    def _info(self, root: ET.Element, showfile: str) -> None:
        ET.SubElement(
            root,
            f"{{{MA2_NS}}}Info",
            {
                "datetime": datetime.now().replace(microsecond=0).isoformat(),
                "showfile": showfile,
            },
        )

    def write_main_sequence(self, plan: SongExportPlan, path: Path) -> None:
        root = self._root()
        self._info(root, plan.song_name)
        # CuePoints / MA2 Import At Sequence N: keep @index=0; destination is At N.
        sequ = ET.SubElement(
            root,
            f"{{{MA2_NS}}}Sequ",
            {
                "index": "0",
                "name": plan.profile.main_sequence_name,
                "timecode_slot": "255",
                "forced_position_mode": "0",
            },
        )
        ET.SubElement(sequ, f"{{{MA2_NS}}}Cue", {"NIL_PLACEHOLDER": "true"})
        for index, cue in enumerate(plan.main_cues, start=1):
            major, sub = split_ma_cue_number(cue.cue_number)
            cue_el = ET.SubElement(sequ, f"{{{MA2_NS}}}Cue", {"index": str(index)})
            ET.SubElement(
                cue_el,
                f"{{{MA2_NS}}}Number",
                {"number": str(major), "sub_number": str(sub)},
            )
            # Golden MA2 Seq XML has bare CuePart — CuePart/@name can fail Import
            # and leave an empty Sequence. Cue labels stay out of MA2 XML.
            ET.SubElement(cue_el, f"{{{MA2_NS}}}CuePart", {"index": "0"})

        write_xml(
            root,
            path,
            default_namespace=MA2_NS,
            stylesheet_hrefs=[
                "styles/sequ@html@default.xsl",
                "styles/sequ@executorsheet.xsl",
                "styles/sequ@trackingsheet.xsl",
            ],
        )
        self._fix_ma2_xsi(path)

    def write_button_sequence(
        self,
        plan: SongExportPlan,
        path: Path,
        *,
        sequence_name: str | None = None,
        sequence_pool: int | None = None,
    ) -> None:
        root = self._root()
        self._info(root, plan.song_name)
        # sequence_pool kept for API compat; install uses Store not Import.
        sequ = ET.SubElement(
            root,
            f"{{{MA2_NS}}}Sequ",
            {
                "index": "0",
                "name": sequence_name or plan.profile.button_sequence_name,
                "timecode_slot": "255",
                "forced_position_mode": "0",
            },
        )
        ET.SubElement(sequ, f"{{{MA2_NS}}}Cue", {"NIL_PLACEHOLDER": "true"})
        cue1 = ET.SubElement(sequ, f"{{{MA2_NS}}}Cue", {"index": "1"})
        ET.SubElement(cue1, f"{{{MA2_NS}}}Number", {"number": "1", "sub_number": "0"})
        ET.SubElement(cue1, f"{{{MA2_NS}}}CuePart", {"index": "0"})

        cue2 = ET.SubElement(
            sequ,
            f"{{{MA2_NS}}}Cue",
            {"index": "2", "cue_mode": "Release"},
        )
        ET.SubElement(cue2, f"{{{MA2_NS}}}Number", {"number": "2", "sub_number": "0"})
        ET.SubElement(
            cue2,
            f"{{{MA2_NS}}}Trigger",
            {
                "type": "Follow",
                "data_f": f"{plan.profile.button_follow_seconds:g}",
            },
        )
        ET.SubElement(
            cue2,
            f"{{{MA2_NS}}}CuePart",
            {"index": "0", "basic_fade": "0.5"},
        )

        write_xml(
            root,
            path,
            default_namespace=MA2_NS,
            stylesheet_hrefs=[
                "styles/sequ@html@default.xsl",
                "styles/sequ@executorsheet.xsl",
                "styles/sequ@trackingsheet.xsl",
            ],
        )
        self._fix_ma2_xsi(path)

    def write_timecode(self, plan: SongExportPlan, path: Path) -> None:
        root = self._root()
        self._info(root, plan.song_name)

        length = _timecode_length_frames(plan)
        frame_format = ma2_timecode_frame_format(plan.profile.fps)

        # CuePoints Timecode shape (from their live Plugin export):
        # - Object name = sequence name only
        # - Object Nos = 30, pagepool(1), page, executor
        # - Cue Nos = 1, sequence_pool, cue_number
        # - Top events have no step=; no Master SubTrack
        # @index always 0 — Import At Timecode N sets the pool (CuePoints style).
        # Event times + lenght are FPS frames (MA default TimeUnit on Import).
        # record_mode=Go → Timecode Options «Record Mode» = Go (not Goto).
        tc_attrs = {
            "index": "0",
            "name": plan.profile.timecode_name,
            "lenght": str(length),
            "frame_format": frame_format,
            "stop_status": "Rewind",
            "no_switch_off": "true",
            "no_status_call": "true",
            "record_mode": "Go",
        }
        tc = ET.SubElement(root, f"{{{MA2_NS}}}Timecode", tc_attrs)

        page_pool = 1  # CuePoints: Assign At Page 1.{page}.{exec}
        main_page, main_exec = parse_page_executor(plan.profile.main_executor)
        main_seq = int(plan.profile.sequence_pool_start)

        main_track = ET.SubElement(
            tc,
            f"{{{MA2_NS}}}Track",
            {"index": "0", "active": "true", "expanded": "true"},
        )
        obj = ET.SubElement(
            main_track,
            f"{{{MA2_NS}}}Object",
            {"name": plan.profile.main_sequence_name},
        )
        for value in (30, page_pool, main_page, main_exec):
            no = ET.SubElement(obj, f"{{{MA2_NS}}}No")
            no.text = str(value)

        main_sub = ET.SubElement(main_track, f"{{{MA2_NS}}}SubTrack", {"index": "0"})
        for idx, cue in enumerate(plan.main_cues, start=1):
            frames = _rel_event_frames(plan, cue.time_seconds)
            link_name = format_ma2_cue_link_name(cue.cue_number)
            event = ET.SubElement(
                main_sub,
                f"{{{MA2_NS}}}Event",
                {
                    "index": str(idx - 1),
                    "time": str(frames),
                    "command": "Go",
                    "pressed": "true",
                    # Do not put Store-order index in step — Import invents Cue 45…N.
                    "step": MA2_TC_STEP_NONE,
                },
            )
            cue_el = ET.SubElement(event, f"{{{MA2_NS}}}Cue", {"name": link_name})
            for value in ma2_timecode_cue_nos(main_seq, idx):
                no = ET.SubElement(cue_el, f"{{{MA2_NS}}}No")
                no.text = str(value)

        for lane_i, lane in enumerate(plan.button_lanes, start=1):
            track = ET.SubElement(
                tc,
                f"{{{MA2_NS}}}Track",
                {"index": str(lane_i), "active": "true", "expanded": "true"},
            )
            button_page, button_exec = parse_page_executor(lane.executor)
            button_name = lane.sequence_name or lane.resolved_ma_name()
            obj = ET.SubElement(track, f"{{{MA2_NS}}}Object", {"name": button_name})
            for value in (30, page_pool, button_page, button_exec):
                no = ET.SubElement(obj, f"{{{MA2_NS}}}No")
                no.text = str(value)
            sub = ET.SubElement(track, f"{{{MA2_NS}}}SubTrack", {"index": "0"})
            for event_i, t in enumerate(lane.mark_times_seconds):
                frames = _rel_event_frames(plan, t)
                ET.SubElement(
                    sub,
                    f"{{{MA2_NS}}}Event",
                    {
                        "index": str(event_i),
                        "time": str(frames),
                        "command": "Top",
                        "pressed": "true",
                    },
                )

        write_xml(
            root,
            path,
            default_namespace=MA2_NS,
            stylesheet_hrefs=["styles/timecode@sheet.xsl"],
        )
        self._fix_ma2_xsi(path)

    def install_commands_for_plan(
        self,
        plan: SongExportPlan,
        *,
        add_main_preset_cue: bool = False,
        main_preset_cue_id: float = 0.5,
    ) -> list[str]:
        """
        CuePoints-style setup for one song (no Timecode Import).

        Main + Button cues are created with Store (Import XML left Reset_0 Main
        empty). Timecode is written/imported later by the show Plugin.
        """
        main_seq = plan.profile.sequence_pool_start
        main_page, main_exec = parse_page_executor(plan.profile.main_executor)
        page_name = sanitize_ma_name(
            plan.profile.page_name or plan.song_name or "",
            fallback="",
        )
        page_pool = 1
        follow = f"{plan.profile.button_follow_seconds:g}"

        cmd_lines: list[str] = [
            f"Store Page {main_page}",
            f"Page {main_page}",
            f"FaderPage {main_page}",
            f"ButtonPage {main_page}",
        ]
        if page_name:
            cmd_lines.append(f'Label Page {main_page} "{page_name}"')

        # Main cues — Store like CuePoints (not Import XML).
        for cue in plan.main_cues:
            cue_label_no = format_ma_cue_number(cue.cue_number)
            label = _ma2_store_cue_label(cue)
            link_name = format_ma2_cue_link_name(cue.cue_number)
            if label:
                cmd_lines.append(
                    f'Store Sequence {main_seq} Cue {cue_label_no} "{label}" /noconfirm'
                )
            else:
                # Empty "" clears the default name; Timecode Event looks up
                # Cue name=link_name and will not link if the cue is unnamed
                # or wrongly titled Cue_15 from a sequential placeholder.
                cmd_lines.append(
                    f"Store Sequence {main_seq} Cue {cue_label_no} /noconfirm"
                )
                cmd_lines.append(
                    f'Label Sequence {main_seq} Cue {cue_label_no} "{link_name}"'
                )
        if add_main_preset_cue:
            preset_id = format_ma_cue_number(float(main_preset_cue_id))
            existing_ids = {
                format_ma_cue_number(cue.cue_number) for cue in plan.main_cues
            }
            if preset_id in existing_ids:
                raise ValueError(
                    f'MA2 Main Preset Cue ID {preset_id} conflicts with an existing '
                    f'cue in "{plan.song_name}"'
                )
            cmd_lines.append(
                f'Store Sequence {main_seq} Cue {preset_id} "Preset" /noconfirm'
            )
        cmd_lines.extend(
            [
                f'Label Sequence {main_seq} "{plan.profile.main_sequence_name}"',
                f"Assign Sequence {main_seq} At Page {page_pool}.{main_page}.{main_exec}",
            ]
        )

        for lane in plan.button_lanes:
            seq_pool = lane.sequence_pool or (main_seq + 1)
            seq_name = lane.sequence_name or plan.profile.button_sequence_name
            b_page, b_exec = parse_page_executor(lane.executor)
            cmd_lines.extend(
                [
                    f'Store Sequence {seq_pool} Cue 1 "" /noconfirm',
                    f'Store Sequence {seq_pool} Cue 2 "follow" /noconfirm',
                    f"Assign Sequence {seq_pool} Cue 2 /Mode=Release",
                    f"Assign Sequence {seq_pool} Cue 2 /Trig=Time",
                    f"Assign Sequence {seq_pool} Cue 2 /TrigTime={follow}",
                    f"Assign Sequence {seq_pool} Cue 1 Fade 0",
                    f"Assign Sequence {seq_pool} Cue 2 Fade 0.5",
                    f'Label Sequence {seq_pool} "{seq_name}"',
                    f"Assign Sequence {seq_pool} At Page {page_pool}.{b_page}.{b_exec}",
                    f"Assign Top Executor {b_page}.{b_exec}",
                ]
            )
        return cmd_lines

    def build_show_timecode_xml(
        self,
        plans: list[SongExportPlan],
        *,
        name: str = "CuePlayer_TC",
    ) -> str:
        """
        CuePoints-style Timecode XML string for one or more plans.

        Show install uses one plan per call (one Timecode pool per song).
        Event times are song-relative frames at profile FPS; song start LTC
        is applied later via Assign /Offset. Object Nos = 30,1,page,exec.
        Cue Nos = 1, seq, cue_index (1-based Store order — not Cue ID).
        """
        full = [p for p in plans if p.profile.export_mode == "full"]
        if not full:
            return ""
        page_pool = 1
        track_i = 0
        max_frames = 0
        tracks: list[str] = []
        # All plans in one XML share one frame format (first plan wins).
        frame_format = ma2_timecode_frame_format(full[0].profile.fps)

        for plan in full:
            main_page, main_exec = parse_page_executor(plan.profile.main_executor)
            main_seq = int(plan.profile.sequence_pool_start)
            seq_name = _xml_esc(plan.profile.main_sequence_name)
            events: list[str] = []
            for idx, cue in enumerate(plan.main_cues, start=1):
                frames = _rel_event_frames(plan, cue.time_seconds)
                max_frames = max(max_frames, frames)
                link_name = _xml_esc(format_ma2_cue_link_name(cue.cue_number))
                nos = "".join(
                    f"<No>{value}</No>" for value in ma2_timecode_cue_nos(main_seq, idx)
                )
                events.append(
                    f'<Event index="{idx - 1}" time="{frames}" command="Go" '
                    f'pressed="true" step="{MA2_TC_STEP_NONE}">'
                    f'<Cue name="{link_name}">{nos}</Cue></Event>'
                )
            tracks.append(
                f'<Track index="{track_i}" active="true" expanded="true">'
                f'<Object name="{seq_name}"><No>30</No><No>{page_pool}</No>'
                f"<No>{main_page}</No><No>{main_exec}</No></Object>"
                f'<SubTrack index="0">{"".join(events)}</SubTrack></Track>'
            )
            track_i += 1
            max_frames = max(max_frames, _timecode_length_frames(plan))

            for lane in plan.button_lanes:
                b_page, b_exec = parse_page_executor(lane.executor)
                b_name = _xml_esc(lane.sequence_name or lane.resolved_ma_name())
                bevents: list[str] = []
                for event_i, t in enumerate(lane.mark_times_seconds):
                    frames = _rel_event_frames(plan, t)
                    max_frames = max(max_frames, frames)
                    bevents.append(
                        f'<Event index="{event_i}" time="{frames}" '
                        f'command="Top" pressed="true"/>'
                    )
                tracks.append(
                    f'<Track index="{track_i}" active="true" expanded="true">'
                    f'<Object name="{b_name}"><No>30</No><No>{page_pool}</No>'
                    f"<No>{b_page}</No><No>{b_exec}</No></Object>"
                    f'<SubTrack index="0">{"".join(bevents)}</SubTrack></Track>'
                )
                track_i += 1

        tc_name = _xml_esc(name)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<MA xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            f'xmlns="{MA2_NS}" '
            f'xsi:schemaLocation="{self._schema()}" '
            f'major_vers="3" minor_vers="9" stream_vers="{self._stream_version}">'
            f'<Info datetime="{datetime.now().replace(microsecond=0).isoformat()}" '
            f'showfile="{tc_name}"/>'
            f'<Timecode index="0" name="{tc_name}" '
            f'lenght="{max_frames}" frame_format="{frame_format}" '
            f'stop_status="Rewind" no_switch_off="true" '
            f'no_status_call="true" record_mode="Go">'
            f'{"".join(tracks)}</Timecode></MA>'
        )

    def write_install_macro(self, plan: SongExportPlan, directory: Path) -> dict[str, Path]:
        """Write one-song setup Macro (Store/Assign + Timecode Offset)."""
        cmd_lines = self.install_commands_for_plan(plan)
        cmd_lines.extend(
            ma2_timecode_assign_settings(
                plan.profile,
                length_seconds=timecode_span_seconds(plan),
            )
        )
        path = self._write_macro_xml(
            directory,
            basename=_install_basename(plan),
            display_name=f"CuePlayer {_install_basename(plan)}",
            cmd_lines=cmd_lines,
            info_name=plan.song_name,
        )
        return {"macro_xml": path}

    def write_show_install_macro(
        self,
        plans: list[SongExportPlan],
        directory: Path,
        *,
        name: str = "CuePlayer_Show_Install",
    ) -> Path:
        """Setup-only Macro (prefer Plugin for Timecode Import)."""
        cmd_lines: list[str] = []
        for plan in plans:
            if plan.profile.export_mode != "full":
                continue
            cmd_lines.extend(self.install_commands_for_plan(plan))
        return self._write_macro_xml(
            directory,
            basename=name,
            display_name=name,
            cmd_lines=cmd_lines,
            info_name=name,
        )

    def write_install_plugin(self, plan: SongExportPlan, directory: Path) -> dict[str, Path]:
        """Single-song CuePoints-style Plugin (Store/Assign + runtime TC Import)."""
        base = _install_basename(plan)
        tc_label = plan.profile.timecode_name or base
        return self._write_plugin_pair(
            directory,
            basename=base,
            display_name=f"CuePlayer {base}",
            cmd_lines=self.install_commands_for_plan(plan),
            info_name=plan.song_name,
            echo_note=f"CuePlayer: Seq {plan.profile.sequence_pool_start}",
            timecode_jobs=[
                (
                    self.build_show_timecode_xml([plan], name=tc_label),
                    int(plan.profile.timecode_pool),
                    f"{base}_TC",
                    tc_label,
                    float(plan.profile.start_offset_seconds),
                    float(plan.profile.fps or 30.0),
                    int(plan.profile.timecode_slot),
                    int(plan.profile.sequence_pool_start),
                    *(ma2_phantom_cue_delete_range(plan) or (0, 0)),
                    float(timecode_span_seconds(plan)),
                )
            ],
        )

    def write_show_install_plugin(
        self,
        plans: list[SongExportPlan],
        directory: Path,
        *,
        name: str = "CuePlayer_Show_Install",
        include_fixed_macros: bool = True,
        include_song_macros: bool = True,
        include_song_list: bool = True,
        template_page: int = 100,
        fixed_macro_start: int = 1001,
        song_macro_start: int = 1009,
        add_main_preset_cue: bool = False,
        main_preset_cue_id: float = 0.5,
        include_song_views: bool = True,
        view_pool_start: int = 201,
        sequence_slots_per_song: int = 20,
    ) -> dict[str, Path]:
        """
        CuePoints-style show Plugin: Store/Assign everything, then write+Import
        one Timecode XML per song (separate TC pools) and Assign /Offset.
        """
        cmd_lines: list[str] = []
        tc_jobs: list[tuple[str, int, str, str, float, float, int, int, int, int, float]] = []
        for plan in plans:
            if plan.profile.export_mode != "full":
                continue
            cmd_lines.extend(
                self.install_commands_for_plan(
                    plan,
                    add_main_preset_cue=add_main_preset_cue,
                    main_preset_cue_id=main_preset_cue_id,
                )
            )
            tc_label = plan.profile.timecode_name or plan.song_name or f"TC{plan.profile.timecode_pool}"
            song_stem = sanitize_ma_name(
                Path(plan.profile.timecode_file).stem or plan.song_name or "TC",
                fallback=f"TC{plan.profile.timecode_pool}",
            ).replace(" ", "_")
            phantom = ma2_phantom_cue_delete_range(plan) or (0, 0)
            tc_jobs.append(
                (
                    self.build_show_timecode_xml([plan], name=tc_label),
                    int(plan.profile.timecode_pool),
                    f"{name}_TC_{song_stem}",
                    tc_label,
                    float(plan.profile.start_offset_seconds),
                    float(plan.profile.fps or 30.0),
                    int(plan.profile.timecode_slot),
                    int(plan.profile.sequence_pool_start),
                    int(phantom[0]),
                    int(phantom[1]),
                    float(timecode_span_seconds(plan)),
                )
            )
        setup_cmd_lines = list(cmd_lines)
        safe_name = sanitize_ma_name(name, fallback="CuePlayer_Show_Install")
        extra_imports: list[str] = []
        if include_fixed_macros or include_song_macros or include_song_list:
            extra_imports.append("SelectDrive 1")
        if include_fixed_macros:
            extra_imports.append(
                f'Import "{safe_name}_Fixed_Macros" At Macro {int(fixed_macro_start)} '
                '/path="macros"'
            )
        if include_song_macros:
            extra_imports.append(
                f'Import "{safe_name}_Song_Macros" At Macro {int(song_macro_start)} '
                '/path="macros"'
            )
        if include_song_list:
            sequence_pools = [int(p.profile.sequence_pool_start) for p in plans]
            sequence_pools.extend(
                int(lane.sequence_pool)
                for plan in plans
                for lane in plan.button_lanes
                if lane.sequence_pool
            )
            reserved_ends = [
                int(plan.profile.sequence_pool_start)
                + max(int(sequence_slots_per_song), 1 + len(plan.button_lanes))
                - 1
                for plan in plans
            ]
            sequence_pools.extend(reserved_ends)
            song_list_pool = max(sequence_pools, default=0) + 1
            page = max(1, int(template_page))
            extra_imports.extend(
                [
                    f'Store Page {page}',
                    f'Label Page {page} "CuePlayer Template Page"',
                    f'Import "{safe_name}_Song_List" At Sequence {song_list_pool}',
                    f'Label Sequence {song_list_pool} "CuePlayer Song List"',
                    f'Assign Sequence {song_list_pool} At Page 1.{page}.130',
                    f'Page {page}',
                    f'Label Executor {page}.130 "CuePlayer Song List"',
                ]
            )
        if include_song_views:
            for index, plan in enumerate(plans):
                view_pool = int(view_pool_start) + index
                view_name = sanitize_ma_name(
                    plan.song_name, fallback=f"Song{index + 1}"
                )
                extra_imports.extend(
                    [
                        f'Import "{safe_name}_View_{index + 1}" At View {view_pool}',
                        f'Label View {view_pool} "{view_name}"',
                    ]
                )
        cmd_lines.extend(extra_imports)
        paths = self._write_plugin_pair(
            directory,
            basename=name,
            display_name=name,
            cmd_lines=cmd_lines,
            info_name=name,
            echo_note=f"CuePlayer show install: {len(tc_jobs)} Timecode(s)",
            timecode_jobs=tc_jobs,
            final_cmd_lines=(
                ['Macro "Set Songviewbutton"'] if include_fixed_macros else []
            ),
        )
        # Keep a setup-only macro as backup (no TC Import / Offset).
        paths["macro_xml"] = self._write_macro_xml(
            directory,
            basename=name,
            display_name=f"{name}_SetupOnly",
            cmd_lines=setup_cmd_lines,
            info_name=name,
        )
        return paths

    def _write_macro_xml(
        self,
        directory: Path,
        *,
        basename: str,
        display_name: str,
        cmd_lines: list[str],
        info_name: str,
    ) -> Path:
        _import_dir, _plugins_dir, macros_dir = resolve_ma2_pool_dirs(Path(directory))
        macros_dir.mkdir(parents=True, exist_ok=True)
        macro_xml_path = macros_dir / f"{basename}_install_macro.xml"

        macro_root = self._root()
        self._info(macro_root, info_name)
        macro = ET.SubElement(
            macro_root,
            f"{{{MA2_NS}}}Macro",
            {"index": "0", "name": display_name},
        )
        for i, line in enumerate(cmd_lines):
            macroline = ET.SubElement(macro, f"{{{MA2_NS}}}Macroline", {"index": str(i)})
            text = ET.SubElement(macroline, f"{{{MA2_NS}}}text")
            text.text = line
        write_xml(macro_root, macro_xml_path, default_namespace=MA2_NS)
        self._fix_ma2_xsi(macro_xml_path)
        return macro_xml_path

    def _write_plugin_pair(
        self,
        directory: Path,
        *,
        basename: str,
        display_name: str,
        cmd_lines: list[str],
        info_name: str,
        echo_note: str,
        timecode_jobs: list[
            tuple[str, int, str, str, float, float, int, int, int, int, float]
        ]
        | None = None,
        final_cmd_lines: list[str] | None = None,
    ) -> dict[str, Path]:
        """Write Plugin XML + Lua.

        timecode_jobs: (xml, pool, import_stem, label, start_offset_seconds, fps,
        slot, sequence_pool, phantom_cue_lo, phantom_cue_hi, length_seconds)
        — one entry per Timecode. Options + Offset + Length are Assigned after Import.
        phantom_cue_lo/hi are 0 when no Delete is needed.
        """
        _import_dir, plugins_dir, _macros_dir = resolve_ma2_pool_dirs(Path(directory))
        plugins_dir.mkdir(parents=True, exist_ok=True)

        lua_name = f"{basename}_export.lua"
        lua_path = plugins_dir / lua_name
        plugin_xml_path = plugins_dir / f"{basename}_export.xml"

        lua_cmds = "\n".join(_lua_cmd_line(line) for line in cmd_lines)
        jobs = list(timecode_jobs or [])
        if jobs:
            # CuePoints: write each TC after assigns, Import (no .xml), delete temp,
            # then Assign Timecode options + Offset (events stay relative).
            parts: list[str] = [
                "",
                "  gma.cmd('SelectDrive 1')",
                "  gma.sleep(0.5)",
                "  local path = gma.show.getvar('PATH')",
                "  local slash = package.config:sub(1,1)",
                "  local ie = path..slash..'importexport'..slash",
            ]
            for (
                tc_xml,
                tc_pool,
                tc_stem,
                tc_label,
                start_offset,
                fps,
                tc_slot,
                seq_pool,
                phantom_lo,
                phantom_hi,
                length_seconds,
            ) in jobs:
                tc_escaped = tc_xml.replace("\\", "\\\\").replace("'", "\\'")
                label = sanitize_ma_name(tc_label, fallback=f"TC{tc_pool}")
                job_profile = MaExportProfile(
                    console="ma2",
                    timecode_pool=int(tc_pool),
                    timecode_slot=int(tc_slot),
                    start_offset_seconds=float(start_offset),
                    fps=float(fps),
                )
                # TimeUnit after Import is fine for FPS frame XML (MA default on
                # empty Import is 30 FPS). Do NOT Store Timecode first — that
                # creates an empty "Timecode N" and Import then prompts Overwrite
                # even when the pool slot was empty.
                assign_cmds = ma2_timecode_assign_settings(
                    job_profile,
                    length_seconds=float(length_seconds),
                )
                assign_lines = "\n".join(
                    "    " + _lua_cmd_line(cmd).lstrip() for cmd in assign_cmds
                )
                phantom_lines = ""
                if int(phantom_lo) > 0 and int(phantom_hi) >= int(phantom_lo):
                    phantom_lines = (
                        f"\n    gma.cmd('Delete Sequence {int(seq_pool)} "
                        f"Cue {int(phantom_lo)} Thru {int(phantom_hi)} /nc')"
                    )
                parts.append(
                    f"""
  do
    local tcname = '{_lua_str(tc_stem)}'
    local tcfile = ie..tcname..'.xml'
    local tcxml = io.open(tcfile, 'w')
    tcxml:write('{tc_escaped}')
    tcxml:close()
    -- Import into the pool slot directly (no Store — avoids Overwrite on empty).
    gma.cmd('Import "'..tcname..'" At Timecode {int(tc_pool)}')
    gma.sleep(0.5)
    os.remove(tcfile)
    gma.cmd('Label Timecode {int(tc_pool)} "{_lua_str(label)}"')
{assign_lines}{phantom_lines}
  end"""
                )
            tc_block = "\n".join(parts)
        else:
            tc_block = ""
        final_lua_cmds = "\n".join(
            _lua_cmd_line(line) for line in (final_cmd_lines or [])
        )

        lua = f"""-- CuePlayer MA2 install plugin (CuePoints-style)
-- Store/Assign sequences, then write+Import one Timecode per song + Offset.
local function Start()
{lua_cmds}
{tc_block}
{final_lua_cmds}
  gma.echo("{_lua_str(echo_note)}")
end

return Start
"""
        lua_path.write_text(lua, encoding="utf-8")

        plugin_root = self._root()
        self._info(plugin_root, info_name)
        ET.SubElement(
            plugin_root,
            f"{{{MA2_NS}}}Plugin",
            {
                "index": "0",
                "execute_on_load": "0",
                "name": display_name,
                "luafile": lua_name,
            },
        )
        write_xml(plugin_root, plugin_xml_path, default_namespace=MA2_NS)
        self._fix_ma2_xsi(plugin_xml_path)

        return {
            "plugin_xml": plugin_xml_path,
            "plugin_lua": lua_path,
        }
