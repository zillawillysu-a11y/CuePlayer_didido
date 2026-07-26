"""grandMA3 exporter — Sequence + Timecode XML generation."""

from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

from cueplayer.exporters.common import SongExportPlan
from cueplayer.exporters.xml_write import ma3_guid, write_xml

MA3_TARGET_VERSION = "2.3.2"
MA3_DATA_VERSION = "2.4.2.2"  # matches collected golden XML from this machine


class Ma3Exporter:
    target_version = MA3_TARGET_VERSION
    data_version = MA3_DATA_VERSION

    def export_plan_summary(self, plan: SongExportPlan) -> dict:
        return {
            "console": "ma3",
            "target_version": self.target_version,
            "data_version": self.data_version,
            "song_name": plan.song_name,
            "main_cue_count": len(plan.main_cues),
            "button_lane_count": len(plan.button_lanes),
            "button_event_count": sum(len(lane.mark_times_seconds) for lane in plan.button_lanes),
            "sequence_pool_start": plan.profile.sequence_pool_start,
            "timecode_pool": plan.profile.timecode_pool,
            "data_pool": plan.profile.data_pool,
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

    def write_main_sequence(self, plan: SongExportPlan, path: Path) -> None:
        root = self._root()
        sequ = ET.SubElement(
            root,
            "Sequence",
            {
                "Name": "CuePlayer_Main",
                "Guid": ma3_guid(),
                "AutoStart": "Yes",
                "AutoStop": "Yes",
                "Tracking": "Yes",
                "Action": "Pool Default",
            },
        )
        off = ET.SubElement(
            sequ,
            "Cue",
            {"Name": "OffCue", "Release": "Yes", "Assert": "Assert"},
        )
        self._cue_part(off)
        zero = ET.SubElement(sequ, "Cue", {"Name": "CueZero", "No": "  0"})
        self._cue_part(zero)

        for cue in plan.main_cues:
            cue_no = int(cue.cue_number)
            attrs = {"No": f"{cue_no:3d}", "AllowDuplicates": ""}
            label = cue.resolved_ma_name()
            if label and not label.startswith("Cue"):
                attrs["Name"] = label
            cue_el = ET.SubElement(sequ, "Cue", attrs)
            part = self._cue_part(cue_el)
            part.set("Sync", "")
            part.set("Morph", "")

        write_xml(root, path)

    def write_button_sequence(self, plan: SongExportPlan, path: Path) -> None:
        root = self._root()
        sequ = ET.SubElement(
            root,
            "Sequence",
            {
                "Name": "CuePlayer_Button",
                "Guid": ma3_guid(),
                "AutoStart": "Yes",
                "AutoStop": "Yes",
                "Tracking": "Yes",
                "WrapAround": "No",
                "Action": "Pool Default",
            },
        )
        off = ET.SubElement(
            sequ,
            "Cue",
            {
                "Name": "OffCue",
                "Release": "Yes",
                "Assert": "Assert",
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
        offset = plan.profile.start_offset_seconds
        times = [c.time_seconds + offset for c in plan.main_cues]
        for lane in plan.button_lanes:
            times.extend(t + offset for t in lane.mark_times_seconds)
        duration = max(times) if times else 0.0

        tc = ET.SubElement(
            root,
            "Timecode",
            {
                "Name": "CuePlayer_TC",
                "Guid": ma3_guid(),
                "Cursor": f"{duration:.2f}",
                "Duration": f"{duration:.2f}",
                "LoopCount": "0",
                "TCSlot": "-1",
                "AutoStop": "No",
                "SwitchOff": "Keep Playbacks",
                "Goto": "as Go",
                "AssertPrevEvents": "No",
                "TimeDisplayFormat": "Default",
                "FrameReadout": "Default",
                "RestartOption": "Continue",
            },
        )
        group = ET.SubElement(tc, "TrackGroup", {"Play": "", "Rec": ""})
        ET.SubElement(group, "MarkerTrack", {"Name": "Marker", "Guid": ma3_guid()})

        pool = plan.profile.data_pool
        main_target = f"ShowData.DataPools.{pool}.Sequences.CuePlayer_Main"
        main_track = ET.SubElement(
            group,
            "Track",
            {
                "Name": "CuePlayer_Main",
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
        for cue in plan.main_cues:
            cue_no = int(cue.cue_number)
            t = cue.time_seconds + offset
            event = ET.SubElement(
                main_cmds,
                "CmdEvent",
                {
                    "Name": "Go+",
                    "Time": f"{t:.3f}",
                    "CueDestination": f"Cue {cue_no}",
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
                    "Object": "13.13.0.5.0",
                    "ExecToken": "Go+",
                    "ValCueDestination": f"0.5.0.{cue_no}000",
                },
            )

        for lane_i, lane in enumerate(plan.button_lanes):
            button_name = "CuePlayer_Button" if lane_i == 0 else lane.resolved_ma_name()
            target = f"ShowData.DataPools.{pool}.Sequences.{button_name}"
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
                abs_t = t + offset
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
                        "Object": "13.13.0.5.1",
                        "ExecToken": "Top",
                        "ValCueDestination": "0.5.1.1000",
                    },
                )

        write_xml(root, path)
