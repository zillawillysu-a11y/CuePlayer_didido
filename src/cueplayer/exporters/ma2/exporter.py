"""grandMA2 exporter — Sequence + Timecode XML generation."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import xml.etree.ElementTree as ET

from cueplayer.exporters.common import SongExportPlan
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
            "main_cue_count": len(plan.main_cues),
            "button_lane_count": len(plan.button_lanes),
            "button_event_count": sum(len(lane.mark_times_seconds) for lane in plan.button_lanes),
            "sequence_pool_start": plan.profile.sequence_pool_start,
            "timecode_pool": plan.profile.timecode_pool,
        }

    def export_to_directory(self, plan: SongExportPlan, directory: Path) -> dict[str, Path]:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        paths = {
            "main_sequence": directory / "main_sequence.xml",
            "button_sequence": directory / "button_sequence.xml",
            "timecode": directory / "timecode.xml",
        }
        self.write_main_sequence(plan, paths["main_sequence"])
        self.write_button_sequence(plan, paths["button_sequence"])
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
                "name": "CuePlayer_Main",
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
                "name": "CuePlayer_Button",
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
        offset = plan.profile.start_offset_seconds

        event_frames: list[int] = []
        for cue in plan.main_cues:
            event_frames.append(seconds_to_ma2_frames(cue.time_seconds + offset, fps))
        for lane in plan.button_lanes:
            for t in lane.mark_times_seconds:
                event_frames.append(seconds_to_ma2_frames(t + offset, fps))
        length = max(event_frames) if event_frames else 0

        tc = ET.SubElement(
            root,
            f"{{{MA2_NS}}}Timecode",
            {
                "index": str(max(0, plan.profile.timecode_pool - 1)),
                "name": "CuePlayer_TC",
                "lenght": str(length),
                "stop_status": "Rewind",
                "no_switch_off": "true",
                "no_status_call": "true",
            },
        )

        # Main track
        main_track = ET.SubElement(
            tc,
            f"{{{MA2_NS}}}Track",
            {"index": "0", "active": "true", "expanded": "true"},
        )
        page = plan.profile.page
        main_seq = plan.profile.sequence_pool_start
        obj = ET.SubElement(
            main_track,
            f"{{{MA2_NS}}}Object",
            {"name": f"CuePlayer_Main {page}.{main_seq}"},
        )
        for value in (30, page, page, main_seq):
            no = ET.SubElement(obj, f"{{{MA2_NS}}}No")
            no.text = str(value)

        main_sub = ET.SubElement(main_track, f"{{{MA2_NS}}}SubTrack", {"index": "0"})
        for idx, cue in enumerate(plan.main_cues):
            frames = seconds_to_ma2_frames(cue.time_seconds + offset, fps)
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
            for value in (page, page, cue_no):
                no = ET.SubElement(cue_el, f"{{{MA2_NS}}}No")
                no.text = str(value)
        ET.SubElement(main_track, f"{{{MA2_NS}}}SubTrack", {"index": "1", "fader_command": "Master"})

        # Button tracks: one sequence / many Top events
        for lane_i, lane in enumerate(plan.button_lanes, start=1):
            track = ET.SubElement(
                tc,
                f"{{{MA2_NS}}}Track",
                {"index": str(lane_i), "active": "true", "expanded": "true"},
            )
            button_seq = plan.profile.sequence_pool_start + lane_i
            obj = ET.SubElement(
                track,
                f"{{{MA2_NS}}}Object",
                {"name": f"{lane.resolved_ma_name()} {page}.{button_seq}"},
            )
            # First button lane mirrors golden fixture naming CuePlayer_Button
            if lane_i == 1:
                obj.set("name", f"CuePlayer_Button {page}.{button_seq}")
            for value in (30, page, page, button_seq):
                no = ET.SubElement(obj, f"{{{MA2_NS}}}No")
                no.text = str(value)
            sub = ET.SubElement(track, f"{{{MA2_NS}}}SubTrack", {"index": "0"})
            for event_i, t in enumerate(lane.mark_times_seconds):
                frames = seconds_to_ma2_frames(t + offset, fps)
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
