"""grandMA2 exporter — Sequence + Timecode XML generation."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import xml.etree.ElementTree as ET

from cueplayer.exporters.common import SongExportPlan, export_event_time_seconds, parse_page_executor
from cueplayer.exporters.xml_write import (
    MA2_NS,
    MA2_XSI,
    seconds_to_ma2_frames,
    write_xml,
)

MA2_TARGET_VERSION = "3.9.61.5"
MA2_SCHEMA = "http://schemas.malighting.de/grandma2/xml/MA http://schemas.malighting.de/grandma2/xml/3.9.61/MA.xsd"


class Ma2Exporter:
    target_version = MA2_TARGET_VERSION

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

    def export_to_directory(self, plan: SongExportPlan, directory: Path) -> dict[str, Path]:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        paths: dict[str, Path] = {}

        if plan.profile.export_mode == "full":
            paths["main_sequence"] = directory / "main_sequence.xml"
            paths["button_sequence"] = directory / "button_sequence.xml"
            self.write_main_sequence(plan, paths["main_sequence"])
            self.write_button_sequence(plan, paths["button_sequence"])
            plugin_paths = self.write_install_plugin(plan, directory)
            paths.update(plugin_paths)

        paths["timecode"] = directory / "timecode.xml"
        self.write_timecode(plan, paths["timecode"])
        return paths

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
                f"{{{MA2_XSI}}}schemaLocation": MA2_SCHEMA,
                "major_vers": "3",
                "minor_vers": "9",
                "stream_vers": "61",
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
        for cue in plan.main_cues:
            cue_el = ET.SubElement(sequ, f"{{{MA2_NS}}}Cue", {"index": str(int(cue.cue_number))})
            ET.SubElement(
                cue_el,
                f"{{{MA2_NS}}}Number",
                {"number": str(int(cue.cue_number)), "sub_number": "0"},
            )
            part = ET.SubElement(cue_el, f"{{{MA2_NS}}}CuePart", {"index": "0"})
            label = cue.resolved_ma_name()
            if label and not label.startswith("Cue"):
                part.set("name", label)

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

    def write_button_sequence(self, plan: SongExportPlan, path: Path) -> None:
        root = self._root()
        self._info(root, plan.song_name)
        sequ = ET.SubElement(
            root,
            f"{{{MA2_NS}}}Sequ",
            {
                "index": "1",
                "name": plan.profile.button_sequence_name,
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
        fps = plan.profile.fps

        event_frames: list[int] = []
        for cue in plan.main_cues:
            event_frames.append(
                seconds_to_ma2_frames(export_event_time_seconds(cue.time_seconds, plan.profile), fps)
            )
        for lane in plan.button_lanes:
            for t in lane.mark_times_seconds:
                event_frames.append(
                    seconds_to_ma2_frames(export_event_time_seconds(t, plan.profile), fps)
                )
        length = max(event_frames) if event_frames else 0

        tc = ET.SubElement(
            root,
            f"{{{MA2_NS}}}Timecode",
            {
                "index": str(max(0, plan.profile.timecode_pool - 1)),
                "name": plan.profile.timecode_name,
                "lenght": str(length),
                "stop_status": "Rewind",
                "no_switch_off": "true",
                "no_status_call": "true",
            },
        )

        # Main track — Object must point at the Executor (page.exec), not Sequence pool #.
        main_track = ET.SubElement(
            tc,
            f"{{{MA2_NS}}}Track",
            {"index": "0", "active": "true", "expanded": "true"},
        )
        main_page, main_exec = parse_page_executor(plan.profile.main_executor)
        obj = ET.SubElement(
            main_track,
            f"{{{MA2_NS}}}Object",
            {"name": f"{plan.profile.main_sequence_name} {main_page}.{main_exec}"},
        )
        # Golden fixture pattern: 30, page, page, executor
        for value in (30, main_page, main_page, main_exec):
            no = ET.SubElement(obj, f"{{{MA2_NS}}}No")
            no.text = str(value)

        main_sub = ET.SubElement(main_track, f"{{{MA2_NS}}}SubTrack", {"index": "0"})
        for idx, cue in enumerate(plan.main_cues):
            frames = seconds_to_ma2_frames(
                export_event_time_seconds(cue.time_seconds, plan.profile), fps
            )
            cue_no = int(cue.cue_number)
            event = ET.SubElement(
                main_sub,
                f"{{{MA2_NS}}}Event",
                {
                    "index": str(idx),
                    "time": str(frames),
                    "command": "Go",
                    "pressed": "true",
                    "step": str(cue_no),
                },
            )
            cue_el = ET.SubElement(event, f"{{{MA2_NS}}}Cue", {"name": f"Cue {cue_no}"})
            for value in (main_page, main_page, cue_no):
                no = ET.SubElement(cue_el, f"{{{MA2_NS}}}No")
                no.text = str(value)
        ET.SubElement(main_track, f"{{{MA2_NS}}}SubTrack", {"index": "1", "fader_command": "Master"})

        # Button tracks: one sequence / many Top events — also bind by Executor.
        for lane_i, lane in enumerate(plan.button_lanes, start=1):
            track = ET.SubElement(
                tc,
                f"{{{MA2_NS}}}Track",
                {"index": str(lane_i), "active": "true", "expanded": "true"},
            )
            button_page, button_exec = parse_page_executor(lane.executor)
            button_name = (
                plan.profile.button_sequence_name if lane_i == 1 else lane.resolved_ma_name()
            )
            obj = ET.SubElement(
                track,
                f"{{{MA2_NS}}}Object",
                {"name": f"{button_name} {button_page}.{button_exec}"},
            )
            for value in (30, button_page, button_page, button_exec):
                no = ET.SubElement(obj, f"{{{MA2_NS}}}No")
                no.text = str(value)
            sub = ET.SubElement(track, f"{{{MA2_NS}}}SubTrack", {"index": "0"})
            for event_i, t in enumerate(lane.mark_times_seconds):
                frames = seconds_to_ma2_frames(
                    export_event_time_seconds(t, plan.profile), fps
                )
                ET.SubElement(
                    sub,
                    f"{{{MA2_NS}}}Event",
                    {
                        "index": str(event_i),
                        "time": str(frames),
                        "command": "Top",
                        "pressed": "true",
                        "step": "4294967295",
                    },
                )
            ET.SubElement(track, f"{{{MA2_NS}}}SubTrack", {"index": "1", "fader_command": "Master"})

        write_xml(
            root,
            path,
            default_namespace=MA2_NS,
            stylesheet_hrefs=["styles/timecode@sheet.xsl"],
        )
        self._fix_ma2_xsi(path)

    def write_install_plugin(self, plan: SongExportPlan, directory: Path) -> dict[str, Path]:
        """
        MA2 install helpers.

        CuePoints ships a Plugin (.xml + .lua). We generate that pair in the
        real MA2 shape (luafile=...), and also a Macro XML which is usually
        more reliable for auto-generated installers.
        """
        directory = Path(directory)
        lua_path = directory / "cueplayer_export.lua"
        plugin_xml_path = directory / "cueplayer_export.xml"
        macro_xml_path = directory / "cueplayer_install_macro.xml"

        main_seq = plan.profile.sequence_pool_start
        button_seq = plan.profile.sequence_pool_start + 1
        tc_pool = plan.profile.timecode_pool
        main_page, main_exec = parse_page_executor(plan.profile.main_executor)
        button_page, button_exec = parse_page_executor(
            plan.button_lanes[0].executor if plan.button_lanes else "1.201"
        )

        cmd_lines = [
            f'Import "{plan.profile.main_sequence_file}" At Sequence {main_seq} /nc',
            f'Label Sequence {main_seq} "{plan.profile.main_sequence_name}"',
            f"Assign Sequence {main_seq} At Exec {main_page}.{main_exec}",
            f"Assign Go At Exec {main_page}.{main_exec}",
            f'Import "{plan.profile.button_sequence_file}" At Sequence {button_seq} /nc',
            f'Label Sequence {button_seq} "{plan.profile.button_sequence_name}"',
            f"Assign Sequence {button_seq} At Exec {button_page}.{button_exec}",
            f"Assign Top At Exec {button_page}.{button_exec}",
            f'Import "{plan.profile.timecode_file}" At Timecode {tc_pool} /nc',
            f'Label Timecode {tc_pool} "{plan.profile.timecode_name}"',
        ]

        # Real MA2 plugins expect a Start function, not "return function()".
        # Use single-quoted Lua strings because CMD lines contain double quotes.
        lua_cmds = "\n".join(f"  gma.cmd('{line}')" for line in cmd_lines)
        lua = f"""-- CuePlayer MA2 install plugin (.xml + .lua pair)
local function Start()
{lua_cmds}
  gma.echo("CuePlayer export installed: Seq {main_seq}/{button_seq}, Exec {main_page}.{main_exec}/{button_page}.{button_exec}, TC {tc_pool}")
end

local function Cleanup()
end

return Start, Cleanup
"""
        lua_path.write_text(lua, encoding="utf-8")

        # Match real MA2 plugin descriptors: Plugin/@luafile (not ComponentLua).
        plugin_root = self._root()
        self._info(plugin_root, plan.song_name)
        ET.SubElement(
            plugin_root,
            f"{{{MA2_NS}}}Plugin",
            {
                "index": "1",
                "execute_on_load": "0",
                "name": "CuePlayer Export",
                "luafile": "cueplayer_export.lua",
            },
        )
        write_xml(plugin_root, plugin_xml_path, default_namespace=MA2_NS)
        self._fix_ma2_xsi(plugin_xml_path)

        # Macro is the preferred auto-generated path (same commands, no Lua runtime).
        macro_root = self._root()
        self._info(macro_root, plan.song_name)
        macro = ET.SubElement(
            macro_root,
            f"{{{MA2_NS}}}Macro",
            {"index": "0", "name": "CuePlayer Export"},
        )
        for i, line in enumerate(cmd_lines):
            macroline = ET.SubElement(macro, f"{{{MA2_NS}}}Macroline", {"index": str(i)})
            text = ET.SubElement(macroline, f"{{{MA2_NS}}}text")
            text.text = line
        write_xml(macro_root, macro_xml_path, default_namespace=MA2_NS)
        self._fix_ma2_xsi(macro_xml_path)

        return {
            "plugin_xml": plugin_xml_path,
            "plugin_lua": lua_path,
            "macro_xml": macro_xml_path,
        }
